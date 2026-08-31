import re
from datetime import timedelta

from .common import absolute_url, clean_text, request_get
from crawler.date_utils import parse_any_date


HKMA_PRESS_RELEASE_RE = re.compile(r"/press-releases/(\d{4})/(\d{2})/(\d{8})-\d+/?$")
HKMA_API_URL = "https://api.hkma.gov.hk/public/press-releases?lang=en&offset={offset}"
HKMA_DETAIL_URL = "https://www.hkma.gov.hk/eng/news-and-media/press-releases/{year}/{month}/{ymd}-{sequence}/"


def parse_hkma_api(week_start):
    items = []
    seen_offsets = set()
    offsets = [0, 50, 100]
    for offset in offsets:
        if offset in seen_offsets:
            continue
        seen_offsets.add(offset)
        try:
            response = request_get(HKMA_API_URL.format(offset=offset), timeout=12, attempts=1)
        except Exception:
            continue
        payload = response.json()
        records = payload.get("result", {}).get("records", [])
        if not records:
            continue
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
    return items


def covers_target_start(items, week_start):
    dates = []
    for item in items:
        parsed = parse_any_date(item.get("date", ""))
        if parsed:
            dates.append(parsed.date())
    return bool(dates and min(dates) < week_start)


def parse_hkma_html(soup, list_url):
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
    return items


def parse_hkma_target_week_urls(week_start, week_end):
    if not week_start or not week_end:
        return []
    items = []
    current = week_end
    while current >= week_start:
        ymd = current.strftime("%Y%m%d")
        for sequence in range(1, 11):
            items.append(
                {
                    "title": "",
                    "url": HKMA_DETAIL_URL.format(
                        year=current.strftime("%Y"),
                        month=current.strftime("%m"),
                        ymd=ymd,
                        sequence=sequence,
                    ),
                    "date": "",
                    "summary": "",
                    "content_type": "press_release",
                }
            )
        current -= timedelta(days=1)
    return items


def parse_hkma_list(soup, list_url, source, week_start=None, week_end=None):
    items = []
    if week_start:
        api_items = parse_hkma_api(week_start)
        if api_items and covers_target_start(api_items, week_start):
            return api_items
        items.extend(api_items)

    items.extend(parse_hkma_html(soup, list_url))
    items.extend(parse_hkma_target_week_urls(week_start, week_end))

    unique = {}
    for item in items:
        unique[item["url"]] = item
    return list(unique.values())
