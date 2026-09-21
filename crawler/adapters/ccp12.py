import re
from datetime import datetime
from urllib.parse import unquote, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .common import absolute_url, clean_text, request_get
from ..date_utils import in_week, parse_date_for_source
from ..news_model import normalize_text_encoding, standardize_news


CCP_GLOBAL_SURFACES = (
    {
        "surface_key": "responses",
        "surface_name": "CCP Global Responses",
        "url": "https://ccp-global.org/responses",
        "document_type": "regulatory_response",
    },
    {
        "surface_key": "papers",
        "surface_name": "CCP Global Papers",
        "url": "https://ccp-global.org/papers",
        "document_type": "policy_paper",
    },
    {
        "surface_key": "pqd_reports",
        "surface_name": "CCP Global PQD Reports",
        "url": "https://ccp-global.org/pqd",
        "document_type": "pqd_report",
    },
    {
        "surface_key": "press_releases",
        "surface_name": "CCP Global Press Releases",
        "url": "https://ccp-global.org/press-releases",
        "document_type": "press_release",
    },
)

CCP_GLOBAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 weekly-report-contact",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
}

EXACT_DATE_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b", re.I),
    re.compile(r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b", re.I),
)
MONTH_YEAR_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
    re.I,
)
PDF_CREATION_DATE_RE = re.compile(r"/CreationDate\s*\(?D:(20\d{2})(\d{2})(\d{2})", re.I)
FILENAME_DATE_PATTERNS = (
    (re.compile(r"(?<!\d)(20\d{2})[-_.](\d{2})[-_.](\d{2})(?!\d)"), "ymd"),
    (re.compile(r"(?<!\d)(\d{2})[.](\d{2})[.](20\d{2})(?!\d)"), "dmy"),
    (re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"), "ymd"),
)
FILENAME_MONTH_ONLY_RE = re.compile(r"(?<!\d)20\d{2}[-_.](?:0[1-9]|1[0-2])(?![-_.]?\d)")
FILENAME_QUARTER_ONLY_RE = re.compile(r"(?:20\d{2}[-_. ]?Q[1-4]|Q[1-4][-_ .]?20\d{2})", re.I)

KEEP_CONCEPTS = (
    "central counterparty",
    "ccp",
    "clearing",
    "margin",
    "collateral",
    "default fund",
    "default management",
    "recovery",
    "resolution",
    "resolvability",
    "liquidity",
    "stress test",
    "stress testing",
    "cyber resilience",
    "operational resilience",
    "public quantitative disclosure",
    "pqd",
    "settlement finality",
    "portfolio margining",
    "cross-margining",
    "cross margining",
    "capital treatment",
    "leverage ratio",
    "sa-ccr",
    "kccp",
    "repo",
    "derivatives",
    "financial market infrastructure",
    "fmi",
)
KEEP_ACTIONS = (
    "respond",
    "response",
    "consultation",
    "position paper",
    "report",
    "primer",
    "publishes",
    "published",
    "releases",
    "released",
    "framework",
    "standard",
    "guidance",
    "simulation",
)
REJECT_TERMS = {
    "ccp_global_event_or_training": (
        "conference",
        "annual general meeting",
        "special general meeting",
        "clearing academy",
        "training",
        "course on central counterparties",
        "webinar",
    ),
    "ccp_global_newsletter_wrapper": ("newsletter",),
    "ccp_global_membership_update": (
        "welcomes ",
        "observer member",
        "primary member",
        "ceased primary membership",
        "no longer observer member",
    ),
    "ccp_global_hr_or_corporate": (
        "appoints",
        "appointment",
        "executive committee",
        "officer changes",
        "joins the board",
        "season's greetings",
        "statement of condolences",
    ),
}
GENERIC_LINK_TEXT = {"download", "read more", "link", "view", "learn more"}


def _empty_meta():
    return {
        "error": "",
        "list_url": CCP_GLOBAL_SURFACES[0]["url"],
        "feed_used": ", ".join(surface["surface_name"] for surface in CCP_GLOBAL_SURFACES),
        "feed_key": ",".join(surface["surface_key"] for surface in CCP_GLOBAL_SURFACES),
        "feed_stats": [],
        "candidates": 0,
        "candidates_discovered": 0,
        "candidates_scanned": 0,
        "pages_scanned": 0,
        "list_items_with_date": 0,
        "detail_pages_requested": 0,
        "pdf_documents_requested": 0,
        "filename_date_recovered": 0,
        "filename_date_rejected": 0,
        "filename_date_rejection_reasons": {},
        "dated_candidates": 0,
        "date_parse_failed": 0,
        "before_source_filter": 0,
        "after_source_filter": 0,
        "source_local_rejected": 0,
        "filtering_reasons": {},
        "cross_surface_duplicates_suppressed": 0,
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


def _surface_stats(surface):
    return {
        "surface_key": surface["surface_key"],
        "surface_name": surface["surface_name"],
        "surface_url": surface["url"],
        "pages_scanned": 0,
        "candidates_discovered": 0,
        "candidates_scanned": 0,
        "dated_candidates": 0,
        "date_parse_failed": 0,
        "within_period": 0,
        "before_source_filter": 0,
        "after_source_filter": 0,
        "source_local_rejected": 0,
        "filtering_reasons": {},
        "detail_pages_requested": 0,
        "pdf_documents_requested": 0,
        "filename_date_recovered": 0,
        "filename_date_rejected": 0,
        "filename_date_rejection_reasons": {},
        "duplicates_suppressed": 0,
        "newest_date_seen": "",
        "oldest_date_seen": "",
        "target_period_reached": False,
        "stopped_reason": "",
        "error": "",
    }


def _merge_network_meta(meta, network_meta):
    meta["requests_total"] += int(network_meta.get("requests_total") or 0)
    meta["request_attempts_total"] += int(network_meta.get("request_attempts_total") or 0)
    meta["retried_requests"] += int(network_meta.get("retried_requests") or 0)
    for key in ("last_retry_error", "last_request_error", "last_status_code"):
        meta[key] = network_meta.get(key, "") or meta[key]


def _official_url(url):
    parsed = urlsplit(url or "")
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() in {
        "ccp-global.org",
        "www.ccp-global.org",
    }


def _normalized_url(url):
    parsed = urlsplit(url or "")
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower().removeprefix("www.")
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    return urlunsplit((scheme, host, path, parsed.query, ""))


def _exact_date(text, source=None):
    for pattern in EXACT_DATE_PATTERNS:
        for match in pattern.finditer(text or ""):
            parsed = parse_date_for_source(match.group(0), source)
            if parsed:
                return parsed, match.group(0)
    return None, ""


def _month_context(text):
    match = MONTH_YEAR_RE.search(text or "")
    if not match:
        return None
    return datetime.strptime(f"{match.group(1)} {match.group(2)}", "%B %Y")


def _response_text(response):
    text = getattr(response, "text", "") or ""
    if text:
        return text
    content = getattr(response, "content", b"") or b""
    return content.decode("latin1", errors="ignore") if isinstance(content, bytes) else str(content)


def _document_date(response, month_context, source=None):
    text = _response_text(response)[:16000]
    parsed, _ = _exact_date(text, source)
    if parsed and (
        month_context is None
        or (parsed.year == month_context.year and parsed.month == month_context.month)
    ):
        return parsed, "document_exact"

    metadata = PDF_CREATION_DATE_RE.search(text)
    if metadata and month_context is not None:
        try:
            parsed = datetime(*(int(value) for value in metadata.groups()))
        except ValueError:
            parsed = None
        if parsed and parsed.year == month_context.year and parsed.month == month_context.month:
            return parsed, "pdf_metadata_confirmed"
    return None, ""


def _month_from_document_url(url):
    match = re.search(r"/sites/default/files/(20\d{2})-(\d{2})/", url or "")
    if not match:
        return ""
    try:
        return datetime(int(match.group(1)), int(match.group(2)), 1).strftime("%B %Y")
    except ValueError:
        return ""


def _filename_date(url, month_context):
    filename = unquote(urlsplit(url or "").path.rsplit("/", 1)[-1])
    for pattern, order in FILENAME_DATE_PATTERNS:
        match = pattern.search(filename)
        if not match:
            continue
        values = tuple(int(value) for value in match.groups())
        year, month, day = values if order == "ymd" else (values[2], values[1], values[0])
        try:
            parsed = datetime(year, month, day)
        except ValueError:
            return None, "filename_date_invalid"
        if month_context is None:
            return None, "filename_date_missing_page_month"
        if parsed.year != month_context.year or parsed.month != month_context.month:
            return None, "filename_date_month_conflict"
        return parsed, ""
    if FILENAME_MONTH_ONLY_RE.search(filename):
        return None, "filename_month_only"
    if FILENAME_QUARTER_ONLY_RE.search(filename):
        return None, "filename_quarter_only"
    return None, "filename_date_absent"


def _record_filename_rejection(meta, stats, reason):
    if reason == "filename_date_absent":
        return
    meta["filename_date_rejected"] += 1
    stats["filename_date_rejected"] += 1
    meta["filename_date_rejection_reasons"][reason] = (
        int(meta["filename_date_rejection_reasons"].get(reason) or 0) + 1
    )
    stats["filename_date_rejection_reasons"][reason] = (
        int(stats["filename_date_rejection_reasons"].get(reason) or 0) + 1
    )


def _month_overlaps_week(month_context, week_start, week_end):
    if month_context is None:
        return False
    return (week_start.year, week_start.month) <= (
        month_context.year,
        month_context.month,
    ) <= (week_end.year, week_end.month)


def _publication_title(node, link):
    if "latestPublishBox" in (node.get("class") or []):
        heading = node.find(["h2", "h3", "h5"])
        if heading:
            title = clean_text(heading.get_text(" ", strip=True))
        else:
            paragraphs = [clean_text(value.get_text(" ", strip=True)) for value in node.find_all("p")]
            title = next((value for value in paragraphs if value), "")
    else:
        title = clean_text(link.get_text(" ", strip=True))
    title = re.sub(
        r"^(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}\s*(?:\||Press Release:)?\s*",
        "",
        title,
        flags=re.I,
    )
    return clean_text(title)


def _publication_records(soup, surface):
    records = []
    seen_urls = set()
    for node in soup.select(".latestPublishBox, .pdfbox"):
        links = [link for link in node.find_all("a", href=True)]
        link = next(
            (
                value
                for value in links
                if _official_url(absolute_url(surface["url"], value.get("href", "")))
                and (
                    "latestPublishBox" in (node.get("class") or [])
                    or ".pdf" in urlsplit(value.get("href", "")).path.lower()
                )
            ),
            None,
        )
        if not link:
            continue
        url = absolute_url(surface["url"], link.get("href", ""))
        normalized = _normalized_url(url)
        if normalized in seen_urls:
            continue
        title = _publication_title(node, link)
        if not title or len(title) < 8:
            continue
        date_node = node.select_one("time, [class*='date'], [data-date], h4")
        raw_date = ""
        if date_node:
            raw_date = clean_text(
                date_node.get("datetime", "")
                or date_node.get("data-date", "")
                or date_node.get_text(" ", strip=True)
            )
        if not raw_date:
            raw_date = clean_text(link.get_text(" ", strip=True))
        summary = ""
        if "pdfbox" in (node.get("class") or []):
            paragraphs = [clean_text(value.get_text(" ", strip=True)) for value in node.find_all("p")]
            summary = next((value for value in paragraphs if value and title.lower() not in value.lower()), "")
        seen_urls.add(normalized)
        records.append(
            {
                "title": title,
                "url": url,
                "summary": summary,
                "raw_date": raw_date,
                "surface_key": surface["surface_key"],
                "surface_name": surface["surface_name"],
                "document_type": surface["document_type"],
            }
        )
    return records


def _pqd_records(soup, surface):
    records = []
    seen_urls = set()
    for link in soup.select(".dropdown-menu a[href]"):
        title = clean_text(link.get_text(" ", strip=True))
        if not re.match(r"^PQD\s+(?:QTR|Newsflash)\b", title, re.I):
            continue
        url = absolute_url(surface["url"], link.get("href", ""))
        normalized = _normalized_url(url)
        if not _official_url(url) or normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        records.append(
            {
                "title": title,
                "url": url,
                "summary": "",
                "raw_date": _month_from_document_url(url),
                "surface_key": surface["surface_key"],
                "surface_name": surface["surface_name"],
                "document_type": surface["document_type"],
            }
        )
    return records


def parse_ccp_global_surface(html, surface):
    soup = BeautifulSoup(html or "", "html.parser")
    if surface["surface_key"] == "pqd_reports":
        return _pqd_records(soup, surface)
    return _publication_records(soup, surface)


def _filter_reason(candidate):
    text = " ".join(
        [candidate.get("title", ""), candidate.get("summary", ""), candidate.get("document_type", "")]
    ).lower()
    for reason, terms in REJECT_TERMS.items():
        if any(term in text for term in terms):
            return reason
    has_concept = any(term in text for term in KEEP_CONCEPTS)
    has_action = any(term in text for term in KEEP_ACTIONS)
    if candidate.get("surface_key") == "responses" and has_concept:
        return ""
    if candidate.get("surface_key") == "pqd_reports" and ("pqd" in text or "quantitative disclosure" in text):
        return ""
    if has_concept and has_action:
        return ""
    return "ccp_global_non_material"


def _title_fingerprint(title):
    text = (title or "").lower()
    text = re.sub(r"\b(?:ccp global|ccpg|ccp12|press release|response|paper|report)\b", " ", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _document_identity(candidate):
    normalized = _normalized_url(candidate.get("url", ""))
    parsed = urlsplit(normalized)
    if parsed.path.lower().endswith(".pdf"):
        return f"document:{parsed.netloc}{parsed.path.lower()}"
    return f"url:{normalized}"


def _deduplicate(candidates, meta):
    kept = []
    identities = set()
    fingerprints = {}
    surface_priority = {"responses": 4, "papers": 3, "pqd_reports": 2, "press_releases": 1}
    for candidate in sorted(candidates, key=lambda item: -surface_priority.get(item["surface_key"], 0)):
        identity = _document_identity(candidate)
        fingerprint_key = (
            candidate["parsed_date"].date().isoformat(),
            _title_fingerprint(candidate["title"]),
        )
        duplicate = identity in identities or (
            fingerprint_key[1] and fingerprint_key in fingerprints
        )
        if duplicate:
            meta["cross_surface_duplicates_suppressed"] += 1
            candidate["stats"]["duplicates_suppressed"] += 1
            _sample(meta, candidate, "ccp_global_cross_surface_duplicate")
            continue
        identities.add(identity)
        fingerprints[fingerprint_key] = candidate
        kept.append(candidate)
    return kept


def _record_date(meta, stats, parsed):
    iso = parsed.date().isoformat()
    meta["dated_candidates"] += 1
    meta["list_items_with_date"] += 1
    stats["dated_candidates"] += 1
    for target in (meta, stats):
        if not target["newest_date_seen"] or iso > target["newest_date_seen"]:
            target["newest_date_seen"] = iso
        if not target["oldest_date_seen"] or iso < target["oldest_date_seen"]:
            target["oldest_date_seen"] = iso


def _sample(meta, candidate, reason):
    if len(meta["sample_candidates"]) >= 8:
        return
    meta["sample_candidates"].append(
        {
            "title": candidate.get("title", ""),
            "url": candidate.get("url", ""),
            "raw_date": candidate.get("raw_date", ""),
            "parsed_date": candidate.get("parsed_date").date().isoformat()
            if candidate.get("parsed_date")
            else "",
            "surface_key": candidate.get("surface_key", ""),
            "drop_reason": reason,
        }
    )


def collect_ccp_global_publications(source, week_start, week_end, logger):
    meta = _empty_meta()
    dated_candidates = []

    for surface in CCP_GLOBAL_SURFACES:
        stats = _surface_stats(surface)
        meta["feed_stats"].append(stats)
        logger.info("CCP Global surface start: %s", surface["surface_name"])
        try:
            network_meta = {}
            response = request_get(
                surface["url"], headers=CCP_GLOBAL_HEADERS, timeout=25, attempts=2, meta=network_meta
            )
            _merge_network_meta(meta, network_meta)
            stats["pages_scanned"] = 1
            meta["pages_scanned"] += 1
            records = parse_ccp_global_surface(response.text, surface)
            stats["candidates_discovered"] = len(records)
            meta["candidates_discovered"] += len(records)

            for record in records:
                stats["candidates_scanned"] += 1
                meta["candidates_scanned"] += 1
                parsed, date_text = _exact_date(record["raw_date"], source)
                date_source = "html_exact" if parsed else ""
                month_context = _month_context(record["raw_date"])
                filename_reason = ""
                if not parsed:
                    parsed, filename_reason = _filename_date(record["url"], month_context)
                    if parsed:
                        date_source = "filename_exact"
                        date_text = parsed.date().isoformat()
                        stats["filename_date_recovered"] += 1
                        meta["filename_date_recovered"] += 1
                    else:
                        _record_filename_rejection(meta, stats, filename_reason)
                is_pdf = urlsplit(record["url"]).path.lower().endswith(".pdf")
                filename_blocks_fallback = filename_reason not in {"", "filename_date_absent"}
                if (
                    not parsed
                    and not filename_blocks_fallback
                    and is_pdf
                    and _month_overlaps_week(month_context, week_start, week_end)
                ):
                    stats["detail_pages_requested"] += 1
                    stats["pdf_documents_requested"] += 1
                    meta["detail_pages_requested"] += 1
                    meta["pdf_documents_requested"] += 1
                    document_meta = {}
                    document = request_get(
                        record["url"], headers=CCP_GLOBAL_HEADERS, timeout=25, attempts=2, meta=document_meta
                    )
                    _merge_network_meta(meta, document_meta)
                    parsed, date_source = _document_date(document, month_context, source)
                    date_text = parsed.date().isoformat() if parsed else ""
                if not parsed:
                    stats["date_parse_failed"] += 1
                    meta["date_parse_failed"] += 1
                    _sample(meta, record, "ccp_global_undated")
                    continue
                record["parsed_date"] = parsed
                record["date_text"] = date_text
                record["date_source"] = date_source
                record["stats"] = stats
                _record_date(meta, stats, parsed)
                dated_candidates.append(record)

            if stats["dated_candidates"] and stats["oldest_date_seen"] < week_start.isoformat():
                stats["target_period_reached"] = True
                stats["stopped_reason"] = "passed_target_start"
            elif stats["dated_candidates"]:
                stats["stopped_reason"] = "archive_did_not_reach_target_start"
            elif records:
                stats["stopped_reason"] = "no_dated_candidates"
            else:
                stats["stopped_reason"] = "no_candidates"
        except Exception as exc:
            stats["error"] = str(exc)
            stats["stopped_reason"] = "surface_error"
            meta["error"] = str(exc) if not meta["error"] else f'{meta["error"]}; {exc}'

    raw_items = []
    in_period = []
    for candidate in dated_candidates:
        raw = standardize_news(
            source,
            candidate["title"],
            candidate["url"],
            date=candidate["parsed_date"].date().isoformat(),
            summary=candidate.get("summary", ""),
        )
        raw["relevance_context"] = " | ".join(
            ["CCP Global official publication", candidate["surface_key"], candidate["document_type"]]
        )
        raw_items.append(raw)
        if in_week(candidate["parsed_date"], week_start, week_end):
            candidate["stats"]["within_period"] += 1
            in_period.append(candidate)

    retained = []
    for candidate in in_period:
        stats = candidate["stats"]
        stats["before_source_filter"] += 1
        meta["before_source_filter"] += 1
        reason = _filter_reason(candidate)
        if reason:
            stats["source_local_rejected"] += 1
            meta["source_local_rejected"] += 1
            stats["filtering_reasons"][reason] = int(stats["filtering_reasons"].get(reason) or 0) + 1
            meta["filtering_reasons"][reason] = int(meta["filtering_reasons"].get(reason) or 0) + 1
            _sample(meta, candidate, reason)
            continue
        stats["after_source_filter"] += 1
        meta["after_source_filter"] += 1
        retained.append(candidate)

    retained = _deduplicate(retained, meta)
    filtered_items = []
    for candidate in retained:
        item = standardize_news(
            source,
            candidate["title"],
            candidate["url"],
            date=candidate["parsed_date"].date().isoformat(),
            summary=candidate.get("summary", ""),
        )
        item["relevance_context"] = " | ".join(
            ["CCP Global official publication", candidate["surface_key"], candidate["document_type"]]
        )
        filtered_items.append(item)

    successful_stats = [stats for stats in meta["feed_stats"] if not stats["error"]]
    meta["target_period_reached"] = bool(successful_stats) and all(
        stats["target_period_reached"] for stats in successful_stats
    )
    if meta["target_period_reached"]:
        meta["stopped_reason"] = "passed_target_start"
    elif meta["error"] and not dated_candidates:
        meta["stopped_reason"] = "surface_error"
    elif dated_candidates:
        meta["stopped_reason"] = "archive_did_not_reach_target_start"
    else:
        meta["stopped_reason"] = "no_dated_candidates"
    meta["candidates"] = len(raw_items)
    return raw_items, filtered_items, meta
