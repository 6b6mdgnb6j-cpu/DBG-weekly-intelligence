import unittest

from bs4 import BeautifulSoup

from crawler.official_source_parser import (
    parse_iosco_media_release_entry,
    parse_iosco_public_report_entry,
    parse_sp_dji_archive_entry,
    sp_dji_source_filter,
)
from crawler.adapters.shfe import parse_shfe_notice_list


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

    def test_sp_dji_uses_archive_publication_date_not_effective_date(self):
        html = """
        <li class="wd_item">
            <div class="wd_item_wrapper">
                <div class="wd_date">Aug 26, 2026</div>
                <div class="wd_title">
                    <a href="https://press.spglobal.com/2026-08-26-Tenable-Holdings-Set-to-Join-S-P-SmallCap-600">
                        Tenable Holdings Set to Join S&P SmallCap 600
                    </a>
                </div>
                <div class="wd_body">
                    This change is effective prior to the opening of trading
                    on Monday, August 31, 2026.
                </div>
            </div>
        </li>
        """
        entry = BeautifulSoup(html, "html.parser").find("li")
        parsed = parse_sp_dji_archive_entry(entry, "https://press.spglobal.com/index.php")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["raw_date"], "Aug 26, 2026")
        self.assertEqual(parsed["date"].isoformat(), "2026-08-26")

    def test_sp_dji_routine_filter_drops_only_narrow_families(self):
        drop_titles = [
            "Company X Set to Join S&P SmallCap 600",
            "Company Y Set to Join S&P 500",
            "S&P Cotality Case-Shiller Index Reports Annual Gain in June 2026",
            "S&P Dow Jones Indices Reports U.S. Common Indicated Dividend Payments Increase of $13.1 Billion in Q4 2025 and $46.4 Billion for 2025",
        ]
        keep_titles = [
            "S&P Dow Jones Indices and Pantera Capital Launch New Index for Digital Assets",
            "S&P Dow Jones Indices Introduces the S&P U.S. CLO Investment Grade Indices",
            "S&P DOW JONES INDICES AND MSCI ANNOUNCE CONSULTATION ON POTENTIAL CHANGES TO THE GLOBAL INDUSTRY CLASSIFICATION STANDARD (GICS®)",
            "S&P Dow Jones Indices Consultation on Treatment of MegaCap Companies - Results",
            "S&P Dow Jones Indices and Kaiko Introduce S&P Kaiko Digital Asset Indices",
            "S&P Dow Jones Indices Launches Dividend Growth Index Methodology for Global Income Strategies",
        ]

        for title in drop_titles:
            kept, reason = sp_dji_source_filter(title)
            self.assertFalse(kept, title)
            self.assertNotEqual(reason, "kept")

        for title in keep_titles:
            kept, reason = sp_dji_source_filter(title)
            self.assertTrue(kept, title)
            self.assertEqual(reason, "kept")

    def test_shfe_notice_list_extracts_canonical_article_candidate(self):
        html = """
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
            <a href="/products/futures/index_f/">指数</a>
          </div>
          <div class="info_item_date">2026-09-11</div>
        </div>
        <a href="/publicnotice/notice/">公告通知</a>
        """
        soup = BeautifulSoup(html, "html.parser")
        items = parse_shfe_notice_list(
            soup,
            "https://www.shfe.com.cn/publicnotice/notice/",
            {"id": "SRC-076", "name": "上海期货交易所"},
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "关于做好市场风险控制工作的通知")
        self.assertEqual(items[0]["date"], "2026-09-11")
        self.assertEqual(
            items[0]["url"],
            "https://www.shfe.com.cn/publicnotice/notice/202609/t20260911_833384.html",
        )


if __name__ == "__main__":
    unittest.main()
