import re

from .common import absolute_url, clean_text


DATE_RE = re.compile(
    r"\b\d{4}-\d{1,2}-\d{1,2}\b"
    r"|\b\d{1,2}[./]\d{1,2}[./]\d{4}\b"
    r"|\b\d{1,2}\s+[A-Z][a-z]+\s+\d{4}\b"
    r"|\b[A-Z][a-z]{2,8}\.?\s+\d{1,2},\s+\d{4}\b"
)


def _date_from_text(text):
    match = DATE_RE.search(text or "")
    return match.group(0).replace(".", "") if match else ""


def _strip_date(text, raw_date):
    text = clean_text(text)
    if raw_date:
        text = clean_text(text.replace(raw_date, " "))
    return text


def _title_from_block(block, link, raw_date):
    title = clean_text(link.get_text(" ", strip=True))
    if title and len(title) > 3:
        return _strip_date(title, raw_date)
    text = clean_text(block.get_text(" ", strip=True))
    if raw_date and raw_date in text:
        before, after = text.split(raw_date, 1)
        return _strip_date(before or after, raw_date)
    return _strip_date(text, raw_date)


def _append_unique(items, seen, title, url, date, summary=""):
    title = clean_text(title)
    if not title or not url or url in seen:
        return
    seen.add(url)
    items.append({"title": title, "url": url, "date": date, "summary": clean_text(summary)})


def parse_table_release_list(soup, current_url, source, week_start=None, week_end=None):
    items = []
    seen = set()
    for row in soup.select("table tr"):
        text = clean_text(row.get_text(" ", strip=True))
        raw_date = _date_from_text(text)
        link = row.find("a", href=True)
        if not raw_date or not link:
            continue
        title = _strip_date(link.get_text(" ", strip=True), raw_date)
        if not title:
            title = _strip_date(text, raw_date)
        _append_unique(items, seen, title, absolute_url(current_url, link["href"]), raw_date)
    return items


def parse_article_release_list(soup, current_url, source, week_start=None, week_end=None):
    items = []
    seen = set()
    blocks = []
    blocks.extend(soup.find_all("article"))
    blocks.extend(soup.select("div.views-row"))
    blocks.extend(soup.find_all("li"))
    for article in blocks:
        text = clean_text(article.get_text(" ", strip=True))
        raw_date = _date_from_text(text)
        link = article.find("a", href=True)
        if not raw_date or not link:
            continue
        title = _title_from_block(article, link, raw_date)
        summary = _strip_date(text, raw_date)
        _append_unique(items, seen, title, absolute_url(current_url, link["href"]), raw_date, summary)
    for link in soup.find_all("a", href=True):
        text = clean_text(link.get_text(" ", strip=True))
        raw_date = _date_from_text(text)
        if not raw_date:
            continue
        title = _strip_date(text, raw_date)
        _append_unique(items, seen, title, absolute_url(current_url, link["href"]), raw_date)
    return items


def parse_six_list(soup, current_url, source, week_start=None, week_end=None):
    items = []
    seen = set()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/newsroom/media-releases/" not in href:
            continue
        text = clean_text(link.get_text(" ", strip=True))
        raw_date = _date_from_text(text)
        if not raw_date:
            continue
        title = _strip_date(text.split(raw_date)[0], raw_date) or _strip_date(text, raw_date)
        summary = text.split(raw_date, 1)[-1] if raw_date in text else ""
        _append_unique(items, seen, title, absolute_url(current_url, href), raw_date, summary)
    return items


def parse_b3_list(soup, current_url, source, week_start=None, week_end=None):
    items = []
    seen = set()
    container = soup.select_one(".bg-conteudo") or soup
    for link in container.find_all("a", href=True):
        text = clean_text(link.get_text(" ", strip=True))
        raw_date = _date_from_text(text)
        if not raw_date:
            continue
        title = _strip_date(text, raw_date)
        _append_unique(items, seen, title, absolute_url(current_url, link["href"]), raw_date)
    return items


def parse_korea_fsc_list(soup, current_url, source, week_start=None, week_end=None):
    items = []
    seen = set()
    for row in soup.find_all("li"):
        text = clean_text(row.get_text(" ", strip=True))
        raw_date = _date_from_text(text)
        link = row.find("a", href=True)
        if not raw_date or not link:
            continue
        title = _strip_date(link.get_text(" ", strip=True), raw_date)
        for marker in (" The Financial Services Commission", " The FSC "):
            if marker in title:
                title = title.split(marker, 1)[0].strip()
        summary = _strip_date(text, raw_date)
        _append_unique(items, seen, title, absolute_url(current_url, link["href"]), raw_date, summary)
    return items


def parse_adgm_list(soup, current_url, source, week_start=None, week_end=None):
    items = []
    seen = set()
    for card in soup.find_all(attrs={"date": True, "href": True}):
        raw_date = card.get("date", "")
        title = clean_text(card.get_text(" ", strip=True))
        href = card.get("href", "")
        if not raw_date or not title or href.startswith("/faqs/"):
            continue
        _append_unique(items, seen, title, absolute_url(current_url, href), raw_date)
    return items


def parse_bma_list(soup, current_url, source, week_start=None, week_end=None):
    items = []
    seen = set()
    for row in soup.find_all("li"):
        text = clean_text(row.get_text(" ", strip=True))
        match = re.search(r"Uploaded on\s+(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})", text)
        link = row.find("a", href=True)
        if not match or not link:
            continue
        raw_date = match.group(1)
        title = text.split("Uploaded on", 1)[0]
        _append_unique(items, seen, title, absolute_url(current_url, link["href"]), raw_date)
    return items


def parse_naic_list(soup, current_url, source, week_start=None, week_end=None):
    items = []
    seen = set()
    for article in soup.find_all("article"):
        text = clean_text(article.get_text(" ", strip=True))
        raw_date = _date_from_text(text)
        link = article.find("a", href=True)
        if not raw_date or not link:
            continue
        title = _strip_date(link.get_text(" ", strip=True), raw_date)
        summary = _strip_date(text, raw_date)
        _append_unique(items, seen, title, absolute_url(current_url, link["href"]), raw_date, summary)
    return items
