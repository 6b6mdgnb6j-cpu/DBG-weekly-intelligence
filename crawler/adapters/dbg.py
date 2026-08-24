from .common import absolute_url, clean_text


def parse_deutsche_boerse_search_cards(soup, list_url, source):
    items = []
    for link in soup.select("a.teasable-search-result-link[href]"):
        date_tag = link.select_one(".search-result-date")
        title_tag = link.select_one(".search-result-description")
        if not date_tag or not title_tag:
            continue
        title = clean_text(title_tag.get_text(" ", strip=True))
        date_text = clean_text(date_tag.get_text(" ", strip=True)).replace("Release date:", "").strip()
        if not title or not date_text:
            continue
        items.append(
            {
                "title": title,
                "url": absolute_url(list_url, link.get("href")),
                "date": date_text,
                "summary": "",
                "content_type": "news_card",
            }
        )
    return items


def parse_dbg_list(soup, list_url, source):
    return parse_deutsche_boerse_search_cards(soup, list_url, source)


def parse_eurex_list(soup, list_url, source):
    return parse_deutsche_boerse_search_cards(soup, list_url, source)
