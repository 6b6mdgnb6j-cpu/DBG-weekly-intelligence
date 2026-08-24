from .content_filter import (
    HIGH_IMPORTANCE_TERMS,
    INDIVIDUAL_ENFORCEMENT_TERMS,
    MARKET_WIDE_TERMS,
    NEGATIVE_TERMS,
    normalize_text,
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
    for term in HIGH_IMPORTANCE_TERMS:
        if term in text:
            return term
    words = [word for word in text.split() if len(word) > 4]
    return " ".join(words[:3]) if words else item.get("source", "")


def highlight_score(item):
    text = normalize_text(item.get("title_original"), item.get("summary"))
    if any(term in text for term in NEGATIVE_TERMS):
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
