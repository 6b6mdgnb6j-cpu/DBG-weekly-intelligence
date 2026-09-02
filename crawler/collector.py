import json
import logging
from pathlib import Path

from .content_filter import apply_relevance, audit_rejection
from .competitor_mapping import apply_competitor_mapping
from .date_utils import parse_week_start, week_file_key
from .dedupe import dedupe_news
from .event_cluster import cluster_same_event_items
from .news_model import ensure_news_schema
from .official_source_parser import (
    collect_cboe_press,
    collect_clearstream_search,
    collect_ice_q4,
    collect_lseg_search,
    collect_msci_rss,
    collect_nasdaq_press,
    collect_simcorp_sitemap,
)
from .rss_parser import collect_rss
from .translator import TitleTranslator
from .web_parser import collect_web
from .wp_json_parser import collect_wp_json


BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_FILE = BASE_DIR / "config" / "sources.json"
RAW_DIR = BASE_DIR / "raw"
LOG_DIR = BASE_DIR / "logs"
OUTPUT_DIR = BASE_DIR / "output"
LEGACY_DATA_FILE = BASE_DIR / "data" / "news.json"


def load_sources():
    with open(SOURCE_FILE, encoding="utf-8") as f:
        return json.load(f)


def setup_logger(start):
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"collect_{week_file_key(start)}.log"

    logger = logging.getLogger("weekly_report.collector")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger, log_file


def save_json(path, data):
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def empty_status(source):
    return {
        "source": source.get("name", ""),
        "status": "success",
        "method": source.get("method", ""),
        "list_url": source.get("crawl_url") or source.get("url", ""),
        "candidates": 0,
        "candidates_discovered": 0,
        "candidates_scanned": 0,
        "pages_scanned": 0,
        "list_items_with_date": 0,
        "detail_pages_requested": 0,
        "dated_candidates": 0,
        "date_parse_failed": 0,
        "non_news_candidates": 0,
        "newest_date_seen": "",
        "oldest_date_seen": "",
        "target_period_reached": False,
        "stopped_reason": "",
        "within_period": 0,
        "after_relevance": 0,
        "final_items": 0,
        "sample_candidates": [],
        "relevance_rejected_samples": [],
        "error": "",
    }


def classify_error(error):
    error_lower = (error or "").lower()
    if not error:
        return ""
    if "403" in error_lower or "blocked" in error_lower:
        return "blocked"
    if (
        "timeout" in error_lower
        or "connection" in error_lower
        or "resolve" in error_lower
        or "ssl" in error_lower
        or "502" in error_lower
        or "503" in error_lower
        or "504" in error_lower
        or "bad gateway" in error_lower
    ):
        return "network_error"
    return "parser_failed"


def classify_empty_status(status, source):
    if status["error"]:
        return classify_error(status["error"])
    if source.get("method") == "wp_json" and status.get("target_period_reached") and status["candidates"] == 0:
        return "true_no_updates"
    if status["candidates"] == 0:
        return "no_candidates"
    if status["dated_candidates"] == 0:
        return "date_parse_failed"
    date_bounded_methods = {
        "rss",
        "wp_json",
        "simcorp_sitemap",
        "clearstream_search",
        "lseg_search",
        "nasdaq_press",
        "cboe_press",
        "ice_q4",
        "msci_rss",
    }
    if status["within_period"] == 0:
        if status["date_parse_failed"] > status["dated_candidates"]:
            return "date_parse_failed"
        if source.get("method") == "web" and not status.get("target_period_reached"):
            return "parser_failed"
        if source.get("method") in date_bounded_methods and status.get("target_period_reached"):
            return "true_no_updates"
        return "all_outside_period"
    if status["after_relevance"] == 0:
        return "relevance_filtered"
    if status["final_items"] == 0:
        return "parser_failed"
    return "success"


def strip_internal_fields(item):
    clean = dict(item)
    clean.pop("relevance_context", None)
    return clean


def collect_week(start_arg=None, translate=True):
    week_start, week_end = parse_week_start(start_arg)
    logger, log_file = setup_logger(week_start)
    sources = load_sources()
    enabled_sources = [source for source in sources if source.get("enabled", True)]

    logger.info("Weekly collection started: %s to %s", week_start, week_end)
    logger.info("Source count: %s enabled=%s", len(sources), len(enabled_sources))

    raw_items = []
    filtered_items = []
    source_statuses = []

    for source in enabled_sources:
        name = source.get("name", "")
        method = source.get("method", "")
        logger.info("Source begin: %s method=%s", name, method)
        status = empty_status(source)

        try:
            technical_status = source.get("technical_status", "")
            if technical_status == "js_required":
                status["status"] = "js_required"
                status["error"] = "marked as JS-rendered source during technical classification"
                source_statuses.append(status)
                logger.info("Source skipped: %s reason=js_required", name)
                continue
            if technical_status == "blocked":
                status["status"] = "blocked"
                status["error"] = "marked as blocked during technical classification"
                source_statuses.append(status)
                logger.info("Source skipped: %s reason=blocked", name)
                continue

            if not source.get("url"):
                status["status"] = "invalid_config"
                status["error"] = "missing url"
                source_statuses.append(status)
                logger.error("Source failed: %s reason=missing url", name)
                continue

            if method == "rss":
                source_raw, source_filtered, meta = collect_rss(source, week_start, week_end, logger)
            elif method == "wp_json":
                source_raw, source_filtered, meta = collect_wp_json(source, week_start, week_end, logger)
            elif method == "simcorp_sitemap":
                source_raw, source_filtered, meta = collect_simcorp_sitemap(source, week_start, week_end, logger)
            elif method == "clearstream_search":
                source_raw, source_filtered, meta = collect_clearstream_search(source, week_start, week_end, logger)
            elif method == "lseg_search":
                source_raw, source_filtered, meta = collect_lseg_search(source, week_start, week_end, logger)
            elif method == "nasdaq_press":
                source_raw, source_filtered, meta = collect_nasdaq_press(source, week_start, week_end, logger)
            elif method == "cboe_press":
                source_raw, source_filtered, meta = collect_cboe_press(source, week_start, week_end, logger)
            elif method == "ice_q4":
                source_raw, source_filtered, meta = collect_ice_q4(source, week_start, week_end, logger)
            elif method == "msci_rss":
                source_raw, source_filtered, meta = collect_msci_rss(source, week_start, week_end, logger)
            elif method == "web":
                source_raw, source_filtered, meta = collect_web(source, week_start, week_end, logger)
            else:
                logger.error("Source failed: %s reason=unsupported method %s", name, method)
                status["status"] = "invalid_config"
                status["error"] = f"unsupported method {method}"
                source_statuses.append(status)
                continue

            raw_items.extend(ensure_news_schema(item) for item in source_raw)
            capped = source_filtered[: int(source.get("max_items") or 10)]
            filtered_items.extend(ensure_news_schema(item) for item in capped)
            status["candidates"] = int(meta.get("candidates") or len(source_raw))
            status["candidates_discovered"] = int(meta.get("candidates_discovered") or status["candidates"])
            status["candidates_scanned"] = int(meta.get("candidates_scanned") or status["candidates"])
            status["pages_scanned"] = int(meta.get("pages_scanned") or 0)
            status["list_items_with_date"] = int(meta.get("list_items_with_date") or 0)
            status["detail_pages_requested"] = int(meta.get("detail_pages_requested") or 0)
            status["dated_candidates"] = int(meta.get("dated_candidates") or 0)
            status["date_parse_failed"] = int(meta.get("date_parse_failed") or 0)
            status["non_news_candidates"] = int(meta.get("non_news_candidates") or 0)
            status["newest_date_seen"] = meta.get("newest_date_seen", "")
            status["oldest_date_seen"] = meta.get("oldest_date_seen", "")
            status["target_period_reached"] = bool(meta.get("target_period_reached", method == "rss"))
            status["stopped_reason"] = meta.get("stopped_reason", "")
            status["within_period"] = len(source_filtered)
            status["sample_candidates"] = meta.get("sample_candidates", [])[:3]
            status["list_url"] = meta.get("list_url", status["list_url"])
            status["error"] = meta.get("error", "")

            source_statuses.append(status)
            logger.info(
                "Source success: %s raw=%s date_filtered=%s final_kept=%s",
                name,
                len(source_raw),
                len(source_filtered),
                len(capped),
            )

        except Exception as exc:
            logger.exception("Source failed: %s reason=%s", name, exc)
            status["status"] = "parser_failed"
            status["error"] = str(exc)
            source_statuses.append(status)

    raw_path = RAW_DIR / f"weekly_{week_start:%Y%m%d}_{week_end:%Y%m%d}.json"
    save_json(raw_path, raw_items)
    logger.info("Raw saved: %s items=%s", raw_path, len(raw_items))

    relevant, relevance_reviewed = apply_relevance(filtered_items)
    relevant = [strip_internal_fields(item) for item in relevant]
    logger.info("Relevance filtered: before=%s after=%s", len(filtered_items), len(relevant))

    deduped = dedupe_news(relevant)
    logger.info("Deduped: before=%s after=%s", len(relevant), len(deduped))

    clustered, same_event_clustered_samples = cluster_same_event_items(deduped)
    logger.info(
        "Same-event clustered: before=%s after=%s dropped=%s",
        len(deduped),
        len(clustered),
        len(same_event_clustered_samples),
    )

    after_relevance_by_source = {}
    for item in relevant:
        after_relevance_by_source[item.get("source", "")] = after_relevance_by_source.get(item.get("source", ""), 0) + 1

    relevant_keys = {
        (item.get("source", ""), item.get("url", ""), item.get("title_original", ""))
        for item in relevant
    }
    rejected_by_source = {}
    relevance_rejected = []
    for item in relevance_reviewed:
        key = (item.get("source", ""), item.get("url", ""), item.get("title_original", ""))
        if key in relevant_keys:
            continue
        rejected = {
            "source": item.get("source", ""),
            "title": item.get("title_original", ""),
            "date": item.get("date", ""),
            "relevance_score": int(item.get("relevance_score") or 0),
            "relevance_reason": item.get("relevance_reason", ""),
            "rejection_reason": "below_relevance_threshold",
            "url": item.get("url", ""),
        }
        rejected.update(audit_rejection(item))
        relevance_rejected.append(rejected)
        rejected_by_source.setdefault(item.get("source", ""), []).append(rejected)

    final_by_source = {}
    for item in clustered:
        final_by_source[item.get("source", "")] = final_by_source.get(item.get("source", ""), 0) + 1

    enabled_by_name = {source.get("name", ""): source for source in enabled_sources}
    for status in source_statuses:
        name = status["source"]
        status["after_relevance"] = after_relevance_by_source.get(name, 0)
        status["final_items"] = final_by_source.get(name, 0)
        if status["within_period"] > 0 and status["after_relevance"] == 0:
            status["relevance_rejected_samples"] = rejected_by_source.get(name, [])[:5]
        if status["status"] == "success":
            status["status"] = classify_empty_status(status, enabled_by_name.get(name, {}))

    mapped_items = apply_competitor_mapping(clustered)
    translated = TitleTranslator(enabled=translate, logger=logger).translate(mapped_items)

    weekly_payload = {
        "week_start": str(week_start),
        "week_end": str(week_end),
        "source_count": len(enabled_sources),
        "registered_source_count": len(sources),
        "item_count": len(translated),
        "pipeline_counts": {
            "candidates": sum(status["candidates"] for status in source_statuses),
            "candidates_scanned": sum(status["candidates_scanned"] for status in source_statuses),
            "list_items_with_date": sum(status["list_items_with_date"] for status in source_statuses),
            "detail_pages_requested": sum(status["detail_pages_requested"] for status in source_statuses),
            "valid_dates": sum(status["dated_candidates"] for status in source_statuses),
            "within_target_week": sum(status["within_period"] for status in source_statuses),
            "after_relevance_filter": len(relevant),
            "after_dedupe": len(deduped),
            "same_event_clustered_count": len(same_event_clustered_samples),
            "after_same_event_cluster": len(clustered),
            "final_weekly_items": len(translated),
        },
        "same_event_clustered_samples": same_event_clustered_samples[:20],
        "items": translated,
    }

    weekly_data_path = OUTPUT_DIR / f"weekly_data_{week_file_key(week_start)}.json"
    status_path = OUTPUT_DIR / f"source_status_{week_file_key(week_start)}.json"
    rejected_path = OUTPUT_DIR / f"relevance_rejected_{week_file_key(week_start)}.json"
    save_json(weekly_data_path, weekly_payload)
    save_json(status_path, source_statuses)
    save_json(rejected_path, relevance_rejected)
    save_json(LEGACY_DATA_FILE, translated)

    logger.info("Weekly data saved: %s items=%s", weekly_data_path, len(translated))
    logger.info("Source status saved: %s", status_path)
    logger.info("Relevance rejected saved: %s items=%s", rejected_path, len(relevance_rejected))
    logger.info("Legacy data saved: %s", LEGACY_DATA_FILE)

    summary = {}
    for status in source_statuses:
        summary[status["status"]] = summary.get(status["status"], 0) + 1
    logger.info("Source status summary: %s", summary)
    logger.info(
        "Pipeline counts: candidates=%s valid_dates=%s within_week=%s relevant=%s after_dedupe=%s same_event_clustered=%s final=%s",
        weekly_payload["pipeline_counts"]["candidates"],
        weekly_payload["pipeline_counts"]["valid_dates"],
        weekly_payload["pipeline_counts"]["within_target_week"],
        weekly_payload["pipeline_counts"]["after_relevance_filter"],
        weekly_payload["pipeline_counts"]["after_dedupe"],
        weekly_payload["pipeline_counts"]["same_event_clustered_count"],
        weekly_payload["pipeline_counts"]["final_weekly_items"],
    )

    return {
        "week_start": week_start,
        "week_end": week_end,
        "raw_path": raw_path,
        "log_path": log_file,
        "weekly_data_path": weekly_data_path,
        "source_status_path": status_path,
        "relevance_rejected_path": rejected_path,
        "items": translated,
        "source_count": len(enabled_sources),
        "registered_source_count": len(sources),
        "source_status_summary": summary,
        "pipeline_counts": weekly_payload["pipeline_counts"],
    }


def main():
    result = collect_week()
    print(f"Finished: {len(result['items'])} news")


if __name__ == "__main__":
    main()
