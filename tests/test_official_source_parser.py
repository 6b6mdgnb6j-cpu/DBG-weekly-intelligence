import unittest

from bs4 import BeautifulSoup

from crawler.official_source_parser import (
    parse_iosco_media_release_entry,
    parse_iosco_public_report_entry,
    parse_sp_dji_archive_entry,
    sp_dji_source_filter,
)
from crawler.adapters.csrc import parse_csrc_search_json
from crawler.adapters.nfra import parse_nfra_docinfo_json
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

    def test_nfra_docinfo_json_extracts_title_date_url_and_category(self):
        payload = """
        {
          "rptCode": 200,
          "msg": "成功",
          "data": [
            {
              "itemName": "政策规章规范性文件",
              "itemId": 861,
              "docInfoVOList": [
                {
                  "docId": 1270034,
                  "docTitle": "国家金融监督管理总局关于印发《商品住房开发贷款管理办法（试行）》的通知",
                  "publishDate": "2026-08-28 19:15:10",
                  "builddate": "2026-08-28",
                  "docSummary": "规范商品住房开发贷款管理。",
                  "itemName": null,
                  "itemId": null
                }
              ]
            }
          ]
        }
        """
        soup = BeautifulSoup(payload, "html.parser")
        items = parse_nfra_docinfo_json(
            soup,
            "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemUUIdsAndChild",
            {"id": "SRC-001", "name": "国家金融监督管理总局"},
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "国家金融监督管理总局关于印发《商品住房开发贷款管理办法（试行）》的通知")
        self.assertEqual(items[0]["date"], "2026-08-28 19:15:10")
        self.assertEqual(
            items[0]["url"],
            "https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId=1270034&itemId=861",
        )
        self.assertEqual(items[0]["summary"], "规范商品住房开发贷款管理。")
        self.assertEqual(items[0]["content_type"], "nfra_docinfo")
        self.assertEqual(items[0]["category"], "政策规章规范性文件")

    def test_nfra_docinfo_json_ignores_malformed_records(self):
        payload = """
        {
          "rptCode": 200,
          "data": [
            {"docId": 1, "docTitle": "", "publishDate": "2026-08-28", "itemId": 861},
            {"docId": 2, "docTitle": "Missing date", "itemId": 861},
            {"docTitle": "Missing URL parts", "publishDate": "2026-08-28"},
            {
              "docId": 3,
              "docTitle": "Valid NFRA item",
              "builddate": "2026-08-28",
              "itemId": 861
            }
          ]
        }
        """
        soup = BeautifulSoup(payload, "html.parser")
        items = parse_nfra_docinfo_json(
            soup,
            "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemUUIdsAndChild",
            {"id": "SRC-001", "name": "国家金融监督管理总局"},
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Valid NFRA item")
        self.assertEqual(items[0]["date"], "2026-08-28")

    def test_nfra_docinfo_json_handles_empty_or_invalid_payload(self):
        invalid = BeautifulSoup("<html>not json</html>", "html.parser")
        empty = BeautifulSoup('{"rptCode": 200, "data": []}', "html.parser")

        self.assertEqual(parse_nfra_docinfo_json(invalid, "https://www.nfra.gov.cn", {}), [])
        self.assertEqual(parse_nfra_docinfo_json(empty, "https://www.nfra.gov.cn", {}), [])

    def test_csrc_search_json_extracts_title_date_url_and_category(self):
        payload = """
        {
          "data": {
            "results": [
              {
                "title": "证监会发布资本市场监管规则",
                "publishedTime": "2026-09-11",
                "url": "/csrc/c100028/c7424382/content.shtml?from=search",
                "channelName": "证监会要闻",
                "summary": "完善资本市场基础制度。"
              }
            ]
          }
        }
        """
        soup = BeautifulSoup(payload, "html.parser")
        items = parse_csrc_search_json(
            soup,
            "https://www.csrc.gov.cn/searchList/a1a078ee0bc54721ab6b148884c784a8",
            {"id": "SRC-003", "name": "中国证券监督管理委员会"},
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "证监会发布资本市场监管规则")
        self.assertEqual(items[0]["date"], "2026-09-11")
        self.assertEqual(
            items[0]["url"],
            "https://www.csrc.gov.cn/csrc/c100028/c7424382/content.shtml?from=search",
        )
        self.assertEqual(items[0]["summary"], "完善资本市场基础制度。")
        self.assertEqual(items[0]["content_type"], "csrc_search")
        self.assertEqual(items[0]["category"], "证监会要闻")

    def test_csrc_search_json_ignores_malformed_and_duplicate_records(self):
        payload = """
        {
          "result": {
            "list": [
              {"title": "", "publishedTime": "2026-09-11", "url": "/csrc/a.shtml"},
              {"title": "Missing date", "url": "/csrc/b.shtml"},
              {"title": "Missing URL", "publishedTime": "2026-09-11"},
              {"title": "Valid CSRC item", "pubDate": "2026-09-11", "link": "/csrc/c.shtml"},
              {"title": "Duplicate CSRC item", "pubDate": "2026-09-11", "link": "/csrc/c.shtml"}
            ]
          }
        }
        """
        soup = BeautifulSoup(payload, "html.parser")
        items = parse_csrc_search_json(
            soup,
            "https://www.csrc.gov.cn/searchList/a1a078ee0bc54721ab6b148884c784a8",
            {"id": "SRC-003", "name": "中国证券监督管理委员会"},
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Valid CSRC item")
        self.assertEqual(items[0]["date"], "2026-09-11")
        self.assertEqual(items[0]["url"], "https://www.csrc.gov.cn/csrc/c.shtml")

    def test_csrc_search_json_handles_empty_jsonp_or_invalid_payload(self):
        jsonp = BeautifulSoup('callback({"data":[{"title":"JSONP item","date":"2026-09-11","url":"/csrc/j.shtml"}]});', "html.parser")
        invalid = BeautifulSoup("<html>not json</html>", "html.parser")
        empty = BeautifulSoup('{"data": []}', "html.parser")

        self.assertEqual(len(parse_csrc_search_json(jsonp, "https://www.csrc.gov.cn/searchList/channel", {})), 1)
        self.assertEqual(parse_csrc_search_json(invalid, "https://www.csrc.gov.cn", {}), [])
        self.assertEqual(parse_csrc_search_json(empty, "https://www.csrc.gov.cn", {}), [])

    def test_csrc_search_html_extracts_title_date_url_and_category(self):
        html = """
        <ul class="listTxt" id="body">
          <li>
            <div class="title">
              <a href="//www.csrc.gov.cn/csrc/c100028/c7658236/content.shtml?from=search" target="_blank">
                [证监会要闻 ]  中国证监会发布《期货公司监督管理办法》及配套实施公告
              </a>
            </div>
            <div style="float: right" class="date">2026-09-11 </div>
          </li>
          <li>
            <a href="/csrc/c100028/">证监会要闻</a>
            <div class="date">2026-09-11</div>
          </li>
          <li>
            <div class="title"><a href="/csrc/c100028/c7658000/content.shtml">Missing date</a></div>
          </li>
        </ul>
        """
        soup = BeautifulSoup(html, "html.parser")
        items = parse_csrc_search_json(
            soup,
            "https://www.csrc.gov.cn/searchList/a1a078ee0bc54721ab6b148884c784a8",
            {"id": "SRC-003", "name": "中国证券监督管理委员会"},
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "中国证监会发布《期货公司监督管理办法》及配套实施公告")
        self.assertEqual(items[0]["date"], "2026-09-11")
        self.assertEqual(
            items[0]["url"],
            "https://www.csrc.gov.cn/csrc/c100028/c7658236/content.shtml?from=search",
        )
        self.assertEqual(items[0]["category"], "证监会要闻")
        self.assertEqual(items[0]["content_type"], "csrc_search_html")

    def test_csrc_search_html_handles_empty_page(self):
        soup = BeautifulSoup("<html><body><ul class='listTxt'></ul></body></html>", "html.parser")

        self.assertEqual(
            parse_csrc_search_json(
                soup,
                "https://www.csrc.gov.cn/searchList/a1a078ee0bc54721ab6b148884c784a8",
                {"id": "SRC-003", "name": "中国证券监督管理委员会"},
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
