import re
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
from urllib.parse import urlparse


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
        return _cross_source_event_key(item) or _official_repost_key(item)
    source = item.get("source", "")
    date = item.get("date", "")
    if not source or not date:
        return None
    return source, date, "same-day-results-package"


def _official_repost_key(item):
    if not item.get("official"):
        return None
    title = _normalize_text(item.get("title_original", ""))
    summary = _normalize_text(item.get("summary_original") or item.get("summary") or "")
    date = item.get("date", "")
    family = _official_source_family(item)
    if not title or not summary or not date or not family:
        return None
    return "official-repost", family, date, title, summary


def _normalize_text(text):
    text = (text or "").lower()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())


def _official_source_family(item):
    url = item.get("url", "")
    host = urlparse(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    if host:
        return host
    return _normalize_text(item.get("source", ""))


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

    grouped, repost_passthrough = _merge_official_repost_groups(grouped)
    passthrough.extend(repost_passthrough)

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


def _merge_official_repost_groups(grouped):
    regular_groups = defaultdict(list)
    repost_candidates = []
    passthrough = []

    for key, group in grouped.items():
        if key and key[0] == "official-repost":
            repost_candidates.extend((key, entry) for entry in group)
        else:
            regular_groups[key].extend(group)

    used = set()
    for pos, (key, entry) in enumerate(repost_candidates):
        if pos in used:
            continue
        family = key[1]
        date = key[2]
        title = key[3]
        summary = key[4]
        group = [entry]
        used.add(pos)
        for other_pos, (other_key, other_entry) in enumerate(repost_candidates[pos + 1 :], start=pos + 1):
            if other_pos in used:
                continue
            if other_key[1] != family or not _dates_close(date, other_key[2]):
                continue
            if _similarity(title, other_key[3]) < 0.94:
                continue
            if _similarity(summary, other_key[4]) < 0.80:
                continue
            group.append(other_entry)
            used.add(other_pos)

        if len(group) > 1:
            regular_groups[("official-repost", family, date, title)].extend(group)
        else:
            passthrough.extend(group)

    return regular_groups, passthrough


def _dates_close(left, right):
    if left == right:
        return True
    try:
        left_date = date.fromisoformat(left)
        right_date = date.fromisoformat(right)
    except ValueError:
        return False
    return abs((left_date - right_date).days) <= 1


def _similarity(left, right):
    return SequenceMatcher(None, left, right).ratio()


def _event_priority_rank(item):
    official_repost_rank = _official_repost_priority_rank(item)
    if official_repost_rank:
        return official_repost_rank
    source = (item.get("source") or "").lower()
    if any(term in source for term in PRIMARY_SOURCE_TERMS):
        return -1
    if any(term in source for term in SECONDARY_SOURCE_TERMS):
        return 5
    return _priority_rank(item)


def _official_repost_priority_rank(item):
    if not item.get("official"):
        return 0
    url = (item.get("url") or "").lower()
    title = (item.get("title_original") or "").lower()
    text = f"{url} {title}"
    leadership_terms = (
        "leadership",
        "leader",
        "leaders",
        "profile",
        "biography",
        "management",
        "senior-official",
        "hanglingdao",
        "lingdao",
        "领导",
    )
    primary_terms = (
        "news",
        "press",
        "announcement",
        "announcements",
        "media",
        "communication",
        "communications",
        "goutongjiaoliu",
        "要闻",
        "公告",
    )
    if any(term in url for term in leadership_terms):
        return 10
    if any(term in text for term in primary_terms):
        return -2
    return 0
