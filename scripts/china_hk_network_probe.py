#!/usr/bin/env python3
"""GitHub-runner network probe for selected China/HK official sources.

This diagnostic script is intentionally read-only. It performs one bounded
curl GET, one direct requests GET, one project-client GET, and one OpenSSL
TLS probe for HTTPS endpoints.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import ssl
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from crawler import http_client


ENDPOINTS = [
    {"source": "SRC-001 NFRA", "url": "https://www.nfra.gov.cn"},
    {"source": "SRC-002 PBOC", "url": "http://www.pbc.gov.cn"},
    {"source": "SRC-002 PBOC", "url": "https://www.pbc.gov.cn"},
    {"source": "SRC-003 CSRC", "url": "http://www.csrc.gov.cn"},
    {"source": "SRC-003 CSRC", "url": "https://www.csrc.gov.cn"},
    {"source": "SRC-004 SAFE", "url": "http://www.safe.gov.cn"},
    {"source": "SRC-004 SAFE", "url": "https://www.safe.gov.cn"},
    {
        "source": "SRC-006 HKMA",
        "url": "https://www.hkma.gov.hk/eng/news-and-media/press-releases/",
    },
]


def _elapsed(start: float) -> float:
    return round(time.monotonic() - start, 3)


def _safe_text(value: object, limit: int = 500) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def environment_metadata() -> dict:
    try:
        import urllib3

        urllib3_version = urllib3.__version__
    except Exception:
        urllib3_version = "unavailable"
    return {
        "runner_os": platform.platform(),
        "python_version": sys.version.replace("\n", " "),
        "requests_version": requests.__version__,
        "urllib3_version": urllib3_version,
        "openssl_version": ssl.OPENSSL_VERSION,
    }


def probe_curl(url: str) -> dict:
    start = time.monotonic()
    fmt = "\t".join(
        [
            "http_code=%{http_code}",
            "url_effective=%{url_effective}",
            "content_type=%{content_type}",
            "time_total=%{time_total}",
        ]
    )
    cmd = [
        "curl",
        "-sS",
        "-L",
        "--max-time",
        "20",
        "-o",
        "/dev/null",
        "-w",
        fmt,
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25, check=False)
    except Exception as exc:
        return {
            "ok": False,
            "exit_code": None,
            "error": _safe_text(exc),
            "elapsed": _elapsed(start),
        }

    fields = {}
    for part in proc.stdout.strip().split("\t"):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key] = value
    status = fields.get("http_code", "")
    ok = proc.returncode == 0 and status.startswith(("2", "3"))
    return {
        "ok": ok,
        "exit_code": proc.returncode,
        "status": status,
        "final_url": fields.get("url_effective", ""),
        "content_type": fields.get("content_type", ""),
        "time_total": fields.get("time_total", ""),
        "stderr": _safe_text(proc.stderr),
        "elapsed": _elapsed(start),
    }


def probe_requests(url: str) -> dict:
    start = time.monotonic()
    try:
        response = requests.get(url, timeout=(8, 20), allow_redirects=True)
        return {
            "ok": response.ok,
            "status": response.status_code,
            "final_url": response.url,
            "redirect_history": [r.status_code for r in response.history],
            "content_type": response.headers.get("content-type", ""),
            "elapsed": _elapsed(start),
        }
    except Exception as exc:
        return {
            "ok": False,
            "exception_class": exc.__class__.__name__,
            "exception_message": _safe_text(exc),
            "elapsed": _elapsed(start),
        }


def probe_project_client(url: str) -> dict:
    start = time.monotonic()
    meta = {}
    try:
        response = http_client.get(url, timeout=(8, 20), meta=meta)
        return {
            "ok": response.ok,
            "status": response.status_code,
            "final_url": response.url,
            "content_type": response.headers.get("content-type", ""),
            "network_meta": meta,
            "elapsed": _elapsed(start),
        }
    except Exception as exc:
        return {
            "ok": False,
            "exception_class": exc.__class__.__name__,
            "exception_message": _safe_text(exc),
            "network_meta": meta,
            "elapsed": _elapsed(start),
        }


def probe_tls(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return {"skipped": True, "reason": "not_https"}
    host = parsed.hostname
    if not host:
        return {"skipped": True, "reason": "missing_host"}

    start = time.monotonic()
    cmd = [
        "openssl",
        "s_client",
        "-servername",
        host,
        "-connect",
        f"{host}:443",
        "-verify_return_error",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input="",
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": _safe_text(exc), "elapsed": _elapsed(start)}

    text = f"{proc.stdout}\n{proc.stderr}"
    protocol = ""
    cipher = ""
    verify = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Protocol"):
            protocol = stripped.split(":", 1)[-1].strip()
        elif stripped.startswith("Cipher"):
            cipher = stripped.split(":", 1)[-1].strip()
        elif "Verify return code:" in stripped:
            verify = stripped.split("Verify return code:", 1)[-1].strip()
    ok = proc.returncode == 0 and verify.startswith("0 ")
    return {
        "ok": ok,
        "exit_code": proc.returncode,
        "protocol": protocol,
        "cipher": cipher,
        "verify_return_code": verify,
        "elapsed": _elapsed(start),
    }


def _result_label(result: dict) -> str:
    if result.get("skipped"):
        return "SKIPPED"
    return "OK" if result.get("ok") else "FAIL"


def _status(result: dict) -> str:
    value = result.get("status")
    return str(value) if value not in (None, "") else "-"


def diagnosis_hint(curl: dict, py: dict, project: dict, tls: dict) -> str:
    curl_ok = bool(curl.get("ok"))
    py_ok = bool(py.get("ok"))
    project_ok = bool(project.get("ok"))
    tls_ok = bool(tls.get("ok") or tls.get("skipped"))

    statuses = {_status(curl), _status(py), _status(project)}
    if any(s.startswith("5") for s in statuses if s != "-"):
        return "SERVER_5XX"
    if tls and not tls_ok:
        return "TLS_FAILURE"
    if curl_ok and not py_ok and not project_ok:
        return "PYTHON_ONLY_FAILURE"
    if curl_ok and py_ok and not project_ok:
        return "PROJECT_CLIENT_ONLY_FAILURE"
    if curl_ok and py_ok and project_ok:
        return "ALL_OK"
    if not curl_ok and py_ok and project_ok:
        return "HTTP_ONLY_FAILURE"
    if any("timeout" in _safe_text(v).lower() for r in (curl, py, project) for v in r.values()):
        return "TIMEOUT"
    if len({curl_ok, py_ok, project_ok}) > 1:
        return "MIXED"
    return "UNKNOWN"


def markdown_summary(payload: dict) -> str:
    lines = [
        "# China/HK Network Probe",
        "",
        "## Environment",
        "",
    ]
    for key, value in payload["environment"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Results",
            "",
            "| source | url | curl_result | curl_status | python_requests_result | python_status | project_client_result | project_status | tls_result | final_url | diagnosis_hint |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in payload["results"]:
        curl = row["curl"]
        py = row["python_requests"]
        project = row["project_client"]
        tls = row["tls"]
        final_url = curl.get("final_url") or py.get("final_url") or project.get("final_url") or ""
        lines.append(
            "| {source} | `{url}` | {curl_result} | {curl_status} | {py_result} | {py_status} | {project_result} | {project_status} | {tls_result} | `{final_url}` | {hint} |".format(
                source=row["source"],
                url=row["url"],
                curl_result=_result_label(curl),
                curl_status=_status(curl),
                py_result=_result_label(py),
                py_status=_status(py),
                project_result=_result_label(project),
                project_status=_status(project),
                tls_result=_result_label(tls),
                final_url=final_url,
                hint=row["diagnosis_hint"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def run_probe() -> dict:
    results = []
    for endpoint in ENDPOINTS:
        url = endpoint["url"]
        curl_result = probe_curl(url)
        requests_result = probe_requests(url)
        project_result = probe_project_client(url)
        tls_result = probe_tls(url)
        results.append(
            {
                "source": endpoint["source"],
                "url": url,
                "curl": curl_result,
                "python_requests": requests_result,
                "project_client": project_result,
                "tls": tls_result,
                "diagnosis_hint": diagnosis_hint(
                    curl_result,
                    requests_result,
                    project_result,
                    tls_result,
                ),
            }
        )
    return {"environment": environment_metadata(), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run China/HK network probe.")
    parser.add_argument("--output-dir", default="network_probe", help="Directory for probe artifacts.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = run_probe()
    summary = markdown_summary(payload)

    (output_dir / "network_probe_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "network_probe_summary.md").write_text(summary, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
