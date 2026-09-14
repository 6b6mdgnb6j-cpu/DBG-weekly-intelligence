import unittest
import logging
from datetime import date
from unittest.mock import patch

import requests

from crawler import http_client
from crawler.rss_parser import collect_rss
from crawler.web_parser import collect_web


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
        self.assertEqual(meta["requests_total"], 1)
        self.assertEqual(meta["request_attempts_total"], 2)
        self.assertEqual(meta["retried_requests"], 1)
        self.assertEqual(meta["last_retry_error"], "status:502")
        self.assertEqual(meta["last_status_code"], 200)
        self.assertNotIn("last_request_error", meta)

    def test_two_successful_gets_record_request_count_without_retries(self):
        meta = {}
        with patch.object(http_client.SESSION, "request", return_value=FakeResponse(200)):
            first = http_client.request("GET", "https://example.test/one", meta=meta)
            second = http_client.request("GET", "https://example.test/two", meta=meta)
        self.assertEqual(first.network_attempts, 1)
        self.assertEqual(second.network_attempts, 1)
        self.assertEqual(meta["requests_total"], 2)
        self.assertEqual(meta["request_attempts_total"], 2)
        self.assertEqual(meta.get("retried_requests", 0), 0)

    def test_two_logical_requests_with_one_timeout_retry(self):
        meta = {}
        outcomes = [FakeResponse(200), requests.exceptions.ReadTimeout("read timed out"), FakeResponse(200)]

        def fake_request(method, url, **request_kwargs):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch.object(http_client.SESSION, "request", side_effect=fake_request), patch(
            "crawler.http_client.time.sleep"
        ):
            http_client.request("GET", "https://example.test/one", meta=meta)
            http_client.request("GET", "https://example.test/two", meta=meta)
        self.assertEqual(meta["requests_total"], 2)
        self.assertEqual(meta["request_attempts_total"], 3)
        self.assertEqual(meta["retried_requests"], 1)
        self.assertEqual(meta["last_retry_error"], "timeout")

    def test_final_502_failure_records_bounded_attempts(self):
        meta = {}
        with patch.object(http_client.SESSION, "request", return_value=FakeResponse(502)), patch(
            "crawler.http_client.time.sleep"
        ):
            with self.assertRaises(requests.exceptions.HTTPError) as ctx:
                http_client.request("GET", "https://example.test", attempts=2, meta=meta)
        self.assertEqual(ctx.exception.network_attempts, 2)
        self.assertTrue(ctx.exception.network_retried)
        self.assertEqual(meta["requests_total"], 1)
        self.assertEqual(meta["request_attempts_total"], 2)
        self.assertEqual(meta["retried_requests"], 1)
        self.assertEqual(meta["last_retry_error"], "status:502")
        self.assertEqual(meta["last_request_error"], "http_502")
        self.assertNotIn("last_network_error", meta)

    def test_429_then_success_records_retry_without_final_error(self):
        meta = {}
        response, _, _ = self.request_with(
            [FakeResponse(429, headers={"Retry-After": "1"}), FakeResponse(200)],
            meta=meta,
        )
        self.assertEqual(response.network_final_error_type, "")
        self.assertEqual(meta["requests_total"], 1)
        self.assertEqual(meta["request_attempts_total"], 2)
        self.assertEqual(meta["retried_requests"], 1)
        self.assertEqual(meta["last_retry_error"], "status:429")
        self.assertNotIn("last_request_error", meta)

    def test_connection_error_then_success_records_retry_without_final_error(self):
        meta = {}
        response, _, _ = self.request_with(
            [requests.exceptions.ConnectionError("connection reset by peer"), FakeResponse(200)],
            meta=meta,
        )
        self.assertEqual(response.network_final_error_type, "")
        self.assertEqual(meta["requests_total"], 1)
        self.assertEqual(meta["request_attempts_total"], 2)
        self.assertEqual(meta["retried_requests"], 1)
        self.assertEqual(meta["last_retry_error"], "connection_error")
        self.assertNotIn("last_request_error", meta)

    def test_403_records_single_request_without_retry(self):
        meta = {}
        with patch.object(http_client.SESSION, "request", return_value=FakeResponse(403)):
            with self.assertRaises(requests.exceptions.HTTPError):
                http_client.request("GET", "https://example.test", meta=meta)
        self.assertEqual(meta["requests_total"], 1)
        self.assertEqual(meta["request_attempts_total"], 1)
        self.assertEqual(meta.get("retried_requests", 0), 0)
        self.assertEqual(meta["last_request_error"], "http_403")

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
        self.assertEqual(meta["requests_total"], 1)
        self.assertEqual(meta["request_attempts_total"], 2)
        self.assertEqual(meta["retried_requests"], 1)
        self.assertEqual(meta["last_status_code"], 200)

    def test_generic_web_pipeline_aggregates_detail_retry_metadata(self):
        source = {
            "name": "Mock Web",
            "url": "https://example.test/news",
            "method": "web",
            "max_pages": 1,
            "max_items": 5,
        }
        list_html = """
        <html><body>
          <article>
            <a href="/news/2026/market-infrastructure-rule-update">
              Market infrastructure rule update 2026-09-01
            </a>
          </article>
        </body></html>
        """
        detail_html = """
        <html>
          <head><meta name="description" content="Relevant market infrastructure news."></head>
          <body><h1>Market infrastructure rule update</h1><time>2026-09-01</time></body>
        </html>
        """
        with patch.object(
            http_client.SESSION,
            "request",
            side_effect=[
                FakeResponse(200, text=list_html),
                FakeResponse(502),
                FakeResponse(200, text=detail_html),
            ],
        ), patch("crawler.http_client.time.sleep"):
            raw, filtered, meta = collect_web(
                source,
                date(2026, 8, 31),
                date(2026, 9, 6),
                logging.getLogger("test"),
            )

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(meta["requests_total"], 2)
        self.assertEqual(meta["request_attempts_total"], 3)
        self.assertEqual(meta["retried_requests"], 1)
        self.assertEqual(meta["last_retry_error"], "status:502")
        self.assertEqual(meta["last_status_code"], 200)
        self.assertEqual(meta["error"], "")

    def test_generic_web_max_scan_limit_does_not_claim_target_boundary(self):
        source = {
            "name": "Mock Web",
            "url": "https://example.test/news",
            "method": "web",
            "max_pages": 1,
            "max_scan_candidates": 1,
            "max_items": 5,
        }
        list_html = """
        <html><body>
          <article>
            <a href="/news/2026/market-infrastructure-rule-update">
              Market infrastructure rule update 2026-09-11
            </a>
          </article>
          <article>
            <a href="/news/2026/older-market-infrastructure-rule-update">
              Older market infrastructure rule update 2026-09-06
            </a>
          </article>
        </body></html>
        """
        detail_html = """
        <html>
          <head><meta name="description" content="Relevant market infrastructure news."></head>
          <body><h1>Market infrastructure rule update</h1><time>2026-09-11</time></body>
        </html>
        """
        with patch.object(
            http_client.SESSION,
            "request",
            side_effect=[FakeResponse(200, text=list_html), FakeResponse(200, text=detail_html)],
        ):
            raw, filtered, meta = collect_web(
                source,
                date(2026, 9, 7),
                date(2026, 9, 13),
                logging.getLogger("test"),
            )

        self.assertEqual(meta["candidates_discovered"], 2)
        self.assertEqual(meta["candidates_scanned"], 1)
        self.assertEqual(meta["stopped_reason"], "max_scan_candidates")
        self.assertFalse(meta["target_period_reached"])
        self.assertEqual(len(filtered), 1)

    def test_shfe_web_adapter_reaches_historical_target_week(self):
        source = {
            "id": "SRC-076",
            "name": "上海期货交易所",
            "url": "https://www.shfe.com.cn",
            "crawl_url": "https://www.shfe.com.cn/publicnotice/notice/",
            "method": "web",
            "category": "Competitor",
            "subcategory": "交易与清算",
            "brand": "Eurex",
            "max_pages": 1,
            "max_items": 5,
        }
        list_html = """
        <html><body>
          <div class="table_item_info">
            <div class="info_item_title">
              <a href="./202609/t20260911_833384.html" title="关于做好市场风险控制工作的通知">
                关于做好市场风险控制工作的通知
              </a>
            </div>
            <div class="info_item_date">2026-09-11</div>
          </div>
          <div class="table_item_info">
            <div class="info_item_title">
              <a href="./202609/t20260906_833100.html" title="早于目标周的公告">
                早于目标周的公告
              </a>
            </div>
            <div class="info_item_date">2026-09-06</div>
          </div>
          <a href="/publicnotice/notice/">公告通知</a>
        </body></html>
        """
        detail_html = """
        <html><body>
          <h1>关于做好市场风险控制工作的通知</h1>
          <div class="content">发布日期：2026-09-11</div>
          <div class="TRS_Editor">请各有关单位关注市场动态，采取有力措施。</div>
        </body></html>
        """
        with patch.object(
            http_client.SESSION,
            "request",
            side_effect=[FakeResponse(200, text=list_html), FakeResponse(200, text=detail_html)],
        ):
            raw, filtered, meta = collect_web(
                source,
                date(2026, 9, 7),
                date(2026, 9, 13),
                logging.getLogger("test"),
            )

        self.assertEqual(meta["error"], "")
        self.assertEqual(meta["candidates_discovered"], 2)
        self.assertEqual(meta["candidates_scanned"], 2)
        self.assertEqual(meta["list_items_with_date"], 2)
        self.assertEqual(meta["dated_candidates"], 2)
        self.assertEqual(meta["newest_date_seen"], "2026-09-11")
        self.assertEqual(meta["oldest_date_seen"], "2026-09-06")
        self.assertTrue(meta["target_period_reached"])
        self.assertEqual(meta["stopped_reason"], "passed_target_start")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["date"], "2026-09-11")

    def test_shfe_max_items_does_not_hide_target_week_candidates(self):
        source = {
            "id": "SRC-076",
            "name": "上海期货交易所",
            "url": "https://www.shfe.com.cn",
            "crawl_url": "https://www.shfe.com.cn/publicnotice/notice/",
            "method": "web",
            "category": "Competitor",
            "subcategory": "交易与清算",
            "brand": "Eurex",
            "max_pages": 1,
            "max_items": 1,
        }
        list_html = """
        <html><body>
          <div class="table_item_info">
            <div class="info_item_title">
              <a href="./202609/t20260911_833384.html" title="9月11日公告">9月11日公告</a>
            </div>
            <div class="info_item_date">2026-09-11</div>
          </div>
          <div class="table_item_info">
            <div class="info_item_title">
              <a href="./202609/t20260908_833288.html" title="9月8日公告">9月8日公告</a>
            </div>
            <div class="info_item_date">2026-09-08</div>
          </div>
          <div class="table_item_info">
            <div class="info_item_title">
              <a href="./202609/t20260906_833100.html" title="早于目标周的公告">早于目标周的公告</a>
            </div>
            <div class="info_item_date">2026-09-06</div>
          </div>
        </body></html>
        """
        detail_html = """
        <html><body>
          <h1>SHFE 公告</h1>
          <div class="content">发布日期：2026-09-11</div>
          <div class="TRS_Editor">市场公告正文。</div>
        </body></html>
        """
        with patch.object(
            http_client.SESSION,
            "request",
            side_effect=[
                FakeResponse(200, text=list_html),
                FakeResponse(200, text=detail_html),
                FakeResponse(200, text=detail_html),
            ],
        ):
            raw, filtered, meta = collect_web(
                source,
                date(2026, 9, 7),
                date(2026, 9, 13),
                logging.getLogger("test"),
            )

        self.assertEqual(meta["error"], "")
        self.assertEqual(meta["candidates_scanned"], 3)
        self.assertEqual(meta["detail_pages_requested"], 2)
        self.assertEqual(meta["oldest_date_seen"], "2026-09-06")
        self.assertEqual(meta["stopped_reason"], "passed_target_start")
        self.assertEqual(len(filtered), 2)


if __name__ == "__main__":
    unittest.main()
