import re
from collections import defaultdict


RESULT_TERMS = (
    "financial results",
    "consolidated financial results",
    "quarterly results",
    "annual results",
    "earnings",
    "explanatory material",
    "earnings forecast",
    "dividend forecast",
    "results presentation",
    "financial report",
)

PRIMARY_SOURCE_TERMS = (
    "authority",
    "commission",
    "central bank",
    "exchange",
    "reserve",
    "treasury",
    "监管",
    "管理局",
    "委员会",
    "央行",
    "交易所",
)

SECONDARY_SOURCE_TERMS = (
    "association",
    "协会",
    "institute",
    "commentary",
    "blog",
)

CROSS_SOURCE_ENTITY_TERMS = (
    ("monetary authority of singapore", "mas"),
    ("mas", "mas"),
    ("securities and exchange commission", "sec"),
    ("证券交易委员会", "sec"),
    ("sec", "sec"),
    ("commodity futures trading commission", "cftc"),
    ("商品期货交易委员会", "cftc"),
    ("cftc", "cftc"),
    ("hong kong monetary authority", "hkma"),
    ("香港金融管理局", "hkma"),
    ("hkma", "hkma"),
    ("european central bank", "ecb"),
    ("欧洲中央银行", "ecb"),
    ("ecb", "ecb"),
    ("lch", "lch"),
    ("ice", "ice"),
    ("eurex", "eurex"),
    ("clearstream", "clearstream"),
)

CROSS_SOURCE_ACTION_FAMILIES = (
    ("measures", ("introduces measures", "announce set of measures", "announces measures", "measures")),
    ("rulemaking", ("proposal", "proposed rule", "proposed regulation", "final rule", "rulemaking", "regulation")),
    ("consultation", ("consultation", "public consultation", "seeks comment", "requests comment")),
    ("launch", ("launch", "launches", "launched", "introduction", "introduces")),
    ("partnership", ("partnership", "partner", "partners")),
    ("transaction", ("acquisition", "acquire", "sale", "disposal", "divestment")),
    ("clearing", ("clearing", "clears", "cleared")),
)

CROSS_SOURCE_OBJECT_TERMS = (
    "asset management hub",
    "transfer agents",
    "clearing requirement",
    "order book requirement",
    "interest rate swaps",
    "overnight index swaps",
    "crypto asset index",
    "market integrity",
    "stablecoin",
    "market access",
    "financial risks",
    "benchmark regulation",
)

PERIOD_PATTERNS = (
    r"\bq[1-4]\s*fy\s*20\d{2}\b",
    r"\bq[1-4]\s*20\d{2}\b",
    r"\bfy\s*20\d{2}\b",
    r"\bh[1-2]\s*20\d{2}\b",
)


def _normalized_title(item):
    return (item.get("title_original") or "").lower()


def _is_results_document(item):
    title = _normalized_title(item)
    return any(term in title for term in RESULT_TERMS)


def _period_key(item):
    title = _normalized_title(item)
    for pattern in PERIOD_PATTERNS:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group().lower())
    ended = re.search(r"\bthree months ended\s+([a-z]+\s+\d{1,2},\s+20\d{2})\b", title, re.IGNORECASE)
    if ended:
        return f"three months ended {ended.group(1).lower()}"
    return ""


def _priority_rank(item):
    title = _normalized_title(item)
    if any(term in title for term in ("financial results", "quarterly results", "annual results")):
        return 0
    if any(term in title for term in ("overview of earnings", "explanatory material", "earnings overview")):
        return 1
    if any(term in title for term in ("forecast", "dividend revision", "dividend forecast")):
        return 2
    return 9


def _cluster_key(item):
    if not _is_results_document(item):
        return _cross_source_event_key(item)
    source = item.get("source", "")
    date = item.get("date", "")
    if not source or not date:
        return None
    return source, date, "same-day-results-package"


def _cross_source_event_key(item):
    title = _normalized_title(item)
    summary = (item.get("summary_original") or item.get("summary") or "").lower()
    text = f"{title} {summary}"
    date = item.get("date", "")
    if not date:
        return None
    entity = _canonical_entity(text)
    action = _action_family(text)
    event_object = _event_object(text)
    if entity and action and event_object:
        return "cross-source", date, entity, action, event_object
    return None


def _contains_alias(text, alias):
    if re.fullmatch(r"[a-z0-9]+", alias):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text))
    return alias in text


def _canonical_entity(text):
    for alias, canonical in CROSS_SOURCE_ENTITY_TERMS:
        if _contains_alias(text, alias):
            return canonical
    return ""


def _action_family(text):
    for family, phrases in CROSS_SOURCE_ACTION_FAMILIES:
        if any(phrase in text for phrase in phrases):
            return family
    return ""


def _event_object(text):
    for phrase in CROSS_SOURCE_OBJECT_TERMS:
        if phrase in text:
            return phrase
    return ""


def cluster_same_event_items(items):
    grouped = defaultdict(list)
    passthrough = []
    for index, item in enumerate(items):
        key = _cluster_key(item)
        if key:
            grouped[key].append((index, item))
        else:
            passthrough.append((index, item))

    kept_indexed = list(passthrough)
    clustered_samples = []
    for group in grouped.values():
        if len(group) == 1:
            kept_indexed.extend(group)
            continue

        group_sorted = sorted(group, key=lambda entry: (_event_priority_rank(entry[1]), entry[0]))
        main_index, main_item = group_sorted[0]
        kept_indexed.append((main_index, main_item))
        main_title = main_item.get("title_original", "")
        main_url = main_item.get("url", "")
        for _, dropped in group_sorted[1:]:
            clustered_samples.append(
                {
                    "source": dropped.get("source", ""),
                    "date": dropped.get("date", ""),
                    "title": dropped.get("title_original", ""),
                    "url": dropped.get("url", ""),
                    "drop_reason": "same_event_clustered",
                    "clustered_into": main_title,
                    "clustered_into_url": main_url,
                }
            )

    kept_indexed.sort(key=lambda entry: entry[0])
    return [item for _, item in kept_indexed], clustered_samples


def _event_priority_rank(item):
    source = (item.get("source") or "").lower()
    if any(term in source for term in PRIMARY_SOURCE_TERMS):
        return -1
    if any(term in source for term in SECONDARY_SOURCE_TERMS):
        return 5
    return _priority_rank(item)
