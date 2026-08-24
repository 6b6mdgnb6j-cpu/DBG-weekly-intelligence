from crawler.article_parser import extract_date

from .common import absolute_url, clean_text


def parse_govuk_list(soup, list_url, source):
    items = []
    selectors = [
        "li.gem-c-document-list__item",
        ".gem-c-document-list__item",
        "li[class*='document-list']",
    ]
    for entry in soup.select(", ".join(selectors)):
        link = entry.find("a", href=True)
        if not link:
            continue
        href = link.get("href") or ""
        if not (
            href.startswith("/government/news/")
            or href.startswith("/government/press-releases/")
            or href.startswith("/government/publications/")
        ):
            continue
        title = clean_text(link.get_text(" ", strip=True))
        if not title:
            continue
        time_tag = entry.find("time")
        raw_date = ""
        if time_tag:
            raw_date = (time_tag.get("datetime") or time_tag.get_text(" ", strip=True)).strip()
        raw_date = raw_date or extract_date(entry.get_text(" ", strip=True))
        if not raw_date:
            continue
        items.append(
            {
                "title": title,
                "url": absolute_url(list_url, href),
                "date": raw_date,
                "summary": "",
                "content_type": "official_document",
            }
        )

    unique = {}
    for item in items:
        unique[item["url"]] = item
    return list(unique.values())
