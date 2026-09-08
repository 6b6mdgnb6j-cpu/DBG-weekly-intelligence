from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler.http_client import HEADERS, get, post


def request_get(url, timeout=20, attempts=2, headers=None, params=None, meta=None, **kwargs):
    return get(
        url,
        headers=headers or HEADERS,
        timeout=timeout,
        attempts=attempts,
        params=params,
        meta=meta,
        **kwargs,
    )


def request_post(url, timeout=20, attempts=1, headers=None, params=None, meta=None, retry_post=False, **kwargs):
    return post(
        url,
        headers=headers or HEADERS,
        timeout=timeout,
        attempts=attempts,
        params=params,
        meta=meta,
        retry_post=retry_post,
        **kwargs,
    )


def fetch_soup(url, timeout=20):
    response = request_get(url, timeout=timeout)
    return BeautifulSoup(response.text, "html.parser"), response.url


def clean_text(value):
    return " ".join((value or "").split())


def absolute_url(base_url, href):
    return urljoin(base_url, href or "").split("#")[0]
