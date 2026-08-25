import html
from datetime import timedelta

import requests
from bs4 import BeautifulSoup

from .date_utils import in_week
from .news_model import standardize_news


HEADERS = {
    "User-Agent": "Mozilla/5.0 weekly-report-contact",
    "Accept": "application/json",
}


def _plain_text(value):
    text = BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)
    return " ".join(html.unescape(text).split())


def _rendered(value):
    if isinstance(value, dict):
        return value.get("rendered", "")
    return value or ""


def collect_wp_json(source, week_start, week_end, logger):
    results = []
    raw_items = []
    error = ""
    sample_candidates = []
    dated_candidates = 0
    date_parse_failed = 0
    newest_date_seen = ""
    oldest_date_seen = ""
    pages_scanned = 0

    logger.info("WP JSON start: %s", source["name"])

    list_url = source.get("crawl_url") or source["url"]
    params = {
        "per_page": int(source.get("api_per_page") or 50),
        "orderby": "date",
        "order": "desc",
        "after": f"{week_start}T00:00:00",
        "before": f"{week_end + timedelta(days=1)}T00:00:00",
    }

    try:
        response = requests.get(list_url, headers=HEADERS, params=params, timeout=20)
        response.raise_for_status()
        pages_scanned = 1
        entries = response.json()
        if not isinstance(entries, list):
            raise ValueError("WordPress JSON endpoint did not return a list")

        logger.info("WP JSON candidate count for %s: %s", source["name"], len(entries))

        for entry in entries:
            raw_date = entry.get("date") or entry.get("date_gmt") or ""
            title = _plain_text(_rendered(entry.get("title")))
            summary = _plain_text(_rendered(entry.get("excerpt")))
            item = standardize_news(
                source=source,
                title=title,
                url=entry.get("link", ""),
                date=raw_date,
                summary=summary,
            )
            raw_items.append(item)

            diagnostic = {
                "title": item["title_original"],
                "url": item["url"],
                "raw_date": raw_date,
                "parsed_date": item["date"],
                "drop_reason": "",
            }

            if item["date"]:
                dated_candidates += 1
                newest_date_seen = max(newest_date_seen, item["date"]) if newest_date_seen else item["date"]
                oldest_date_seen = min(oldest_date_seen, item["date"]) if oldest_date_seen else item["date"]
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
        logger.info("WP JSON success: %s filtered=%s kept=%s", source["name"], len(results), len(results))

    except Exception as exc:
        error = str(exc)
        logger.exception("WP JSON failed: %s reason=%s", source["name"], exc)

    return raw_items, results, {
        "error": error,
        "list_url": response.url if not error else list_url,
        "candidates": len(raw_items),
        "candidates_discovered": len(raw_items),
        "candidates_scanned": len(raw_items),
        "pages_scanned": pages_scanned,
        "list_items_with_date": dated_candidates,
        "detail_pages_requested": 0,
        "dated_candidates": dated_candidates,
        "date_parse_failed": date_parse_failed,
        "newest_date_seen": newest_date_seen,
        "oldest_date_seen": oldest_date_seen,
        "target_period_reached": not error,
        "stopped_reason": "date_bounded_official_api" if not error else "",
        "sample_candidates": sample_candidates,
    }
