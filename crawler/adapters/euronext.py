from .common import absolute_url, clean_text


def parse_euronext_list(soup, list_url, source):
    items = []
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        date_text = clean_text(cells[0].get_text(" ", strip=True))
        link = cells[1].find("a", href=True)
        if not link:
            continue
        title = clean_text(link.get_text(" ", strip=True))
        href = link.get("href") or ""
        if not title or not date_text or "euronext-press-releases" not in href.lower():
            continue
        items.append(
            {
                "title": title,
                "url": absolute_url(list_url, href),
                "date": date_text,
                "summary": "",
                "content_type": "press_release",
            }
        )
    return items
