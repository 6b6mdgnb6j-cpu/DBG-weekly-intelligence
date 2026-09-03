import json
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from .adapters.common import request_get
from .date_utils import in_week, parse_date_for_source
from .news_model import normalize_text_encoding, standardize_news


HEADERS = {
    "User-Agent": "Mozilla/5.0 weekly-report-contact",
    "Accept": "text/html,application/xhtml+xml,application/xml,text/x-component",
}

CLEARSTREAM_ACTION = "7fab35ad2b2486b54594ca187dc07db87e015b8215"
CLEARSTREAM_ACTION_ID = "4604146"
CLEARSTREAM_TABLE_SUMMARY_TERMS = (
    "business overview",
    "change (%",
    "ytd",
    "securities deposits",
    "number of transactions",
    "assets under custody",
    "volume outstanding",
)

LSEG_SEARCH_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.lseg.com/en/media-centre/press-releases",
}

NASDAQ_PRESS_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nasdaq.com/newsroom",
}

CBOE_PRESS_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://ir.cboe.com/news/default.aspx",
}

ICE_PRESS_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://ir.theice.com/press/press-releases/default.aspx",
    "X-Requested-With": "XMLHttpRequest",
}

ASIC_MEDIA_RELEASES_URL = "https://download.asic.gov.au/asic-nga/data/newsroom/newsroom-all.json"
ASIC_MEDIA_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.asic.gov.au/newsroom/media-releases",
}


def _empty_meta(source, list_url):
    return {
        "error": "",
        "list_url": list_url,
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
        "sample_candidates": [],
    }


def _record_date(meta, date_text, source):
    parsed = parse_date_for_source(date_text, source)
    if not parsed:
        meta["date_parse_failed"] += 1
        return None
    date_value = parsed.date()
    meta["dated_candidates"] += 1
    if not meta["newest_date_seen"] or date_value.isoformat() > meta["newest_date_seen"]:
        meta["newest_date_seen"] = date_value.isoformat()
    if not meta["oldest_date_seen"] or date_value.isoformat() < meta["oldest_date_seen"]:
        meta["oldest_date_seen"] = date_value.isoformat()
    return date_value


def _record_parsed_date(meta, date_value):
    meta["dated_candidates"] += 1
    if not meta["newest_date_seen"] or date_value.isoformat() > meta["newest_date_seen"]:
        meta["newest_date_seen"] = date_value.isoformat()
    if not meta["oldest_date_seen"] or date_value.isoformat() < meta["oldest_date_seen"]:
        meta["oldest_date_seen"] = date_value.isoformat()


def _drop_reason(date_value, week_start, week_end):
    if not date_value:
        return "date_parse_failed"
    if date_value > week_end:
        return "after_period"
    if date_value < week_start:
        return "before_period"
    return "kept"


def _sample(meta, title, url, raw_date, parsed_date, drop_reason):
    if len(meta["sample_candidates"]) >= 3:
        return
    meta["sample_candidates"].append(
        {
            "title": title,
            "url": url,
            "raw_date": raw_date or "",
            "parsed_date": parsed_date.isoformat() if parsed_date else "",
            "drop_reason": drop_reason,
        }
    )


def _parse_iso_date(raw_date):
    text = (raw_date or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _field_value(data, names):
    for node in _walk(data):
        for name in names:
            value = node.get(name)
            if isinstance(value, dict) and isinstance(value.get("value"), str):
                return value["value"]
            if isinstance(value, str):
                return value
    return ""


def _simcorp_date(data):
    for node in _walk(data):
        value = node.get("Date")
        if isinstance(value, dict) and value.get("value"):
            return value["value"]
    return ""


def _simcorp_article_urls(xml_text, week_start, week_end):
    years = {week_start.year, week_end.year}
    locs = re.findall(r"<loc>(.*?)</loc>", xml_text)
    urls = []
    for url in locs:
        if not re.search(r"/about-us/news/\d{4}/[^/]+$", url):
            continue
        match = re.search(r"/about-us/news/(\d{4})/", url)
        if match and int(match.group(1)) in years:
            urls.append(url)
    return urls


def _asic_media_release_item(row):
    title = normalize_text_encoding(row.get("name", ""))
    url = urljoin("https://www.asic.gov.au", row.get("url") or "")
    raw_date = row.get("publishedDate") or ""
    summary = normalize_text_encoding(row.get("metaDescription") or "", clear_garbage=True)
    return title, url, raw_date, summary


def collect_asic_media_releases(source, week_start, week_end, logger):
    list_url = source.get("crawl_url") or ASIC_MEDIA_RELEASES_URL
    meta = _empty_meta(source, list_url)
    raw_items = []
    results = []

    logger.info("ASIC official media releases JSON start: %s", source["name"])
    try:
        response = request_get(list_url, headers=ASIC_MEDIA_HEADERS, timeout=30, attempts=2)
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("ASIC newsroom JSON did not return a list")

        media_rows = [
            row
            for row in rows
            if isinstance(row, dict) and (row.get("metaType") or "").strip().lower() == "media release"
        ]
        media_rows.sort(
            key=lambda row: _parse_iso_date(row.get("publishedDate") or "") or datetime.min.date(),
            reverse=True,
        )

        max_scan = int(source.get("max_scan_candidates") or 300)
        meta["pages_scanned"] = 1
        meta["candidates_discovered"] = len(media_rows)
        meta["candidates"] = len(media_rows)
        meta["non_news_candidates"] = max(0, len(rows) - len(media_rows))

        for row in media_rows[:max_scan]:
            title, url, raw_date, summary = _asic_media_release_item(row)
            meta["candidates_scanned"] += 1
            parsed_date = _parse_iso_date(raw_date)
            if parsed_date:
                _record_parsed_date(meta, parsed_date)
                meta["list_items_with_date"] += 1
                if parsed_date <= week_end:
                    meta["target_period_reached"] = True
            else:
                meta["date_parse_failed"] += 1

            drop_reason = _drop_reason(parsed_date, week_start, week_end)
            _sample(meta, title, url, raw_date, parsed_date, drop_reason)
            item = standardize_news(
                source,
                title=title,
                url=url,
                date=parsed_date.isoformat() if parsed_date else raw_date,
                summary=summary,
            )
            raw_items.append(item)
            if drop_reason == "kept" and in_week(item["date"], week_start, week_end):
                results.append(item)

            if parsed_date and parsed_date < week_start:
                meta["stopped_reason"] = "passed_target_start"
                break

        if not meta["stopped_reason"]:
            meta["stopped_reason"] = (
                "max_scan_candidates"
                if meta["candidates_scanned"] >= max_scan and meta["candidates_scanned"] < len(media_rows)
                else "completed"
            )

    except Exception as exc:
        meta["error"] = str(exc)
        meta["stopped_reason"] = "error"
        logger.exception("ASIC official media releases JSON failed: %s reason=%s", source["name"], exc)

    logger.info(
        "ASIC official media releases JSON success: discovered=%s scanned=%s dated=%s within=%s stopped=%s",
        meta["candidates_discovered"],
        meta["candidates_scanned"],
        meta["dated_candidates"],
        len(results),
        meta["stopped_reason"],
    )
    return raw_items, results, meta


def collect_simcorp_sitemap(source, week_start, week_end, logger):
    list_url = source.get("crawl_url") or "https://www.simcorp.com/sitemap.xml"
    meta = _empty_meta(source, list_url)
    raw_items = []
    results = []

    logger.info("SimCorp sitemap start: %s", source["name"])
    try:
        sitemap = request_get(list_url, headers=HEADERS, timeout=25, attempts=3)
        meta["pages_scanned"] = 1
        urls = _simcorp_article_urls(sitemap.text, week_start, week_end)
        meta["candidates_discovered"] = len(urls)
        meta["candidates"] = len(urls)

        max_scan = int(source.get("max_scan_candidates") or len(urls) or 50)
        for url in urls[:max_scan]:
            meta["candidates_scanned"] += 1
            meta["detail_pages_requested"] += 1
            response = request_get(url, headers=HEADERS, timeout=25, attempts=3)
            soup = BeautifulSoup(response.text, "html.parser")
            next_data = soup.find("script", id="__NEXT_DATA__")
            data = json.loads(next_data.string) if next_data and next_data.string else {}

            raw_date = _simcorp_date(data)
            title = _field_value(data, {"Title", "MetadataPageTitle", "PageTitle"})
            summary = _field_value(data, {"Description", "MetadataPageDescription", "Summary", "TeaserText"})
            if not title and soup.title:
                title = soup.title.get_text(" ", strip=True).replace("| SimCorp", "").strip()

            title = normalize_text_encoding(title)
            summary = normalize_text_encoding(summary, clear_garbage=True)
            parsed_date = _record_date(meta, raw_date, source)
            drop_reason = _drop_reason(parsed_date, week_start, week_end)
            _sample(meta, title, url, raw_date, parsed_date, drop_reason)

            item = standardize_news(source, title=title, url=url, date=raw_date, summary=summary)
            raw_items.append(item)
            if parsed_date and in_week(item["date"], week_start, week_end):
                results.append(item)

        meta["target_period_reached"] = meta["candidates_scanned"] == len(urls)
        meta["stopped_reason"] = (
            "completed_official_sitemap_year_scan"
            if meta["target_period_reached"]
            else "max_scan_candidates"
        )

    except Exception as exc:
        meta["error"] = str(exc)
        meta["stopped_reason"] = "error"
        logger.exception("SimCorp sitemap failed: %s reason=%s", source["name"], exc)

    logger.info(
        "SimCorp sitemap success: discovered=%s scanned=%s dated=%s within=%s stopped=%s",
        meta["candidates_discovered"],
        meta["candidates_scanned"],
        meta["dated_candidates"],
        len(results),
        meta["stopped_reason"],
    )
    return raw_items, results, meta


def _lseg_search_endpoint(list_url):
    response = request_get(list_url, headers=HEADERS, timeout=25, attempts=2)
    soup = BeautifulSoup(response.text, "html.parser")
    search = soup.find(attrs={"data-ts-rehydratable": "Search"})
    endpoint = search.get("data-endpoint", "") if search else ""
    if not endpoint:
        raise ValueError("LSEG search endpoint not found on official press release page")
    return urljoin(list_url, endpoint)


def _lseg_result_item(row):
    title = normalize_text_encoding(row.get("title", ""))
    url = row.get("path") or row.get("url") or row.get("link") or ""
    raw_date = (row.get("publishedDate") or row.get("date") or "")[:10]
    summary = normalize_text_encoding(row.get("description", ""), clear_garbage=True)
    return title, url, raw_date, summary


def collect_lseg_search(source, week_start, week_end, logger):
    list_url = source.get("crawl_url") or "https://www.lseg.com/en/media-centre/press-releases"
    meta = _empty_meta(source, list_url)
    raw_items = []
    results = []

    logger.info("LSEG official search start: %s", source["name"])
    try:
        endpoint = source.get("api_url") or _lseg_search_endpoint(list_url)
        hits_per_page = int(source.get("api_per_page") or 10)
        max_pages = int(source.get("max_pages") or 8)
        max_scan = int(source.get("max_scan_candidates") or max_pages * hits_per_page)

        for page in range(1, max_pages + 1):
            if meta["candidates_scanned"] >= max_scan:
                meta["stopped_reason"] = "max_scan_candidates"
                break
            response = request_get(
                endpoint,
                headers=LSEG_SEARCH_HEADERS,
                timeout=25,
                attempts=2,
                params={"page": page, "sortBy": "w_search_date|desc"},
            )
            data = response.json()
            meta["pages_scanned"] += 1
            rows = data.get("searchResults") or []
            if not meta["candidates_discovered"]:
                meta["candidates_discovered"] = int(data.get("totalResults") or len(rows))
                meta["candidates"] = meta["candidates_discovered"]
            if not rows:
                meta["stopped_reason"] = "no_results_page"
                break

            page_has_before_target = False
            for row in rows:
                if meta["candidates_scanned"] >= max_scan:
                    meta["stopped_reason"] = "max_scan_candidates"
                    break
                title, url, raw_date, summary = _lseg_result_item(row)
                meta["candidates_scanned"] += 1
                parsed = parse_date_for_source(raw_date, source)
                if parsed:
                    date_value = parsed.date()
                    _record_parsed_date(meta, date_value)
                    meta["list_items_with_date"] += 1
                    if date_value <= week_end:
                        meta["target_period_reached"] = True
                    if date_value < week_start:
                        page_has_before_target = True
                else:
                    date_value = None
                    meta["date_parse_failed"] += 1

                drop_reason = _drop_reason(date_value, week_start, week_end)
                _sample(meta, title, url, raw_date, date_value, drop_reason)
                item = standardize_news(source, title=title, url=url, date=raw_date, summary=summary)
                raw_items.append(item)
                if drop_reason == "kept" and in_week(item["date"], week_start, week_end):
                    results.append(item)

            if meta["stopped_reason"]:
                break
            if page_has_before_target:
                meta["stopped_reason"] = "passed_target_start"
                break

        if not meta["stopped_reason"]:
            meta["stopped_reason"] = "max_pages" if meta["pages_scanned"] >= max_pages else "completed"

    except Exception as exc:
        meta["error"] = str(exc)
        meta["stopped_reason"] = "error"
        logger.exception("LSEG official search failed: %s reason=%s", source["name"], exc)

    logger.info(
        "LSEG official search success: discovered=%s scanned=%s dated=%s within=%s stopped=%s",
        meta["candidates_discovered"],
        meta["candidates_scanned"],
        meta["dated_candidates"],
        len(results),
        meta["stopped_reason"],
    )
    return raw_items, results, meta


def _nasdaq_item(row):
    title = normalize_text_encoding(row.get("node_title", ""))
    url = urljoin("https://www.nasdaq.com/", row.get("node_url", ""))
    raw_date = row.get("created_formatted", "")
    summary = normalize_text_encoding(row.get("description", ""), clear_garbage=True)
    return title, url, raw_date, summary


def _is_nasdaq_low_signal_notice(title):
    text = normalize_text_encoding(title or "").lower()
    low_signal_patterns = (
        "resumes trading in",
        "halts trading in",
        "notified of anticipated delisting",
        "regains compliance with nasdaq continued listing requirements",
        "to join the nasdaq-100 index",
        "to join the nasdaq biotechnology index",
        "announces pricing of",
        "announces closing of",
    )
    return any(pattern in text for pattern in low_signal_patterns)


def collect_nasdaq_press(source, week_start, week_end, logger):
    list_url = source.get("crawl_url") or "https://www.nasdaq.com/api/reference-group/paginated/press_release/1020126"
    meta = _empty_meta(source, list_url)
    raw_items = []
    results = []

    logger.info("Nasdaq official press JSON start: %s", source["name"])
    try:
        per_page = int(source.get("api_per_page") or 10)
        max_pages = int(source.get("max_pages") or 8)
        max_scan = int(source.get("max_scan_candidates") or max_pages * per_page)

        for page in range(1, max_pages + 1):
            if meta["candidates_scanned"] >= max_scan:
                meta["stopped_reason"] = "max_scan_candidates"
                break
            response = request_get(
                list_url,
                headers=NASDAQ_PRESS_HEADERS,
                timeout=25,
                attempts=2,
                params={"limit": per_page, "page": page},
            )
            data = response.json()
            meta["pages_scanned"] += 1
            rows = data.get("items") or []
            pagination = data.get("pagination") or {}
            if not meta["candidates_discovered"]:
                meta["candidates_discovered"] = int(pagination.get("total_items") or len(rows))
                meta["candidates"] = meta["candidates_discovered"]
            if not rows:
                meta["stopped_reason"] = "no_results_page"
                break

            page_has_before_target = False
            for row in rows:
                if meta["candidates_scanned"] >= max_scan:
                    meta["stopped_reason"] = "max_scan_candidates"
                    break
                title, url, raw_date, summary = _nasdaq_item(row)
                meta["candidates_scanned"] += 1
                parsed = parse_date_for_source(raw_date, source)
                if parsed:
                    date_value = parsed.date()
                    _record_parsed_date(meta, date_value)
                    meta["list_items_with_date"] += 1
                    if date_value <= week_end:
                        meta["target_period_reached"] = True
                    if date_value < week_start:
                        page_has_before_target = True
                else:
                    date_value = None
                    meta["date_parse_failed"] += 1

                drop_reason = _drop_reason(date_value, week_start, week_end)
                if _is_nasdaq_low_signal_notice(title):
                    meta["non_news_candidates"] += 1
                    _sample(meta, title, url, raw_date, date_value, "source_specific_low_signal_notice")
                    continue
                _sample(meta, title, url, raw_date, date_value, drop_reason)
                item = standardize_news(source, title=title, url=url, date=raw_date, summary=summary)
                raw_items.append(item)
                if drop_reason == "kept" and in_week(item["date"], week_start, week_end):
                    results.append(item)

            if meta["stopped_reason"]:
                break
            if page_has_before_target:
                meta["stopped_reason"] = "passed_target_start"
                break
            if pagination and not pagination.get("has_next"):
                meta["stopped_reason"] = "completed"
                break

        if not meta["stopped_reason"]:
            meta["stopped_reason"] = "max_pages" if meta["pages_scanned"] >= max_pages else "completed"

    except Exception as exc:
        meta["error"] = str(exc)
        meta["stopped_reason"] = "error"
        logger.exception("Nasdaq official press JSON failed: %s reason=%s", source["name"], exc)

    logger.info(
        "Nasdaq official press JSON success: discovered=%s scanned=%s dated=%s within=%s stopped=%s",
        meta["candidates_discovered"],
        meta["candidates_scanned"],
        meta["dated_candidates"],
        len(results),
        meta["stopped_reason"],
    )
    return raw_items, results, meta


def _parse_cboe_press_date(raw_date):
    text = (raw_date or "").strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(fmt))], fmt).date()
        except ValueError:
            continue
    return None


def _cboe_item(row):
    title = normalize_text_encoding(row.get("Headline", ""))
    url = urljoin("https://ir.cboe.com/", row.get("LinkToDetailPage") or row.get("LinkToUrl") or "")
    raw_date = row.get("PressReleaseDate", "")
    summary = normalize_text_encoding(row.get("ShortBody") or row.get("Subheadline") or "", clear_garbage=True)
    return title, url, raw_date, summary


def collect_cboe_press(source, week_start, week_end, logger):
    list_url = (
        source.get("crawl_url")
        or "https://ir.cboe.com/feed/PressRelease.svc/GetPressReleaseList"
    )
    meta = _empty_meta(source, list_url)
    raw_items = []
    results = []

    logger.info("Cboe official Q4 press JSON start: %s", source["name"])
    try:
        max_scan = int(source.get("max_scan_candidates") or 120)
        response = request_get(
            list_url,
            headers=CBOE_PRESS_HEADERS,
            timeout=30,
            attempts=2,
            params={
                "LanguageId": 1,
                "bodyType": 3,
                "pressReleaseDateFilter": 3,
            },
        )
        data = response.json()
        rows = data.get("GetPressReleaseListResult") or []
        meta["pages_scanned"] = 1
        meta["candidates_discovered"] = len(rows)
        meta["candidates"] = len(rows)

        for row in rows[:max_scan]:
            title, url, raw_date, summary = _cboe_item(row)
            meta["candidates_scanned"] += 1
            parsed_date = _parse_cboe_press_date(raw_date)
            if parsed_date:
                _record_parsed_date(meta, parsed_date)
                meta["list_items_with_date"] += 1
                if parsed_date <= week_end:
                    meta["target_period_reached"] = True
            else:
                meta["date_parse_failed"] += 1

            drop_reason = _drop_reason(parsed_date, week_start, week_end)
            _sample(meta, title, url, raw_date, parsed_date, drop_reason)
            item = standardize_news(source, title=title, url=url, date=parsed_date.isoformat() if parsed_date else raw_date, summary=summary)
            raw_items.append(item)
            if drop_reason == "kept" and in_week(item["date"], week_start, week_end):
                results.append(item)

            if parsed_date and parsed_date < week_start:
                meta["stopped_reason"] = "passed_target_start"
                break

        if not meta["stopped_reason"]:
            meta["stopped_reason"] = (
                "max_scan_candidates"
                if meta["candidates_scanned"] >= max_scan and meta["candidates_scanned"] < len(rows)
                else "completed"
            )

    except Exception as exc:
        meta["error"] = str(exc)
        meta["stopped_reason"] = "error"
        logger.exception("Cboe official Q4 press JSON failed: %s reason=%s", source["name"], exc)

    logger.info(
        "Cboe official Q4 press JSON success: discovered=%s scanned=%s dated=%s within=%s stopped=%s",
        meta["candidates_discovered"],
        meta["candidates_scanned"],
        meta["dated_candidates"],
        len(results),
        meta["stopped_reason"],
    )
    return raw_items, results, meta


def _parse_q4_press_date(raw_date):
    text = (raw_date or "").strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(fmt))], fmt).date()
        except ValueError:
            continue
    return None


def _ice_item(row):
    title = normalize_text_encoding(row.get("Headline", ""))
    url = urljoin("https://ir.theice.com/", row.get("LinkToDetailPage") or row.get("LinkToUrl") or "")
    raw_date = row.get("PressReleaseDate", "")
    summary = normalize_text_encoding(row.get("ShortBody") or row.get("Subheadline") or "", clear_garbage=True)
    return title, url, raw_date, summary


def _is_ice_low_signal_notice(title):
    text = normalize_text_encoding(title or "").lower()
    low_signal_patterns = (
        "to commence delisting proceedings",
        "short interest report",
        "consolidated short interest",
        "approves third quarter dividend",
        "approves quarterly dividend",
        "opens headquarters",
        "headquarters at",
    )
    return any(pattern in text for pattern in low_signal_patterns)


def collect_ice_q4(source, week_start, week_end, logger):
    list_url = (
        source.get("crawl_url")
        or "https://ir.theice.com/feed/PressRelease.svc/GetPressReleaseList"
    )
    meta = _empty_meta(source, list_url)
    raw_items = []
    results = []

    logger.info("ICE official Q4 press JSON start: %s", source["name"])
    try:
        max_scan = int(source.get("max_scan_candidates") or 120)
        response = request_get(
            list_url,
            headers=ICE_PRESS_HEADERS,
            timeout=30,
            attempts=2,
            params={
                "LanguageId": 1,
                "bodyType": 3,
                "pressReleaseDateFilter": 3,
            },
        )
        data = response.json()
        rows = data.get("GetPressReleaseListResult") or []
        meta["pages_scanned"] = 1
        meta["candidates_discovered"] = len(rows)
        meta["candidates"] = len(rows)

        for row in rows[:max_scan]:
            title, url, raw_date, summary = _ice_item(row)
            meta["candidates_scanned"] += 1
            parsed_date = _parse_q4_press_date(raw_date)
            if parsed_date:
                _record_parsed_date(meta, parsed_date)
                meta["list_items_with_date"] += 1
                if parsed_date <= week_end:
                    meta["target_period_reached"] = True
            else:
                meta["date_parse_failed"] += 1

            drop_reason = _drop_reason(parsed_date, week_start, week_end)
            _sample(meta, title, url, raw_date, parsed_date, drop_reason)
            if _is_ice_low_signal_notice(title):
                meta["non_news_candidates"] += 1
                continue
            item = standardize_news(
                source,
                title=title,
                url=url,
                date=parsed_date.isoformat() if parsed_date else raw_date,
                summary=summary,
            )
            raw_items.append(item)
            if drop_reason == "kept" and in_week(item["date"], week_start, week_end):
                results.append(item)

            if parsed_date and parsed_date < week_start:
                meta["stopped_reason"] = "passed_target_start"
                break

        if not meta["stopped_reason"]:
            meta["stopped_reason"] = (
                "max_scan_candidates"
                if meta["candidates_scanned"] >= max_scan and meta["candidates_scanned"] < len(rows)
                else "completed"
            )

    except Exception as exc:
        meta["error"] = str(exc)
        meta["stopped_reason"] = "error"
        logger.exception("ICE official Q4 press JSON failed: %s reason=%s", source["name"], exc)

    logger.info(
        "ICE official Q4 press JSON success: discovered=%s scanned=%s dated=%s within=%s stopped=%s",
        meta["candidates_discovered"],
        meta["candidates_scanned"],
        meta["dated_candidates"],
        len(results),
        meta["stopped_reason"],
    )
    return raw_items, results, meta


def collect_msci_rss(source, week_start, week_end, logger):
    list_url = source.get("crawl_url") or "https://ir.msci.com/rss/news-releases.xml"
    meta = _empty_meta(source, list_url)
    raw_items = []
    results = []

    logger.info("MSCI official RSS start: %s", source["name"])
    try:
        response = request_get(
            list_url,
            headers={"User-Agent": HEADERS["User-Agent"], "Accept": "application/rss+xml,text/xml,*/*"},
            timeout=25,
            attempts=2,
        )
        feed = feedparser.parse(response.text)
        entries = list(feed.entries)
        max_scan = int(source.get("max_scan_candidates") or len(entries) or 20)
        meta["pages_scanned"] = 1
        meta["candidates_discovered"] = len(entries)
        meta["candidates"] = len(entries)

        for entry in entries[:max_scan]:
            title = normalize_text_encoding(entry.get("title", ""))
            url = entry.get("link", "")
            raw_date = entry.get("published") or entry.get("updated") or entry.get("created") or ""
            summary = normalize_text_encoding(entry.get("summary", ""), clear_garbage=True)
            meta["candidates_scanned"] += 1

            parsed = parse_date_for_source(raw_date, source)
            if parsed:
                date_value = parsed.date()
                _record_parsed_date(meta, date_value)
                meta["list_items_with_date"] += 1
                if date_value <= week_end:
                    meta["target_period_reached"] = True
            else:
                date_value = None
                meta["date_parse_failed"] += 1

            drop_reason = _drop_reason(date_value, week_start, week_end)
            _sample(meta, title, url, raw_date, date_value, drop_reason)
            item = standardize_news(source, title=title, url=url, date=raw_date, summary=summary)
            raw_items.append(item)
            if drop_reason == "kept" and in_week(item["date"], week_start, week_end):
                results.append(item)

            if date_value and date_value < week_start:
                meta["stopped_reason"] = "passed_target_start"
                break

        if not meta["stopped_reason"]:
            meta["stopped_reason"] = (
                "max_scan_candidates"
                if meta["candidates_scanned"] >= max_scan and meta["candidates_scanned"] < len(entries)
                else "completed"
            )

    except Exception as exc:
        meta["error"] = str(exc)
        meta["stopped_reason"] = "error"
        logger.exception("MSCI official RSS failed: %s reason=%s", source["name"], exc)

    logger.info(
        "MSCI official RSS success: discovered=%s scanned=%s dated=%s within=%s stopped=%s",
        meta["candidates_discovered"],
        meta["candidates_scanned"],
        meta["dated_candidates"],
        len(results),
        meta["stopped_reason"],
    )
    return raw_items, results, meta


def _clearstream_action_headers(list_url):
    return {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/x-component",
        "Content-Type": "text/plain;charset=UTF-8",
        "Next-Action": CLEARSTREAM_ACTION,
        "Origin": "https://www.clearstream.com",
        "Referer": list_url,
    }


def _decode_clearstream_response(text):
    marker = '1:{"numFound"'
    start = text.find(marker)
    if start < 0:
        raise ValueError("Clearstream search response did not include result payload")
    payload = text[start + 2 :]
    data, _ = json.JSONDecoder().raw_decode(payload)
    return data


def _clearstream_page(list_url, offset):
    body = json.dumps([CLEARSTREAM_ACTION_ID, "", [None, None], [], "date desc", offset])
    last_error = None
    for _ in range(3):
        try:
            response = requests.post(
                list_url,
                headers=_clearstream_action_headers(list_url),
                data=body,
                timeout=25,
            )
            response.raise_for_status()
            return _decode_clearstream_response(response.text)
        except Exception as exc:
            last_error = exc
    raise last_error


def _is_clearstream_table_like_summary(summary):
    text = normalize_text_encoding(summary or "").lower().replace(" ", "")
    spaced = normalize_text_encoding(summary or "").lower()
    if "july2026july2025" in text or "ytd2026ytd2025" in text:
        return True
    term_hits = sum(1 for term in CLEARSTREAM_TABLE_SUMMARY_TERMS if term in spaced)
    numeric_tokens = re.findall(r"\b\d[\d,]*(?:\.\d+)?%?\b", summary or "")
    return term_hits >= 3 and len(numeric_tokens) >= 8


def _is_clearstream_prose(text):
    clean = normalize_text_encoding(text or "", clear_garbage=True)
    if len(clean) < 80:
        return False
    lowered = clean.lower()
    if _is_clearstream_table_like_summary(clean):
        return False
    if lowered.startswith("clearstream news:") or "complete the subscription form" in lowered:
        return False
    if lowered.startswith("*") or "due to rounding" in lowered or "figures include" in lowered:
        return False
    if "deutsche börse group" in lowered and "whistleblowers" in lowered:
        return False
    alpha_count = sum(1 for char in clean if char.isalpha())
    digit_count = sum(1 for char in clean if char.isdigit())
    if digit_count and alpha_count / max(digit_count, 1) < 2:
        return False
    return "." in clean or "," in clean or ";" in clean


def extract_clearstream_detail_summary(url):
    try:
        response = request_get(url, headers=HEADERS, timeout=20, attempts=2)
    except Exception:
        return ""
    soup = BeautifulSoup(response.text, "html.parser")
    for node in soup.find_all(
        [
            "table",
            "thead",
            "tbody",
            "tfoot",
            "tr",
            "td",
            "th",
            "caption",
            "nav",
            "header",
            "footer",
        ]
    ):
        node.decompose()

    for paragraph in soup.select("p.rt"):
        text = paragraph.get_text(" ", strip=True)
        if _is_clearstream_prose(text):
            return normalize_text_encoding(text, clear_garbage=True)[:300]
    return ""


def _clearstream_relevance_context(content):
    values = []
    for field in ("productsServices", "entities", "market"):
        for item in content.get(field) or []:
            value = normalize_text_encoding(item.get("value", ""))
            if value and value not in values:
                values.append(value)
    return " | ".join(values[:5])


def collect_clearstream_search(source, week_start, week_end, logger):
    list_url = source.get("crawl_url") or "https://www.clearstream.com/clearstream-en/newsroom"
    meta = _empty_meta(source, list_url)
    raw_items = []
    results = []

    logger.info("Clearstream official search start: %s", source["name"])
    try:
        hits_per_page = int(source.get("api_per_page") or 12)
        max_pages = int(source.get("max_pages") or 8)
        max_scan = int(source.get("max_scan_candidates") or 96)

        for page in range(max_pages):
            if meta["candidates_scanned"] >= max_scan:
                meta["stopped_reason"] = "max_scan_candidates"
                break
            data = _clearstream_page(list_url, page * hits_per_page)
            meta["pages_scanned"] += 1
            if not meta["candidates_discovered"]:
                meta["candidates_discovered"] = int(data.get("numFound") or 0)
                meta["candidates"] = meta["candidates_discovered"]
            rows = data.get("result") or []
            if not rows:
                meta["stopped_reason"] = "no_results_page"
                break

            page_has_before_target = False
            for row in rows:
                if meta["candidates_scanned"] >= max_scan:
                    meta["stopped_reason"] = "max_scan_candidates"
                    break
                content = row.get("content") or {}
                meta["candidates_scanned"] += 1

                raw_date = (content.get("date") or "")[:10]
                title = normalize_text_encoding(content.get("teaserTitle", ""))
                summary = normalize_text_encoding((content.get("teaserText") or {}).get("text", ""), clear_garbage=True)
                url = urljoin("https://www.clearstream.com/", (content.get("teaserTarget") or {}).get("url", ""))
                content_type = content.get("type", "")

                if content_type != "CSNews":
                    meta["non_news_candidates"] += 1
                    parsed_date = parse_date_for_source(raw_date, source)
                    _sample(
                        meta,
                        title,
                        url,
                        raw_date,
                        parsed_date.date() if parsed_date else None,
                        "non_news_candidate",
                    )
                    continue

                parsed_date = _record_date(meta, raw_date, source)
                if parsed_date and parsed_date <= week_end:
                    meta["target_period_reached"] = True
                if parsed_date and parsed_date < week_start:
                    page_has_before_target = True

                meta["list_items_with_date"] += 1 if parsed_date else 0
                drop_reason = _drop_reason(parsed_date, week_start, week_end)
                _sample(meta, title, url, raw_date, parsed_date, drop_reason)

                if drop_reason == "kept":
                    meta["detail_pages_requested"] += 1
                    summary = extract_clearstream_detail_summary(url)
                    relevance_context = "" if summary else _clearstream_relevance_context(content)
                elif _is_clearstream_table_like_summary(summary):
                    summary = ""
                    relevance_context = ""
                else:
                    relevance_context = ""

                item = standardize_news(source, title=title, url=url, date=raw_date, summary=summary)
                item["relevance_context"] = relevance_context
                raw_items.append(item)
                if parsed_date and in_week(item["date"], week_start, week_end):
                    results.append(item)

            if meta["stopped_reason"]:
                break
            if page_has_before_target:
                meta["stopped_reason"] = "passed_target_start"
                break

        if not meta["stopped_reason"]:
            meta["stopped_reason"] = "max_pages" if meta["pages_scanned"] >= max_pages else "completed"

    except Exception as exc:
        meta["error"] = str(exc)
        meta["stopped_reason"] = "error"
        logger.exception("Clearstream official search failed: %s reason=%s", source["name"], exc)

    logger.info(
        "Clearstream official search success: discovered=%s scanned=%s dated=%s within=%s stopped=%s",
        meta["candidates_discovered"],
        meta["candidates_scanned"],
        meta["dated_candidates"],
        len(results),
        meta["stopped_reason"],
    )
    return raw_items, results, meta
