"""Explicitly approved editorial additions for offline snapshot replay only."""

import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .competitor_mapping import apply_competitor_mapping
from .content_filter import score_item


SOURCE_FILE = Path(__file__).resolve().parent.parent / "config" / "sources.json"
ORIGIN = "manual_editorial_supplement"
SUMMARY_BASIS = "editorial_paraphrase_of_official_release"


class ManualSupplementError(ValueError):
    pass


def content_hash(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonical_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ManualSupplementError("supplement URL must be an official HTTPS URL")
    if parsed.port not in (None, 443):
        raise ManualSupplementError("supplement URL has an unsupported port")
    query = sorted((key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                   if not key.lower().startswith("utm_"))
    # Only unreserved URL characters are interchangeable with their escaped forms.
    path = re.sub(r"%([0-9a-fA-F]{2})", lambda match: (
        chr(int(match[1], 16)) if chr(int(match[1], 16)) in
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~" else match[0].upper()
    ), parsed.path)
    return urlunsplit(("https", parsed.hostname.lower(), path.rstrip("/") or "/",
                       urlencode(query), ""))


def supplement_id(record):
    return content_hash({key: record[key] for key in ("source_id", "publication_date", "canonical_url")})


def record_hash(record):
    return content_hash({key: value for key, value in record.items() if key != "content_sha256"})


def _validate_approval(approval):
    if not isinstance(approval, dict):
        raise ManualSupplementError("supplement human approval metadata is missing")
    try:
        approved_at = datetime.fromisoformat(approval.get("approved_at", "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ManualSupplementError("supplement approval timestamp is missing or invalid")
    if not isinstance(approval.get("reviewed_by"), str) or not approval["reviewed_by"].strip() or not approved_at.tzinfo:
        raise ManualSupplementError("supplement human approval metadata is missing")


def _text(value):
    return " ".join(re.findall(r"\w+", (value or "").casefold()))


def duplicate_reason(record, existing):
    for item in existing:
        try:
            if canonical_url(item.get("url") or "") == record["canonical_url"]:
                return "canonical_url"
        except (ValueError, TypeError):
            pass
        if item.get("source") != record["source_name"]:
            continue
        try:
            close_date = abs((date.fromisoformat(str(item.get("date")))
                              - date.fromisoformat(record["publication_date"])).days) <= 3
        except ValueError:
            continue
        if not close_date:
            continue
        title = _text(record["title_en"])
        old_title = _text(item.get("title_original") or item.get("title"))
        old_summary = _text(item.get("summary_original") or item.get("summary"))
        if title == old_title or (title and title in old_summary):
            return "same_source_title_or_release_mention"
        title_similarity = SequenceMatcher(None, title, old_title).ratio()
        words = set(_text(record["summary_en"]).split())
        old_words = set(old_summary.split())
        overlap = len(words & old_words) / max(1, len(words | old_words))
        if title_similarity >= 0.85 or (title_similarity >= 0.7 and overlap >= 0.65):
            return "same_source_event_similarity"
    return ""


def load_supplements(path, expected_sha256, week_start, existing, sources_path=SOURCE_FILE):
    path = Path(path)
    if "drafts" in path.parts:
        raise ManualSupplementError("draft supplements cannot be consumed")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ManualSupplementError("supplement file SHA-256 mismatch")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ManualSupplementError("supplement document must be an object")
    start = date.fromisoformat(week_start)
    end = start + timedelta(days=6)
    if data.get("schema_version") != 1 or data.get("week_start") != week_start or data.get("week_end") != end.isoformat():
        raise ManualSupplementError("supplement schema or week mismatch")
    if data.get("approval_status") != "APPROVED":
        raise ManualSupplementError("supplements require explicit human approval")
    approval = data.get("approval") or {}
    _validate_approval(approval)
    if "revision_approval" in data:
        _validate_approval(data["revision_approval"])
        if not re.fullmatch(r"[0-9a-f]{64}", data["revision_approval"].get("previous_file_sha256", "")):
            raise ManualSupplementError("supplement revision approval lacks previous file binding")
    records = data.get("records")
    if not isinstance(records, list) or not records:
        raise ManualSupplementError("approved supplement records are missing")
    registry = json.loads(Path(sources_path).read_text(encoding="utf-8"))
    sources = {source["id"]: source for source in registry}
    appended = []
    ids = set()
    for record in records:
        if not isinstance(record, dict):
            raise ManualSupplementError("malformed supplement record")
        required = ("source_id", "source_name", "publication_date", "official_title", "url", "canonical_url",
                    "title_en", "title_cn", "summary_en", "summary_cn", "category", "subcategory",
                    "business_relevance", "supplement_id", "content_sha256")
        if any(not isinstance(record.get(key), str) or not record[key].strip() for key in required):
            raise ManualSupplementError("supplement required content or identity is missing")
        if record.get("approval_status") != "APPROVED" or record.get("editorial_origin") != ORIGIN:
            raise ManualSupplementError("supplement record is not approved editorial content")
        record_approval = record.get("approval", approval)
        _validate_approval(record_approval)
        if record_hash(record) != record["content_sha256"] or supplement_id(record) != record["supplement_id"]:
            raise ManualSupplementError("supplement content hash or identity mismatch")
        if record["supplement_id"] in ids:
            raise ManualSupplementError("duplicate supplement identity")
        ids.add(record["supplement_id"])
        source = sources.get(record["source_id"])
        if not source or not source.get("official") or not source.get("enabled"):
            raise ManualSupplementError("supplement source is not a registered official source")
        for key, source_key in (("source_name", "name"), ("category", "category"), ("subcategory", "subcategory")):
            if record[key] != source.get(source_key):
                raise ManualSupplementError("supplement registry metadata mismatch")
        canonical = canonical_url(record["url"])
        if canonical != record["canonical_url"]:
            raise ManualSupplementError("supplement canonical URL mismatch")
        host = urlsplit(canonical).hostname
        domains = [urlsplit(source.get(key) or "").hostname for key in ("url", "crawl_url")]
        domains = [domain.removeprefix("www.") for domain in domains if domain]
        if not any(host == domain or host.endswith("." + domain) for domain in domains):
            raise ManualSupplementError("supplement URL is outside registered official domains")
        publication = date.fromisoformat(record["publication_date"])
        if not start <= publication <= end:
            raise ManualSupplementError("supplement publication date is outside target week")
        evidence = record.get("source_verification") or {}
        if (evidence.get("official_url") != record["url"]
                or evidence.get("publication_date") != record["publication_date"]
                or evidence.get("official_title") != record["official_title"]
                or evidence.get("method") != "official_release_review"
                or not evidence.get("verified_on") or not isinstance(evidence.get("notes"), list)
                or not evidence["notes"] or not all(isinstance(note, str) and note.strip() for note in evidence["notes"])):
            raise ManualSupplementError("supplement source verification provenance is missing or inconsistent")
        date.fromisoformat(evidence["verified_on"])
        reason = duplicate_reason(record, list(existing) + appended)
        if reason:
            raise ManualSupplementError(f"duplicate supplementary article: {reason}: {record['url']}")
        item = {
            "date": record["publication_date"], "source": source["name"], "url": record["url"],
            "category": source["category"], "subcategory": source.get("subcategory", ""),
            "brand": source.get("brand", ""), "competitor_type": source.get("competitor_type", ""),
            "priority": source.get("priority", 99), "official": True,
            "title_original": record["title_en"], "title_original_lang": "en",
            "title_en": record["title_en"], "title_cn": record["title_cn"],
            "summary": record["summary_en"], "summary_original": record["summary_en"],
            "summary_original_lang": "en", "summary_en": record["summary_en"], "summary_cn": record["summary_cn"],
            "editorial_provenance": {
                "origin": ORIGIN, "summary_basis": SUMMARY_BASIS, "source_id": source["id"],
                "supplement_id": record["supplement_id"], "content_sha256": record["content_sha256"],
                "approval_status": "APPROVED", "approval": deepcopy(record_approval),
                "source_verification": deepcopy(evidence),
            },
        }
        item["relevance_score"], item["relevance_reason"] = score_item(item)
        appended.extend(apply_competitor_mapping([item]))
    return appended, data


def supplement_provenance(path, expected_sha256, data, original_items):
    provenance = {
        "file_name": Path(path).name, "artifact_filename": "editorial_supplements_" + data["week_start"].replace("-", "") + ".json",
        "file_sha256": expected_sha256, "approval_status": "APPROVED", "approval": data["approval"],
        "inserted_count": len(data["records"]), "original_item_count": len(original_items),
        "original_items_sha256": content_hash(original_items), "editorial_origin": ORIGIN,
        "records": [{key: record[key] for key in ("supplement_id", "content_sha256", "source_id", "source_name",
                                                  "publication_date", "url", "approval_status")}
                    for record in data["records"]],
    }
    if "revision_approval" in data:
        provenance["revision_approval"] = data["revision_approval"]
    return provenance


def validate_supplement_bundle(bundle_dir, weekly, provenance, artifacts):
    supplemented = [item for item in weekly.get("items", [])
                    if (item.get("editorial_provenance") or {}).get("origin") == ORIGIN]
    entry = artifacts.get("editorial_supplements")
    if not provenance:
        if supplemented or entry:
            raise ManualSupplementError("supplement items or artifact lack manifest provenance")
        return
    filename = provenance.get("artifact_filename")
    if not filename or Path(filename).name != filename:
        raise ManualSupplementError("unsafe supplement artifact filename")
    if entry != {"filename": filename, "sha256": provenance.get("file_sha256")}:
        raise ManualSupplementError("supplement artifact binding mismatch")
    count = provenance.get("original_item_count")
    if not isinstance(count, int) or count < 0 or count > len(weekly["items"]):
        raise ManualSupplementError("invalid original item count in supplement provenance")
    original = weekly["items"][:count]
    if content_hash(original) != provenance.get("original_items_sha256"):
        raise ManualSupplementError("original items changed after supplementation")
    path = Path(bundle_dir) / filename
    expected, data = load_supplements(path, provenance.get("file_sha256"), weekly["week_start"], original)
    if supplement_provenance(provenance.get("file_name", ""), provenance["file_sha256"], data, original) != provenance:
        raise ManualSupplementError("supplement manifest provenance is inconsistent")
    if weekly["items"][count:] != expected or supplemented != expected:
        raise ManualSupplementError("supplementary item content was tampered with")
