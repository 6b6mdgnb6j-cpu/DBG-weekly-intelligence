from .content_filter import contains_any_phrase, normalize_text


MACRO_REGION_RULES = [
    (
        "中国",
        (
            "hong kong",
            "hkma",
            "hong kong monetary authority",
            "香港",
            "renminbi",
            "mainland",
            "china",
            "chinese",
        ),
    ),
    (
        "亚太",
        (
            "monetary authority of singapore",
            "新加坡金融管理局",
            "mas ",
            "singapore",
            "asset management hub",
            "korea",
            "korean",
            "australia",
            "asic",
            "apra",
            "japan",
        ),
    ),
    (
        "美国",
        (
            "securities and exchange commission",
            "federal reserve",
            "fomc",
            "fdic",
            "occ ",
            "u.s. treasury",
            "us treasury",
            "united states",
            "u.s.",
        ),
    ),
    (
        "欧洲",
        (
            "european central bank",
            "ecb",
            "eu ",
            "european union",
            "esma",
            "eiopa",
            "eba",
            "bafin",
            "eurosystem",
        ),
    ),
]


def macro_region_for_item(item):
    if (item.get("category") or "").lower() != "macro":
        return item.get("subcategory", "")
    text = f" {normalize_text(item.get('title_original'), item.get('summary'), item.get('source'), item.get('brand'))} "
    for region, terms in MACRO_REGION_RULES:
        if contains_any_phrase(text, terms):
            return region
    return item.get("subcategory", "")


def apply_macro_geography(items):
    mapped = []
    for item in items:
        clean = dict(item)
        region = macro_region_for_item(clean)
        if region:
            clean["subcategory"] = region
        mapped.append(clean)
    return mapped
