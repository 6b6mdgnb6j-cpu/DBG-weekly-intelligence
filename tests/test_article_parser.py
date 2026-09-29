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


if __name__ == "__main__":
    unittest.main()
