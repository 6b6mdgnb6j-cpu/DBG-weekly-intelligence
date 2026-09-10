import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from qa_gate import FAIL, PASS, WARNING, file_sha256


REVIEW_SCHEMA_VERSION = 1
PRODUCTION_WORKFLOW_NAME = "DBG Weekly Report - Production"
REVIEW_ARTIFACT_PREFIX = "weekly-report-review"
VALID_QA_STATUSES = {PASS, WARNING, FAIL}
VALID_WEEK_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
VALID_RUN_ID_RE = re.compile(r"\d+")


class AutomationValidationError(Exception):
    pass


def load_json(path):
    try:
        with Path(path).open(encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        raise AutomationValidationError(f"JSON artifact could not be read: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AutomationValidationError(f"JSON artifact must contain an object: {path}")
    return payload


def validate_week_start(value):
    if not VALID_WEEK_RE.fullmatch(value or ""):
        raise AutomationValidationError("week_start must use YYYY-MM-DD format")
    try:
        start = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise AutomationValidationError(f"week_start is not a valid date: {exc}") from exc
    if start.weekday() != 0:
        raise AutomationValidationError("week_start must be Monday")
    return start


def previous_natural_week(today):
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7)


def compact_week(value):
    return value.replace("-", "")


def review_artifact_name(week_start):
    return f"{REVIEW_ARTIFACT_PREFIX}-{week_start}"


def artifact_filename(kind, week_start):
    key = compact_week(week_start)
    return {
        "weekly_data": f"weekly_data_{key}.json",
        "source_status": f"source_status_{key}.json",
        "qa_report": f"qa_report_{key}.json",
        "qa_markdown": f"qa_report_{key}.md",
        "html": f"weekly_report_{key}.html",
        "manifest": f"review_manifest_{key}.json",
    }[kind]


def artifact_path(output_dir, kind, week_start):
    return Path(output_dir) / artifact_filename(kind, week_start)


def translation_preflight(provider_factory=None, attempts=3, sleep_seconds=5):
    if provider_factory is None:
        from crawler.translator import LocalNLLBProvider

        provider_factory = LocalNLLBProvider

    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception as exc:
        raise AutomationValidationError(f"TRANSLATION PREFLIGHT FAILED: dependency unavailable: {exc}") from exc

    last_error = ""
    for attempt in range(1, attempts + 1):
        provider = provider_factory()
        try:
            output = provider.translate(
                "Clearstream settlement update",
                source_lang="en",
                target_lang="zh",
            )
        except Exception as exc:
            output = ""
            last_error = str(exc)
        if output and output.strip():
            return True
        last_error = last_error or getattr(provider, "load_error", "") or "empty translation output"
        if attempt < attempts:
            time.sleep(sleep_seconds * attempt)

    raise AutomationValidationError(f"TRANSLATION PREFLIGHT FAILED: model download/load unavailable: {last_error}")


def validate_bilingual_artifacts(output_dir, week_start):
    validate_week_start(week_start)
    output_dir = Path(output_dir)
    weekly = artifact_path(output_dir, "weekly_data", week_start)
    source_status = artifact_path(output_dir, "source_status", week_start)
    qa_report = artifact_path(output_dir, "qa_report", week_start)
    html = artifact_path(output_dir, "html", week_start)

    for path in (weekly, source_status, qa_report, html):
        if not path.exists():
            raise AutomationValidationError(f"required artifact missing before manifest: {path.name}")

    weekly_payload = load_json(weekly)
    qa_payload = load_json(qa_report)
    validate_bilingual_payload(weekly_payload)
    validate_qa_binding(weekly_payload, weekly, qa_payload, week_start)
    if not html.read_text(encoding="utf-8", errors="replace").strip():
        raise AutomationValidationError("HTML artifact is empty")
    return True


def summary_highlight_count(weekly_payload, qa_payload):
    qa_summary = qa_payload.get("summary") if isinstance(qa_payload, dict) else {}
    qa_highlights = qa_summary.get("highlights") if isinstance(qa_summary, dict) else None
    if isinstance(qa_highlights, int):
        return qa_highlights
    highlights = weekly_payload.get("highlights") if isinstance(weekly_payload, dict) else []
    return len(highlights) if isinstance(highlights, list) else 0


def summary_final_item_count(weekly_payload, qa_payload):
    qa_summary = qa_payload.get("summary") if isinstance(qa_payload, dict) else {}
    qa_final_items = qa_summary.get("final_items") if isinstance(qa_summary, dict) else None
    if isinstance(qa_final_items, int):
        return qa_final_items
    return weekly_payload.get("item_count", len(weekly_payload.get("items") or []))


def html_report_data_highlight_count(html_text):
    match = re.search(
        r'<script[^>]+id=["\']report-data["\'][^>]*>(.*?)</script>',
        html_text or "",
        flags=re.I | re.S,
    )
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except Exception:
        return None
    highlights = payload.get("highlights") if isinstance(payload, dict) else None
    return len(highlights) if isinstance(highlights, list) else None


def review_artifact_ready(review_uploaded, validation_code, manifest_code, bundle_validation_code):
    return (
        str(review_uploaded).lower() == "true"
        and str(validation_code) == "0"
        and str(manifest_code) == "0"
        and str(bundle_validation_code) == "0"
    )


def workflow_step_status(outcome, exit_code):
    if outcome == "skipped" or exit_code in (None, "", "unavailable"):
        return "NOT RUN"
    if outcome == "success" and str(exit_code) == "0":
        return "PASS"
    return "FAILED"


def write_review_manifest(output_dir, week_start, generation_commit_sha, generation_run_id):
    if not VALID_RUN_ID_RE.fullmatch(str(generation_run_id or "")):
        raise AutomationValidationError("generation_run_id must contain digits only")
    validate_week_start(week_start)

    output_dir = Path(output_dir)
    weekly = artifact_path(output_dir, "weekly_data", week_start)
    source_status = artifact_path(output_dir, "source_status", week_start)
    qa_report = artifact_path(output_dir, "qa_report", week_start)
    qa_markdown = artifact_path(output_dir, "qa_markdown", week_start)
    html = artifact_path(output_dir, "html", week_start)

    validate_bilingual_artifacts(output_dir, week_start)
    weekly_payload = load_json(weekly)
    qa_payload = load_json(qa_report)

    artifacts = {}
    for key, path in (
        ("weekly_data", weekly),
        ("source_status", source_status),
        ("qa_report", qa_report),
        ("weekly_report_html", html),
        ("qa_markdown", qa_markdown),
    ):
        if not path.exists():
            raise AutomationValidationError(f"required artifact missing: {path.name}")
        artifacts[key] = {"filename": path.name, "sha256": file_sha256(path)}

    manifest = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "week_start": weekly_payload.get("week_start"),
        "week_end": weekly_payload.get("week_end"),
        "generation_commit_sha": generation_commit_sha,
        "generation_run_id": str(generation_run_id),
        "translation_mode": weekly_payload.get("translation_mode"),
        "qa_status": qa_payload.get("status"),
        "final_items": summary_final_item_count(weekly_payload, qa_payload),
        "highlights": summary_highlight_count(weekly_payload, qa_payload),
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "artifacts": artifacts,
    }
    manifest_path = artifact_path(output_dir, "manifest", week_start)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def validate_bilingual_payload(payload):
    if payload.get("translation_mode") != "bilingual":
        raise AutomationValidationError("weekly_data translation_mode must be bilingual")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise AutomationValidationError("weekly_data items must be a non-empty list")

    for index, item in enumerate(items):
        title_original = (item.get("title_original") or "").strip()
        if not title_original:
            raise AutomationValidationError(f"item {index} missing title_original")
        title_lang = item.get("title_original_lang") or ""
        if title_lang != "zh" and not (item.get("title_cn") or "").strip():
            raise AutomationValidationError(f"item {index} missing title_cn for non-Chinese title")

        summary_original = (item.get("summary_original") or item.get("summary") or "").strip()
        summary_lang = item.get("summary_original_lang") or ""
        if summary_original and summary_lang != "zh" and not (item.get("summary_cn") or "").strip():
            raise AutomationValidationError(f"item {index} missing summary_cn for non-Chinese summary")


def validate_qa_binding(weekly_payload, weekly_path, qa_payload, week_start):
    validate_week_start(week_start)
    if qa_payload.get("status") not in VALID_QA_STATUSES:
        raise AutomationValidationError("QA status is malformed or missing")
    if weekly_payload.get("week_start") != week_start or qa_payload.get("week_start") != week_start:
        raise AutomationValidationError("QA/weekly_data week_start mismatch")
    if weekly_payload.get("week_end") != qa_payload.get("week_end"):
        raise AutomationValidationError("QA/weekly_data week_end mismatch")
    if qa_payload.get("translation_mode") != weekly_payload.get("translation_mode"):
        raise AutomationValidationError("QA/weekly_data translation_mode mismatch")

    expected_sha = (qa_payload.get("input_artifacts") or {}).get("weekly_data_sha256")
    if not expected_sha:
        raise AutomationValidationError("QA report missing weekly_data_sha256")
    if expected_sha != file_sha256(weekly_path):
        raise AutomationValidationError("QA weekly_data_sha256 does not match artifact")


def validate_manifest(bundle_dir, week_start, source_run_id=None, generation_sha=None, current_main_sha=None):
    if source_run_id is not None and not VALID_RUN_ID_RE.fullmatch(str(source_run_id)):
        raise AutomationValidationError("source_run_id must contain digits only")
    validate_week_start(week_start)
    bundle_dir = Path(bundle_dir)
    manifest_path = artifact_path(bundle_dir, "manifest", week_start)
    if not manifest_path.exists():
        raise AutomationValidationError("review manifest missing")

    manifest = load_json(manifest_path)
    if manifest.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise AutomationValidationError("unsupported review manifest schema_version")
    if manifest.get("week_start") != week_start:
        raise AutomationValidationError("manifest week_start mismatch")
    if source_run_id is not None and str(manifest.get("generation_run_id")) != str(source_run_id):
        raise AutomationValidationError("manifest generation_run_id mismatch")
    if generation_sha is not None and manifest.get("generation_commit_sha") != generation_sha:
        raise AutomationValidationError("manifest generation_commit_sha mismatch")
    if current_main_sha is not None and manifest.get("generation_commit_sha") != current_main_sha:
        raise AutomationValidationError("production artifact is stale relative to main")
    if manifest.get("translation_mode") != "bilingual":
        raise AutomationValidationError("manifest translation_mode must be bilingual")

    artifacts = manifest.get("artifacts") or {}
    for key in ("weekly_data", "source_status", "qa_report", "weekly_report_html"):
        entry = artifacts.get(key) or {}
        filename = entry.get("filename")
        expected_sha = entry.get("sha256")
        if not filename or not expected_sha:
            raise AutomationValidationError(f"manifest artifact entry incomplete: {key}")
        path = bundle_dir / filename
        if not path.exists():
            raise AutomationValidationError(f"manifest artifact missing: {filename}")
        if file_sha256(path) != expected_sha:
            raise AutomationValidationError(f"manifest artifact hash mismatch: {filename}")

    weekly = load_json(bundle_dir / artifacts["weekly_data"]["filename"])
    qa = load_json(bundle_dir / artifacts["qa_report"]["filename"])
    validate_bilingual_payload(weekly)
    validate_qa_binding(weekly, bundle_dir / artifacts["weekly_data"]["filename"], qa, week_start)
    if qa.get("status") != manifest.get("qa_status"):
        raise AutomationValidationError("manifest QA status does not match QA report")
    qa_final_items = summary_final_item_count(weekly, qa)
    qa_highlights = summary_highlight_count(weekly, qa)
    if manifest.get("final_items") != qa_final_items:
        raise AutomationValidationError("manifest final_items does not match QA report")
    if manifest.get("highlights") != qa_highlights:
        raise AutomationValidationError("manifest highlights does not match QA report")
    html_path = bundle_dir / artifacts["weekly_report_html"]["filename"]
    html_highlights = html_report_data_highlight_count(html_path.read_text(encoding="utf-8", errors="replace"))
    if html_highlights is not None and html_highlights != qa_highlights:
        raise AutomationValidationError("HTML highlights count does not match QA report")
    return manifest


def publish_allowed_by_qa(qa_status, approve_warning=False):
    if qa_status == PASS:
        return True
    if qa_status == WARNING:
        if approve_warning:
            return True
        raise AutomationValidationError("QA WARNING requires explicit manual approval")
    if qa_status == FAIL:
        raise AutomationValidationError("QA FAIL prohibits publish")
    raise AutomationValidationError("QA status is malformed or missing")


def validate_source_run_metadata(source_run, current_repo, current_branch="main"):
    if source_run.get("repository") != current_repo:
        raise AutomationValidationError("source run does not belong to current repository")
    if source_run.get("workflow_name") != PRODUCTION_WORKFLOW_NAME:
        raise AutomationValidationError("source run is not the production workflow")
    if source_run.get("branch") != current_branch:
        raise AutomationValidationError("source run branch is not main")
    if source_run.get("conclusion") != "success":
        raise AutomationValidationError("source run did not complete successfully")
    if not source_run.get("head_sha"):
        raise AutomationValidationError("source run head SHA unavailable")
    return True


def validate_published_diff_paths(paths):
    bad = [path for path in paths if path and not path.startswith("published/")]
    if bad:
        raise AutomationValidationError("non-published paths changed: " + ", ".join(bad))
    return True


def cli(argv=None):
    parser = argparse.ArgumentParser(description="Automation Pipeline V1 artifact helpers.")
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest")
    manifest.add_argument("--output-dir", required=True)
    manifest.add_argument("--week-start", required=True)
    manifest.add_argument("--generation-sha", required=True)
    manifest.add_argument("--generation-run-id", required=True)

    validate = sub.add_parser("validate-bundle")
    validate.add_argument("--bundle-dir", required=True)
    validate.add_argument("--week-start", required=True)
    validate.add_argument("--source-run-id")
    validate.add_argument("--generation-sha")
    validate.add_argument("--current-main-sha")
    validate.add_argument("--approve-warning", action="store_true")

    preflight = sub.add_parser("translation-preflight")
    preflight.add_argument("--attempts", type=int, default=3)
    preflight.add_argument("--sleep-seconds", type=int, default=5)

    bilingual = sub.add_parser("validate-bilingual")
    bilingual.add_argument("--output-dir", required=True)
    bilingual.add_argument("--week-start", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "manifest":
            path = write_review_manifest(args.output_dir, args.week_start, args.generation_sha, args.generation_run_id)
            print(path)
            return 0
        if args.command == "translation-preflight":
            translation_preflight(attempts=args.attempts, sleep_seconds=args.sleep_seconds)
            print("TRANSLATION PREFLIGHT: PASS")
            return 0
        if args.command == "validate-bilingual":
            validate_bilingual_artifacts(args.output_dir, args.week_start)
            print("BILINGUAL VALIDATION: PASS")
            return 0
        if args.command == "validate-bundle":
            manifest_payload = validate_manifest(
                args.bundle_dir,
                args.week_start,
                source_run_id=args.source_run_id,
                generation_sha=args.generation_sha,
                current_main_sha=args.current_main_sha,
            )
            publish_allowed_by_qa(manifest_payload.get("qa_status"), approve_warning=args.approve_warning)
            print("BUNDLE VALIDATION: PASS")
            print(f"QA status: {manifest_payload.get('qa_status')}")
            return 0
    except AutomationValidationError as exc:
        print(f"BUNDLE VALIDATION: BLOCKED: {exc}", file=sys.stderr)
        return 4
    return 4


if __name__ == "__main__":
    raise SystemExit(cli())
