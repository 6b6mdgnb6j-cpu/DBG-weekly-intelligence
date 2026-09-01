from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


HEADERS = {"User-Agent": "Mozilla/5.0"}


def request_get(url, timeout=20, attempts=2, headers=None, params=None):
    last_error = None
    for _ in range(attempts):
        try:
            response = requests.get(url, headers=headers or HEADERS, timeout=timeout, params=params)
            response.raise_for_status()
            if (response.encoding or "").lower() in ("iso-8859-1", "windows-1252"):
                response.encoding = response.apparent_encoding
            return response
        except Exception as exc:
            last_error = exc
    raise last_error


def fetch_soup(url, timeout=20):
    response = request_get(url, timeout=timeout)
    return BeautifulSoup(response.text, "html.parser"), response.url


def clean_text(value):
    return " ".join((value or "").split())


def absolute_url(base_url, href):
    return urljoin(base_url, href or "").split("#")[0]
