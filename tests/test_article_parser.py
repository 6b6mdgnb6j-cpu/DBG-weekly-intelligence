import unittest
from datetime import date
from unittest.mock import Mock, patch

from crawler import web_parser


class ArticleParserTests(unittest.TestCase):
    def test_bafin_generic_page_title_yields_to_article_h1(self):
        response = Mock()
        response.headers = {"Content-Type": "text/html"}
        response.text = """
            <html>
              <head>
                <meta property="og:title" content="Use of cookies">
                <meta name="date" content="2026-09-23">
              </head>
              <body>
                <h1>Operation Heracles delivers another blow to international cyber investment fraud</h1>
                <p>BaFin and its partners took action against international cyber investment fraud.</p>
              </body>
            </html>
        """
        source = {"id": "SRC-025", "name": "德国联邦金融监管局", "url": "https://www.bafin.de"}

        with patch("crawler.article_parser.request_get", return_value=response):
            raw, kept, diagnostic = web_parser.parse_article(
                "https://www.bafin.de/EN/PublikationenDaten/Heracles.html",
                source,
                date(2026, 9, 21),
                date(2026, 9, 27),
                Mock(),
                list_title="Use of cookies",
                list_date="2026-09-23",
            )

        expected = "Operation Heracles delivers another blow to international cyber investment fraud"
        self.assertEqual(raw["title_original"], expected)
        self.assertEqual(kept["title_original"], expected)
        self.assertEqual(diagnostic["title"], expected)
        self.assertNotEqual(kept["title_original"], "Use of cookies")

    def test_bafin_skips_generic_first_h1_for_later_article_heading(self):
        response = Mock()
        response.headers = {"Content-Type": "text/html"}
        response.text = """
            <html>
              <head>
                <meta property="og:title" content="Use of cookies">
                <meta name="date" content="2026-09-23">
              </head>
              <body>
                <div class="cookie-layer"><h1>Use of cookies</h1></div>
                <aside><h2>Information</h2></aside>
                <main>
                  <h1>Operation Heracles delivers another blow to international cyber investment fraud</h1>
                  <p>BaFin and its partners took action against international cyber investment fraud.</p>
                </main>
              </body>
            </html>
        """
        source = {"id": "SRC-025", "name": "德国联邦金融监管局", "url": "https://www.bafin.de"}

        with patch("crawler.article_parser.request_get", return_value=response):
            _, kept, _ = web_parser.parse_article(
                "https://www.bafin.de/EN/PublikationenDaten/Heracles.html",
                source,
                date(2026, 9, 21),
                date(2026, 9, 27),
                Mock(),
                list_title="Use of cookies",
                list_date="2026-09-23",
            )

        self.assertEqual(
            kept["title_original"],
            "Operation Heracles delivers another blow to international cyber investment fraud",
        )
        self.assertNotEqual(kept["title_original"], "Use of cookies")
        self.assertNotEqual(kept["title_original"], "Information")

    def test_non_bafin_title_precedence_is_unchanged(self):
        response = Mock()
        response.headers = {"Content-Type": "text/html"}
        response.text = """
            <html><head><meta property="og:title" content="Use of cookies"></head>
            <body><h1>Specific heading</h1></body></html>
        """
        source = {"id": "SRC-999", "name": "Other", "url": "https://example.test"}

        with patch("crawler.article_parser.request_get", return_value=response):
            raw, _, _ = web_parser.parse_article(
                "https://example.test/news/item",
                source,
                date(2026, 9, 21),
                date(2026, 9, 27),
                Mock(),
                list_date="2026-09-23",
            )

        self.assertEqual(raw["title_original"], "Use of cookies")

    def test_korea_fsc_uses_article_subject_without_body_or_date(self):
        response = Mock()
        response.headers = {"Content-Type": "text/html"}
        response.text = """
            <html>
              <head><meta name="description" content="Financial Services Commission"></head>
              <body>
                <h1 class="logo-cont"><a><img alt="Financial Services Commission"></a></h1>
                <div class="board-view-wrap">
                  <div class="header">
                    <div class="subject">
                      Korea Premium Weeks 2026 to be Held from Sept 28 to Oct 16
                      <span>Sep 15, 2026</span>
                      <div class="file-set">Attachments</div>
                    </div>
                  </div>
                  <div class="body">
                    <p>Korea Premium Weeks 2026 will be held over three weeks, from September 28 to October 16, 2026.</p>
                    <p>Week 1 will feature capital market policy sessions and investor meetings.</p>
                  </div>
                </div>
              </body>
            </html>
        """
        source = {"id": "SRC-050", "name": "韩国金融监督委员会", "url": "https://www.fsc.go.kr"}
        contaminated_list_title = (
            "Korea Premium Weeks 2026 to be Held from Sept 28 to Oct 16 "
            "Korea Premium Weeks 2026 will be held over three weeks. Week 1 will feature sessions."
        )

        with patch("crawler.article_parser.request_get", return_value=response):
            raw, kept, diagnostic = web_parser.parse_article(
                "https://www.fsc.go.kr/eng/pr010101/87713",
                source,
                date(2026, 9, 14),
                date(2026, 9, 20),
                Mock(),
                list_title=contaminated_list_title,
                list_date="Sep 15, 2026",
            )

        expected = "Korea Premium Weeks 2026 to be Held from Sept 28 to Oct 16"
        self.assertEqual(raw["title_original"], expected)
        self.assertEqual(kept["title_original"], expected)
        self.assertEqual(diagnostic["title"], expected)
        self.assertNotIn("Week 1", kept["title_original"])
        self.assertEqual(
            kept["summary_original"],
            "Korea Premium Weeks 2026 will be held over three weeks, from September 28 to October 16, 2026.",
        )

    def test_korea_fsc_subject_selector_is_not_title_specific(self):
        response = Mock()
        response.headers = {"Content-Type": "text/html"}
        response.text = """
            <html><body>
              <h1 class="logo-cont"><img alt="FSC"></h1>
              <div class="board-view-wrap">
                <div class="header"><div class="subject">
                  FSC Announces New Capital Market Reform Measures
                  <span>Oct 2, 2026</span>
                </div></div>
                <div class="body"><p>The measures introduce material reforms for Korea's capital markets.</p></div>
              </div>
            </body></html>
        """
        source = {"id": "SRC-050", "name": "韩国金融监督委员会", "url": "https://www.fsc.go.kr"}

        with patch("crawler.article_parser.request_get", return_value=response):
            _, kept, _ = web_parser.parse_article(
                "https://www.fsc.go.kr/eng/pr010101/99999",
                source,
                date(2026, 9, 28),
                date(2026, 10, 4),
                Mock(),
                list_title="Contaminated list title and teaser text",
                list_date="Oct 2, 2026",
            )

        self.assertEqual(kept["title_original"], "FSC Announces New Capital Market Reform Measures")


if __name__ == "__main__":
    unittest.main()
