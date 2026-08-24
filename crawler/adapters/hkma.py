import re

from .common import absolute_url, clean_text, request_get
from crawler.date_utils import parse_any_date


HKMA_PRESS_RELEASE_RE = re.compile(r"/press-releases/(\d{4})/(\d{2})/(\d{8})-\d+/?$")
HKMA_API_URL = "https://api.hkma.gov.hk/public/press-releases?lang=en&offset={offset}"


def parse_hkma_api(week_start):
    items = []
    offset = 0
    while offset <= 300:
        try:
            response = request_get(HKMA_API_URL.format(offset=offset), timeout=10, attempts=1)
        except Exception:
            return items
        payload = response.json()
        records = payload.get("result", {}).get("records", [])
        if not records:
            break
        for record in records:
            title = clean_text(record.get("title", ""))
            url = record.get("link", "")
            raw_date = record.get("date", "")
            if not title or not url or not raw_date:
                continue
            items.append(
                {
                    "title": title,
                    "url": url,
                    "date": raw_date,
                    "summary": "",
                    "content_type": "press_release",
                }
            )
        oldest = parse_any_date(records[-1].get("date", ""))
        if oldest and oldest.date() < week_start:
            break
        offset += len(records)
    return items


def parse_hkma_list(soup, list_url, source, week_start=None, week_end=None):
    if week_start:
        api_items = parse_hkma_api(week_start)
        if api_items:
            return api_items

    items = []
    for link in soup.select("a[href*='/press-releases/20']"):
        href = link.get("href") or ""
        match = HKMA_PRESS_RELEASE_RE.search(href)
        if not match:
            continue
        title = clean_text(link.get_text(" ", strip=True))
        if not title:
            continue
        ymd = match.group(3)
        items.append(
            {
                "title": title,
                "url": absolute_url(list_url, href),
                "date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}",
                "summary": "",
                "content_type": "press_release",
            }
        )

    unique = {}
    for item in items:
        unique[item["url"]] = item
    return list(unique.values())
