import feedparser
from bs4 import BeautifulSoup

from .common import absolute_url, request_get
from ..date_utils import in_week, parse_date_for_source
from ..news_model import normalize_text_encoding, standardize_news


CME_FEEDS = [
    {
        "feed_key": "press_releases",
        "feed_name": "All Press Releases",
        "url": "https://feeds.feedburner.com/mediaroom/CMsF",
        "feed_type": "press_release",
        "business_category": "strategic_product_business",
        "date_semantics": "publication_date",
        "detail_required": False,
    },
    {
        "feed_key": "globex_notices",
        "feed_name": "CME Globex Notices",
        "url": "https://feeds.feedburner.com/GlobexAdvisories",
        "feed_type": "technical_notice",
        "business_category": "trading_infrastructure",
        "date_semantics": "notice_publication_date_with_detail_effective_dates",
        "detail_required": True,
    },
]

CME_PRESS_FEED = CME_FEEDS[0]
CME_GLOBEX_FEED = CME_FEEDS[1]

CME_RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 weekly-report-contact",
    "Accept": "application/rss+xml,application/xml,text/xml,*/*",
}

CME_DETAIL_HEADERS = {
    "User-Agent": "Mozilla/5.0 weekly-report-contact",
    "Accept": "text/html,application/xhtml+xml,*/*",
}

GLOBEX_GENERIC_TITLE_PREFIX = "cme globex notice:"
GLOBEX_POSITIVE_TERMS = (
    "cme globex",
    "globex",
    "protocol",
    "connectivity",
    "order entry",
    "market data",
    "matching",
    "trading hours",
    "new product",
    "product launch",
    "launch",
    "contract",
    "futures",
    "options",
    "market structure",
    "trading infrastructure",
)
GLOBEX_MATERIAL_ACTION_TERMS = (
    "launch",
    "support",
    "change",
    "changes",
    "update",
    "updates",
    "available",
    "introduced",
    "expanded",
    "migration",
    "enhancement",
    "new",
)
GLOBEX_ROUTINE_TERMS = (
    "maintenance window",
    "scheduled maintenance",
    "test environment",
    "testing",
    "certification",
    "reminder",
    "deadline",
    "updated timeline",
)


def _empty_meta(source, list_url):
    return {
        "error": "",
        "list_url": list_url,
        "feed_used": ", ".join(feed["feed_name"] for feed in CME_FEEDS),
        "feed_key": ",".join(feed["feed_key"] for feed in CME_FEEDS),
        "feed_stats": [],
        "candidates": 0,
        "candidates_discovered": 0,
        "candidates_scanned": 0,
        "pages_scanned": 0,
        "list_items_with_date": 0,
        "detail_pages_requested": 0,
        "dated_candidates": 0,
        "date_parse_failed": 0,
        "before_source_filter": 0,
        "after_source_filter": 0,
        "newest_date_seen": "",
        "oldest_date_seen": "",
        "target_period_reached": False,
        "stopped_reason": "",
        "sample_candidates": [],
        "requests_total": 0,
        "request_attempts_total": 0,
        "retried_requests": 0,
        "last_retry_error": "",
        "last_request_error": "",
        "last_network_error": "",
        "final_network_error": "",
        "last_status_code": "",
    }


def _empty_feed_stats(feed):
    return {
        "feed_key": feed["feed_key"],
        "feed_name": feed["feed_name"],
        "candidates_discovered": 0,
        "candidates_scanned": 0,
        "dated_candidates": 0,
        "date_parse_failed": 0,
        "within_period": 0,
        "after_source_filter": 0,
        "detail_pages_requested": 0,
        "newest_date_seen": "",
        "oldest_date_seen": "",
        "target_period_reached": False,
        "stopped_reason": "",
        "dropped_samples": [],
    }


def _record_date(meta, date_value, feed_stats=None):
    meta["dated_candidates"] += 1
    meta["list_items_with_date"] += 1
    iso_date = date_value.isoformat()
    if not meta["newest_date_seen"] or iso_date > meta["newest_date_seen"]:
        meta["newest_date_seen"] = iso_date
    if not meta["oldest_date_seen"] or iso_date < meta["oldest_date_seen"]:
        meta["oldest_date_seen"] = iso_date
    if feed_stats is not None:
        feed_stats["dated_candidates"] += 1
        if not feed_stats["newest_date_seen"] or iso_date > feed_stats["newest_date_seen"]:
            feed_stats["newest_date_seen"] = iso_date
        if not feed_stats["oldest_date_seen"] or iso_date < feed_stats["oldest_date_seen"]:
            feed_stats["oldest_date_seen"] = iso_date


def _sample(meta, item, raw_date, parsed_date, drop_reason):
    if len(meta["sample_candidates"]) >= 3:
        return
    meta["sample_candidates"].append(
        {
            "title": item["title_original"],
            "url": item["url"],
            "raw_date": raw_date or "",
            "parsed_date": parsed_date.isoformat() if parsed_date else "",
            "drop_reason": drop_reason,
        }
    )


def _entry_date(entry):
    return entry.get("published") or entry.get("updated") or entry.get("created") or ""


def _entry_url(entry, list_url):
    link = (entry.get("link") or "").strip()
    if not link:
        return ""
    return absolute_url(list_url, link)


def _merge_network_meta(meta, network_meta):
    meta["requests_total"] += int(network_meta.get("requests_total") or 0)
    meta["request_attempts_total"] += int(network_meta.get("request_attempts_total") or 0)
    meta["retried_requests"] += int(network_meta.get("retried_requests") or 0)
    meta["last_retry_error"] = network_meta.get("last_retry_error", "") or meta["last_retry_error"]
    meta["last_request_error"] = network_meta.get("last_request_error", "") or meta["last_request_error"]
    meta["last_status_code"] = network_meta.get("last_status_code", "") or meta["last_status_code"]


def _is_generic_globex_title(title):
    return normalize_text_encoding(title).lower().startswith(GLOBEX_GENERIC_TITLE_PREFIX)


def _has_material_globex_signal(text):
    lowered = normalize_text_encoding(text).lower()
    has_positive = any(term in lowered for term in GLOBEX_POSITIVE_TERMS)
    has_action = any(term in lowered for term in GLOBEX_MATERIAL_ACTION_TERMS)
    return has_positive and has_action


def _is_routine_globex_notice(text):
    lowered = normalize_text_encoding(text).lower()
    return any(term in lowered for term in GLOBEX_ROUTINE_TERMS) and not _has_material_globex_signal(text)


def _append_drop_sample(feed_stats, title, url, reason):
    if len(feed_stats["dropped_samples"]) >= 3:
        return
    feed_stats["dropped_samples"].append({"title": title, "url": url, "reason": reason})


def _best_detail_title(soup, fallback_title):
    for selector in ("h1", "article h2", "main h2", ".article h2", "h2", "h3"):
        element = soup.select_one(selector)
        if element:
            title = normalize_text_encoding(element.get_text(" "))
            if title and not _is_generic_globex_title(title):
                return title
    return normalize_text_encoding(fallback_title)


def _detail_paragraphs(soup):
    selectors = (
        "article p",
        "main p",
        ".article p",
        ".content p",
        ".body p",
        "p",
    )
    seen = set()
    paragraphs = []
    for selector in selectors:
        for element in soup.select(selector):
            text = normalize_text_encoding(element.get_text(" "))
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            if len(text) < 30:
                continue
            if "copyright" in key or "all rights reserved" in key:
                continue
            paragraphs.append(text)
        if paragraphs:
            break
    return paragraphs


def _parse_globex_detail(html, fallback_title):
    soup = BeautifulSoup(html or "", "html.parser")
    title = _best_detail_title(soup, fallback_title)
    paragraphs = _detail_paragraphs(soup)
    body_text = " ".join([title] + paragraphs)
    meaningful = _has_material_globex_signal(body_text) and not _is_routine_globex_notice(body_text)
    summary = ""
    for paragraph in paragraphs:
        if _has_material_globex_signal(paragraph) or not summary:
            summary = paragraph
            if _has_material_globex_signal(paragraph):
                break
    return {
        "title": title,
        "summary": summary,
        "meaningful": meaningful,
    }


def _collect_cme_feed(feed, source, week_start, week_end, logger, meta, raw_items, results, seen_urls):
    list_url = feed["url"]
    feed_stats = _empty_feed_stats(feed)
    meta["feed_stats"].append(feed_stats)
    logger.info("CME RSS feed start: %s feed=%s", source["name"], feed["feed_name"])

    network_meta = {}
    response = request_get(list_url, headers=CME_RSS_HEADERS, timeout=25, attempts=2, meta=network_meta)
    _merge_network_meta(meta, network_meta)
    feed_doc = feedparser.parse(response.text)
    entries = list(feed_doc.entries)
    max_scan = int(source.get("max_scan_candidates") or len(entries) or 20)
    meta["pages_scanned"] += 1
    meta["candidates_discovered"] += len(entries)
    meta["candidates"] += len(entries)
    feed_stats["candidates_discovered"] = len(entries)

    for entry in entries[:max_scan]:
        meta["candidates_scanned"] += 1
        feed_stats["candidates_scanned"] += 1
        title = normalize_text_encoding(entry.get("title", ""))
        url = _entry_url(entry, list_url)
        raw_date = _entry_date(entry)
        summary = normalize_text_encoding(entry.get("summary", ""), clear_garbage=True)

        if not title or not url:
            meta["date_parse_failed"] += 1
            feed_stats["date_parse_failed"] += 1
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        item = standardize_news(source, title=title, url=url, date=raw_date, summary=summary)

        parsed = parse_date_for_source(raw_date, source)
        if parsed:
            date_value = parsed.date()
            _record_date(meta, date_value, feed_stats)
            if date_value <= week_end:
                meta["target_period_reached"] = True
                feed_stats["target_period_reached"] = True
        else:
            date_value = None
            meta["date_parse_failed"] += 1
            feed_stats["date_parse_failed"] += 1

        if not date_value:
            drop_reason = "date_parse_failed"
        elif not in_week(item["date"], week_start, week_end):
            drop_reason = "outside_period"
        else:
            feed_stats["within_period"] += 1
            meta["before_source_filter"] += 1
            drop_reason = "kept"

        if drop_reason == "kept" and feed.get("detail_required"):
            meta["detail_pages_requested"] += 1
            feed_stats["detail_pages_requested"] += 1
            detail_meta = {}
            detail_response = request_get(url, headers=CME_DETAIL_HEADERS, timeout=25, attempts=2, meta=detail_meta)
            _merge_network_meta(meta, detail_meta)
            detail = _parse_globex_detail(detail_response.text, title)
            if not detail["meaningful"]:
                drop_reason = "source_filter:generic_or_routine_globex_notice"
                _append_drop_sample(feed_stats, title, url, drop_reason)
            else:
                item = standardize_news(
                    source,
                    title=detail["title"],
                    url=url,
                    date=raw_date,
                    summary=detail["summary"],
                )

        raw_items.append(item)
        _sample(meta, item, raw_date, date_value, drop_reason)

        if drop_reason == "kept":
            feed_stats["after_source_filter"] += 1
            meta["after_source_filter"] += 1
            results.append(item)

        if date_value and date_value < week_start:
            feed_stats["stopped_reason"] = "passed_target_start"
            break

    if not feed_stats["stopped_reason"]:
        feed_stats["stopped_reason"] = (
            "max_scan_candidates"
            if feed_stats["candidates_scanned"] >= max_scan and feed_stats["candidates_scanned"] < len(entries)
            else "completed"
        )


def collect_cme_press_rss(source, week_start, week_end, logger):
    list_url = source.get("crawl_url") or CME_PRESS_FEED["url"]
    meta = _empty_meta(source, list_url)
    raw_items = []
    results = []
    seen_urls = set()

    logger.info("CME RSS start: %s feeds=%s", source["name"], meta["feed_used"])

    try:
        for feed in CME_FEEDS:
            _collect_cme_feed(feed, source, week_start, week_end, logger, meta, raw_items, results, seen_urls)
        stopped = {feed["stopped_reason"] for feed in meta["feed_stats"]}
        if "error" in stopped:
            meta["stopped_reason"] = "error"
        elif "max_scan_candidates" in stopped:
            meta["stopped_reason"] = "max_scan_candidates"
        elif "completed" in stopped:
            meta["stopped_reason"] = "completed"
        else:
            meta["stopped_reason"] = "passed_target_start"

    except Exception as exc:
        meta["error"] = str(exc)
        meta["stopped_reason"] = "error"
        meta["last_network_error"] = meta.get("last_request_error", "") or str(exc)
        meta["final_network_error"] = meta["last_network_error"]
        logger.exception("CME press RSS failed: %s reason=%s", source["name"], exc)

    logger.info(
        "CME RSS success: discovered=%s scanned=%s dated=%s within=%s stopped=%s",
        meta["candidates_discovered"],
        meta["candidates_scanned"],
        meta["dated_candidates"],
        len(results),
        meta["stopped_reason"],
    )
    return raw_items, results, meta
