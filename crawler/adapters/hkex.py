from .common import absolute_url, clean_text


def parse_hkex_list(soup, list_url, source):
    items = []
    for row in soup.select(".whats_on_tdy_row"):
        date_box = row.select_one(".whats_on_tdy_ball")
        title_link = row.select_one(".whats_on_tdy_text_2 a[href]")
        category_text = clean_text(row.select_one(".whats_on_tdy_text_1").get_text(" ", strip=True) if row.select_one(".whats_on_tdy_text_1") else "")
        if not date_box or not title_link:
            continue
        href = title_link.get("href") or ""
        if ".pdf" in href.lower() or "/-/media/" in href.lower():
            continue
        if "corporate" not in category_text.lower():
            continue
        title = clean_text(title_link.get_text(" ", strip=True))
        date_text = clean_text(date_box.get_text(" ", strip=True))
        if not title or not date_text:
            continue
        items.append(
            {
                "title": title,
                "url": absolute_url(list_url, href),
                "date": date_text,
                "summary": "",
                "content_type": "corporate_news_release",
            }
        )
    return items
