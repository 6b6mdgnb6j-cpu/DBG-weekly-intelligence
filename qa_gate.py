import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from crawler.date_utils import parse_week_start, week_file_key
from crawler.highlight_ranker import select_highlights
from crawler.translation_quality import audit_translation_quality


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
POLICY_FILE = BASE_DIR / "config" / "qa_policy.json"
SOURCE_FILE = BASE_DIR / "config" / "sources.json"

PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"
INFO = "INFO"

SUCCESS_LIKE = {"success", "true_no_updates", "relevance_filtered"}
FAILURE_LIKE = {
    "network_error",
    "blocked",
    "js_required",
    "parser_failed",
    "date_parse_failed",
    "no_candidates",
    "invalid_config",
}


class QAExecutionError(Exception):
    pass


def load_json(path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def load_policy(path=POLICY_FILE):
    return load_json(path)


def load_sources(path=SOURCE_FILE):
    return load_json(path)


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_indexes(sources):
    by_id = {source.get("id"): source for source in sources if source.get("id")}
    by_name = {}
    for source in sources:
        by_name.setdefault(source.get("name", ""), []).append(source)
    return by_id, by_name


def source_id_for_status(status, by_name):
    if status.get("source_id"):
        return status.get("source_id")
    matches = by_name.get(status.get("source", ""), [])
    if len(matches) == 1:
        return matches[0].get("id", "")
    enabled = [source for source in matches if source.get("enabled", True)]
    if len(enabled) == 1:
        return enabled[0].get("id", "")
    return ""


def get_thresholds(policy):
    defaults = {
        "critical_unexpected_failures_fail": 3,
        "systemic_failure_warning_ratio": 0.1,
        "systemic_failure_fail_ratio": 0.25,
        "retry_hotspot_min_retried_requests": 3,
        "retry_hotspot_warning_ratio": 0.3,
        "global_retry_min_requests": 20,
        "global_retry_warning_ratio": 0.15,
        "global_retry_fail_ratio": 0.35,
        "final_items_low_warning": 5,
        "final_items_high_warning": 100,
    }
    values = dict(defaults)
    values.update(policy.get("thresholds") or {})
    return values


def check_result(checks, check_id, severity, passed, message, evidence=None):
    checks.append(
        {
            "id": check_id,
            "severity": severity,
            "result": PASS if passed else severity,
            "message": message,
            "evidence": evidence or {},
        }
    )


def normalize_title(value):
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def item_text(item):
    return normalize_title(
        " ".join(
            str(value)
            for value in (
                item.get("title_original"),
                item.get("summary"),
                item.get("source"),
                item.get("brand"),
                item.get("mapped_dbg_business"),
            )
            if value
        )
    )


def parse_item_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def status_is_success_like(status):
    name = status.get("status", "")
    if name == "all_outside_period":
        return bool(status.get("target_period_reached"))
    return name in SUCCESS_LIKE


def status_is_failure_like(status):
    name = status.get("status", "")
    if name == "all_outside_period":
        return not bool(status.get("target_period_reached"))
    return name in FAILURE_LIKE


def evaluate_content(payload, week_start, week_end):
    checks = []
    issues = []
    items = payload.get("items") or []
    final_count = int(payload.get("item_count") or len(items))
    thresholds = {}

    check_result(
        checks,
        "final_items_not_empty",
        FAIL,
        final_count > 0,
        "Final weekly items must not be empty.",
        {"final_items": final_count},
    )
    if 0 < final_count < 5:
        check_result(
            checks,
            "final_items_low",
            WARNING,
            False,
            "Final weekly item count is unusually low.",
            {"final_items": final_count, "threshold": 5},
        )
    if final_count > 100:
        check_result(
            checks,
            "final_items_high",
            WARNING,
            False,
            "Final weekly item count is unusually high.",
            {"final_items": final_count, "threshold": 100},
        )

    urls = Counter()
    titles = Counter()
    today = date.today()
    for index, item in enumerate(items):
        title = item.get("title_original") or item.get("title") or ""
        url = item.get("url") or ""
        source = item.get("source") or ""
        category = item.get("category") or ""
        item_date = parse_item_date(item.get("date"))

        missing = [field for field, value in (("title", title), ("url", url), ("source", source), ("category", category)) if not value]
        if missing:
            issues.append({"type": "missing_required_field", "index": index, "missing": missing, "title": title})
        if not item_date:
            issues.append({"type": "malformed_date", "index": index, "date": item.get("date"), "title": title})
        elif item_date < week_start or item_date > week_end:
            issues.append({"type": "outside_week_date", "index": index, "date": item.get("date"), "title": title})
        elif item_date > today:
            issues.append({"type": "future_date", "index": index, "date": item.get("date"), "title": title})
        if url:
            urls[url] += 1
        if title:
            titles[normalize_title(title)] += 1

    duplicate_urls = [url for url, count in urls.items() if count > 1]
    duplicate_titles = [title for title, count in titles.items() if title and count > 1]
    required_field_issues = [issue for issue in issues if issue["type"] == "missing_required_field"]
    date_issues = [issue for issue in issues if issue["type"] in {"malformed_date", "outside_week_date", "future_date"}]

    check_result(
        checks,
        "required_item_fields_present",
        FAIL,
        not required_field_issues,
        "Every final item must include title, URL, source, and category.",
        {"issues": required_field_issues[:10], "count": len(required_field_issues)},
    )
    check_result(
        checks,
        "final_item_dates_valid",
        FAIL,
        not date_issues,
        "Every final item date must be parseable, not future-dated, and inside the target week.",
        {"issues": date_issues[:10], "count": len(date_issues)},
    )
    check_result(
        checks,
        "no_duplicate_urls",
        FAIL,
        not duplicate_urls,
        "Final items must not contain exact duplicate URLs.",
        {"duplicate_urls": duplicate_urls[:10], "count": len(duplicate_urls)},
    )
    check_result(
        checks,
        "no_duplicate_normalized_titles",
        WARNING,
        not duplicate_titles,
        "Final items should not contain exact duplicate normalized titles.",
        {"duplicate_titles": duplicate_titles[:10], "count": len(duplicate_titles)},
    )

    highlights = payload.get("highlights")
    if highlights is None:
        highlights = select_highlights(items)
    highlight_count = len(highlights or [])
    enough_items = final_count >= 5
    if highlight_count == 0 and enough_items:
        check_result(
            checks,
            "highlights_present",
            FAIL,
            False,
            "Highlights must not be empty when enough final items exist.",
            {"highlights": highlight_count, "final_items": final_count},
        )
    elif highlight_count < min(5, final_count) and enough_items:
        check_result(
            checks,
            "highlights_count_normal",
            WARNING,
            False,
            "Highlight count is lower than expected.",
            {"highlights": highlight_count, "final_items": final_count},
        )
    else:
        check_result(
            checks,
            "highlights_count_normal",
            WARNING,
            True,
            "Highlight count is mechanically normal.",
            {"highlights": highlight_count, "final_items": final_count},
        )

    competitor_missing_mapping = []
    competitor_mapping_warnings = []
    container_page_issues = []
    for index, item in enumerate(items):
        title = normalize_title(item.get("title_original") or item.get("title"))
        text = item_text(item)
        container_titles = {"podcast", "podcasts", "press releases", "newsroom", "media"}
        if title in container_titles or title.startswith(("podcast:", "podcasts:", "podcast ", "podcasts ")):
            container_page_issues.append({"index": index, "title": item.get("title_original") or item.get("title")})
        if item.get("category") != "Competitor":
            continue
        if "competitor_group" in item and "mapped_dbg_business" in item:
            mapped = item.get("mapped_dbg_business", "")
            has_derivatives_context = any(term in text for term in ("derivatives", "futures", "options", "clearing", "swap"))
            if any(term in text for term in ("without derivatives", "no derivatives")):
                has_derivatives_context = False
            if mapped == "Eurex" and any(term in text for term in ("etf", "etfs", "cash equity", "listing")) and not has_derivatives_context:
                competitor_mapping_warnings.append(
                    {
                        "index": index,
                        "title": item.get("title_original") or item.get("title"),
                        "mapped_dbg_business": mapped,
                        "reason": "cash/ETF/listing signal mapped to Eurex without derivatives or clearing context",
                    }
                )
            continue
        competitor_missing_mapping.append({"index": index, "title": item.get("title_original") or item.get("title")})
    check_result(
        checks,
        "competitor_mapping_fields_available",
        WARNING,
        not competitor_missing_mapping,
        "Competitor items should include mapping fields when the current schema provides them.",
        {"issues": competitor_missing_mapping[:10], "count": len(competitor_missing_mapping)},
    )
    check_result(
        checks,
        "no_obvious_container_pages",
        WARNING,
        not container_page_issues,
        "Final items should not include obvious container/listing pages.",
        {"issues": container_page_issues[:10], "count": len(container_page_issues)},
    )
    check_result(
        checks,
        "competitor_mapping_signals_consistent",
        WARNING,
        not competitor_mapping_warnings,
        "Competitor business mapping should not contradict strong content signals.",
        {"issues": competitor_mapping_warnings[:10], "count": len(competitor_mapping_warnings)},
    )

    translation_issues = audit_translation_quality(items, payload.get("translation_mode", ""))
    translation_failures = [issue for issue in translation_issues if issue.get("severity") == FAIL]
    translation_warnings = [issue for issue in translation_issues if issue.get("severity") == WARNING]
    check_result(
        checks,
        "translation_quality_failures",
        FAIL,
        not translation_failures,
        "Translated artifact must not contain material entity, proper-noun, proposition, or action-direction errors.",
        {"issues": translation_failures[:10], "count": len(translation_failures)},
    )
    check_result(
        checks,
        "translation_quality_warnings",
        WARNING,
        not translation_warnings,
        "Translated artifact contains minor quality warnings that need review.",
        {"issues": translation_warnings[:10], "count": len(translation_warnings)},
    )
    issues.extend(translation_issues)

    return checks, issues, {"final_items": final_count, "highlights": highlight_count}


def evaluate_source_health(source_statuses, policy, sources):
    checks = []
    thresholds = get_thresholds(policy)
    policy_sources = policy.get("sources") or {}
    _, by_name = source_indexes(sources)

    source_health = {
        "status_counts": dict(Counter(status.get("status", "") for status in source_statuses)),
        "monitored_sources": 0,
        "unexpected_failures": 0,
        "critical_unexpected_failures": 0,
    }
    known_gaps = []
    recovered_sources = []
    unexpected_failures = []
    retry_hotspots = []
    missing_network_diagnostics = []

    total_requests = 0
    total_retried = 0

    for status in source_statuses:
        source_id = source_id_for_status(status, by_name)
        cfg = policy_sources.get(source_id, {})
        source_policy = cfg.get("policy", "expected_healthy")
        tier = cfg.get("tier", "normal")
        source_name = status.get("source", "")
        status_name = status.get("status", "")
        success_like = status_is_success_like(status)
        failure_like = status_is_failure_like(status)

        requests_total = int(status.get("requests_total") or 0)
        retried_requests = int(status.get("retried_requests") or 0)
        request_attempts_total = int(status.get("request_attempts_total") or 0)
        if "requests_total" not in status and request_attempts_total:
            missing_network_diagnostics.append(source_name)
        total_requests += requests_total
        total_retried += retried_requests
        retry_ratio = retried_requests / requests_total if requests_total else 0
        if retried_requests >= thresholds["retry_hotspot_min_retried_requests"] and retry_ratio >= thresholds["retry_hotspot_warning_ratio"]:
            retry_hotspots.append(
                {
                    "source_id": source_id,
                    "source": source_name,
                    "retried_requests": retried_requests,
                    "requests_total": requests_total,
                    "retry_ratio": round(retry_ratio, 3),
                    "last_retry_error": status.get("last_retry_error", ""),
                }
            )

        if source_policy == "known_gap":
            expected = set(cfg.get("expected_failures") or [])
            if success_like:
                recovered_sources.append({"source_id": source_id, "source": source_name, "status": status_name})
            elif status_name in expected or failure_like:
                known_gaps.append({"source_id": source_id, "source": source_name, "status": status_name})
            else:
                unexpected_failures.append({"source_id": source_id, "source": source_name, "status": status_name, "reason": "known_gap_unexpected_status"})
            continue

        source_health["monitored_sources"] += 1
        target_reach_problem = (
            not bool(status.get("target_period_reached"))
            and int(status.get("within_period") or 0) == 0
            and status_name not in {"blocked", "js_required"}
        )
        final_error = status.get("final_network_error") or status.get("last_network_error")
        if failure_like or target_reach_problem or final_error:
            issue = {
                "source_id": source_id,
                "source": source_name,
                "status": status_name,
                "tier": tier,
                "target_period_reached": bool(status.get("target_period_reached")),
                "final_network_error": final_error or "",
                "policy": source_policy,
            }
            unexpected_failures.append(issue)
            source_health["unexpected_failures"] += 1
            if tier == "critical":
                source_health["critical_unexpected_failures"] += 1

    check_result(
        checks,
        "critical_unexpected_failures_below_limit",
        FAIL,
        source_health["critical_unexpected_failures"] < thresholds["critical_unexpected_failures_fail"],
        "Too many critical expected-healthy sources failed in the same week.",
        {
            "critical_unexpected_failures": source_health["critical_unexpected_failures"],
            "threshold": thresholds["critical_unexpected_failures_fail"],
            "issues": [issue for issue in unexpected_failures if issue.get("tier") == "critical"][:10],
        },
    )

    monitored = max(1, source_health["monitored_sources"])
    failure_ratio = source_health["unexpected_failures"] / monitored
    if failure_ratio >= thresholds["systemic_failure_fail_ratio"]:
        check_result(
            checks,
            "systemic_source_failure_ratio",
            FAIL,
            False,
            "Unexpected source failures exceed the fail threshold.",
            {"ratio": round(failure_ratio, 3), "unexpected_failures": source_health["unexpected_failures"], "monitored_sources": monitored},
        )
    elif failure_ratio >= thresholds["systemic_failure_warning_ratio"]:
        check_result(
            checks,
            "systemic_source_failure_ratio",
            WARNING,
            False,
            "Unexpected source failures exceed the warning threshold.",
            {"ratio": round(failure_ratio, 3), "unexpected_failures": source_health["unexpected_failures"], "monitored_sources": monitored},
        )
    else:
        check_result(
            checks,
            "systemic_source_failure_ratio",
            WARNING,
            True,
            "Unexpected source failure ratio is within threshold.",
            {"ratio": round(failure_ratio, 3), "unexpected_failures": source_health["unexpected_failures"], "monitored_sources": monitored},
        )

    check_result(
        checks,
        "unexpected_source_failures",
        WARNING,
        not unexpected_failures,
        "One or more expected-healthy/flaky sources failed or did not reach the target period.",
        {"issues": unexpected_failures[:20], "count": len(unexpected_failures)},
    )
    check_result(
        checks,
        "retry_hotspots",
        WARNING,
        not retry_hotspots,
        "One or more sources had a high retry ratio but may still have completed.",
        {"hotspots": retry_hotspots[:20], "count": len(retry_hotspots)},
    )

    global_retry_ratio = total_retried / total_requests if total_requests else 0
    if total_requests >= thresholds["global_retry_min_requests"] and global_retry_ratio >= thresholds["global_retry_fail_ratio"]:
        check_result(
            checks,
            "global_retry_pressure",
            FAIL,
            False,
            "Global retry pressure exceeds the fail threshold.",
            {"requests_total": total_requests, "retried_requests": total_retried, "ratio": round(global_retry_ratio, 3)},
        )
    elif total_requests >= thresholds["global_retry_min_requests"] and global_retry_ratio >= thresholds["global_retry_warning_ratio"]:
        check_result(
            checks,
            "global_retry_pressure",
            WARNING,
            False,
            "Global retry pressure exceeds the warning threshold.",
            {"requests_total": total_requests, "retried_requests": total_retried, "ratio": round(global_retry_ratio, 3)},
        )
    else:
        check_result(
            checks,
            "global_retry_pressure",
            WARNING,
            True,
            "Global retry pressure is within threshold or unavailable.",
            {"requests_total": total_requests, "retried_requests": total_retried, "ratio": round(global_retry_ratio, 3)},
        )

    if missing_network_diagnostics:
        checks.append(
            {
                "id": "network_diagnostics_optional_fields",
                "severity": INFO,
                "result": INFO,
                "message": "Some historical source statuses do not include Stage-2 network diagnostics fields.",
                "evidence": {"sources": missing_network_diagnostics[:20], "count": len(missing_network_diagnostics)},
            }
        )

    return checks, {
        "source_health": source_health,
        "known_gaps": known_gaps,
        "recovered_sources": recovered_sources,
        "unexpected_failures": unexpected_failures,
        "retry_hotspots": retry_hotspots,
        "global_retry": {
            "requests_total": total_requests,
            "retried_requests": total_retried,
            "retry_ratio": round(global_retry_ratio, 3),
        },
    }


def final_status(checks):
    if any(check["severity"] == FAIL and check["result"] == FAIL for check in checks):
        return FAIL
    if any(check["result"] == WARNING for check in checks):
        return WARNING
    return PASS


def publish_recommendation(status):
    return {
        PASS: "ready_for_manual_review",
        WARNING: "manual_review_required",
        FAIL: "do_not_publish",
    }[status]


def evaluate_qa(weekly_payload, source_statuses, policy, sources, today=None):
    week_start = parse_item_date(weekly_payload.get("week_start"))
    week_end = parse_item_date(weekly_payload.get("week_end"))
    if not week_start or not week_end:
        raise ValueError("weekly payload must include parseable week_start and week_end")

    content_checks, content_issues, content_summary = evaluate_content(weekly_payload, week_start, week_end)
    source_checks, source_result = evaluate_source_health(source_statuses, policy, sources)
    checks = content_checks + source_checks
    status = final_status(checks)
    summary = {
        "final_items": content_summary["final_items"],
        "highlights": content_summary["highlights"],
        "source_count": weekly_payload.get("source_count", len(source_statuses)),
        "registered_source_count": weekly_payload.get("registered_source_count", ""),
        "source_status_count": len(source_statuses),
        "pipeline_counts": weekly_payload.get("pipeline_counts", {}),
        "translation_mode": weekly_payload.get("translation_mode", ""),
    }
    return {
        "week_start": str(week_start),
        "week_end": str(week_end),
        "status": status,
        "summary": summary,
        "checks": checks,
        "source_health": source_result["source_health"],
        "retry_hotspots": source_result["retry_hotspots"],
        "content_issues": content_issues,
        "known_gaps": source_result["known_gaps"],
        "recovered_sources": source_result["recovered_sources"],
        "unexpected_failures": source_result["unexpected_failures"],
        "global_retry": source_result["global_retry"],
        "publish_recommendation": publish_recommendation(status),
        "translation_mode": weekly_payload.get("translation_mode", ""),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def render_markdown(report):
    failed = [check for check in report["checks"] if check["result"] == FAIL]
    warnings = [check for check in report["checks"] if check["result"] == WARNING]
    lines = [
        "# Weekly QA Report",
        "",
        f"Status: {report['status']}",
        "",
        "## Summary",
        "",
        f"- Week: {report['week_start']} to {report['week_end']}",
        f"- Final items: {report['summary']['final_items']}",
        f"- Highlights: {report['summary']['highlights']}",
        f"- Translation mode: {report.get('translation_mode', '') or 'unknown'}",
        f"- Publish recommendation: {report['publish_recommendation']}",
        "",
        "## Blocking Issues",
        "",
    ]
    lines.extend([f"- {check['id']}: {check['message']}" for check in failed] or ["None"])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {check['id']}: {check['message']}" for check in warnings] or ["None"])
    lines.extend(["", "## Known Gaps", ""])
    lines.extend([f"- {gap['source']} ({gap['source_id']}): {gap['status']}" for gap in report["known_gaps"]] or ["None"])
    lines.extend(["", "## Retry Hotspots", ""])
    lines.extend(
        [
            f"- {hotspot['source']} ({hotspot['source_id']}): {hotspot['retried_requests']}/{hotspot['requests_total']} requests retried ({hotspot['retry_ratio']})"
            for hotspot in report["retry_hotspots"]
        ]
        or ["None"]
    )
    lines.extend(["", "## Source Health", ""])
    lines.append(json.dumps(report["source_health"], ensure_ascii=False, indent=2))
    lines.extend(["", "## Content QA", ""])
    lines.append(json.dumps(report["content_issues"][:20], ensure_ascii=False, indent=2))
    return "\n".join(lines) + "\n"


def write_reports(report, output_dir=OUTPUT_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)
    key = report["week_start"].replace("-", "")
    json_path = output_dir / f"qa_report_{key}.json"
    md_path = output_dir / f"qa_report_{key}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def qa_exit_code(status, fail_on_warning=False):
    if status == FAIL:
        return 2
    if status == WARNING and fail_on_warning:
        return 1
    return 0


def artifact_paths(start, output_dir=OUTPUT_DIR):
    week_start, _ = parse_week_start(start)
    key = week_file_key(week_start)
    output_dir = Path(output_dir)
    return output_dir / f"weekly_data_{key}.json", output_dir / f"source_status_{key}.json"


def run_qa(
    start=None,
    weekly_data_path=None,
    source_status_path=None,
    policy_path=POLICY_FILE,
    sources_path=SOURCE_FILE,
    fail_on_warning=False,
    write_report_files=True,
    expected_week_start=None,
    output_dir=OUTPUT_DIR,
):
    if weekly_data_path and source_status_path:
        weekly_path = Path(weekly_data_path)
        status_path = Path(source_status_path)
    elif start:
        weekly_path, status_path = artifact_paths(start, output_dir=output_dir)
    else:
        raise QAExecutionError("Provide start or both weekly_data_path and source_status_path.")

    if not weekly_path.exists():
        raise QAExecutionError(f"Weekly data artifact not found: {weekly_path}")
    if not status_path.exists():
        raise QAExecutionError(f"Source status artifact not found: {status_path}")

    weekly_payload = load_json(weekly_path)
    source_statuses = load_json(status_path)
    policy = load_policy(policy_path)
    sources = load_sources(sources_path)

    if expected_week_start is not None:
        expected_start = parse_item_date(expected_week_start)
        payload_start = parse_item_date(weekly_payload.get("week_start"))
        if not expected_start:
            raise QAExecutionError(f"Expected week_start is not parseable: {expected_week_start}")
        if payload_start != expected_start:
            raise QAExecutionError(
                f"Weekly data week_start mismatch: expected {expected_start}, got {weekly_payload.get('week_start')}"
            )

    report = evaluate_qa(weekly_payload, source_statuses, policy, sources)
    report["input_artifacts"] = {
        "weekly_data": str(weekly_path),
        "weekly_data_sha256": file_sha256(weekly_path),
        "source_status": str(status_path),
        "source_status_sha256": file_sha256(status_path),
    }
    json_path = None
    md_path = None
    if write_report_files:
        json_path, md_path = write_reports(report, output_dir=output_dir)

    return {
        "status": report["status"],
        "exit_code": qa_exit_code(report["status"], fail_on_warning=fail_on_warning),
        "report": report,
        "json_path": json_path,
        "md_path": md_path,
        "blocking_count": sum(1 for check in report["checks"] if check["result"] == FAIL),
        "warning_count": sum(1 for check in report["checks"] if check["result"] == WARNING),
        "known_gap_count": len(report["known_gaps"]),
        "publish_recommendation": report["publish_recommendation"],
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate weekly report artifacts with a QA gate.")
    parser.add_argument("--start", help="Target week Monday in YYYY-MM-DD format.")
    parser.add_argument("--weekly-data", help="Path to weekly_data JSON.")
    parser.add_argument("--source-status", help="Path to source_status JSON.")
    parser.add_argument("--policy", default=str(POLICY_FILE), help="Path to QA policy JSON.")
    parser.add_argument("--sources", default=str(SOURCE_FILE), help="Path to sources.json.")
    parser.add_argument("--fail-on-warning", action="store_true", help="Return non-zero for WARNING as well as FAIL.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Directory for default weekly/QA artifacts.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        result = run_qa(
            start=args.start,
            weekly_data_path=args.weekly_data,
            source_status_path=args.source_status,
            policy_path=args.policy,
            sources_path=args.sources,
            fail_on_warning=args.fail_on_warning,
            output_dir=args.output_dir,
        )
    except QAExecutionError as exc:
        print(f"QA EXECUTION ERROR: {exc}", file=sys.stderr)
        return 3

    report = result["report"]
    failed = [check for check in report["checks"] if check["result"] == FAIL]
    warnings = [check for check in report["checks"] if check["result"] == WARNING]
    print(f"QA STATUS: {report['status']}")
    print(f"Week: {report['week_start']} to {report['week_end']}")
    print(f"Final items: {report['summary']['final_items']}")
    print(f"Highlights: {report['summary']['highlights']}")
    print("Blocking issues:")
    print("None" if not failed else "\n".join(f"- {check['id']}: {check['message']}" for check in failed))
    print("Warnings:")
    print("None" if not warnings else "\n".join(f"- {check['id']}: {check['message']}" for check in warnings[:10]))
    print("Known gaps:")
    print("None" if not report["known_gaps"] else "\n".join(f"- {gap['source']}: {gap['status']}" for gap in report["known_gaps"][:10]))
    print(f"Report: {result['json_path']}")
    print(f"Markdown: {result['md_path']}")

    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
