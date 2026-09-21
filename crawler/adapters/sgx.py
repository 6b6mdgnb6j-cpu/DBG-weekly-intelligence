import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .common import absolute_url, clean_text, request_get
from ..date_utils import in_week, parse_date_for_source
from ..news_model import normalize_text_encoding, standardize_news


SGX_RULEBOOK_URL = "https://rulebook.sgx.com/latest-updates?items_per_page=20"
SGX_RULEBOOK_HOST = "rulebook.sgx.com"
SGX_MAX_PAGES = 5
SGX_RULEBOOK_HEADERS = {
    "User-Agent": "Mozilla/5.0 weekly-report-contact",
    "Accept": "text/html,application/xhtml+xml,*/*",
}

DATE_SUFFIX_RE = re.compile(r"\((\d{1,2}\s+[A-Za-z]+\s+\d{4})\)\s*$")
NUMERIC_RULE_RE = re.compile(r"^\s*\d+(?:\.\d+)+(?:\([^)]+\))?\b")
REFERENCE_ONLY_APPENDIX_RE = re.compile(
    r"^\s*appendix\s+[a-z0-9]+\s+to\s+regulatory\s+notice\s+\d+(?:\.\d+)+(?:\([^)]+\))?\s*$",
    re.I,
)

SGX_KEEP_TERMS = (
    "trading rule",
    "trading rules",
    "futures trading",
    "clearing rule",
    "clearing rules",
    "sgx-dc",
    "settlement",
    "final settlement price",
    "contract",
    "contracts",
    "product",
    "products",
    "market structure",
    "regulatory notice",
    "negotiated large trade",
    "margin",
    "risk management",
    "depository rules",
    "eligible securities",
    "derivatives",
    "futures",
    "options",
)

SGX_ROUTINE_TERMS = (
    "administrative",
    "housekeeping",
    "typographical",
    "editorial",
    "formatting",
    "renumbering",
    "navigation",
)

SGX_SUPPORTING_TERMS = (
    "appendix",
    "appendices",
    "practice note",
    "practice notes",
    "definitions",
    "implementation",
    "supporting",
    "schedule",
)

SGX_PRIMARY_TERMS = (
    "regulatory notice",
    "amendment",
    "amendments",
    "rule change",
    "rule changes",
    "new rules",
    "trading rule",
    "clearing rule",
    "contract specification",
    "market structure",
)


def _empty_meta(source, list_url):
    return {
        "error": "",
        "list_url": list_url,
        "feed_used": "SGX Rulebook Latest Updates",
        "feed_key": "sgx_rulebook_latest_updates",
        "surface_used": "SGX Rulebook Latest Updates",
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
        "after_package_grouping": 0,
        "grouped_items_count": 0,
        "package_groups": [],
        "newest_date_seen": "",
        "oldest_date_seen": "",
        "target_period_reached": False,
        "stopped_reason": "",
        "sample_candidates": [],
        "source_filter_rejected_samples": [],
        "requests_total": 0,
        "request_attempts_total": 0,
        "retried_requests": 0,
        "last_retry_error": "",
        "last_request_error": "",
        "last_network_error": "",
        "final_network_error": "",
        "last_status_code": "",
    }


def _merge_network_meta(meta, network_meta):
    meta["requests_total"] += int(network_meta.get("requests_total") or 0)
    meta["request_attempts_total"] += int(network_meta.get("request_attempts_total") or 0)
    meta["retried_requests"] += int(network_meta.get("retried_requests") or 0)
    meta["last_retry_error"] = network_meta.get("last_retry_error", "") or meta["last_retry_error"]
    meta["last_request_error"] = network_meta.get("last_request_error", "") or meta["last_request_error"]
    meta["last_status_code"] = network_meta.get("last_status_code", "") or meta["last_status_code"]


def _record_date(meta, date_value):
    iso_date = date_value.isoformat()
    meta["dated_candidates"] += 1
    meta["list_items_with_date"] += 1
    if not meta["newest_date_seen"] or iso_date > meta["newest_date_seen"]:
        meta["newest_date_seen"] = iso_date
    if not meta["oldest_date_seen"] or iso_date < meta["oldest_date_seen"]:
        meta["oldest_date_seen"] = iso_date


def _append_sample(meta, title, url, raw_date, parsed_date, drop_reason):
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


def _append_source_filter_sample(meta, title, url, reason):
    if len(meta["source_filter_rejected_samples"]) >= 5:
        return
    meta["source_filter_rejected_samples"].append({"title": title, "url": url, "reason": reason})


def _is_rulebook_detail_url(url):
    parsed = urlparse(url or "")
    return parsed.netloc == SGX_RULEBOOK_HOST and (
        parsed.path.startswith("/rulebook/") or "/revisions/" in parsed.path
    )


def _extract_title_and_date(raw_title):
    title = normalize_text_encoding(raw_title)
    match = DATE_SUFFIX_RE.search(title)
    if not match:
        return title, ""
    raw_date = match.group(1)
    clean_title = normalize_text_encoding(title[: match.start()])
    return clean_title, raw_date


def _parse_list_rows(html, current_url):
    soup = BeautifulSoup(html or "", "html.parser")
    rows = []
    seen = set()
    for row in soup.select(".views-row"):
        link = row.select_one("a[href]")
        if not link:
            continue
        url = absolute_url(current_url, link.get("href", ""))
        if not _is_rulebook_detail_url(url) or url in seen:
            continue
        raw_title = clean_text(link.get_text(" ", strip=True))
        title, raw_date = _extract_title_and_date(raw_title)
        context_text = clean_text(row.get_text(" ", strip=True))
        if raw_title and context_text.startswith(raw_title):
            context_text = clean_text(context_text[len(raw_title) :])
        if not title or not raw_date:
            continue
        seen.add(url)
        rows.append(
            {
                "title": title,
                "url": url,
                "date": raw_date,
                "context": context_text,
            }
        )
    return rows


def _next_page_url(html, current_url):
    soup = BeautifulSoup(html or "", "html.parser")
    link = soup.select_one('a[rel="next"][href]')
    if not link:
        link = soup.find("a", string=lambda value: value and "next" in value.lower())
    if not link or not link.get("href"):
        return ""
    url = absolute_url(current_url, link.get("href", ""))
    parsed = urlparse(url)
    if parsed.netloc != SGX_RULEBOOK_HOST or parsed.path != "/latest-updates":
        return ""
    return url


def _has_keep_signal(text):
    lowered = normalize_text_encoding(text).lower()
    return any(term in lowered for term in SGX_KEEP_TERMS)


def _is_routine_update(text):
    lowered = normalize_text_encoding(text).lower()
    return any(term in lowered for term in SGX_ROUTINE_TERMS) and not _has_keep_signal(text)


def _source_filter_reason(candidate):
    text = " ".join([candidate.get("title", ""), candidate.get("context", "")])
    if REFERENCE_ONLY_APPENDIX_RE.match(normalize_text_encoding(candidate.get("title", ""))):
        return "sgx_rulebook_package_grouped"
    if _is_routine_update(text):
        return "sgx_rulebook_routine_update"
    if not _has_keep_signal(text):
        return "sgx_rulebook_no_market_structure_signal"
    return ""


def _context_parts(context):
    return [part.strip() for part in normalize_text_encoding(context).split(">>") if part.strip()]


def _context_family(candidate):
    parts = _context_parts(candidate.get("context", ""))
    if not parts:
        return ("general", "general")
    top_level = parts[0]
    detail = parts[1] if len(parts) > 1 else "general"
    return (top_level, detail)


def _package_key(item):
    top_level, detail = item.get("_sgx_package_family") or ("general", "general")
    return "|".join([item.get("date", ""), top_level.lower(), detail.lower()])


def _is_supporting_document(title):
    lowered = normalize_text_encoding(title).lower()
    if NUMERIC_RULE_RE.search(lowered):
        return True
    return any(term in lowered for term in SGX_SUPPORTING_TERMS)


def _is_primary_rule_update(title):
    lowered = normalize_text_encoding(title).lower()
    return any(term in lowered for term in SGX_PRIMARY_TERMS)


def _representative_score(item):
    title = item.get("title_original") or item.get("title") or ""
    text = " ".join([title, item.get("summary", ""), item.get("relevance_context", "")])
    score = 0
    if _is_primary_rule_update(title):
        score += 80
    if not _is_supporting_document(title):
        score += 50
    if _has_keep_signal(text):
        score += 20
    if "regulatory notice" in title.lower():
        score += 20
    if "appendix" in title.lower() or "appendices" in title.lower():
        score -= 20
    if "definitions" in title.lower():
        score -= 30
    if NUMERIC_RULE_RE.search(title.lower()):
        score -= 20
    return score


def _apply_package_grouping(items, meta):
    groups = {}
    order = []
    for item in items:
        key = _package_key(item)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    retained = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            group[0].pop("_sgx_package_family", None)
            retained.append(group[0])
            continue

        representative = max(group, key=_representative_score)
        representative.pop("_sgx_package_family", None)
        retained.append(representative)
        grouped_titles = [
            item.get("title_original") or item.get("title") or ""
            for item in group
            if item is not representative
        ]
        meta["grouped_items_count"] += len(grouped_titles)
        meta["package_groups"].append(
            {
                "package_key": key,
                "representative_title": representative.get("title_original") or representative.get("title") or "",
                "grouped_count": len(grouped_titles),
                "grouped_titles": grouped_titles,
            }
        )
        for item in group:
            if item is representative:
                continue
            _append_source_filter_sample(
                meta,
                item.get("title_original") or item.get("title") or "",
                item.get("url", ""),
                "sgx_rulebook_package_grouped",
            )

    meta["after_package_grouping"] = len(retained)
    return retained


def _detail_summary(html, fallback_context):
    soup = BeautifulSoup(html or "", "html.parser")
    for selector in ("main p", ".layout-content p", ".field p", "article p", "p"):
        for element in soup.select(selector):
            text = normalize_text_encoding(element.get_text(" "))
            lowered = text.lower()
            if len(text) < 40:
                continue
            if "copyright" in lowered or "all rights reserved" in lowered:
                continue
            if "rulebooks" == lowered.strip():
                continue
            return text
    context = normalize_text_encoding(fallback_context)
    return context if _has_keep_signal(context) else ""


def _build_item(source, candidate, detail_html=""):
    summary = _detail_summary(detail_html, candidate.get("context", ""))
    item = standardize_news(
        source,
        title=candidate["title"],
        url=candidate["url"],
        date=candidate["date"],
        summary=summary,
    )
    item["relevance_context"] = normalize_text_encoding(
        " ".join(
            part
            for part in (
                "SGX Rulebook Latest Updates",
                candidate.get("context", ""),
                candidate.get("effective_context", ""),
            )
            if part
        )
    )
    item["_sgx_package_family"] = _context_family(candidate)
    return item


def collect_sgx_rulebook(source, week_start, week_end, logger):
    list_url = source.get("crawl_url") or source.get("url") or SGX_RULEBOOK_URL
    meta = _empty_meta(source, list_url)
    raw_items = []
    filtered_items = []
    seen_urls = set()
    visited_pages = set()
    max_scan = int(source.get("max_scan_candidates") or 100)
    max_pages = int(source.get("max_pages") or SGX_MAX_PAGES)
    current_url = list_url

    logger.info("SGX rulebook start: %s url=%s", source["name"], list_url)

    try:
        while current_url and current_url not in visited_pages and meta["pages_scanned"] < max_pages:
            visited_pages.add(current_url)
            page_meta = {}
            response = request_get(current_url, headers=SGX_RULEBOOK_HEADERS, timeout=25, attempts=2, meta=page_meta)
            _merge_network_meta(meta, page_meta)
            meta["pages_scanned"] += 1
            rows = _parse_list_rows(response.text, response.url)
            meta["candidates_discovered"] += len(rows)
            meta["candidates"] += len(rows)

            for candidate in rows:
                if meta["candidates_scanned"] >= max_scan:
                    meta["stopped_reason"] = "max_scan_candidates"
                    break

                meta["candidates_scanned"] += 1
                if candidate["url"] in seen_urls:
                    continue
                seen_urls.add(candidate["url"])

                parsed = parse_date_for_source(candidate["date"], source)
                if not parsed:
                    meta["date_parse_failed"] += 1
                    _append_sample(meta, candidate["title"], candidate["url"], candidate["date"], None, "date_parse_failed")
                    continue

                date_value = parsed.date()
                _record_date(meta, date_value)
                item = _build_item(source, candidate)
                raw_items.append(item)

                if date_value < week_start:
                    meta["target_period_reached"] = True
                    _append_sample(meta, candidate["title"], candidate["url"], candidate["date"], date_value, "outside_period")
                    meta["stopped_reason"] = "passed_target_start"
                    break

                if not in_week(item["date"], week_start, week_end):
                    _append_sample(meta, candidate["title"], candidate["url"], candidate["date"], date_value, "outside_period")
                    continue

                meta["before_source_filter"] += 1
                filter_reason = _source_filter_reason(candidate)
                if filter_reason:
                    _append_source_filter_sample(meta, candidate["title"], candidate["url"], filter_reason)
                    _append_sample(meta, candidate["title"], candidate["url"], candidate["date"], date_value, filter_reason)
                    continue

                detail_meta = {}
                detail_html = ""
                try:
                    detail_response = request_get(
                        candidate["url"],
                        headers=SGX_RULEBOOK_HEADERS,
                        timeout=25,
                        attempts=2,
                        meta=detail_meta,
                    )
                    detail_html = detail_response.text
                except Exception as exc:
                    meta["last_request_error"] = str(exc)
                finally:
                    _merge_network_meta(meta, detail_meta)
                    meta["detail_pages_requested"] += 1

                item = _build_item(source, candidate, detail_html)
                filtered_items.append(item)
                meta["after_source_filter"] += 1
                _append_sample(meta, candidate["title"], candidate["url"], candidate["date"], date_value, "kept")

            if meta["stopped_reason"]:
                break
            next_url = _next_page_url(response.text, response.url)
            if not next_url:
                meta["target_period_reached"] = True
                meta["stopped_reason"] = "pagination_end"
                break
            current_url = next_url

        if not meta["stopped_reason"]:
            meta["stopped_reason"] = "max_pages"

    except Exception as exc:
        meta["error"] = str(exc)
        meta["stopped_reason"] = "error"
        meta["last_network_error"] = meta.get("last_request_error", "") or str(exc)
        meta["final_network_error"] = meta["last_network_error"]
        logger.exception("SGX rulebook failed: %s reason=%s", source["name"], exc)

    filtered_items = _apply_package_grouping(filtered_items, meta)

    logger.info(
        "SGX rulebook success: discovered=%s scanned=%s dated=%s within=%s stopped=%s",
        meta["candidates_discovered"],
        meta["candidates_scanned"],
        meta["dated_candidates"],
        len(filtered_items),
        meta["stopped_reason"],
    )
    return raw_items, filtered_items, meta
