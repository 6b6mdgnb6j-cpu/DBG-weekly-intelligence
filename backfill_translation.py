import argparse
import json
import re
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

from crawler.translator import TitleTranslator, detect_language, looks_chinese, looks_english
from qa_gate import file_sha256


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "output" / "backfill"
DEFAULT_OVERRIDE_PATH = BASE_DIR / "config" / "historical_translation_overrides.json"
LANGUAGE_FIELDS = {
    "title_cn",
    "title_en",
    "title_original_lang",
    "summary_original",
    "summary_cn",
    "summary_en",
    "summary_original_lang",
}
ALLOWED_TOP_LEVEL_FIELDS = {"translation_mode"}


def load_json(path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def load_historical_overrides(path=DEFAULT_OVERRIDE_PATH):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    clean = {}
    for url, fields in data.items():
        if not isinstance(url, str) or not isinstance(fields, dict):
            continue
        clean_fields = {}
        for field in ("title_cn", "summary_cn"):
            value = fields.get(field)
            if isinstance(value, str) and value.strip():
                clean_fields[field] = value.strip()
        if clean_fields:
            clean[url] = clean_fields
    return clean


def historical_override_for(item, field, overrides):
    url = item.get("url") or ""
    fields = overrides.get(url) or {}
    value = fields.get(field)
    return value.strip() if isinstance(value, str) else ""


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as f:
            temp_path = Path(f.name)
            f.write(encoded)
            f.flush()
        json.loads(temp_path.read_text(encoding="utf-8"))
        temp_path.replace(path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def is_english_fallback(value, original):
    text = (value or "").strip()
    source = (original or "").strip()
    return bool(text and source and text == source and looks_english(text) and not looks_chinese(text))


def needs_chinese(value, original):
    if not (original or "").strip() or detect_language(original) != "en":
        return False
    if not (value or "").strip():
        return True
    if is_english_fallback(value, original):
        return True
    return looks_english(value) and not looks_chinese(value)


def coverage(payload):
    items = payload.get("items") or []
    title_cn_fallback = 0
    visibly_untranslated = 0
    for item in items:
        title_original = item.get("title_original") or item.get("title") or ""
        summary_original = item.get("summary_original") or item.get("summary") or ""
        if is_english_fallback(item.get("title_cn"), title_original):
            title_cn_fallback += 1
        if needs_chinese(item.get("title_cn"), title_original):
            visibly_untranslated += 1
        if needs_chinese(item.get("summary_cn"), summary_original):
            visibly_untranslated += 1

    def count(field):
        return sum(1 for item in items if (item.get(field) or "").strip())

    return {
        "items": len(items),
        "item_count": payload.get("item_count", len(items)),
        "translation_mode": payload.get("translation_mode", ""),
        "title_original": count("title_original"),
        "title_cn": count("title_cn"),
        "title_en": count("title_en"),
        "summary_original": count("summary_original"),
        "summary_cn": count("summary_cn"),
        "summary_en": count("summary_en"),
        "title_cn_english_fallback": title_cn_fallback,
        "visibly_untranslated": visibly_untranslated,
    }


def normalize_item_language_fields(item, translator, stats, historical_overrides=None):
    historical_overrides = historical_overrides or {}
    clean = dict(item)
    source = clean.get("source", "")
    title_original = clean.get("title_original") or clean.get("title") or clean.get("title_en") or clean.get("title_cn") or ""
    summary_original = clean.get("summary_original")
    if summary_original is None:
        summary_original = clean.get("summary") or clean.get("summary_en") or clean.get("summary_cn") or ""

    title_lang = detect_language(title_original)
    summary_lang = detect_language(summary_original)
    clean["title_original"] = title_original
    clean["title_original_lang"] = title_lang
    clean["summary_original"] = summary_original
    clean["summary_original_lang"] = summary_lang

    if title_lang == "en":
        clean["title_en"] = clean.get("title_en") or title_original
        if needs_chinese(clean.get("title_cn"), title_original):
            translated = translator._translate_text(title_original, source)
            if translated:
                clean["title_cn"] = translated
                stats["title_translated"] += 1
            else:
                override = historical_override_for(clean, "title_cn", historical_overrides)
                if override:
                    clean["title_cn"] = override
                    stats["title_overridden"] += 1
                else:
                    clean["title_cn"] = ""
                    stats["title_failures"] += 1
        else:
            stats["title_preserved"] += 1
    elif title_lang == "zh":
        clean["title_cn"] = clean.get("title_cn") or title_original
        clean["title_en"] = clean.get("title_en", "")
        stats["title_preserved"] += 1

    if summary_lang == "en":
        clean["summary_en"] = clean.get("summary_en") or summary_original
        if needs_chinese(clean.get("summary_cn"), summary_original):
            translated = translator._translate_text(summary_original, source)
            if translated:
                clean["summary_cn"] = translated
                stats["summary_translated"] += 1
            else:
                override = historical_override_for(clean, "summary_cn", historical_overrides)
                if override:
                    clean["summary_cn"] = override
                    stats["summary_overridden"] += 1
                else:
                    clean["summary_cn"] = ""
                    stats["summary_failures"] += 1
        else:
            stats["summary_preserved"] += 1
    elif summary_lang == "zh":
        clean["summary_cn"] = clean.get("summary_cn") or summary_original
        clean["summary_en"] = clean.get("summary_en", "")
        stats["summary_preserved"] += 1
    else:
        clean["summary_en"] = clean.get("summary_en", "")
        clean["summary_cn"] = clean.get("summary_cn", "")

    return clean


def item_key(item):
    return (
        item.get("url") or "",
        item.get("title_original") or item.get("title") or "",
        item.get("date") or "",
        item.get("source") or "",
    )


def refresh_highlights(payload, translated_items):
    translated_by_key = {item_key(item): item for item in translated_items}
    highlights = []
    for highlight in payload.get("highlights") or []:
        translated = translated_by_key.get(item_key(highlight))
        if not translated:
            highlights.append(highlight)
            continue
        merged = dict(highlight)
        for field in LANGUAGE_FIELDS:
            if field in translated:
                merged[field] = translated[field]
        highlights.append(merged)
    return highlights


def non_language_projection(payload):
    clean = deepcopy(payload)
    for field in ALLOWED_TOP_LEVEL_FIELDS:
        clean.pop(field, None)
    for item in clean.get("items") or []:
        for field in LANGUAGE_FIELDS:
            item.pop(field, None)
    for item in clean.get("highlights") or []:
        for field in LANGUAGE_FIELDS:
            item.pop(field, None)
    return clean


def structural_diff_count(before, after):
    before_projection = non_language_projection(before)
    after_projection = non_language_projection(after)
    if before_projection == after_projection:
        return 0
    before_items = before_projection.get("items") or []
    after_items = after_projection.get("items") or []
    diff = 0
    if len(before_items) != len(after_items):
        diff += abs(len(before_items) - len(after_items))
    for old, new in zip(before_items, after_items):
        if old != new:
            diff += 1
    for field, value in before_projection.items():
        if field == "items":
            continue
        if after_projection.get(field) != value:
            diff += 1
    return diff


def backfill_payload(payload, translator, historical_overrides=None):
    historical_overrides = historical_overrides or {}
    before = deepcopy(payload)
    stats = {
        "title_translated": 0,
        "summary_translated": 0,
        "title_overridden": 0,
        "summary_overridden": 0,
        "title_failures": 0,
        "summary_failures": 0,
        "title_preserved": 0,
        "summary_preserved": 0,
    }
    translated_items = [
        normalize_item_language_fields(item, translator, stats, historical_overrides) for item in payload.get("items") or []
    ]
    result = dict(payload)
    result["translation_mode"] = "bilingual"
    result["items"] = translated_items
    if payload.get("highlights") is not None:
        result["highlights"] = refresh_highlights(payload, translated_items)
    return result, {
        **stats,
        "before": coverage(before),
        "after": coverage(result),
        "structural_diff_count": structural_diff_count(before, result),
    }


def default_candidate_path(input_path, payload, output_dir):
    week = str(payload.get("week_start", "")).replace("-", "")
    stem = f"weekly_data_{week}" if week else Path(input_path).stem
    return Path(output_dir) / f"{stem}.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline translation backfill for an existing weekly JSON artifact.")
    parser.add_argument("weekly_json", help="Existing weekly_data or published weekly JSON.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for bilingual candidate artifacts.")
    parser.add_argument("--output", help="Explicit candidate output path.")
    args = parser.parse_args(argv)

    input_path = Path(args.weekly_json)
    payload = load_json(input_path)
    translator = TitleTranslator(enabled=True)
    historical_overrides = load_historical_overrides()
    candidate, report = backfill_payload(payload, translator, historical_overrides)
    output_path = Path(args.output) if args.output else default_candidate_path(input_path, payload, args.output_dir)
    report_path = output_path.with_name(output_path.stem + "_backfill_report.json")

    write_json_atomic(output_path, candidate)
    report.update(
        {
            "input_path": str(input_path),
            "output_path": str(output_path),
            "input_sha256": file_sha256(input_path),
            "output_sha256": file_sha256(output_path),
        }
    )
    write_json_atomic(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
