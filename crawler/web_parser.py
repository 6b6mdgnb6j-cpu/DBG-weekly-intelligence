import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .adapters import get_adapter
from .adapters.common import request_get
from .article_parser import extract_date, parse_article
from .date_utils import in_week, parse_date_for_source
from .news_model import standardize_news


HEADERS = {
    "User-Agent": "Mozilla/5.0",
}


BLOCK_WORDS = [
    "contact",
    "privacy",
    "cookie",
    "login",
    "career",
    "product",
    "service",
    "support",
    "resource",
    "library",
    "investor-relations",
    "terms",
    "imprint",
    "sitemap",
    "search.html",
    "/search?",
    "search-results",
    "media-library",
    "wp-content/uploads",
]


BLOCK_EXTENSIONS = (
    ".pdf",
    ".zip",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
)


NEWS_HINTS = [
    "news",
    "press",
    "release",
    "media",
    "article",
    "date",
    "202",
]


LISTING_TITLES = {
    "media centre",
    "media center",
    "newsroom",
    "news releases",
    "press releases",
    "market news",
    "statements & remarks",
    "speeches and interviews",
    "events",
    "publications",
}


LISTING_PATH_ENDINGS = (
    "/news",
    "/news/",
    "/media-centre",
    "/media-center",
    "/newsroom",
    "/news-releases",
    "/press-releases",
    "/speeches-and-interviews",
    "/statements-remarks",
    "/events",
    "/publications",
)


def valid_url(url, base_url, source=None):
    lower = url.lower()
    if any(word in lower for word in BLOCK_WORDS):
        return False
    if lower.endswith(BLOCK_EXTENSIONS):
        return False

    parsed = urlparse(url)
    base = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.netloc and base.netloc and parsed.netloc != base.netloc:
        return False

    if url.split("?")[0].rstrip("/") == base_url.split("?")[0].rstrip("/"):
        return False

    query = parsed.query.lower()
    if any(token in query for token in ("page=", "start=", "sort_by=", "category=", "n_search_term=", "f%5b")):
        return False

    path = parsed.path.rstrip("/").lower()
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[-1] == parts[-2]:
        return False
    if any(path.endswith(ending.rstrip("/")) for ending in LISTING_PATH_ENDINGS):
        return False

    if source and source.get("allow_same_host_article_links"):
        return True

    return any(hint in lower for hint in NEWS_HINTS)


def likely_listing_link(url, text):
    title = re.sub(r"\s+", " ", (text or "").strip().lower())
    if title in LISTING_TITLES:
        return True
    if len(title.split()) <= 4 and any(title == value for value in LISTING_TITLES):
        return True
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[-1] == parts[-2]:
        return True
    return any(path.endswith(ending.rstrip("/")) for ending in LISTING_PATH_ENDINGS)


def context_text(anchor):
    pieces = [anchor.get_text(" ", strip=True)]
    for parent in anchor.parents:
        if not getattr(parent, "name", None):
            continue
        if parent.name in ("article", "li", "tr"):
            pieces.append(parent.get_text(" ", strip=True))
            break
        classes = " ".join(parent.get("class", [])).lower()
        if any(key in classes for key in ("card", "teaser", "item", "result", "views-row", "press")):
            pieces.append(parent.get_text(" ", strip=True))
            break
    return " ".join(piece for piece in pieces if piece)


def link_score(url, text):
    lower = f"{url} {text}".lower()
    score = 0
    for hint in NEWS_HINTS:
        if hint in lower:
            score += 1
    if re.search(r"/20\d{2}/|20\d{2}-|20\d{2}", lower):
        score += 2
    if extract_date(text):
        score += 4
    if len(text.strip()) > 20:
        score += 1
    return score


def parsed_date_value(value, source=None):
    parsed = parse_date_for_source(value, source)
    return parsed.date() if parsed else None


def date_drop_reason(parsed_date, week_start, week_end):
    if not parsed_date:
        return "date_parse_failed"
    if parsed_date > week_end:
        return "after_period"
    if parsed_date < week_start:
        return "before_period"
    return "within_period"


def make_list_diagnostic(url, title, raw_date, parsed_date, drop_reason):
    return {
        "title": title,
        "url": url,
        "raw_date": raw_date or "",
        "parsed_date": parsed_date.isoformat() if parsed_date else "",
        "drop_reason": drop_reason,
    }


def make_list_item(source, url, title, raw_date):
    return standardize_news(
        source=source,
        title=title,
        url=url,
        date=raw_date,
        summary="",
    )


def find_next_page(soup, current_url, seen_pages):
    current_page = 1
    parsed_url = urlparse(current_url)
    page_match = re.search(r"/page/(\d+)/?", current_url)
    query_page = parse_qs(parsed_url.query).get("tx_news_pi1[currentPage]", [])
    if page_match:
        current_page = int(page_match.group(1))
    elif query_page:
        try:
            current_page = int(query_page[0])
        except ValueError:
            current_page = 1

    candidates = []
    next_page_labels = {str(current_page + 1), f"page {current_page + 1}"}
    for anchor in soup.find_all("a"):
        text = anchor.get_text(" ", strip=True).lower()
        href = anchor.get("href") or ""
        if text in next_page_labels or f"/page/{current_page + 1}/" in href:
            candidates.append(anchor)

    rel_next = soup.find("a", rel=lambda value: value and "next" in value)
    if rel_next and rel_next.get("href"):
        candidates.append(rel_next)

    for anchor in soup.find_all("a"):
        text = anchor.get_text(" ", strip=True).lower()
        aria = (anchor.get("aria-label") or "").lower()
        classes = " ".join(anchor.get("class", [])).lower()
        if any(
            token in f"{text} {aria} {classes}"
            for token in ("next", "older", "load more", "more results", "下一", "older posts")
        ):
            candidates.append(anchor)

    for anchor in candidates:
        href = anchor.get("href")
        if not href:
            continue
        url = urljoin(current_url, href).split("#")[0]
        if url not in seen_pages and url != current_url:
            return url
    return ""


def discover_links(soup, list_url, source):
    discovered = []
    seen = set()

    for order, anchor in enumerate(soup.find_all("a")):
        href = anchor.get("href")
        if not href:
            continue

        url = urljoin(list_url, href).split("#")[0]
        if url in seen or not valid_url(url, list_url, source):
            continue

        text = context_text(anchor)
        if likely_listing_link(url, text):
            continue
        score = link_score(url, text)
        if score <= 0:
            continue

        seen.add(url)
        list_date = extract_date(text)
        parsed = parsed_date_value(list_date, source)
        discovered.append(
            {
                "score": score,
                "url": url,
                "title": text,
                "raw_date": list_date,
                "parsed_date": parsed,
                "order": order,
            }
        )

    return discovered


def ordered_candidates(candidates):
    with_dates = [candidate for candidate in candidates if candidate["parsed_date"]]
    without_dates = [candidate for candidate in candidates if not candidate["parsed_date"]]
    with_dates.sort(key=lambda item: (item["parsed_date"], -item["order"]), reverse=True)
    without_dates.sort(key=lambda item: (-item["score"], item["order"]))
    return with_dates + without_dates


def adapter_candidates(items, source):
    candidates = []
    for order, item in enumerate(items):
        raw_date = item.get("date", "")
        candidates.append(
            {
                "score": 10,
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "raw_date": raw_date,
                "parsed_date": parsed_date_value(raw_date, source),
                "summary": item.get("summary", ""),
                "content_type": item.get("content_type", ""),
                "order": order,
            }
        )
    return candidates


def collect_web(source, week_start, week_end, logger):
    results = []
    raw_items = []
    error = ""
    candidates_discovered = 0
    candidates_scanned = 0
    pages_scanned = 0
    dated_candidates = 0
    date_parse_failed = 0
    list_items_with_date = 0
    detail_pages_requested = 0
    sample_candidates = []
    newest_date_seen = None
    oldest_date_seen = None
    target_period_reached = False
    stopped_reason = ""
    network_meta = {}

    logger.info("WEB start: %s", source["name"])

    try:
        list_url = source.get("crawl_url") or source["url"]
        current_url = list_url
        seen_pages = set()
        seen_candidates = set()
        max_pages = int(source.get("max_pages") or 3)
        max_scan_candidates = int(source.get("max_scan_candidates") or max(int(source.get("max_candidates") or 10) * 8, 40))
        max_items = int(source.get("max_items") or 10)
        adapter = get_adapter(source)

        while current_url and pages_scanned < max_pages and candidates_scanned < max_scan_candidates:
            seen_pages.add(current_url)
            response = request_get(
                current_url,
                timeout=20,
                attempts=2,
                headers=source.get("request_headers"),
                meta=network_meta,
            )
            pages_scanned += 1

            soup = BeautifulSoup(response.text, "html.parser")
            if adapter:
                try:
                    discovered = adapter(soup, current_url, source, week_start, week_end)
                except TypeError:
                    discovered = adapter(soup, current_url, source)
                page_candidates = adapter_candidates(discovered, source)
            else:
                page_candidates = discover_links(soup, current_url, source)

            unique_candidates = []
            for candidate in page_candidates:
                if candidate["url"] in seen_candidates:
                    continue
                seen_candidates.add(candidate["url"])
                unique_candidates.append(candidate)
            page_candidates = unique_candidates
            list_items_with_date += sum(1 for candidate in page_candidates if candidate.get("parsed_date"))

            candidates_discovered += len(page_candidates)
            logger.info(
                "WEB candidate page for %s: page=%s discovered=%s total=%s adapter=%s",
                source["name"],
                pages_scanned,
                len(page_candidates),
                candidates_discovered,
                bool(adapter),
            )

            if not page_candidates:
                stopped_reason = "no_candidates_on_page"
                break

            page_has_before_target = False
            for candidate in ordered_candidates(page_candidates):
                if candidates_scanned >= max_scan_candidates:
                    stopped_reason = "max_scan_candidates"
                    break

                candidates_scanned += 1
                parsed = candidate["parsed_date"]
                raw_date = candidate["raw_date"]
                title = candidate["title"]
                url = candidate["url"]

                if parsed:
                    dated_candidates += 1
                    newest_date_seen = max(newest_date_seen, parsed) if newest_date_seen else parsed
                    oldest_date_seen = min(oldest_date_seen, parsed) if oldest_date_seen else parsed
                    drop_reason = date_drop_reason(parsed, week_start, week_end)
                    if parsed <= week_end:
                        target_period_reached = True
                    if parsed < week_start:
                        page_has_before_target = True

                    if drop_reason != "within_period":
                        raw_items.append(make_list_item(source, url, title, raw_date))
                        if len(sample_candidates) < 3:
                            sample_candidates.append(
                                make_list_diagnostic(url, title, raw_date, parsed, drop_reason)
                            )
                        continue

                raw_item, filtered_item, diagnostic = parse_article(
                    url,
                    source,
                    week_start,
                    week_end,
                    logger,
                    list_title=title,
                    list_date=raw_date,
                    network_meta=network_meta,
                )
                detail_pages_requested += 1
                if raw_item:
                    raw_items.append(raw_item)
                article_date = parsed_date_value(diagnostic.get("parsed_date") or diagnostic.get("raw_date"), source)
                if article_date and not parsed:
                    dated_candidates += 1
                    newest_date_seen = max(newest_date_seen, article_date) if newest_date_seen else article_date
                    oldest_date_seen = min(oldest_date_seen, article_date) if oldest_date_seen else article_date
                    if article_date <= week_end:
                        target_period_reached = True
                    if article_date < week_start:
                        page_has_before_target = True
                elif not article_date:
                    date_parse_failed += 1

                if len(sample_candidates) < 3:
                    sample_candidates.append(diagnostic)
                if filtered_item:
                    target_period_reached = True
                    results.append(filtered_item)
                if len(results) >= max_items:
                    stopped_reason = "max_items"
                    break

            if stopped_reason in ("max_items", "max_scan_candidates"):
                break
            if page_has_before_target:
                stopped_reason = "passed_target_start"
                break
            next_url = find_next_page(soup, current_url, seen_pages)
            if not next_url:
                stopped_reason = (
                    "no_next_page_after_reaching_target_period"
                    if target_period_reached
                    else "no_next_page_before_target_period"
                )
                break
            current_url = next_url

        if not stopped_reason:
            stopped_reason = "max_pages" if pages_scanned >= max_pages else "completed"

        logger.info(
            "WEB success: %s discovered=%s scanned=%s list_dates=%s details=%s pages=%s filtered=%s kept=%s stopped=%s",
            source["name"],
            candidates_discovered,
            candidates_scanned,
            list_items_with_date,
            detail_pages_requested,
            pages_scanned,
            len(results),
            len(results),
            stopped_reason,
        )

    except Exception as exc:
        error = str(exc)
        logger.exception("WEB failed: %s reason=%s", source["name"], exc)

    return raw_items, results, {
        "error": error,
        "list_url": source.get("crawl_url") or source["url"],
        "candidates": candidates_discovered or len(raw_items),
        "candidates_discovered": candidates_discovered or len(raw_items),
        "candidates_scanned": candidates_scanned,
        "pages_scanned": pages_scanned,
        "list_items_with_date": list_items_with_date,
        "detail_pages_requested": detail_pages_requested,
        "dated_candidates": dated_candidates,
        "date_parse_failed": date_parse_failed,
        "newest_date_seen": newest_date_seen.isoformat() if newest_date_seen else "",
        "oldest_date_seen": oldest_date_seen.isoformat() if oldest_date_seen else "",
        "target_period_reached": target_period_reached,
        "stopped_reason": stopped_reason,
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
