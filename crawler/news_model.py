import html
import unicodedata

from .date_utils import normalize_date


NEWS_FIELDS = [
    "date",
    "title_original",
    "title_cn",
    "title_en",
    "summary",
    "source",
    "category",
    "subcategory",
    "brand",
    "competitor_type",
    "priority",
    "official",
    "relevance_score",
    "relevance_reason",
    "url",
]


MOJIBAKE_REPLACEMENTS = {
    "â": '"',
    "â": '"',
    "â": "'",
    "â": "'",
    "â": "-",
    "â": "-",
    "â¦": "...",
    "Â ": " ",
    "Â": "",
}


def is_garbled_text(text):
    if not text:
        return False
    stripped = text.lstrip()
    if stripped.startswith("%PDF"):
        return True
    if text.count("\ufffd") >= 3:
        return True

    checked = 0
    control_or_binary = 0
    for char in text:
        if char in "\n\r\t":
            continue
        checked += 1
        category = unicodedata.category(char)
        if category.startswith("C"):
            control_or_binary += 1

    if checked and control_or_binary / checked > 0.08:
        return True
    return False


def normalize_text_encoding(value, clear_garbage=False):
    text = html.unescape(value or "").strip()
    if clear_garbage and is_garbled_text(text):
        return ""
    if any(marker in text for marker in ("â", "Â", "Ã")):
        try:
            repaired = text.encode("latin1").decode("utf-8")
            if repaired.count("\ufffd") <= text.count("\ufffd"):
                text = repaired
        except Exception:
            pass
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, good)
    text = " ".join(text.split())
    if clear_garbage and is_garbled_text(text):
        return ""
    return text


def standardize_news(source, title, url, date="", summary=""):
    title = normalize_text_encoding(title)
    return {
        "date": normalize_date(date, source),
        "title_original": title,
        "title_cn": "",
        "title_en": "",
        "summary": normalize_text_encoding(summary, clear_garbage=True),
        "source": source.get("name", ""),
        "category": source.get("category", ""),
        "subcategory": source.get("subcategory", ""),
        "brand": source.get("brand", ""),
        "competitor_type": source.get("competitor_type", ""),
        "priority": int(source.get("priority") or 99),
        "official": bool(source.get("official", False)),
        "relevance_score": 0,
        "relevance_reason": "",
        "url": (url or "").strip(),
    }


def ensure_news_schema(item):
    clean = {}
    for field in NEWS_FIELDS:
        if field == "priority":
            clean[field] = int(item.get(field) or 99)
        elif field == "official":
            clean[field] = bool(item.get(field, False))
        elif field == "relevance_score":
            clean[field] = int(item.get(field) or 0)
        else:
            clean[field] = item.get(field, "") or ""
    return clean
