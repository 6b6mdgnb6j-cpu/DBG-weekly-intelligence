"""Approved, identity-bound summaries for empty-source snapshot articles."""

import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from .manual_supplements import SOURCE_FILE, canonical_url, content_hash
from .manual_translations import original_sha256, stable_item_id
from .translation_quality import validate_translation_field


ORIGIN = "manual_editorial_summary"
BASIS = "human_authored_summary_of_official_evidence"


class EditorialSummaryError(ValueError):
    pass


def summary_id(record):
    return content_hash({key: record[key] for key in
                         ("source_id", "source", "date", "url", "article_id",
                          "original_title_sha256", "original_summary_sha256")})


def record_hash(record):
    return content_hash({key: value for key, value in record.items() if key != "content_sha256"})


def _approval(value):
    if not isinstance(value, dict) or not isinstance(value.get("reviewed_by"), str) or not value["reviewed_by"].strip():
        raise EditorialSummaryError("editorial summary approval metadata is missing")
    try:
        timestamp = datetime.fromisoformat(value.get("approved_at", "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise EditorialSummaryError("editorial summary approval timestamp is invalid")
    if not timestamp.tzinfo:
        raise EditorialSummaryError("editorial summary approval timestamp requires a timezone")


def load_editorial_summaries(path, expected_sha256, week_start, items, sources_path=SOURCE_FILE):
    path = Path(path)
    if "drafts" in path.parts:
        raise EditorialSummaryError("draft editorial summaries cannot be consumed")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or ""):
        raise EditorialSummaryError("editorial summary SHA-256 is required")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise EditorialSummaryError("editorial summary file SHA-256 mismatch")
    data = json.loads(raw)
    start = date.fromisoformat(week_start)
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or data.get("week_start") != week_start
            or data.get("week_end") != (start + timedelta(days=6)).isoformat()):
        raise EditorialSummaryError("editorial summary schema or week mismatch")
    if data.get("approval_status") != "APPROVED":
        raise EditorialSummaryError("editorial summary requires explicit human approval")
    _approval(data.get("approval"))
    records = data.get("records")
    if not isinstance(records, list) or not records:
        raise EditorialSummaryError("approved editorial summary records are missing")
    sources = {source["id"]: source for source in json.loads(Path(sources_path).read_text(encoding="utf-8"))}
    output = deepcopy(items)
    seen = set()
    for record in records:
        required = ("source_id", "source", "date", "url", "article_id", "original_title_sha256",
                    "original_summary_sha256", "summary_en", "summary_cn", "summary_id", "content_sha256")
        if not isinstance(record, dict) or any(not isinstance(record.get(key), str) or not record[key].strip() for key in required):
            raise EditorialSummaryError("editorial summary content or identity is missing")
        if (record.get("approval_status") != "APPROVED" or record.get("origin") != ORIGIN
                or record.get("summary_basis") != BASIS):
            raise EditorialSummaryError("editorial summary record is not approved")
        if record_hash(record) != record["content_sha256"] or summary_id(record) != record["summary_id"]:
            raise EditorialSummaryError("editorial summary content hash or identity mismatch")
        source = sources.get(record["source_id"])
        if not source or not source.get("enabled") or not source.get("official") or source["name"] != record["source"]:
            raise EditorialSummaryError("editorial summary source identity is invalid")
        if not start <= date.fromisoformat(record["date"]) <= start + timedelta(days=6):
            raise EditorialSummaryError("editorial summary date is outside the week")
        matches = [index for index, item in enumerate(output)
                   if item.get("source") == record["source"] and item.get("date") == record["date"]
                   and item.get("url") == record["url"]
                   and stable_item_id(item, "title", item.get("title_original") or "") == record["article_id"]
                   and original_sha256(item.get("title_original") or "") == record["original_title_sha256"]
                   and original_sha256(item.get("summary_original") or "") == record["original_summary_sha256"]]
        if len(matches) != 1:
            raise EditorialSummaryError("editorial summary unmatched or ambiguous article identity/hash")
        index = matches[0]
        if index in seen or output[index].get("editorial_summary"):
            raise EditorialSummaryError("same article enriched twice")
        seen.add(index)
        if any((output[index].get(key) or "").strip() for key in
               ("summary", "summary_original", "summary_en", "summary_cn")):
            raise EditorialSummaryError("editorial summary requires empty original summary fields")
        evidence = record.get("source_verification") or {}
        urls = evidence.get("official_urls")
        if (not isinstance(urls, list) or record["url"] not in urls or not urls
                or evidence.get("method") != "official_document_review"
                or not isinstance(evidence.get("verified_facts"), list) or not evidence["verified_facts"]
                or not all(isinstance(fact, str) and fact.strip() for fact in evidence["verified_facts"])):
            raise EditorialSummaryError("editorial summary official evidence is missing")
        date.fromisoformat(evidence.get("verified_on", ""))
        domains = [urlsplit(source.get(key) or "").hostname for key in ("url", "crawl_url")]
        domains = [domain.removeprefix("www.") for domain in domains if domain]
        for url in urls:
            host = urlsplit(canonical_url(url)).hostname
            if not any(host == domain or host.endswith("." + domain) for domain in domains):
                raise EditorialSummaryError("editorial summary evidence is outside official domains")
        issues = validate_translation_field(record["summary_en"], record["summary_cn"],
                                            field_type="summary", source=record["source"])
        if issues:
            raise EditorialSummaryError("editorial summary bilingual QA failed: " +
                                        ", ".join(issue["issue_id"] for issue in issues))
        output[index]["editorial_summary"] = {
            "origin": ORIGIN, "summary_basis": BASIS, "summary_en": record["summary_en"],
            "summary_cn": record["summary_cn"], "approval_status": "APPROVED",
            "approval": deepcopy(data["approval"]), "summary_id": record["summary_id"],
            "content_sha256": record["content_sha256"], "approved_file_sha256": expected_sha256,
            "source_verification": deepcopy(evidence),
        }
    return output, data


def summary_provenance(path, digest, data, original_items):
    return {
        "file_name": Path(path).name,
        "artifact_filename": "editorial_summaries_" + data["week_start"].replace("-", "") + ".json",
        "file_sha256": digest, "approval": data["approval"], "editorial_origin": ORIGIN,
        "original_item_count": len(original_items), "original_items_sha256": content_hash(original_items),
        "records": [{key: record[key] for key in ("summary_id", "content_sha256", "article_id")}
                    for record in data["records"]],
    }


def validate_summary_bundle(bundle_dir, weekly, provenance, artifacts):
    items = weekly.get("items", [])
    entry = artifacts.get("editorial_summaries")
    if not provenance:
        if entry or any(item.get("editorial_summary") for item in items):
            raise EditorialSummaryError("editorial summaries lack manifest provenance")
        return
    filename = provenance.get("artifact_filename")
    if not filename or Path(filename).name != filename:
        raise EditorialSummaryError("unsafe editorial summary artifact filename")
    if entry != {"filename": filename, "sha256": provenance.get("file_sha256")}:
        raise EditorialSummaryError("editorial summary artifact binding mismatch")
    count = provenance.get("original_item_count")
    if not isinstance(count, int) or count < 0 or count > len(items):
        raise EditorialSummaryError("invalid editorial summary original count")
    original = deepcopy(items[:count])
    for item in original:
        item.pop("editorial_summary", None)
    if content_hash(original) != provenance.get("original_items_sha256"):
        raise EditorialSummaryError("original items changed during editorial enrichment")
    digest = provenance["file_sha256"]
    expected, data = load_editorial_summaries(Path(bundle_dir) / filename, digest, weekly["week_start"], original)
    if summary_provenance(provenance.get("file_name", ""), digest, data, original) != provenance:
        raise EditorialSummaryError("editorial summary manifest provenance is inconsistent")
    if items[:count] != expected or any(item.get("editorial_summary") for item in items[count:]):
        raise EditorialSummaryError("editorial summary content was tampered with")
