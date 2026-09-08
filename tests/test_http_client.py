import unittest
import logging
from datetime import date
from unittest.mock import patch

import requests

from crawler import http_client
from crawler.rss_parser import collect_rss


class FakeResponse:
    def __init__(self, status_code=200, text="ok", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"
        self.url = "https://example.test"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} Error", response=self)


class HttpClientRetryTests(unittest.TestCase):
    def request_with(self, outcomes, **kwargs):
        calls = []

        def fake_request(method, url, **request_kwargs):
            calls.append((method, url, request_kwargs))
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch.object(http_client.SESSION, "request", side_effect=fake_request), patch(
            "crawler.http_client.time.sleep"
        ) as sleep_mock:
            response = http_client.request("GET", "https://example.test", **kwargs)
        return response, calls, sleep_mock

    def assert_attempts(self, response, attempts, retried=True):
        self.assertEqual(response.network_attempts, attempts)
        self.assertEqual(response.network_retried, retried)

    def test_502_then_200_retries_successfully(self):
        meta = {}
        response, calls, _ = self.request_with([FakeResponse(502), FakeResponse(200)], meta=meta)
        self.assert_attempts(response, 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(response.network_retry_reasons, ["status:502"])
        self.assertEqual(meta["request_attempts_total"], 2)
        self.assertEqual(meta["retried_requests"], 1)
        self.assertEqual(meta["last_status_code"], 200)

    def test_503_twice_then_200_is_bounded(self):
        response, calls, _ = self.request_with(
            [FakeResponse(503), FakeResponse(503), FakeResponse(200)]
        )
        self.assert_attempts(response, 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(response.network_retry_reasons, ["status:503", "status:503"])

    def test_read_timeout_then_200_retries_successfully(self):
        response, calls, _ = self.request_with(
            [requests.exceptions.ReadTimeout("read timed out"), FakeResponse(200)]
        )
        self.assert_attempts(response, 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(response.network_retry_reasons, ["timeout"])

    def test_connection_error_then_200_retries_successfully(self):
        response, calls, _ = self.request_with(
            [requests.exceptions.ConnectionError("connection reset by peer"), FakeResponse(200)]
        )
        self.assert_attempts(response, 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(response.network_retry_reasons, ["connection_error"])

    def test_transient_ssl_eof_then_200_retries_successfully(self):
        response, calls, _ = self.request_with(
            [requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING"), FakeResponse(200)]
        )
        self.assert_attempts(response, 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(response.network_retry_reasons, ["transient_ssl_error"])

    def test_certificate_verify_failure_does_not_retry(self):
        with patch.object(
            http_client.SESSION,
            "request",
            side_effect=requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED"),
        ), patch("crawler.http_client.time.sleep") as sleep_mock:
            with self.assertRaises(requests.exceptions.SSLError) as ctx:
                http_client.request("GET", "https://example.test")
        self.assertEqual(ctx.exception.network_attempts, 1)
        self.assertFalse(ctx.exception.network_retried)
        self.assertEqual(ctx.exception.network_final_error_type, "ssl_certificate_error")
        sleep_mock.assert_not_called()

    def test_403_does_not_retry(self):
        with patch.object(http_client.SESSION, "request", return_value=FakeResponse(403)):
            with self.assertRaises(requests.exceptions.HTTPError) as ctx:
                http_client.request("GET", "https://example.test")
        self.assertEqual(ctx.exception.network_attempts, 1)
        self.assertFalse(ctx.exception.network_retried)
        self.assertEqual(ctx.exception.network_final_error_type, "http_403")

    def test_404_does_not_retry(self):
        with patch.object(http_client.SESSION, "request", return_value=FakeResponse(404)):
            with self.assertRaises(requests.exceptions.HTTPError) as ctx:
                http_client.request("GET", "https://example.test")
        self.assertEqual(ctx.exception.network_attempts, 1)
        self.assertFalse(ctx.exception.network_retried)
        self.assertEqual(ctx.exception.network_final_error_type, "http_404")

    def test_429_retry_after_is_bounded(self):
        response, calls, sleep_mock = self.request_with(
            [FakeResponse(429, headers={"Retry-After": "60"}), FakeResponse(200)]
        )
        self.assert_attempts(response, 2)
        self.assertEqual(len(calls), 2)
        sleep_mock.assert_called_once_with(2.0)

    def test_post_does_not_retry_by_default(self):
        with patch.object(http_client.SESSION, "request", return_value=FakeResponse(502)):
            with self.assertRaises(requests.exceptions.HTTPError) as ctx:
                http_client.request("POST", "https://example.test")
        self.assertEqual(ctx.exception.network_attempts, 1)
        self.assertFalse(ctx.exception.network_retried)

    def test_read_only_post_can_opt_into_retry(self):
        calls = []

        def fake_request(method, url, **request_kwargs):
            calls.append((method, url, request_kwargs))
            return FakeResponse(502) if len(calls) == 1 else FakeResponse(200)

        with patch.object(http_client.SESSION, "request", side_effect=fake_request), patch(
            "crawler.http_client.time.sleep"
        ):
            response = http_client.request("POST", "https://example.test", retry_post=True)
        self.assert_attempts(response, 2)
        self.assertEqual(len(calls), 2)

    def test_source_pipeline_recovers_from_initial_502(self):
        source = {
            "name": "Mock RSS",
            "url": "https://example.test/feed.xml",
            "method": "rss",
        }
        feed_text = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item>
            <title>Market infrastructure rule update</title>
            <link>https://example.test/news</link>
            <pubDate>Tue, 01 Sep 2026 12:00:00 GMT</pubDate>
            <description>Relevant market infrastructure news.</description>
          </item>
        </channel></rss>"""
        with patch.object(
            http_client.SESSION,
            "request",
            side_effect=[FakeResponse(502), FakeResponse(200, text=feed_text)],
        ), patch("crawler.http_client.time.sleep"):
            raw, filtered, meta = collect_rss(
                source,
                date(2026, 8, 31),
                date(2026, 9, 6),
                logging.getLogger("test"),
            )

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(meta["error"], "")
        self.assertEqual(meta["request_attempts_total"], 2)
        self.assertEqual(meta["retried_requests"], 1)
        self.assertEqual(meta["last_status_code"], 200)


if __name__ == "__main__":
    unittest.main()
