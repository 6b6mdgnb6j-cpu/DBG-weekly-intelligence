from .content_filter import (
    HIGH_VALUE_BUSINESS_TERMS,
    HIGH_VALUE_MACRO_TERMS,
    HIGH_IMPORTANCE_TERMS,
    INDIVIDUAL_ENFORCEMENT_TERMS,
    MARKET_WIDE_TERMS,
    NEGATIVE_TERMS,
    contains_term,
    has_material_development_signal,
    has_routine_operational_signal,
    is_recurring_market_commentary,
    normalize_text,
    routine_operational_is_overridden,
)


SOURCE_IMPORTANCE = {
    "European Central Bank": 3,
    "SEC": 3,
    "Federal Reserve": 3,
    "CFTC": 3,
    "BIS": 3,
    "中国人民银行": 3,
    "中国证券监督管理委员会": 3,
    "国家金融监督管理总局": 3,
    "国家外汇管理局": 3,
    "Deutsche Börse Group": 3,
    "Eurex": 3,
    "Clearstream": 3,
}


def topic_key(item):
    text = normalize_text(item.get("title_original"), item.get("summary"))
    for term in HIGH_VALUE_MACRO_TERMS:
        if term in text:
            return term
    for term in HIGH_VALUE_BUSINESS_TERMS:
        if term in text:
            return term
    for term in HIGH_IMPORTANCE_TERMS:
        if term in text:
            return term
    words = [word for word in text.split() if len(word) > 4]
    return " ".join(words[:3]) if words else item.get("source", "")


TIER_1_HIGHLIGHT_TERMS = [
    "fomc statement",
    "fomc minutes",
    "federal open market committee",
    "monetary policy decision",
    "notice of proposed rulemaking",
    "proposed rulemaking",
    "proposed regulation",
    "sef",
    "order book requirement",
    "derivatives contracts",
    "derivatives rule",
    "market structure",
    "market mechanism",
    "market access",
    "foreign market access",
    "mercados admitidos",
    "intermediários estrangeiros",
    "invest in hong kong etfs",
    "financial results",
    "quarterly results",
    "q2 2026 results",
    "capital markets rules change",
]


TIER_2_HIGHLIGHT_TERMS = [
    "new product",
    "data products",
    "ownership datasets",
    "index series",
    "new futures",
    "new options",
    "market expansion",
    "expansion and harmonisation",
    "strategic partnership",
    "stablecoin partnership",
    "cross-border",
    "crypto assets",
    "stablecoin",
    "asset management hub",
    "central moneymarkets unit",
    "renminbi sovereign bonds",
]


LOW_VALUE_HIGHLIGHT_TERMS = [
    "survey",
    "year in review",
    "webinar",
    "event",
    "speech",
    "forum",
    "research institute",
]


MONETARY_POLICY_HIGHLIGHT_TERMS = [
    "fomc statement",
    "fomc minutes",
    "federal open market committee",
    "monetary policy decision",
]


def highlight_score(item):
    text = normalize_text(item.get("title_original"), item.get("summary"))
    if any(contains_term(text, term) for term in NEGATIVE_TERMS):
        return 0
    if has_routine_operational_signal(text) and not routine_operational_is_overridden(text):
        return 0

    score = int(item.get("relevance_score") or 0)
    score += SOURCE_IMPORTANCE.get(item.get("source", ""), 0)
    if item.get("official"):
        score += 2
    if int(item.get("priority") or 99) == 1:
        score += 2
    if any(term in text for term in HIGH_IMPORTANCE_TERMS):
        score += 3
    if any(term in text for term in MARKET_WIDE_TERMS):
        score += 3
    if any(term in text for term in HIGH_VALUE_MACRO_TERMS):
        score += 7
    if any(term in text for term in HIGH_VALUE_BUSINESS_TERMS):
        score += 5
    if any(term in text for term in TIER_1_HIGHLIGHT_TERMS):
        score += 10
    elif any(term in text for term in TIER_2_HIGHLIGHT_TERMS):
        score += 6
    elif any(term in text for term in LOW_VALUE_HIGHLIGHT_TERMS):
        score -= 4
    if any(term in text for term in MONETARY_POLICY_HIGHLIGHT_TERMS):
        score += 8
    if is_recurring_market_commentary(item, text) and not has_material_development_signal(text):
        score -= 8
    if any(term in text for term in INDIVIDUAL_ENFORCEMENT_TERMS):
        score -= 5
        if any(term in text for term in MARKET_WIDE_TERMS):
            score += 2
    return score


def select_highlights(items, min_score=8, max_items=5):
    candidates = []
    for item in items:
        clean = dict(item)
        clean["highlight_score"] = highlight_score(clean)
        if clean["highlight_score"] >= min_score:
            candidates.append(clean)

    candidates.sort(
        key=lambda item: (
            -int(item.get("highlight_score") or 0),
            item.get("category", ""),
            item.get("source", ""),
            item.get("date", ""),
        )
    )

    highlights = []
    used_sources = set()
    used_topics = set()
    categories = ["Macro", "DBG", "Competitor"]

    for category in categories:
        for item in candidates:
            if item.get("category") != category:
                continue
            if item.get("source") in used_sources:
                continue
            topic = topic_key(item)
            if topic in used_topics:
                continue
            highlights.append(item)
            used_sources.add(item.get("source"))
            used_topics.add(topic)
            break

    for item in candidates:
        if len(highlights) >= max_items:
            break
        if item in highlights:
            continue
        if item.get("source") in used_sources:
            continue
        topic = topic_key(item)
        if topic in used_topics:
            continue
        highlights.append(item)
        used_sources.add(item.get("source"))
        used_topics.add(topic)

    return highlights[:max_items]
