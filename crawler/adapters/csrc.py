import json
import re
from html import unescape
from urllib.parse import urljoin


CSRC_BASE_URL = "https://www.csrc.gov.cn/"

TITLE_KEYS = ("title", "bt", "name", "docTitle")
DATE_KEYS = ("publishedTime", "publishTime", "publishDate", "pubDate", "releaseTime", "date", "pubtime", "fbsj")
URL_KEYS = ("url", "link", "href", "docUrl", "docpuburl", "htmlUrl", "contentUrl")
CATEGORY_KEYS = ("channelName", "channel", "category", "columnName", "channelTitle")
SUMMARY_KEYS = ("summary", "description", "docSummary", "content", "intro", "abstract")
CONTAINER_KEYS = ("data", "result", "results", "list", "records", "docs", "rows")


def _clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unescape(str(value))).strip()


def _json_text_from_soup(soup):
    text = soup.get_text("", strip=True)
    if text:
        return unescape(text)
    return unescape(str(soup))


def _load_json_payload(soup):
    text = _json_text_from_soup(soup).strip()
    if not text:
        return None
    match = re.match(r"^[A-Za-z_$][\w$]*\((.*)\)\s*;?$", text, flags=re.S)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _first(record, keys):
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return _clean(value)
    return ""


def _iter_records(value):
    if isinstance(value, list):
        for entry in value:
            yield from _iter_records(entry)
        return

    if not isinstance(value, dict):
        return

    if _first(value, TITLE_KEYS) or _first(value, URL_KEYS):
        yield value

    for key in CONTAINER_KEYS:
        child = value.get(key)
        if isinstance(child, (dict, list)):
            yield from _iter_records(child)


def _normalize_url(href):
    href = _clean(href)
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("www."):
        return "https://" + href
    return urljoin(CSRC_BASE_URL, href).split("#")[0]


def parse_csrc_search_json(soup, current_url, source, week_start=None, week_end=None):
    payload = _load_json_payload(soup)
    if payload is None:
        return []

    items = []
    seen = set()
    for record in _iter_records(payload):
        title = _first(record, TITLE_KEYS)
        raw_date = _first(record, DATE_KEYS)
        url = _normalize_url(_first(record, URL_KEYS))
        if not title or not raw_date or not url or url in seen:
            continue

        seen.add(url)
        items.append(
            {
                "title": title,
                "url": url,
                "date": raw_date,
                "summary": _first(record, SUMMARY_KEYS),
                "content_type": "csrc_search",
                "category": _first(record, CATEGORY_KEYS),
            }
        )
    return items
