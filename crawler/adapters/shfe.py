from .common import absolute_url, clean_text


def parse_shfe_notice_list(soup, current_url, source, week_start=None, week_end=None):
    items = []
    seen = set()
    for block in soup.select(".table_item_info"):
        link = block.select_one(".info_item_title a[href]")
        date_node = block.select_one(".info_item_date")
        if not link or not date_node:
            continue

        href = link.get("href", "")
        if "/publicnotice/" not in absolute_url(current_url, href) or "/t20" not in href:
            continue

        title = clean_text(link.get("title") or link.get_text(" ", strip=True))
        raw_date = clean_text(date_node.get_text(" ", strip=True))
        url = absolute_url(current_url, href)
        if not title or not raw_date or url in seen:
            continue

        seen.add(url)
        items.append(
            {
                "title": title,
                "url": url,
                "date": raw_date,
                "summary": "",
                "content_type": "shfe_notice",
            }
        )
    return items
