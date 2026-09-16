import logging
import unittest
from datetime import date
from unittest.mock import patch

from crawler.adapters.cme import CME_GLOBEX_FEED, CME_PRESS_FEED, collect_cme_press_rss


class FakeResponse:
    def __init__(self, text, url=CME_PRESS_FEED["url"]):
        self.text = text
        self.url = url


def rss_feed(items):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>CME Group Press Releases</title>
        {items}
      </channel>
    </rss>
    """


def rss_item(title="", link="", pub_date="", description=""):
    parts = ["<item>"]
    if title is not None:
        parts.append(f"<title>{title}</title>")
    if link is not None:
        parts.append(f"<link>{link}</link>")
    if pub_date is not None:
        parts.append(f"<pubDate>{pub_date}</pubDate>")
    if description is not None:
        parts.append(f"<description>{description}</description>")
    parts.append("</item>")
    return "\n".join(parts)


class CMEAdapterTests(unittest.TestCase):
    def source(self):
        return {
            "id": "SRC-149",
            "name": "芝加哥商品交易所集团",
            "url": "https://www.cmegroup.com",
            "crawl_url": CME_PRESS_FEED["url"],
            "method": "cme_press_rss",
            "category": "Competitor",
            "subcategory": "交易与清算",
            "brand": "Eurex",
            "competitor_type": "international",
            "priority": 1,
            "official": True,
            "max_items": 10,
            "max_scan_candidates": 30,
        }

    def collect(
        self,
        press_feed_text,
        start=date(2026, 9, 7),
        end=date(2026, 9, 13),
        globex_feed_text=None,
        detail_pages=None,
    ):
        globex_feed_text = globex_feed_text if globex_feed_text is not None else rss_feed("")
        detail_pages = detail_pages or {}

        def fake_get(url, **kwargs):
            if url == CME_PRESS_FEED["url"]:
                return FakeResponse(press_feed_text, url)
            if url == CME_GLOBEX_FEED["url"]:
                return FakeResponse(globex_feed_text, url)
            return FakeResponse(detail_pages.get(url, "<html><body></body></html>"), url)

        with patch("crawler.adapters.cme.request_get", side_effect=fake_get):
            return collect_cme_press_rss(self.source(), start, end, logging.getLogger("test"))

    def test_cme_press_rss_extracts_normal_item(self):
        feed = rss_feed(
            rss_item(
                title="CME Group Announces New Interest Rate Futures Product",
                link="https://www.cmegroup.com/media-room/press-releases/2026/9/09/new-product.html",
                pub_date="Wed, 09 Sep 2026 13:00:00 GMT",
                description="CME Group announced a new futures product for interest rate markets.",
            )
        )

        raw, filtered, meta = self.collect(feed)

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title_original"], "CME Group Announces New Interest Rate Futures Product")
        self.assertEqual(filtered[0]["date"], "2026-09-09")
        self.assertEqual(
            filtered[0]["url"],
            "https://www.cmegroup.com/media-room/press-releases/2026/9/09/new-product.html",
        )
        self.assertIn("interest rate markets", filtered[0]["summary"])
        self.assertIn("All Press Releases", meta["feed_used"])
        self.assertIn("CME Globex Notices", meta["feed_used"])
        self.assertEqual(meta["candidates_discovered"], 1)
        self.assertEqual(meta["dated_candidates"], 1)
        self.assertTrue(meta["target_period_reached"])

    def test_cme_press_rss_ignores_malformed_items_safely(self):
        feed = rss_feed(
            rss_item(
                title="",
                link="https://www.cmegroup.com/media-room/press-releases/2026/9/09/missing-title.html",
                pub_date="Wed, 09 Sep 2026 13:00:00 GMT",
                description="Missing title.",
            )
            + rss_item(
                title="Missing URL",
                link="",
                pub_date="Wed, 09 Sep 2026 13:00:00 GMT",
                description="Missing URL.",
            )
            + rss_item(
                title="Missing date",
                link="https://www.cmegroup.com/media-room/press-releases/2026/9/09/missing-date.html",
                pub_date="",
                description="Missing date.",
            )
        )

        raw, filtered, meta = self.collect(feed)

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 0)
        self.assertEqual(raw[0]["title_original"], "Missing date")
        self.assertEqual(meta["candidates_discovered"], 3)
        self.assertEqual(meta["candidates_scanned"], 3)
        self.assertEqual(meta["date_parse_failed"], 3)

    def test_cme_press_rss_allows_missing_summary(self):
        feed = rss_feed(
            rss_item(
                title="CME Group Reports Monthly Market Statistics",
                link="https://www.cmegroup.com/media-room/press-releases/2026/9/10/statistics.html",
                pub_date="Thu, 10 Sep 2026 13:00:00 GMT",
                description=None,
            )
        )

        raw, filtered, meta = self.collect(feed)

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["summary"], "")
        self.assertEqual(meta["dated_candidates"], 1)

    def test_cme_press_rss_deduplicates_normalized_urls(self):
        duplicate_url = "https://www.cmegroup.com/media-room/press-releases/2026/9/11/results.html"
        feed = rss_feed(
            rss_item(
                title="CME Group Reports Quarterly Results",
                link=duplicate_url,
                pub_date="Fri, 11 Sep 2026 13:00:00 GMT",
                description="Quarterly results.",
            )
            + rss_item(
                title="CME Group Reports Quarterly Results Duplicate",
                link=duplicate_url,
                pub_date="Fri, 11 Sep 2026 14:00:00 GMT",
                description="Duplicate quarterly results.",
            )
        )

        raw, filtered, meta = self.collect(feed)

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(meta["candidates_discovered"], 2)
        self.assertEqual(meta["candidates_scanned"], 2)
        self.assertEqual(meta["dated_candidates"], 1)

    def test_cme_press_rss_parses_dates_and_stops_after_target_boundary(self):
        feed = rss_feed(
            rss_item(
                title="Current week CME launch",
                link="https://www.cmegroup.com/current.html",
                pub_date="Tue, 08 Sep 2026 13:00:00 GMT",
                description="Current week item.",
            )
            + rss_item(
                title="Older CME launch",
                link="https://www.cmegroup.com/older.html",
                pub_date="Fri, 04 Sep 2026 13:00:00 GMT",
                description="Older item.",
            )
            + rss_item(
                title="Even older CME launch",
                link="https://www.cmegroup.com/even-older.html",
                pub_date="Thu, 03 Sep 2026 13:00:00 GMT",
                description="Should not be scanned after boundary.",
            )
        )

        raw, filtered, meta = self.collect(feed)

        self.assertEqual(len(raw), 2)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(meta["candidates_discovered"], 3)
        self.assertEqual(meta["candidates_scanned"], 2)
        self.assertEqual(meta["newest_date_seen"], "2026-09-08")
        self.assertEqual(meta["oldest_date_seen"], "2026-09-04")
        press_stats = [feed for feed in meta["feed_stats"] if feed["feed_key"] == "press_releases"][0]
        self.assertEqual(press_stats["stopped_reason"], "passed_target_start")

    def test_cme_globex_wrapper_detail_with_meaningful_change_is_retained(self):
        detail_url = "https://www.cmegroup.com/notices/electronic-trading/2026/09/20260907.html?utm_medium=rss"
        globex_feed = rss_feed(
            rss_item(
                title="CME Globex Notice: September 7, 2026",
                link=detail_url,
                pub_date="Thu, 10 Sep 2026 13:00:00 GMT",
                description=None,
            )
        )
        detail_html = """
        <html><body>
          <main>
            <h2>New CME Globex Connectivity Enhancements for Interest Rate Futures</h2>
            <p>CME Globex will support new connectivity enhancements and market data updates
            for interest rate futures, improving order entry workflows for customers.</p>
          </main>
        </body></html>
        """

        raw, filtered, meta = self.collect(
            rss_feed(""),
            globex_feed_text=globex_feed,
            detail_pages={detail_url: detail_html},
        )

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(
            filtered[0]["title_original"],
            "New CME Globex Connectivity Enhancements for Interest Rate Futures",
        )
        self.assertIn("market data updates", filtered[0]["summary"])
        self.assertEqual(meta["detail_pages_requested"], 1)
        self.assertEqual(meta["after_source_filter"], 1)
        globex_stats = [feed for feed in meta["feed_stats"] if feed["feed_key"] == "globex_notices"][0]
        self.assertEqual(globex_stats["within_period"], 1)
        self.assertEqual(globex_stats["after_source_filter"], 1)

    def test_cme_globex_empty_wrapper_is_rejected(self):
        detail_url = "https://www.cmegroup.com/notices/electronic-trading/2026/09/20260907.html"
        globex_feed = rss_feed(
            rss_item(
                title="CME Globex Notice: September 7, 2026",
                link=detail_url,
                pub_date="Thu, 10 Sep 2026 13:00:00 GMT",
                description=None,
            )
        )

        raw, filtered, meta = self.collect(
            rss_feed(""),
            globex_feed_text=globex_feed,
            detail_pages={detail_url: "<html><body><h1>CME Globex Notice: September 7, 2026</h1></body></html>"},
        )

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 0)
        self.assertEqual(meta["detail_pages_requested"], 1)
        globex_stats = [feed for feed in meta["feed_stats"] if feed["feed_key"] == "globex_notices"][0]
        self.assertEqual(globex_stats["after_source_filter"], 0)
        self.assertEqual(
            globex_stats["dropped_samples"][0]["reason"],
            "source_filter:generic_or_routine_globex_notice",
        )

    def test_cme_globex_malformed_detail_is_ignored(self):
        detail_url = "https://www.cmegroup.com/notices/electronic-trading/2026/09/20260908.html"
        globex_feed = rss_feed(
            rss_item(
                title="CME Globex Notice: September 8, 2026",
                link=detail_url,
                pub_date="Fri, 11 Sep 2026 13:00:00 GMT",
                description=None,
            )
        )

        raw, filtered, meta = self.collect(
            rss_feed(""),
            globex_feed_text=globex_feed,
            detail_pages={detail_url: "<html><body><nav>Navigation</nav><footer>Copyright</footer></body></html>"},
        )

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 0)
        self.assertEqual(meta["after_source_filter"], 0)

    def test_cme_globex_routine_maintenance_notice_is_rejected(self):
        detail_url = "https://www.cmegroup.com/notices/electronic-trading/2026/09/20260909.html"
        globex_feed = rss_feed(
            rss_item(
                title="CME Globex Notice: September 9, 2026",
                link=detail_url,
                pub_date="Fri, 11 Sep 2026 13:00:00 GMT",
                description=None,
            )
        )
        detail_html = """
        <html><body>
          <h2>Scheduled Maintenance Window</h2>
          <p>CME Globex will conduct a scheduled maintenance window in the test environment.
          This is a routine reminder for certification testing.</p>
        </body></html>
        """

        raw, filtered, meta = self.collect(
            rss_feed(""),
            globex_feed_text=globex_feed,
            detail_pages={detail_url: detail_html},
        )

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 0)
        self.assertEqual(meta["after_source_filter"], 0)


if __name__ == "__main__":
    unittest.main()
