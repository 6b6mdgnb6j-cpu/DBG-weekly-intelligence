import re
from datetime import date
from urllib.parse import urljoin

import requests

from .common import request_get


def month_offsets(start, end, base_year=2026, base_month=8):
    current = date(end.year, end.month, 1)
    stop = date(start.year, start.month, 1)
    while current >= stop:
        offset = base_year * 12 + base_month - (current.year * 12 + current.month)
        if 0 <= offset <= 36:
            yield current.year, current.month, f"news_ym_{offset:02d}.json"
        if current.month == 1:
            current = date(current.year - 1, 12, 1)
        else:
            current = date(current.year, current.month - 1, 1)


def load_base_month(js_text):
    match = re.search(r"baseYear\s*=\s*parseInt\((\d{4}),10\).*?baseMonth\s*=\s*parseInt\((\d{1,2}),10\)", js_text, re.S)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 2026, 8


def parse_jpx_list(soup, list_url, source, week_start=None, week_end=None):
    start = week_start or date(2026, 8, 10)
    end = week_end or date(2026, 8, 16)
    js_url = urljoin(list_url, "news.js")
    js_response = request_get(js_url, timeout=15, attempts=2)
    base_year, base_month = load_base_month(js_response.text)

    items = []
    for _, _, filename in month_offsets(start, end, base_year, base_month):
        response = request_get(urljoin(list_url, filename), timeout=15, attempts=2)
        for entry in response.json():
            title = entry.get("title", "").strip()
            updated = entry.get("updated_date", {})
            href = entry.get("url", "")
            kind = entry.get("kind", "")
            if not title or not href or "JPX" not in kind and "お知らせ" not in kind:
                continue
            items.append(
                {
                    "title": title,
                    "url": urljoin(list_url, href),
                    "date": f"{updated.get('year','')}-{updated.get('month','')}-{updated.get('day','')}",
                    "summary": "",
                    "content_type": kind,
                }
            )
    return items
