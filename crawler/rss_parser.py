import feedparser

from .adapters.common import request_get
from .date_utils import in_week
from .news_model import standardize_news


HEADERS = {
    "User-Agent": "Mozilla/5.0 weekly-report-contact",
}


def collect_rss(source, week_start, week_end, logger):
    results = []
    raw_items = []
    error = ""
    sample_candidates = []
    dated_candidates = 0
    date_parse_failed = 0
    network_meta = {}

    logger.info("RSS start: %s", source["name"])

    try:
        list_url = source.get("crawl_url") or source["url"]
        response = request_get(list_url, headers=HEADERS, timeout=20, attempts=3, meta=network_meta)
        feed = feedparser.parse(response.text)
        entries = list(feed.entries)
        logger.info("RSS candidate count for %s: %s", source["name"], len(entries))

        for entry in entries:
            date = (
                entry.get("published")
                or entry.get("updated")
                or entry.get("created")
                or ""
            )
            item = standardize_news(
                source=source,
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                date=date,
                summary=entry.get("summary", ""),
            )
            raw_items.append(item)
            diagnostic = {
                "title": item["title_original"],
                "url": item["url"],
                "raw_date": date,
                "parsed_date": item["date"],
                "drop_reason": "",
            }

            if item["date"]:
                dated_candidates += 1
            else:
                date_parse_failed += 1
                diagnostic["drop_reason"] = "date_parse_failed"
                if len(sample_candidates) < 3:
                    sample_candidates.append(diagnostic)
                continue

            if not in_week(item["date"], week_start, week_end):
                diagnostic["drop_reason"] = "outside_period"
                if len(sample_candidates) < 3:
                    sample_candidates.append(diagnostic)
                continue

            diagnostic["drop_reason"] = "kept"
            if len(sample_candidates) < 3:
                sample_candidates.append(diagnostic)
            results.append(item)

        max_items = int(source.get("max_items") or 10)
        results = results[:max_items]
        logger.info(
            "RSS success: %s filtered=%s kept=%s",
            source["name"],
            len(results),
            len(results),
        )

    except Exception as exc:
        error = str(exc)
        logger.exception("RSS failed: %s reason=%s", source["name"], exc)

    return raw_items, results, {
        "error": error,
        "list_url": source.get("crawl_url") or source["url"],
        "candidates": len(raw_items),
        "dated_candidates": dated_candidates,
        "date_parse_failed": date_parse_failed,
        "sample_candidates": sample_candidates,
        "requests_total": int(network_meta.get("requests_total") or 0),
        "request_attempts_total": int(network_meta.get("request_attempts_total") or 0),
        "retried_requests": int(network_meta.get("retried_requests") or 0),
        "last_retry_error": network_meta.get("last_retry_error", ""),
        "last_request_error": network_meta.get("last_request_error", ""),
        "last_network_error": network_meta.get("last_request_error", "") if error else "",
        "final_network_error": network_meta.get("last_request_error", "") if error else "",
        "last_status_code": network_meta.get("last_status_code", ""),
    }
