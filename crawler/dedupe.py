import re
from difflib import SequenceMatcher


def normalize_title(title):
    text = (title or "").lower()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())


def better_item(left, right):
    left_priority = int(left.get("priority") or 99)
    right_priority = int(right.get("priority") or 99)
    if left_priority != right_priority:
        return left if left_priority < right_priority else right

    if bool(left.get("official")) != bool(right.get("official")):
        return left if left.get("official") else right

    left_date = left.get("date") or "9999-12-31"
    right_date = right.get("date") or "9999-12-31"
    if left_date != right_date:
        return left if left_date < right_date else right

    return left


def dedupe_news(items, similarity_threshold=0.9):
    final = []
    url_index = {}
    title_index = {}

    for item in items:
        url = item.get("url", "").strip()
        title_key = normalize_title(item.get("title_original", ""))

        match_index = None
        if url and url in url_index:
            match_index = url_index[url]
        elif title_key and title_key in title_index:
            match_index = title_index[title_key]
        else:
            for index, existing in enumerate(final):
                existing_key = normalize_title(existing.get("title_original", ""))
                if not title_key or not existing_key:
                    continue
                score = SequenceMatcher(None, title_key, existing_key).ratio()
                if score >= similarity_threshold:
                    match_index = index
                    break

        if match_index is None:
            final.append(item)
            index = len(final) - 1
        else:
            final[match_index] = better_item(final[match_index], item)
            index = match_index

        kept = final[index]
        kept_url = kept.get("url", "").strip()
        kept_title = normalize_title(kept.get("title_original", ""))
        if kept_url:
            url_index[kept_url] = index
        if kept_title:
            title_index[kept_title] = index

    return sorted(final, key=lambda x: (x.get("category", ""), x.get("subcategory", ""), x.get("date", ""), x.get("source", "")))
