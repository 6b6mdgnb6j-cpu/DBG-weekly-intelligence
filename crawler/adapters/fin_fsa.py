"""FIN-FSA publication pages only; navigation dates are never publication dates."""
import re
from urllib.parse import urljoin, urlparse

from .common import clean_text
from .expansion import _date_from_text


PUBLICATION_PATH = re.compile(
    r"^/en/publications-and-press-releases/(?:press-release|news|supervision-releases)/20\d{2}/[^/]+/?$", re.I)


def is_fin_fsa_publication(url):
    parsed = urlparse(url)
    return parsed.hostname in {"www.finanssivalvonta.fi", "finanssivalvonta.fi"} and bool(PUBLICATION_PATH.fullmatch(parsed.path))


def parse_fin_fsa_list(soup, current_url, source, week_start=None, week_end=None):
    items, seen = [], set()
    # The live press list uses ul.listing.pagelist > li. Do not walk all li:
    # ancestor navigation li contain dates belonging to nested decision links.
    for row in soup.select("ul.listing.pagelist > li"):
        if row.find_parent(["nav", "header", "footer", "aside"]):
            continue
        link = row.find("a", href=True, recursive=False)
        time = row.select_one(".page-list-block-time time")
        if not link or not time:
            continue
        url = urljoin(current_url, link['href']).split('#')[0]
        if not is_fin_fsa_publication(url) or url in seen:
            continue
        raw_date = clean_text(time.get('datetime') or time.get_text(' ', strip=True))
        if not raw_date:
            continue
        seen.add(url)
        items.append({'title': clean_text(link.get_text(' ', strip=True)),
                      'url': url, 'date': raw_date, 'summary': ''})
    return items


def fin_fsa_publication_date(soup):
    # Publication-labelled text in the article itself is required. A date on a
    # related link, navigation, generic <time>, or page-modified tag is unsafe.
    article = soup.find('article')
    if not article:
        return ''
    for node in article.find_all(string=True):
        if node.find_parent(['a', 'nav', 'aside', 'footer', 'ul', 'ol']):
            continue
        label = str(node)
        # A labelled article date may be split across an inline <time>. Only
        # join this explicit date element; never absorb arbitrary child text.
        if re.fullmatch(r'\s*(?:Press release|News|Supervision release)\s*', label, re.I):
            time = node.parent.find('time', recursive=False)
            if time:
                label += ' ' + time.get_text(' ', strip=True)
        match = re.match(r'^\s*(?:Press release|News|Supervision release)\s+(.+)', label, re.I)
        if match:
            value = _date_from_text(match.group(1))
            if value:
                return value
    return ''
