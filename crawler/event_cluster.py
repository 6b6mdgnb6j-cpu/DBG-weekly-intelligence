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
        return None
    source = item.get("source", "")
    date = item.get("date", "")
    if not source or not date:
        return None
    return source, date, "same-day-results-package"


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

        group_sorted = sorted(group, key=lambda entry: (_priority_rank(entry[1]), entry[0]))
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
