import json
from html import unescape
from urllib.parse import urlencode


NFRA_DETAIL_BASE = "https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html"


def _json_text_from_soup(soup):
    text = soup.get_text("", strip=True)
    if text:
        return unescape(text)
    return unescape(str(soup))


def _records_from_payload(payload):
    data = payload.get("data")
    if not isinstance(data, list):
        return

    for entry in data:
        if not isinstance(entry, dict):
            continue
        docs = entry.get("docInfoVOList")
        if isinstance(docs, list):
            for doc in docs:
                if isinstance(doc, dict):
                    merged = dict(doc)
                    if not merged.get("itemName"):
                        merged["itemName"] = entry.get("itemName")
                    if not merged.get("itemId"):
                        merged["itemId"] = entry.get("itemId")
                    yield merged
        elif entry.get("docId"):
            yield entry


def _detail_url(record):
    if str(record.get("isTitleLink") or "") == "1" and record.get("titleLink"):
        return record["titleLink"]

    doc_id = record.get("docId")
    item_id = record.get("itemId")
    if not doc_id or not item_id:
        return ""
    return f"{NFRA_DETAIL_BASE}?{urlencode({'docId': doc_id, 'itemId': item_id})}"


def parse_nfra_docinfo_json(soup, current_url, source, week_start=None, week_end=None):
    try:
        payload = json.loads(_json_text_from_soup(soup))
    except json.JSONDecodeError:
        return []

    if payload.get("rptCode") != 200:
        return []

    items = []
    seen = set()
    for record in _records_from_payload(payload) or []:
        title = (record.get("docTitle") or record.get("docSubtitle") or "").strip()
        raw_date = (record.get("publishDate") or record.get("builddate") or "").strip()
        url = _detail_url(record)
        if not title or not raw_date or not url or url in seen:
            continue
        seen.add(url)
        items.append(
            {
                "title": title,
                "url": url,
                "date": raw_date,
                "summary": (record.get("docSummary") or "").strip(),
                "content_type": "nfra_docinfo",
                "category": (record.get("itemName") or "").strip(),
            }
        )
    return items
