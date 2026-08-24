from crawler.article_parser import extract_date

from .common import absolute_url, clean_text


def parse_amf_list(soup, list_url, source):
    items = []
    for link in soup.select("a[href*='/en/news-publications/']"):
        href = link.get("href") or ""
        if href.rstrip("/").endswith("/amf-news-releases"):
            continue
        if "/en/news-publications/news-releases/" not in href and "/en/news-publications/news/" not in href:
            continue

        title = clean_text(link.get_text(" ", strip=True))
        if not title or title.lower() in {"news releases", "amf news releases", "news"}:
            continue

        container = link
        for parent in link.parents:
            if getattr(parent, "name", None) in ("article", "li", "tr", "div"):
                text = clean_text(parent.get_text(" ", strip=True))
                if len(text) > len(title):
                    container = parent
                    break
        text = clean_text(container.get_text(" ", strip=True))
        raw_date = extract_date(text)
        if not raw_date:
            continue
        items.append(
            {
                "title": title,
                "url": absolute_url(list_url, href),
                "date": raw_date,
                "summary": "",
                "content_type": "news_release",
            }
        )

    unique = {}
    for item in items:
        unique[item["url"]] = item
    return list(unique.values())
