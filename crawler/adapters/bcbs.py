import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .common import clean_text


BCBS_SURFACES = (
    {
        "surface_key": "publications",
        "surface_name": "BCBS Publications",
        "url": "https://www.bis.org/committees/bcbs/publications",
    },
    {
        "surface_key": "media_releases",
        "surface_name": "BCBS Media Releases",
        "url": "https://www.bis.org/committees/bcbs/news",
    },
)

MONTH_PATTERN = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
DATE_RE = re.compile(
    rf"\b(?:\d{{1,2}}\s+{MONTH_PATTERN}\s+20\d{{2}}|"
    rf"{MONTH_PATTERN}\s+\d{{1,2}},?\s+20\d{{2}}|"
    r"20\d{2}-\d{2}-\d{2})\b",
    re.I,
)

STRONG_DOCUMENT_TYPES = {
    "standards",
    "guidelines",
    "sound practices",
    "implementation reports",
    "frequently asked questions",
    "faqs",
    "consultative",
    "qis",
}
KEEP_TOPICS = (
    "basel framework",
    "basel iii",
    "banking regulation",
    "capital",
    "liquidity",
    "leverage ratio",
    "credit risk",
    "counterparty risk",
    "market risk",
    "operational risk",
    "operational resilience",
    "financial stability",
    "systemic",
    "stress test",
    "margin",
    "collateral",
    "resolution",
    "cryptoasset",
    "disclosure",
    "supervisory",
)
MATERIAL_ACTIONS = (
    "publish",
    "issue",
    "consult",
    "finalis",
    "finaliz",
    "amend",
    "update",
    "adopt",
    "approve",
    "standard",
    "framework",
    "guidance",
    "report",
    "assessment",
    "requirement",
)
REJECT_PATTERNS = {
    "bcbs_event_or_speech": ("conference", "webinar", "event", "keynote speech", "fireside chat"),
    "bcbs_career_or_personnel": ("career", "vacancy", "appointed", "appointment", "joins the"),
    "bcbs_generic_announcement": ("save the date", "subscribe", "email alert"),
}


def _contains_reject_term(text, term):
    if term == "event":
        return re.search(r"(?<![\w-])events?(?![\w-])", text) is not None
    return term in text


def _has_substantive_signal(text, document_type=""):
    strong_type = any(value in document_type.lower() for value in STRONG_DOCUMENT_TYPES)
    has_topic = any(value in text for value in KEEP_TOPICS)
    has_action = any(value in text for value in MATERIAL_ACTIONS)
    return (strong_type and (has_topic or has_action)) or (has_topic and has_action)


def _has_substantive_non_event_context(candidate):
    fragments = re.split(
        r"(?<=[.!?])\s+",
        " ".join((candidate.get("title", ""), candidate.get("summary", ""))).lower(),
    )
    event_terms = REJECT_PATTERNS["bcbs_event_or_speech"]
    substantive_text = " ".join(
        fragment
        for fragment in fragments
        if fragment and not any(_contains_reject_term(fragment, term) for term in event_terms)
    )
    return _has_substantive_signal(substantive_text, candidate.get("document_type", ""))


def _official_item_url(url, surface_key):
    parsed = urlsplit(url or "")
    if parsed.netloc.lower() not in {"bis.org", "www.bis.org"}:
        return False
    if surface_key == "publications":
        return parsed.path.startswith("/publications/") or parsed.path.startswith("/bcbs/publ/")
    return parsed.path.startswith("/media-releases/") or parsed.path.startswith("/press/")


def _date_from_node(node):
    date_node = node.select_one(
        "time, [data-publication-date], [data-date], .card-date, .date, .publication-date"
    )
    if date_node:
        value = clean_text(
            date_node.get("datetime", "")
            or date_node.get("data-publication-date", "")
            or date_node.get("data-date", "")
            or date_node.get_text(" ", strip=True)
        )
        match = DATE_RE.search(value)
        if match:
            return match.group(0)
    return ""


def _field_text(node, selectors):
    for selector in selectors:
        value = node.select_one(selector)
        if value:
            text = clean_text(value.get_text(" ", strip=True))
            if text:
                return text
    return ""


def _record_node(link):
    for parent in link.parents:
        if getattr(parent, "name", None) in {"article", "li"}:
            return parent
        classes = set(parent.get("class") or []) if hasattr(parent, "get") else set()
        if classes.intersection({"publication-item", "media-release-item", "search-result", "result-item", "list-item"}):
            return parent
    return link.parent


def _document_type(node, surface):
    explicit = clean_text(node.get("data-document-type", ""))
    if explicit:
        return explicit
    badges = [clean_text(value.get_text(" ", strip=True)) for value in node.select(".card-header .badge")]
    badges = [value for value in badges if value]
    for value in badges:
        if value.lower() not in {"publication", "media release"}:
            return value
    return _field_text(node, (".type", ".publication-type", ".series")) or (
        "Media release" if surface["surface_key"] == "media_releases" else "Publication"
    )


def parse_bcbs_surface(html, surface, current_url):
    soup = BeautifulSoup(html or "", "html.parser")
    records = []
    seen = set()
    links = soup.select(
        ".card-wrapper > a.card-link[href], main a[href], [role='main'] a[href], article a[href]"
    )
    for link in links:
        url = urljoin(current_url, link.get("href", ""))
        if not _official_item_url(url, surface["surface_key"]):
            continue
        canonical = url.split("#", 1)[0]
        if canonical in seen:
            continue
        node = _record_node(link)
        title = _field_text(node, (".card-heading", "h2", "h3", "h4", "h5"))
        if not title:
            title = clean_text(link.get_text(" ", strip=True))
        if len(title) < 12:
            continue
        publication_date = _date_from_node(node)
        document_type = _document_type(node, surface)
        topic = _field_text(node, (".card-topic", ".topic", ".topics", "[data-topic]"))
        summary = _field_text(
            node, (".card-description", ".summary", ".description", ".excerpt", "p")
        )
        if summary == title:
            summary = ""
        official_document_date = clean_text(node.get("data-document-date", ""))
        seen.add(canonical)
        records.append(
            {
                "title": title,
                "url": canonical,
                "publication_date_text": publication_date,
                "official_document_date_text": official_document_date,
                "document_type": document_type,
                "topic": topic,
                "summary": summary,
                "source_context": surface["surface_name"],
                "surface_key": surface["surface_key"],
            }
        )

    next_link = soup.select_one("a[rel='next'][href], .pagination a.next[href], a.next[href]")
    next_url = urljoin(current_url, next_link.get("href", "")) if next_link else ""
    return records, next_url


def bcbs_filter_reason(candidate):
    text = " ".join(
        (
            candidate.get("title", ""),
            candidate.get("summary", ""),
            candidate.get("document_type", ""),
            candidate.get("topic", ""),
        )
    ).lower()
    for reason, terms in REJECT_PATTERNS.items():
        if any(_contains_reject_term(text, term) for term in terms):
            if reason == "bcbs_event_or_speech" and _has_substantive_non_event_context(candidate):
                continue
            return reason

    if _has_substantive_signal(text, candidate.get("document_type", "")):
        return ""
    return "bcbs_non_material"


BCBS_PROFILE = {
    "profile_key": "bcbs",
    "surfaces": BCBS_SURFACES,
    "parse_surface": parse_bcbs_surface,
    "filter_reason": bcbs_filter_reason,
    "max_pages": 12,
}
