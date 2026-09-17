import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .common import absolute_url, clean_text, request_get
from ..date_utils import in_week, parse_date_for_source
from ..news_model import normalize_text_encoding, standardize_news


LCH_SURFACES = (
    {
        "surface_key": "proposed_rule_changes",
        "surface_name": "LCH Proposed Rule Changes",
        "url": "https://www.lseg.com/en/post-trade/clearing/clearing-resources/rulebooks/proposed-rule-changes",
        "date_semantics": "filing_date",
        "detail_required": False,
    },
    {
        "surface_key": "ltd_member_updates",
        "surface_name": "LCH Ltd Member Updates",
        "url": "https://www.lseg.com/en/post-trade/clearing/membership/ltd-membership/ltd-member-updates",
        "date_semantics": "publication_date",
        "detail_required": True,
        "entity": "LCH Ltd",
    },
    {
        "surface_key": "sa_member_updates",
        "surface_name": "LCH SA Member Updates",
        "url": "https://www.lseg.com/en/post-trade/clearing/membership/sa-membership/sa-member-updates",
        "date_semantics": "publication_date",
        "detail_required": True,
        "entity": "LCH SA",
    },
)

LCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 weekly-report-contact",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
}

DATE_RE = re.compile(
    r"\b(?:[A-Z][a-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}\s+[A-Z][a-z]+\s+\d{4}|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b"
)
EFFECTIVE_RE = re.compile(
    r"[^.]{0,140}\b(?:effective|go-live|go live|implementation|take effect)\b[^.]{0,180}(?:\.|$)",
    re.IGNORECASE,
)
CIRCULAR_RE = re.compile(
    r"\b(?:circular|notice|filing)(?:\s+(?:number|no\.?))?\s*[:#-]?\s*([A-Z0-9-]{3,})", re.I
)

KEEP_CONCEPTS = (
    "clearing rule",
    "rulebook",
    "self-certification",
    "self certification",
    "margin",
    "collateral",
    "haircut",
    "default fund",
    "minimum cash",
    "liquidity",
    "risk framework",
    "risk management",
    "membership framework",
    "sponsored clearing",
    "settlement",
    "discounting",
    "benchmark transition",
    "portfolio optimisation",
    "portfolio optimization",
    "swapclear",
    "forexclear",
    "repoclear",
    "cdsclear",
    "equityclear",
    "digitalassetclear",
    "digital asset clear",
)
MATERIAL_ACTIONS = (
    "amend",
    "revis",
    "introduc",
    "launch",
    "extend",
    "expand",
    "implement",
    "activat",
    "propos",
    "consult",
    "self-cert",
    "approv",
    "adopt",
    "change",
    "update",
    "requirement",
    "framework",
    "eligibility",
)
ROUTINE_TERMS = (
    "holiday arrangements",
    "opening hours",
    "scheduled test",
    "contingency test",
    "testing window",
    "change of address",
    "head office address",
    "contact details",
    "webinar",
    "conference",
    "award",
    "podcast",
    "onboarding guide",
    "resignation",
)
MARKETING_TERMS = (
    "watch the video",
    "meet our team",
    "register now",
    "join us",
    "thought leadership",
)


def _empty_meta():
    return {
        "error": "",
        "list_url": LCH_SURFACES[0]["url"],
        "feed_used": ", ".join(surface["surface_name"] for surface in LCH_SURFACES),
        "feed_key": ",".join(surface["surface_key"] for surface in LCH_SURFACES),
        "feed_stats": [],
        "candidates": 0,
        "candidates_discovered": 0,
        "candidates_scanned": 0,
        "pages_scanned": 0,
        "list_items_with_date": 0,
        "detail_pages_requested": 0,
        "detail_fetch_success": 0,
        "detail_fetch_failed": 0,
        "dated_candidates": 0,
        "date_parse_failed": 0,
        "before_source_filter": 0,
        "after_source_filter": 0,
        "before_package_grouping": 0,
        "after_package_grouping": 0,
        "grouped_items_count": 0,
        "package_groups": [],
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
        "date_semantics": surface["date_semantics"],
        "pages_scanned": 0,
        "candidates_discovered": 0,
        "candidates_scanned": 0,
        "dated_candidates": 0,
        "date_parse_failed": 0,
        "within_period": 0,
        "detail_pages_requested": 0,
        "detail_fetch_success": 0,
        "detail_fetch_failed": 0,
        "before_source_filter": 0,
        "after_source_filter": 0,
        "filtering_reasons": {},
        "newest_date_seen": "",
        "oldest_date_seen": "",
        "target_period_reached": False,
        "stopped_reason": "",
    }


def _merge_network_meta(meta, network_meta):
    meta["requests_total"] += int(network_meta.get("requests_total") or 0)
    meta["request_attempts_total"] += int(network_meta.get("request_attempts_total") or 0)
    meta["retried_requests"] += int(network_meta.get("retried_requests") or 0)
    for key in ("last_retry_error", "last_request_error", "last_status_code"):
        meta[key] = network_meta.get(key, "") or meta[key]


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


def _official_lch_url(url):
    parsed = urlparse(url or "")
    if parsed.netloc not in {"www.lseg.com", "lseg.com"}:
        return False
    return (
        parsed.path.startswith("/en/post-trade/clearing/")
        or parsed.path.startswith("/content/lseg/en_us/post-trade/clearing/")
        or parsed.path.startswith("/content/dam/post-trade/")
    )


def _extract_date(text):
    match = DATE_RE.search(clean_text(text))
    return match.group(0) if match else ""


def _row_entity(node, surface):
    if surface.get("entity"):
        return surface["entity"]
    explicit = clean_text(node.get("data-entity", "")) if hasattr(node, "get") else ""
    if explicit:
        return explicit
    heading = node.find_previous(["h2", "h3", "h4"])
    heading_text = clean_text(heading.get_text(" ")) if heading else ""
    combined = f"{heading_text} {clean_text(node.get_text(' '))}".lower()
    return "LCH SA" if "lch sa" in combined or combined.startswith("sa ") else "LCH Ltd"


def _row_context(node, link, raw_date):
    text = clean_text(node.get_text(" "))
    title = clean_text(link.get_text(" "))
    for value in (title, raw_date):
        if value:
            text = clean_text(text.replace(value, " ", 1))
    return text


def _embedded_rows(soup, surface):
    rows = []
    seen = set()
    for node in soup.select("[data-row-data-static]"):
        try:
            records = json.loads(node.get("data-row-data-static") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(records, dict):
            records = records.get("rows") or records.get("items") or []
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            title = normalize_text_encoding(record.get("Title") or record.get("title") or "")
            raw_date = clean_text(
                record.get("Filing Date")
                or record.get("Publication Date")
                or record.get("Date")
                or record.get("date")
                or ""
            )
            href = record.get("New URL") or record.get("URL") or record.get("url") or ""
            if not clean_text(href):
                continue
            url = absolute_url(surface["url"], clean_text(href))
            if not title or not raw_date or not _official_lch_url(url) or url in seen:
                continue
            seen.add(url)
            context = " | ".join(
                clean_text(str(record.get(key) or ""))
                for key in ("Services", "Topic", "Category")
                if record.get(key)
            )
            combined = f"{title} {context}".lower()
            entity = surface.get("entity") or (
                "LCH SA" if "lch sa" in combined else "LCH Ltd"
            )
            rows.append(
                {
                    "title": title,
                    "date": raw_date,
                    "url": url,
                    "context": context,
                    "entity": entity,
                    "surface_key": surface["surface_key"],
                    "date_semantics": surface["date_semantics"],
                }
            )
    return rows


def parse_lch_surface(html, surface):
    soup = BeautifulSoup(html or "", "html.parser")
    rows = _embedded_rows(soup, surface)
    seen = {row["url"] for row in rows}
    containers = list(soup.select("tr"))
    containers.extend(soup.select(".views-row, article, li.lch-update, div.lch-update"))
    for node in containers:
        link = node.select_one("a[href]")
        if not link:
            continue
        url = absolute_url(surface["url"], link.get("href", ""))
        if not _official_lch_url(url) or url in seen:
            continue
        title = normalize_text_encoding(link.get_text(" "))
        raw_date = _extract_date(node.get_text(" "))
        if not title or not raw_date:
            continue
        seen.add(url)
        rows.append(
            {
                "title": title,
                "date": raw_date,
                "url": url,
                "context": _row_context(node, link, raw_date),
                "entity": _row_entity(node, surface),
                "surface_key": surface["surface_key"],
                "date_semantics": surface["date_semantics"],
            }
        )
    return rows


def _next_page_url(html, current_url):
    soup = BeautifulSoup(html or "", "html.parser")
    link = soup.select_one('a[rel="next"][href]')
    if not link:
        link = soup.find("a", string=lambda value: value and value.strip().lower() in {"next", "next page"})
    if not link or not link.get("href"):
        return ""
    url = absolute_url(current_url, link.get("href", ""))
    return url if _official_lch_url(url) else ""


def _detail_text(html):
    soup = BeautifulSoup(html or "", "html.parser")
    for unwanted in soup.select("nav, footer, header, table, form, aside, script, style"):
        unwanted.decompose()
    paragraphs = []
    for element in soup.select("main p, article p, .content p, p"):
        text = normalize_text_encoding(element.get_text(" "))
        lowered = text.lower()
        if len(text) < 40:
            continue
        if any(term in lowered for term in ("contact:", "for further information", "all rights reserved")):
            continue
        if text not in paragraphs:
            paragraphs.append(text)
    body = " ".join(paragraphs)
    summary = paragraphs[0] if paragraphs else ""
    effective_match = EFFECTIVE_RE.search(body)
    effective = clean_text(effective_match.group(0)) if effective_match else ""
    return summary, body, effective


def _filter_reason(candidate):
    text = " ".join(
        [candidate.get("title", ""), candidate.get("context", ""), candidate.get("detail_text", "")]
    ).lower()
    has_concept = any(term in text for term in KEEP_CONCEPTS)
    has_action = any(term in text for term in MATERIAL_ACTIONS)
    if any(term in text for term in MARKETING_TERMS) and not (has_concept and has_action):
        return "lch_marketing_content"
    if any(term in text for term in ROUTINE_TERMS) and not (has_concept and has_action):
        return "lch_routine_or_administrative"
    if not (has_concept and has_action):
        return "lch_no_material_clearing_signal"
    return ""


def _stage(text):
    lowered = text.lower()
    if any(term in lowered for term in ("go-live", "go live", "take effect", "effective", "activation")):
        return "implementation"
    if any(term in lowered for term in ("proposed", "proposal", "consultation", "self-certification", "self certification")):
        return "proposal"
    return "update"


def _service(text):
    lowered = text.lower()
    for service in (
        "swapclear",
        "forexclear",
        "repoclear",
        "cdsclear",
        "equityclear",
        "digitalassetclear",
    ):
        if service in lowered:
            return service
    return "general"


def _normalized_event_title(title):
    text = normalize_text_encoding(title).lower()
    text = re.sub(r"\blch\s+(?:ltd|sa)\b", " ", text)
    text = re.sub(r"\b(?:self[- ]certification|notice|circular)\b", " ", text)
    return " ".join(re.findall(r"[a-z0-9€]+", text))


def _dedupe_key(candidate):
    text = " ".join([candidate.get("title", ""), candidate.get("context", "")])
    circular = CIRCULAR_RE.search(text)
    if circular:
        return (candidate.get("entity", ""), "identifier", circular.group(1).lower())
    return (
        candidate.get("entity", ""),
        _service(text),
        _stage(text),
        _normalized_event_title(candidate.get("title", "")),
    )


def _dedupe_candidates(candidates):
    retained = []
    seen_urls = set()
    seen_keys = set()
    suppressed = []
    for candidate in candidates:
        key = _dedupe_key(candidate)
        if candidate["url"] in seen_urls or key in seen_keys:
            suppressed.append(candidate)
            continue
        seen_urls.add(candidate["url"])
        seen_keys.add(key)
        retained.append(candidate)
    return retained, suppressed


PACKAGE_EXCLUDED_TOKENS = {
    "cftc",
    "sec",
    "fca",
    "self",
    "certification",
    "filing",
    "formal",
    "notice",
    "circular",
    "lch",
    "ltd",
    "limited",
    "sa",
}
PACKAGE_GENERIC_TOKENS = {
    "amendment",
    "amendments",
    "change",
    "changes",
    "clearing",
    "requirement",
    "requirements",
    "rule",
    "rules",
    "update",
    "updates",
}


def _package_lifecycle(candidate):
    text = " ".join(
        [candidate.get("title", ""), candidate.get("context", ""), candidate.get("effective_context", "")]
    ).lower()
    if any(term in text for term in ("go-live", "go live", "take effect", "effective", "activation", "implementation")):
        return "implementation"
    if candidate.get("surface_key") == "proposed_rule_changes" or any(
        term in text
        for term in ("proposed", "proposal", "consultation", "self-certification", "self certification", "19b-4")
    ):
        return "proposal"
    return "update"


def _package_service(candidate):
    text = " ".join([candidate.get("title", ""), candidate.get("context", "")]).lower()
    if "calm" in text:
        return "calm"
    return _service(text)


def _package_topic(candidate):
    text = " ".join([candidate.get("title", ""), candidate.get("context", "")]).lower()
    if any(term in text for term in ("collateral", "haircut", "minimum cash")):
        return "collateral"
    if "margin" in text:
        return "margin"
    if any(term in text for term in ("fee", "pricing", "tariff")):
        return "fees_pricing"
    if any(term in text for term in ("membership", "member eligibility")):
        return "membership"
    if any(term in text for term in ("default", "risk framework", "risk management")):
        return "risk_default"
    if "settlement" in text:
        return "settlement"
    if any(term in text for term in ("product", "eligibility", "contract")):
        return "product_eligibility"
    return "general"


def _package_fingerprint(candidate):
    text = normalize_text_encoding(candidate.get("title", "")).lower()
    text = text.replace("minimun", "minimum")
    text = re.sub(r"\b19b[- ]?4\b", " ", text)
    tokens = []
    for token in re.findall(r"[a-z0-9€]+", text):
        if token in PACKAGE_EXCLUDED_TOKENS or token.isdigit():
            continue
        tokens.append(token)
    return " ".join(tokens)


def _regulatory_channels(candidate):
    text = " ".join([candidate.get("title", ""), candidate.get("context", ""), candidate.get("url", "")]).lower()
    channels = []
    for label in ("CFTC", "SEC", "FCA"):
        if re.search(rf"(?<![a-z0-9]){label.lower()}(?![a-z0-9])", text):
            channels.append(label)
    return channels


def _fingerprints_match(left, right):
    if not left or not right:
        return False
    if left == right:
        return True
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    union = left_tokens | right_tokens
    if not union or len(left_tokens & right_tokens) < 3:
        return False
    distinctive = (left_tokens & right_tokens) - PACKAGE_GENERIC_TOKENS
    return len(distinctive) >= 2 and len(left_tokens & right_tokens) / len(union) >= 0.75


def _same_package(left, right):
    if left.get("entity") != right.get("entity"):
        return False
    if _package_lifecycle(left) != _package_lifecycle(right):
        return False
    if _package_service(left) != _package_service(right):
        return False
    if _package_topic(left) != _package_topic(right):
        return False
    if abs((left["parsed_date"].date() - right["parsed_date"].date()).days) > 3:
        return False
    return _fingerprints_match(_package_fingerprint(left), _package_fingerprint(right))


def _package_representative_score(candidate):
    score = 0
    if candidate.get("surface_key") in {"ltd_member_updates", "sa_member_updates"}:
        score += 100
    if candidate.get("summary") or candidate.get("detail_text"):
        score += 30
    if not candidate.get("url", "").lower().endswith(".pdf"):
        score += 20
    score += min(len(_package_fingerprint(candidate).split()), 15)
    return score


def _package_key(candidate):
    return "|".join(
        [
            candidate.get("entity", "general"),
            _package_lifecycle(candidate),
            _package_service(candidate),
            _package_topic(candidate),
            _package_fingerprint(candidate),
        ]
    )


def _apply_package_grouping(candidates, meta):
    meta["before_package_grouping"] = len(candidates)
    groups = []
    for candidate in candidates:
        group = next((values for values in groups if _same_package(values[0], candidate)), None)
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)

    retained = []
    for group in groups:
        if len(group) == 1:
            retained.append(group[0])
            continue
        representative = max(
            group,
            key=lambda item: (
                _package_representative_score(item),
                -item["parsed_date"].date().toordinal(),
                item.get("url", ""),
            ),
        )
        retained.append(representative)
        suppressed = [item for item in group if item is not representative]
        channels = sorted({value for item in group for value in _regulatory_channels(item)})
        dates = sorted(item["parsed_date"].date().isoformat() for item in group)
        meta["grouped_items_count"] += len(suppressed)
        meta["filtering_reasons"]["lch_clearing_package_grouped"] = (
            int(meta["filtering_reasons"].get("lch_clearing_package_grouped") or 0)
            + len(suppressed)
        )
        meta["package_groups"].append(
            {
                "package_key": _package_key(representative),
                "representative_title": representative.get("title", ""),
                "representative_url": representative.get("url", ""),
                "grouped_count": len(suppressed),
                "grouped_titles": [item.get("title", "") for item in suppressed],
                "grouped_urls": [item.get("url", "") for item in suppressed],
                "regulatory_channels": channels,
                "lifecycle_stage": _package_lifecycle(representative),
                "service_family": _package_service(representative),
                "topic_family": _package_topic(representative),
                "date_window": [dates[0], dates[-1]],
                "drop_reason": "lch_clearing_package_grouped",
            }
        )
        for item in suppressed:
            _sample(meta, item, "lch_clearing_package_grouped")

    meta["after_package_grouping"] = len(retained)
    return retained


def _sample(meta, candidate, reason):
    if len(meta["sample_candidates"]) >= 5:
        return
    meta["sample_candidates"].append(
        {
            "title": candidate.get("title", ""),
            "url": candidate.get("url", ""),
            "raw_date": candidate.get("date", ""),
            "drop_reason": reason,
            "surface_key": candidate.get("surface_key", ""),
        }
    )


def _collect_surface(surface, source, week_start, logger, meta):
    stats = _surface_stats(surface)
    meta["feed_stats"].append(stats)
    candidates = []
    current_url = surface["url"]
    seen_pages = set()
    max_pages = int(source.get("max_pages") or 6)
    max_scan = int(source.get("max_scan_candidates") or 300)

    while current_url and current_url not in seen_pages and stats["pages_scanned"] < max_pages:
        seen_pages.add(current_url)
        network_meta = {}
        response = request_get(current_url, headers=LCH_HEADERS, timeout=25, attempts=2, meta=network_meta)
        _merge_network_meta(meta, network_meta)
        stats["pages_scanned"] += 1
        meta["pages_scanned"] += 1
        rows = parse_lch_surface(response.text, surface)
        stats["candidates_discovered"] += len(rows)
        meta["candidates_discovered"] += len(rows)

        crossed_start = False
        for row in rows:
            if stats["candidates_scanned"] >= max_scan:
                stats["stopped_reason"] = "max_scan_candidates"
                current_url = ""
                break
            stats["candidates_scanned"] += 1
            meta["candidates_scanned"] += 1
            parsed = parse_date_for_source(row["date"], source)
            if not parsed:
                stats["date_parse_failed"] += 1
                meta["date_parse_failed"] += 1
                continue
            _record_date(meta, stats, parsed)
            if parsed.date() < week_start:
                crossed_start = True
            item = dict(row)
            item["parsed_date"] = parsed
            candidates.append(item)

        if crossed_start:
            stats["target_period_reached"] = True
            stats["stopped_reason"] = "passed_target_start"
            break
        next_url = _next_page_url(response.text, current_url)
        if not next_url:
            if stats["dated_candidates"]:
                stats["target_period_reached"] = True
                stats["stopped_reason"] = "pagination_end"
            else:
                stats["stopped_reason"] = "no_dated_candidates"
            break
        current_url = next_url

    if not stats["stopped_reason"]:
        stats["stopped_reason"] = "max_pages" if stats["pages_scanned"] >= max_pages else "pagination_end"
    return candidates, stats


def collect_lch_clearing(source, week_start, week_end, logger):
    meta = _empty_meta()
    raw_items = []
    in_period_candidates = []

    for surface in LCH_SURFACES:
        logger.info("LCH surface start: %s", surface["surface_name"])
        try:
            candidates, stats = _collect_surface(surface, source, week_start, logger, meta)
        except Exception as exc:
            stats = next(
                (value for value in meta["feed_stats"] if value["surface_key"] == surface["surface_key"]),
                _surface_stats(surface),
            )
            stats["stopped_reason"] = "surface_error"
            stats["error"] = str(exc)
            meta["error"] = str(exc) if not meta["error"] else f'{meta["error"]}; {exc}'
            continue

        for candidate in candidates:
            parsed = candidate["parsed_date"]
            raw = standardize_news(
                source,
                candidate["title"],
                candidate["url"],
                date=parsed.date().isoformat(),
                summary="",
            )
            raw["relevance_context"] = " | ".join(
                part
                for part in (
                    "LCH official clearing update",
                    candidate.get("entity", ""),
                    candidate.get("surface_key", ""),
                    candidate.get("context", ""),
                )
                if part
            )
            raw_items.append(raw)
            if in_week(parsed, week_start, week_end):
                stats["within_period"] += 1
                in_period_candidates.append((candidate, stats, surface))

    retained_candidates = []
    for candidate, stats, surface in in_period_candidates:
        stats["before_source_filter"] += 1
        meta["before_source_filter"] += 1
        detail_summary = ""
        detail_body = ""
        effective_context = ""
        if surface["detail_required"] and not candidate["url"].lower().endswith(".pdf"):
            stats["detail_pages_requested"] += 1
            meta["detail_pages_requested"] += 1
            try:
                network_meta = {}
                response = request_get(
                    candidate["url"], headers=LCH_HEADERS, timeout=25, attempts=2, meta=network_meta
                )
                _merge_network_meta(meta, network_meta)
                detail_summary, detail_body, effective_context = _detail_text(response.text)
                stats["detail_fetch_success"] += 1
                meta["detail_fetch_success"] += 1
            except Exception:
                stats["detail_fetch_failed"] += 1
                meta["detail_fetch_failed"] += 1
        candidate["summary"] = detail_summary
        candidate["detail_text"] = detail_body
        candidate["effective_context"] = effective_context
        reason = _filter_reason(candidate)
        if reason:
            stats["filtering_reasons"][reason] = int(stats["filtering_reasons"].get(reason) or 0) + 1
            meta["filtering_reasons"][reason] = int(meta["filtering_reasons"].get(reason) or 0) + 1
            meta["source_local_rejected"] += 1
            _sample(meta, candidate, reason)
            continue
        stats["after_source_filter"] += 1
        meta["after_source_filter"] += 1
        retained_candidates.append(candidate)

    deduped, suppressed = _dedupe_candidates(retained_candidates)
    meta["cross_surface_duplicates_suppressed"] = len(suppressed)
    grouped = _apply_package_grouping(deduped, meta)
    meta["after_source_filter"] = len(grouped)

    filtered_items = []
    for candidate in grouped:
        item = standardize_news(
            source,
            candidate["title"],
            candidate["url"],
            date=candidate["parsed_date"].date().isoformat(),
            summary=candidate.get("summary", ""),
        )
        item["relevance_context"] = " | ".join(
            part
            for part in (
                "LCH official clearing update",
                candidate.get("entity", ""),
                candidate.get("surface_key", ""),
                candidate.get("context", ""),
                candidate.get("effective_context", ""),
            )
            if part
        )
        filtered_items.append(item)

    meta["candidates"] = len(raw_items)
    meta["target_period_reached"] = bool(meta["feed_stats"]) and all(
        stats.get("target_period_reached") for stats in meta["feed_stats"]
    )
    if meta["error"]:
        meta["stopped_reason"] = "partial_surface_failure"
    elif meta["target_period_reached"]:
        meta["stopped_reason"] = "target_period_reached"
    else:
        meta["stopped_reason"] = "incomplete_target_coverage"
    return raw_items, filtered_items, meta
