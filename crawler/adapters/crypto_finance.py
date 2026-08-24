from crawler.article_parser import extract_date

from .common import absolute_url, clean_text


def parse_crypto_finance_list(soup, list_url, source):
    items = []
    containers = soup.select("article, .elementor-post, .elementor-post__card")
    for container in containers:
        link = container.find("a", href=True)
        if not link:
            continue
        href = link.get("href") or ""
        if "/category/" in href or href.rstrip("/").endswith("/news"):
            continue
        title_tag = container.select_one(".elementor-post__title a, h2 a, h3 a, a")
        title = clean_text((title_tag or link).get_text(" ", strip=True))
        if not title:
            continue
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
                "content_type": "news",
            }
        )

    unique = {}
    for item in items:
        unique[item["url"]] = item
    return list(unique.values())
