from .common import absolute_url, clean_text


def _time_value(container):
    time_tag = container.find("time")
    if not time_tag:
        return ""
    return clean_text(time_tag.get("datetime") or time_tag.get_text(" ", strip=True))


def parse_fca_list(soup, list_url, source, week_start=None, week_end=None):
    items = []
    seen = set()

    for row in soup.select("li.content-list-item"):
        anchor = row.find("a", href=True)
        title_tag = row.select_one(".content-item__title")
        if not anchor or not title_tag:
            continue
        url = absolute_url(list_url, anchor.get("href"))
        title = clean_text(title_tag.get_text(" ", strip=True))
        raw_date = _time_value(row)
        if not title or not url or url in seen:
            continue
        seen.add(url)
        items.append(
            {
                "title": title,
                "url": url,
                "date": raw_date,
                "summary": "",
                "content_type": "news",
            }
        )

    for slide in soup.select(".slide__content"):
        anchor = slide.find("a", href=True)
        title_tag = slide.select_one(".slide__title") or slide.find(["h2", "h3", "h4"])
        if not anchor or not title_tag:
            continue
        url = absolute_url(list_url, anchor.get("href"))
        title = clean_text(title_tag.get_text(" ", strip=True))
        summary_tag = slide.find("p")
        summary = clean_text(summary_tag.get_text(" ", strip=True)) if summary_tag else ""
        if not title or not url or url in seen:
            continue
        seen.add(url)
        items.append(
            {
                "title": title,
                "url": url,
                "date": "",
                "summary": summary,
                "content_type": "speech",
            }
        )

    return items
