import unittest

from bs4 import BeautifulSoup

from crawler.official_source_parser import (
    parse_iosco_media_release_entry,
    parse_iosco_public_report_entry,
)


class OfficialSourceParserRegressionTests(unittest.TestCase):
    def test_iosco_public_report_uses_publication_date_not_comment_deadline(self):
        html = """
        <li>
            CR/02/2026 Regulatory Considerations and Good Practices on the
            Evolution of Market Liquidity During the Trading Day ,
            Report of the Board of IOSCO
            Comments on the report should be submitted by 21 August 2026
            21 May 2026 -
            <a href="/library/pubdocs/pdf/IOSCOPD821.pdf">View Report</a>
        </li>
        """
        entry = BeautifulSoup(html, "html.parser").find("li")
        parsed = parse_iosco_public_report_entry(entry, "https://www.iosco.org/publications/")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["raw_date"], "21 May 2026")
        self.assertEqual(parsed["date"].isoformat(), "2026-05-21")
        self.assertNotIn("21 August 2026", parsed["title"])
        self.assertEqual(parsed["content_type"], "public_report")

    def test_iosco_media_release_entry(self):
        html = """
        <li>
            IOSCO publishes Report on Supervisory Technology (SupTech)
            18 Jun 2026 -
            <a href="/news/pdf/IOSCONEWS800.pdf">View Release</a>
        </li>
        """
        entry = BeautifulSoup(html, "html.parser").find("li")
        parsed = parse_iosco_media_release_entry(entry, "https://www.iosco.org/media_room/")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["raw_date"], "18 Jun 2026")
        self.assertEqual(parsed["date"].isoformat(), "2026-06-18")
        self.assertEqual(parsed["content_type"], "media_release")


if __name__ == "__main__":
    unittest.main()
