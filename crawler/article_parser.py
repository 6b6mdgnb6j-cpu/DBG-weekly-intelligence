import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .date_utils import in_week
from .news_model import standardize_news


HEADERS = {
    "User-Agent": "Mozilla/5.0",
}


DATE_PATTERNS = [
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{4}/\d{2}/\d{2}\b",
    r"\b\d{1,2}\.\d{1,2}\.\d{4}\b",
    r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    r"\b\d{1,2}\s[A-Z][a-z]+,?\s\d{4}\b",
    r"\b[A-Z][a-z]+\s\d{1,2},\s\d{4}\b",
]


def extract_date(text):
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            return match.group()
    return ""


def extract_metadata_date(soup):
    selectors = [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "article:published_time"}),
        ("meta", {"name": "date"}),
        ("meta", {"name": "pubdate"}),
        ("meta", {"name": "publishdate"}),
        ("meta", {"name": "DC.date"}),
        ("meta", {"name": "dc.date"}),
        ("meta", {"itemprop": "datePublished"}),
    ]
    for tag_name, attrs in selectors:
        tag = soup.find(tag_name, attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"].strip()

    time_tag = soup.find("time")
    if time_tag:
        return (time_tag.get("datetime") or time_tag.get_text(" ", strip=True)).strip()

    return ""


def extract_title(soup):
    meta_selectors = [
        ("meta", {"property": "og:title"}),
        ("meta", {"name": "twitter:title"}),
    ]
    for tag_name, attrs in meta_selectors:
        tag = soup.find(tag_name, attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"].strip()

    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)

    if soup.title:
        return soup.title.get_text(" ", strip=True)

    return ""


def extract_summary(soup):
    for attrs in (
        {"property": "og:description"},
        {"name": "description"},
        {"name": "twitter:description"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"].strip()[:300]

    for paragraph in soup.find_all("p"):
        text = paragraph.get_text(" ", strip=True)
        if len(text) > 40:
            return text[:300]

    return ""


def is_pdf_response(url, response):
    content_type = response.headers.get("Content-Type", "").lower()
    path = urlparse(url).path.lower()
    return "application/pdf" in content_type or path.endswith(".pdf")


def is_pdf_url(url):
    return urlparse(url).path.lower().endswith(".pdf")


def fallback_pdf_title(url, list_title):
    if list_title:
        return list_title
    filename = urlparse(url).path.rsplit("/", 1)[-1]
    return filename.replace("-", " ").replace("_", " ").replace(".pdf", "").strip()


def build_pdf_article(url, source, week_start, week_end, list_title="", list_date=""):
    raw_date = list_date
    title = fallback_pdf_title(url, list_title)
    item = standardize_news(
        source=source,
        title=title,
        url=url,
        date=raw_date,
        summary="",
    )
    diagnostic = {
        "title": item["title_original"] or list_title,
        "url": url,
        "raw_date": raw_date,
        "parsed_date": item["date"],
        "drop_reason": "",
    }
    if not item["title_original"] or not item["date"]:
        diagnostic["drop_reason"] = "date_parse_failed" if item["title_original"] else "missing_title"
        return item, None, diagnostic
    if not in_week(item["date"], week_start, week_end):
        diagnostic["drop_reason"] = "outside_period"
        return item, None, diagnostic
    diagnostic["drop_reason"] = "kept"
    return item, item, diagnostic


def parse_article(url, source, week_start, week_end, logger, list_title="", list_date=""):
    try:
        if is_pdf_url(url):
            return build_pdf_article(url, source, week_start, week_end, list_title, list_date)

        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        if is_pdf_response(url, response):
            return build_pdf_article(url, source, week_start, week_end, list_title, list_date)

        soup = BeautifulSoup(response.text, "html.parser")
        page_text = soup.get_text(" ", strip=True)
        raw_date = list_date or extract_metadata_date(soup) or extract_date(page_text[:3000])
        title = extract_title(soup) or list_title

        item = standardize_news(
            source=source,
            title=title,
            url=url,
            date=raw_date,
            summary=extract_summary(soup),
        )
        diagnostic = {
            "title": item["title_original"] or list_title,
            "url": url,
            "raw_date": raw_date,
            "parsed_date": item["date"],
            "drop_reason": "",
        }

        if not item["title_original"] or not item["date"]:
            diagnostic["drop_reason"] = "date_parse_failed" if item["title_original"] else "missing_title"
            return item, None, diagnostic

        if not in_week(item["date"], week_start, week_end):
            diagnostic["drop_reason"] = "outside_period"
            return item, None, diagnostic

        diagnostic["drop_reason"] = "kept"
        return item, item, diagnostic

    except Exception as exc:
        logger.info("Article failed: %s reason=%s", url, exc)
        return None, None, {
            "title": list_title,
            "url": url,
            "raw_date": list_date,
            "parsed_date": "",
            "drop_reason": f"parser_failed: {exc}",
        }
