import logging
import unittest
from datetime import date
from unittest.mock import patch

from crawler.adapters.ccp12 import (
    CCP_GLOBAL_SURFACES,
    collect_ccp_global_publications,
    parse_ccp_global_surface,
)


class FakeResponse:
    def __init__(self, text, url):
        self.text = text
        self.url = url
        self.content = text.encode("latin1", errors="ignore")


def article(title, href, date_text, summary="", datetime_value=""):
    time = (
        f'<time datetime="{datetime_value}">{date_text}</time>'
        if datetime_value
        else f"<div class=\"date\">{date_text}</div>"
    )
    paragraph = f"<p>{summary}</p>" if summary else ""
    return (
        f'<div class="latestPublishBox"><h3>{title}</h3>{time}{paragraph}'
        f'<a href="{href}">Download</a></div>'
    )


def page(*records):
    return "<html><body><main>" + "".join(records) + "</main></body></html>"


class CCP12AdapterTests(unittest.TestCase):
    def source(self):
        return {
            "id": "SRC-107",
            "name": "全球中央对手方协会",
            "url": "https://ccp-global.org/",
            "crawl_url": CCP_GLOBAL_SURFACES[0]["url"],
            "method": "ccp_global_publications",
            "category": "Macro",
            "subcategory": "国际组织",
            "priority": 2,
            "official": True,
            "max_items": 10,
        }

    def empty_surfaces(self):
        return {surface["url"]: page() for surface in CCP_GLOBAL_SURFACES}

    def collect(self, responses, start=date(2026, 9, 7), end=date(2026, 9, 13)):
        def fake_get(url, **kwargs):
            if url not in responses:
                raise AssertionError(f"Unexpected URL requested: {url}")
            return FakeResponse(responses[url], url)

        with patch("crawler.adapters.ccp12.request_get", side_effect=fake_get):
            return collect_ccp_global_publications(
                self.source(), start, end, logging.getLogger("test.ccp12")
            )

    def test_extracts_complete_html_publication_date_and_context(self):
        responses = self.empty_surfaces()
        pdf_url = "https://ccp-global.org/sites/default/files/2026-09/ccp-resolution.pdf"
        responses[CCP_GLOBAL_SURFACES[0]["url"]] = page(
            article(
                "CCP Global Responds to the Bank of England Discussion Paper on CCP Resolution",
                pdf_url,
                "September 9, 2026",
                "The response addresses CCP recovery, resolution and clearing risk management.",
                "2026-09-09",
            ),
            article(
                "Older CCP Collateral Report",
                "/sites/default/files/2026-08/older-report.pdf",
                "August 30, 2026",
                "A report on CCP collateral risk management.",
                "2026-08-30",
            ),
        )

        raw, filtered, meta = self.collect(responses)

        self.assertEqual(len(raw), 2)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["date"], "2026-09-09")
        self.assertEqual(filtered[0]["url"], pdf_url)
        self.assertIn("responses", filtered[0]["relevance_context"])
        self.assertIn("regulatory_response", filtered[0]["relevance_context"])
        self.assertEqual(meta["dated_candidates"], 2)
        response_stats = meta["feed_stats"][0]
        self.assertTrue(response_stats["target_period_reached"])

    def test_month_only_date_is_not_used_for_weekly_filtering(self):
        responses = self.empty_surfaces()
        responses[CCP_GLOBAL_SURFACES[0]["url"]] = page(
            article(
                "CCP Global Response on Initial Margin Transparency",
                "/responses/initial-margin.html",
                "September 2026",
                "The consultation response concerns CCP initial margin disclosures.",
            )
        )

        raw, filtered, meta = self.collect(responses)

        self.assertEqual(raw, [])
        self.assertEqual(filtered, [])
        self.assertEqual(meta["date_parse_failed"], 1)
        self.assertEqual(meta["feed_stats"][0]["stopped_reason"], "no_dated_candidates")
        self.assertFalse(meta["target_period_reached"])

    def test_body_date_is_not_mistaken_for_publication_date(self):
        responses = self.empty_surfaces()
        responses[CCP_GLOBAL_SURFACES[0]["url"]] = page(
            article(
                "CCP Global Response on Clearing Resolution",
                "/responses/resolution.html",
                "September 2026",
                "The regulator consultation closes on September 12, 2026.",
            )
        )

        raw, filtered, meta = self.collect(responses)

        self.assertEqual(raw, [])
        self.assertEqual(filtered, [])
        self.assertEqual(meta["date_parse_failed"], 1)

    def test_confirmed_pdf_metadata_recovers_month_only_date(self):
        responses = self.empty_surfaces()
        pdf_url = "https://ccp-global.org/sites/default/files/2026-09/collateral-report.pdf?download=1"
        responses[CCP_GLOBAL_SURFACES[1]["url"]] = page(
            article(
                "CCP Global Report on Collateral Risk Management",
                pdf_url,
                "September 2026",
                "The report covers CCP collateral and default fund risk management.",
            )
        )
        responses[pdf_url] = "%PDF-1.7 /CreationDate (D:20260910121500+00'00')"

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["date"], "2026-09-10")
        self.assertEqual(meta["pdf_documents_requested"], 1)
        self.assertEqual(meta["date_parse_failed"], 0)

    def test_valid_filename_date_matching_page_month_is_accepted(self):
        responses = self.empty_surfaces()
        responses[CCP_GLOBAL_SURFACES[0]["url"]] = page(
            article(
                "CCP Global Response on CCP Margin and Collateral",
                "/sites/default/files/2026-09/response-2026-09-10-final.pdf",
                "September 2026",
                "The regulatory response covers CCP margin, collateral and clearing policy.",
            )
        )

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["date"], "2026-09-10")
        self.assertEqual(meta["filename_date_recovered"], 1)
        self.assertEqual(meta["pdf_documents_requested"], 0)

    def test_site_native_complete_filename_date_is_accepted(self):
        responses = self.empty_surfaces()
        responses[CCP_GLOBAL_SURFACES[0]["url"]] = page(
            article(
                "CCP Global Response on CCP Resolution",
                "/sites/default/files/2026-09/response-10.09.2026-final.pdf",
                "September 2026",
                "The response covers CCP recovery, resolution and risk management.",
            )
        )

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["date"], "2026-09-10")
        self.assertEqual(meta["filename_date_recovered"], 1)

    def test_filename_date_conflicting_with_page_month_is_rejected(self):
        responses = self.empty_surfaces()
        responses[CCP_GLOBAL_SURFACES[0]["url"]] = page(
            article(
                "CCP Global Response on CCP Resolution",
                "/sites/default/files/2026-09/response-2026-08-31-final.pdf",
                "September 2026",
                "The response covers CCP recovery and resolution.",
            )
        )

        raw, filtered, meta = self.collect(responses)

        self.assertEqual(raw, [])
        self.assertEqual(filtered, [])
        self.assertEqual(meta["filename_date_rejected"], 1)
        self.assertEqual(meta["filename_date_rejection_reasons"]["filename_date_month_conflict"], 1)
        self.assertEqual(meta["pdf_documents_requested"], 0)

    def test_month_only_filename_is_rejected_without_pdf_fetch(self):
        responses = self.empty_surfaces()
        responses[CCP_GLOBAL_SURFACES[1]["url"]] = page(
            article(
                "CCP Global Report on CCP Collateral Risk Management",
                "/sites/default/files/2026-09/collateral-report-2026-09.pdf",
                "September 2026",
                "The report covers CCP collateral and risk management.",
            )
        )

        raw, filtered, meta = self.collect(responses)

        self.assertEqual(raw, [])
        self.assertEqual(filtered, [])
        self.assertEqual(meta["filename_date_rejection_reasons"]["filename_month_only"], 1)
        self.assertEqual(meta["pdf_documents_requested"], 0)

    def test_no_reliable_date_remains_excluded(self):
        responses = self.empty_surfaces()
        responses[CCP_GLOBAL_SURFACES[1]["url"]] = page(
            article(
                "CCP Global Paper on CCP Risk Management",
                "/papers/risk-management.html",
                "September 2026",
                "The paper covers CCP clearing risk management.",
            )
        )

        raw, filtered, meta = self.collect(responses)

        self.assertEqual(raw, [])
        self.assertEqual(filtered, [])
        self.assertEqual(meta["date_parse_failed"], 1)
        self.assertEqual(meta["filename_date_recovered"], 0)

    def test_pdf_metadata_must_match_visible_page_month(self):
        responses = self.empty_surfaces()
        pdf_url = "https://ccp-global.org/sites/default/files/report.pdf"
        responses[CCP_GLOBAL_SURFACES[1]["url"]] = page(
            article(
                "CCP Global Report on Clearing Risk Management",
                pdf_url,
                "September 2026",
                "The report concerns CCP clearing risk management.",
            )
        )
        responses[pdf_url] = "%PDF-1.7 /CreationDate (D:20260831121500+00'00')"

        raw, filtered, meta = self.collect(responses)

        self.assertEqual(raw, [])
        self.assertEqual(filtered, [])
        self.assertEqual(meta["date_parse_failed"], 1)

    def test_cross_surface_same_document_is_deduplicated(self):
        responses = self.empty_surfaces()
        pdf_url = "https://ccp-global.org/sites/default/files/2026-09/im-response.pdf"
        duplicate = article(
            "CCP Global Response on Initial Margin and Collateral Transparency",
            pdf_url,
            "September 10, 2026",
            "The regulatory response covers CCP initial margin, collateral and clearing policy.",
            "2026-09-10",
        )
        responses[CCP_GLOBAL_SURFACES[0]["url"]] = page(duplicate)
        responses[CCP_GLOBAL_SURFACES[3]["url"]] = page(duplicate)

        raw, filtered, meta = self.collect(responses)

        self.assertEqual(len(raw), 2)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(meta["cross_surface_duplicates_suppressed"], 1)
        self.assertIn("responses", filtered[0]["relevance_context"])

    def test_source_local_filter_rejects_event_membership_newsletter_and_hr(self):
        responses = self.empty_surfaces()
        responses[CCP_GLOBAL_SURFACES[3]["url"]] = page(
            article("CCP Global Annual General Meeting 2026", "/agm.pdf", "September 7, 2026", datetime_value="2026-09-07"),
            article("CCP Global Clearing Academy Training Course", "/academy.pdf", "September 8, 2026", datetime_value="2026-09-08"),
            article("CCP Global Welcomes Example Clear as an Observer Member", "/member.pdf", "September 9, 2026", datetime_value="2026-09-09"),
            article("CCP Global Publishes its Autumn Newsletter", "/newsletter.pdf", "September 10, 2026", datetime_value="2026-09-10"),
            article("CCP Global Announces Officer Appointment", "/appointment.pdf", "September 11, 2026", datetime_value="2026-09-11"),
        )

        _, filtered, meta = self.collect(responses)

        self.assertEqual(filtered, [])
        self.assertEqual(meta["source_local_rejected"], 5)
        self.assertEqual(meta["filtering_reasons"]["ccp_global_event_or_training"], 2)
        self.assertEqual(meta["filtering_reasons"]["ccp_global_membership_update"], 1)
        self.assertEqual(meta["filtering_reasons"]["ccp_global_newsletter_wrapper"], 1)
        self.assertEqual(meta["filtering_reasons"]["ccp_global_hr_or_corporate"], 1)

    def test_material_pqd_and_default_simulation_items_are_retained(self):
        responses = self.empty_surfaces()
        pqd_url = "https://ccp-global.org/sites/default/files/2026-09/pqd-q2.pdf"
        responses[CCP_GLOBAL_SURFACES[2]["url"]] = """
        <div class="dropdown-menu">
          <a href="/sites/default/files/2026-09/pqd-q2.pdf">PQD QTR 2026 Q2</a>
        </div>
        """
        responses[pqd_url] = "CCP Global PQD Quarterly Trends Report. Published September 8, 2026."
        responses[CCP_GLOBAL_SURFACES[1]["url"]] = page(
            article(
                "CCP Global Publishes Multi-CCP Default Simulation Report",
                "/sites/default/files/2026-09/default-simulation.pdf",
                "September 9, 2026",
                "The report presents material default management and CCP resilience findings.",
                "2026-09-09",
            )
        )

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 2)
        self.assertEqual(meta["source_local_rejected"], 0)
        self.assertEqual({item["date"] for item in filtered}, {"2026-09-08", "2026-09-09"})

    def test_parser_normalizes_relative_urls_and_rejects_external_links(self):
        surface = CCP_GLOBAL_SURFACES[0]
        html = page(
            article(
                "CCP Global Response on Clearing Resolution",
                "/sites/default/files/response.pdf?edition=1",
                "September 9, 2026",
                datetime_value="2026-09-09",
            ),
            article(
                "External Clearing Report",
                "https://example.com/report.pdf",
                "September 9, 2026",
                datetime_value="2026-09-09",
            ),
        )

        records = parse_ccp_global_surface(html, surface)

        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0]["url"],
            "https://ccp-global.org/sites/default/files/response.pdf?edition=1",
        )

    def test_live_latest_publish_box_structure_is_extracted(self):
        surface = CCP_GLOBAL_SURFACES[0]
        html = """
        <div class="latestPublishBox">
          <a href="/sites/default/files/2026-09/CCPG-response-04.09.2026.pdf"></a>
          <img src="pdf.png" alt="">
          <h4>September 2026</h4>
          <p><p>CCP Global responds to Bank of England's discussion paper on CCP resolution</p></p>
          <div class="mdBtnBlack download">Download</div>
        </div>
        """

        records = parse_ccp_global_surface(html, surface)

        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0]["title"],
            "CCP Global responds to Bank of England's discussion paper on CCP resolution",
        )
        self.assertEqual(records[0]["raw_date"], "September 2026")
        self.assertTrue(records[0]["url"].endswith("CCPG-response-04.09.2026.pdf"))

    def test_archive_pdfbox_and_latest_duplicate_are_discovered_once(self):
        surface = CCP_GLOBAL_SURFACES[1]
        href = "/sites/default/files/2025-11/CCPG-position-paper-21.11.2025.pdf"
        html = f"""
        <div class="latestPublishBox">
          <a href="{href}"></a><h4>November 2025</h4>
          <p><p>CCPG Position Paper on Central Bank Deposit Account Access for CCPs</p></p>
        </div>
        <div class="pdfbox">
          <p><a href="{href}">November 2025 | CCPG Position Paper on Central Bank Deposit Account Access for CCPs</a></p>
          <p>This paper addresses CCP liquidity and risk management.</p>
        </div>
        """

        records = parse_ccp_global_surface(html, surface)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["raw_date"], "November 2025")

    def test_navigation_list_items_are_not_publication_candidates(self):
        surface = CCP_GLOBAL_SURFACES[0]
        html = """
        <ul class="navigation">
          <li><a href="/what-we-do">What We Do</a></li>
          <li><a href="/working-committee">Working Committees</a></li>
          <li><a href="/contacts">Contacts</a></li>
        </ul>
        """

        self.assertEqual(parse_ccp_global_surface(html, surface), [])

    def test_pqd_uses_separate_dropdown_document_parser(self):
        surface = CCP_GLOBAL_SURFACES[2]
        html = """
        <div class="dropdown-menu">
          <a class="dropdown-item" href="/sites/default/files/2026-09/CCPG_PQD_QTR_Q2-2026.pdf">PQD QTR 2026 Q2</a>
          <a class="dropdown-item" href="/sites/default/files/2026-06/CCPG_PQD_QTR_Q1-2026.pdf">PQD QTR 2026 Q1</a>
          <a class="dropdown-item" href="/about">About CCP Global</a>
        </div>
        <ul><li><a href="/contacts">Contacts</a></li></ul>
        """

        records = parse_ccp_global_surface(html, surface)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "PQD QTR 2026 Q2")
        self.assertEqual(records[0]["raw_date"], "September 2026")
        self.assertEqual(records[1]["raw_date"], "June 2026")


if __name__ == "__main__":
    unittest.main()
