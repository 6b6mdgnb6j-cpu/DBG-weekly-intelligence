import json
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
MAPPING_FILE = BASE_DIR / "config" / "competitor_mapping.json"
FALLBACK_BUSINESS = "Other / Cross-business"


def _load_config():
    with MAPPING_FILE.open(encoding="utf-8") as f:
        config = json.load(f)
    config["rules"] = sorted(config.get("rules", []), key=lambda rule: int(rule.get("priority") or 999))
    return config


def _norm(value):
    return " ".join((value or "").lower().split())


def _display_text(item):
    fields = [
        item.get("title_original", ""),
        item.get("summary_original", ""),
        item.get("summary", ""),
        item.get("source", ""),
        item.get("brand", ""),
        item.get("subcategory", ""),
        item.get("url", ""),
    ]
    return _norm(" ".join(str(field) for field in fields if field))


def _contains_keyword(text, keyword):
    keyword = _norm(keyword)
    if not keyword:
        return False
    if keyword.startswith(" ") or keyword.endswith(" "):
        return keyword.strip() in f" {text} "
    if re.fullmatch(r"[a-z0-9]+", keyword):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text))
    return keyword in text


def _matches_pattern(text, pattern):
    return bool(re.search(pattern, text, flags=re.I))


def _identify_competitor_group(item, config):
    text = _display_text(item)
    for group, aliases in (config.get("competitor_group_aliases") or {}).items():
        for alias in aliases:
            if _contains_keyword(text, alias):
                return group

    brand = item.get("brand", "")
    source = item.get("source", "")
    for value in (brand, source):
        value_norm = _norm(value)
        for group in (config.get("competitor_group_aliases") or {}):
            if value_norm == _norm(group):
                return group

    return brand or source or "Unknown"


def _valid_business(value, config):
    allowed = set(config.get("mapped_dbg_business_enum") or [])
    return value if value in allowed else FALLBACK_BUSINESS


def _fallback_mapping(group, config):
    default = (config.get("defaults") or {}).get(group)
    if default:
        return {
            "competitor_business": default.get("competitor_business", "source_default"),
            "mapped_dbg_business": _valid_business(default.get("mapped_dbg_business"), config),
            "mapping_confidence": default.get("mapping_confidence", "medium"),
            "mapping_reason": default.get("mapping_reason", "source_default"),
        }
    return {
        "competitor_business": "cross_business_or_unmapped",
        "mapped_dbg_business": FALLBACK_BUSINESS,
        "mapping_confidence": "low",
        "mapping_reason": "fallback: no content rule or source default matched",
    }


def map_competitor_item(item, config=None):
    config = config or _load_config()
    group = _identify_competitor_group(item, config)
    text = _display_text(item)

    for rule in config.get("rules", []):
        groups = rule.get("competitor_groups") or []
        if groups and group not in groups:
            continue
        keywords = rule.get("keywords_any") or []
        patterns = rule.get("regex_any") or []
        if any(_contains_keyword(text, keyword) for keyword in keywords) or any(
            _matches_pattern(text, pattern) for pattern in patterns
        ):
            return {
                "competitor_group": group,
                "competitor_business": rule.get("competitor_business", ""),
                "mapped_dbg_business": _valid_business(rule.get("mapped_dbg_business"), config),
                "mapping_confidence": rule.get("mapping_confidence", "medium"),
                "mapping_reason": rule.get("mapping_reason", f"content_rule:{rule.get('id', '')}"),
            }

    fallback = _fallback_mapping(group, config)
    fallback["competitor_group"] = group
    return fallback


def apply_competitor_mapping(items):
    config = _load_config()
    mapped_items = []
    for item in items:
        clean = dict(item)
        if clean.get("category") == "Competitor":
            clean.update(map_competitor_item(clean, config))
        mapped_items.append(clean)
    return mapped_items
