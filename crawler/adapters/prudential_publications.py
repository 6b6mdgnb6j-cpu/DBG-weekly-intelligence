import re
from urllib.parse import urlsplit, urlunsplit

from .common import request_get
from ..date_utils import in_week, parse_date_for_source
from ..news_model import standardize_news


PRUDENTIAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 weekly-report-contact",
    "Accept": "text/html,application/xhtml+xml,*/*",
}


def _empty_meta(profile):
    surfaces = profile["surfaces"]
    return {
        "error": "",
        "list_url": surfaces[0]["url"],
        "feed_used": ", ".join(surface["surface_name"] for surface in surfaces),
        "feed_key": ",".join(surface["surface_key"] for surface in surfaces),
        "feed_stats": [],
        "candidates": 0,
        "candidates_discovered": 0,
        "candidates_scanned": 0,
        "pages_scanned": 0,
        "list_items_with_date": 0,
        "detail_pages_requested": 0,
        "dated_candidates": 0,
        "date_parse_failed": 0,
        "date_source_counts": {},
        "before_source_filter": 0,
        "after_source_filter": 0,
        "source_local_rejected": 0,
        "filtering_reasons": {},
        "duplicates_suppressed": 0,
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
        "date_source_counts": {},
        "within_period": 0,
        "before_source_filter": 0,
        "after_source_filter": 0,
        "source_local_rejected": 0,
        "filtering_reasons": {},
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


def _normalized_url(url):
    parsed = urlsplit(url or "")
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower().removeprefix("www.")
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    return urlunsplit((scheme, host, path.rstrip("/") or "/", parsed.query, ""))


def _parse_candidate_date(candidate, source):
    for field, date_source in (
        ("publication_date_text", "html_publication_date"),
        ("official_document_date_text", "official_document_date"),
    ):
        value = candidate.get(field, "")
        if not value:
            continue
        parsed = parse_date_for_source(value, source)
        if parsed:
            return parsed, date_source
    return None, ""


def _record_date(meta, stats, parsed, date_source):
    iso = parsed.date().isoformat()
    for target in (meta, stats):
        target["dated_candidates"] += 1
        target["date_source_counts"][date_source] = (
            int(target["date_source_counts"].get(date_source) or 0) + 1
        )
        if not target["newest_date_seen"] or iso > target["newest_date_seen"]:
            target["newest_date_seen"] = iso
        if not target["oldest_date_seen"] or iso < target["oldest_date_seen"]:
            target["oldest_date_seen"] = iso
    meta["list_items_with_date"] += 1


def _sample(meta, candidate, reason):
    if len(meta["sample_candidates"]) >= 10:
        return
    parsed = candidate.get("parsed_date")
    meta["sample_candidates"].append(
        {
            "title": candidate.get("title", ""),
            "url": candidate.get("url", ""),
            "surface_key": candidate.get("surface_key", ""),
            "document_type": candidate.get("document_type", ""),
            "publication_date": parsed.date().isoformat() if parsed else "",
            "drop_reason": reason,
        }
    )


def _candidate_identity(candidate):
    return _normalized_url(candidate.get("url", ""))


def _title_fingerprint(title):
    return " ".join(re.findall(r"[a-z0-9]+", (title or "").lower()))


def _deduplicate(candidates, meta):
    kept = []
    urls = set()
    fingerprints = set()
    for candidate in candidates:
        identity = _candidate_identity(candidate)
        fingerprint = (
            candidate["parsed_date"].date().isoformat(),
            _title_fingerprint(candidate.get("title", "")),
        )
        if identity in urls or (fingerprint[1] and fingerprint in fingerprints):
            meta["duplicates_suppressed"] += 1
            candidate["stats"]["duplicates_suppressed"] += 1
            _sample(meta, candidate, "prudential_duplicate")
            continue
        urls.add(identity)
        fingerprints.add(fingerprint)
        kept.append(candidate)
    return kept


def collect_prudential_profile(source, week_start, week_end, logger, profile):
    meta = _empty_meta(profile)
    dated_candidates = []
    max_pages = max(1, int(source.get("max_pages") or profile.get("max_pages") or 12))

    for surface in profile["surfaces"]:
        stats = _surface_stats(surface)
        meta["feed_stats"].append(stats)
        current_url = surface["url"]
        seen_pages = set()

        try:
            while current_url and stats["pages_scanned"] < max_pages:
                normalized_page = _normalized_url(current_url)
                if normalized_page in seen_pages:
                    stats["stopped_reason"] = "pagination_loop"
                    break
                seen_pages.add(normalized_page)

                network_meta = {}
                response = request_get(
                    current_url,
                    headers=profile.get("headers") or PRUDENTIAL_HEADERS,
                    timeout=25,
                    attempts=2,
                    meta=network_meta,
                )
                _merge_network_meta(meta, network_meta)
                stats["pages_scanned"] += 1
                meta["pages_scanned"] += 1

                records, next_url = profile["parse_surface"](
                    response.text, surface, current_url
                )
                stats["candidates_discovered"] += len(records)
                meta["candidates_discovered"] += len(records)

                for record in records:
                    stats["candidates_scanned"] += 1
                    meta["candidates_scanned"] += 1
                    parsed, date_source = _parse_candidate_date(record, source)
                    if not parsed:
                        stats["date_parse_failed"] += 1
                        meta["date_parse_failed"] += 1
                        _sample(meta, record, "prudential_date_missing_or_invalid")
                        continue
                    record["parsed_date"] = parsed
                    record["date_source"] = date_source
                    record["stats"] = stats
                    _record_date(meta, stats, parsed, date_source)
                    dated_candidates.append(record)

                if stats["dated_candidates"] and stats["oldest_date_seen"] < week_start.isoformat():
                    stats["target_period_reached"] = True
                    stats["stopped_reason"] = "passed_target_start"
                    break
                current_url = next_url

            if not stats["stopped_reason"]:
                if stats["target_period_reached"]:
                    stats["stopped_reason"] = "passed_target_start"
                elif not stats["candidates_discovered"]:
                    stats["stopped_reason"] = "no_candidates"
                elif not stats["dated_candidates"]:
                    stats["stopped_reason"] = "no_dated_candidates"
                elif current_url:
                    stats["stopped_reason"] = "max_pages"
                else:
                    stats["stopped_reason"] = "archive_did_not_reach_target_start"
        except Exception as exc:
            stats["error"] = str(exc)
            stats["stopped_reason"] = "surface_error"
            meta["error"] = str(exc) if not meta["error"] else f'{meta["error"]}; {exc}'

    raw_items = []
    in_period = []
    for candidate in dated_candidates:
        context = " | ".join(
            value
            for value in (
                profile.get("profile_key", "prudential"),
                candidate.get("surface_key", ""),
                candidate.get("document_type", ""),
                candidate.get("topic", ""),
                candidate.get("source_context", ""),
            )
            if value
        )
        item = standardize_news(
            source,
            candidate["title"],
            candidate["url"],
            date=candidate["parsed_date"].date().isoformat(),
            summary=candidate.get("summary", ""),
        )
        item["relevance_context"] = context
        raw_items.append(item)
        if in_week(candidate["parsed_date"], week_start, week_end):
            candidate["stats"]["within_period"] += 1
            in_period.append(candidate)

    retained = []
    for candidate in in_period:
        stats = candidate["stats"]
        stats["before_source_filter"] += 1
        meta["before_source_filter"] += 1
        reason = profile["filter_reason"](candidate)
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
            value
            for value in (
                profile.get("profile_key", "prudential"),
                candidate.get("surface_key", ""),
                candidate.get("document_type", ""),
                candidate.get("topic", ""),
                candidate.get("source_context", ""),
            )
            if value
        )
        filtered_items.append(item)

    successful = [stats for stats in meta["feed_stats"] if not stats["error"]]
    meta["target_period_reached"] = bool(successful) and all(
        stats["target_period_reached"] for stats in successful
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


def collect_prudential_publications(source, week_start, week_end, logger):
    if source.get("id") == "SRC-010":
        from .bcbs import BCBS_PROFILE

        return collect_prudential_profile(source, week_start, week_end, logger, BCBS_PROFILE)
    raise ValueError(f"unsupported prudential publications profile: {source.get('id', '')}")
