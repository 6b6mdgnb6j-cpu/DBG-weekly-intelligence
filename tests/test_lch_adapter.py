import logging
import html
import json
import unittest
from datetime import date
from unittest.mock import patch

from crawler.adapters.lch import LCH_SURFACES, collect_lch_clearing, parse_lch_surface


class FakeResponse:
    def __init__(self, text, url):
        self.text = text
        self.url = url


def table(rows, entity="", next_url=""):
    next_link = f'<a rel="next" href="{next_url}">Next</a>' if next_url else ""
    return f'<html><body><main><table data-entity="{entity}"><tbody>{rows}</tbody></table>{next_link}</main></body></html>'


def row(title, href, date_text, service="", topic=""):
    return (
        f'<tr><td><a href="{href}">{title}</a></td><td>{date_text}</td>'
        f'<td>{service}</td><td>{topic}</td></tr>'
    )


def detail(*paragraphs):
    body = "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
    return f"<html><body><main>{body}</main></body></html>"


def embedded_grid(records):
    payload = html.escape(json.dumps(records), quote=True)
    return f'<html><body><div data-rehydratable="DataGridEnterprise" data-row-data-static="{payload}"></div></body></html>'


class LCHAdapterTests(unittest.TestCase):
    def source(self):
        return {
            "id": "SRC-188",
            "name": "LCH",
            "url": "https://www.lseg.com/en/post-trade/clearing/",
            "crawl_url": LCH_SURFACES[0]["url"],
            "method": "lch_clearing",
            "category": "Competitor",
            "subcategory": "交易与清算",
            "brand": "Eurex",
            "competitor_type": "international",
            "priority": 1,
            "official": True,
            "max_items": 10,
            "max_pages": 3,
            "max_scan_candidates": 50,
        }

    def collect(self, responses, start=date(2026, 9, 7), end=date(2026, 9, 13)):
        def fake_get(url, **kwargs):
            if url in responses:
                return FakeResponse(responses[url], url)
            raise AssertionError(f"Unexpected URL requested: {url}")

        with patch("crawler.adapters.lch.request_get", side_effect=fake_get):
            return collect_lch_clearing(self.source(), start, end, logging.getLogger("test"))

    def empty_surfaces(self):
        return {surface["url"]: "<html><body><main></main></body></html>" for surface in LCH_SURFACES}

    def test_date_extraction_and_multi_surface_parsing(self):
        rule_url = "https://www.lseg.com/content/dam/post-trade/rule-change.pdf"
        ltd_url = "https://www.lseg.com/en/post-trade/clearing/membership/ltd-membership/ltd-member-updates/minimum-cash"
        sa_url = "https://www.lseg.com/en/post-trade/clearing/membership/sa-membership/sa-member-updates/collateral-framework"
        responses = {
            LCH_SURFACES[0]["url"]: table(
                row(
                    "LCH Ltd Self-Certification: Revised Margin Collateral Haircut Schedule",
                    rule_url,
                    "September 11, 2026",
                    "LCH Ltd",
                    "Rule change",
                ),
                entity="LCH Ltd",
            ),
            LCH_SURFACES[1]["url"]: table(
                row("Minimum Cash Framework Implementation", ltd_url, "10 September 2026", "SwapClear", "Collateral"),
                entity="LCH Ltd",
            ),
            LCH_SURFACES[2]["url"]: table(
                row("RepoClear Collateral Risk Framework Update", sa_url, "2026-09-09", "RepoClear", "Risk"),
                entity="LCH SA",
            ),
            ltd_url: detail(
                "LCH will implement a minimum cash collateral requirement across its clearing services.",
                "The framework will take effect on 20 October 2026 for eligible members.",
            ),
            sa_url: detail("LCH SA revised the RepoClear collateral risk management framework for clearing members."),
        }

        raw, filtered, meta = self.collect(responses)

        self.assertEqual(len(raw), 3)
        self.assertEqual(len(filtered), 3)
        self.assertEqual({item["date"] for item in filtered}, {"2026-09-09", "2026-09-10", "2026-09-11"})
        self.assertEqual(meta["pages_scanned"], 3)
        self.assertEqual(meta["candidates_discovered"], 3)
        self.assertEqual(meta["dated_candidates"], 3)
        self.assertEqual(meta["detail_pages_requested"], 2)
        self.assertEqual(meta["detail_fetch_success"], 2)
        self.assertEqual(meta["after_source_filter"], 3)
        self.assertTrue(meta["target_period_reached"])
        item = next(value for value in filtered if "Minimum Cash" in value["title_original"])
        self.assertIn("20 October 2026", item["relevance_context"])

    def test_pdf_rule_discovery_does_not_require_pdf_fetch(self):
        responses = self.empty_surfaces()
        pdf_url = "https://www.lseg.com/content/dam/post-trade/en_us/documents/lch/proposed-rule-changes/margin.pdf"
        responses[LCH_SURFACES[0]["url"]] = table(
            row("LCH Ltd Self-Certification: Margin Requirement Amendments", pdf_url, "September 8, 2026"),
            entity="LCH Ltd",
        )

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["url"], pdf_url)
        self.assertEqual(filtered[0]["summary"], "")
        self.assertEqual(meta["detail_pages_requested"], 0)

    def test_proposal_and_implementation_are_separate_lifecycle_events(self):
        rule_url = "https://www.lseg.com/content/dam/post-trade/minimum-cash-proposal.pdf"
        implementation_url = "https://www.lseg.com/en/post-trade/clearing/membership/ltd-membership/ltd-member-updates/minimum-cash-go-live"
        responses = self.empty_surfaces()
        responses[LCH_SURFACES[0]["url"]] = table(
            row("LCH Ltd Proposed Minimum Cash Collateral Framework", rule_url, "September 8, 2026"),
            entity="LCH Ltd",
        )
        responses[LCH_SURFACES[1]["url"]] = table(
            row("Minimum Cash Collateral Framework Go-Live", implementation_url, "September 10, 2026", "SwapClear"),
            entity="LCH Ltd",
        )
        responses[implementation_url] = detail(
            "The minimum cash collateral framework will go live for SwapClear clearing members."
        )

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 2)
        self.assertEqual(meta["cross_surface_duplicates_suppressed"], 0)
        self.assertEqual(meta["grouped_items_count"], 0)

    def test_same_lifecycle_duplicate_across_surfaces_is_suppressed(self):
        first_url = "https://www.lseg.com/content/dam/post-trade/repoclear-risk-update.pdf"
        second_url = "https://www.lseg.com/en/post-trade/clearing/membership/ltd-membership/ltd-member-updates/repoclear-risk-update"
        title = "LCH Ltd RepoClear Risk Framework Update"
        responses = self.empty_surfaces()
        responses[LCH_SURFACES[0]["url"]] = table(row(title, first_url, "September 8, 2026"), entity="LCH Ltd")
        responses[LCH_SURFACES[1]["url"]] = table(
            row(title, second_url, "September 8, 2026", "RepoClear", "Risk"), entity="LCH Ltd"
        )
        responses[second_url] = detail("LCH Ltd updated the RepoClear risk management framework for clearing members.")

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(meta["cross_surface_duplicates_suppressed"], 1)

    def test_irrelevant_and_routine_content_is_rejected(self):
        marketing_url = "https://www.lseg.com/en/post-trade/clearing/membership/ltd-membership/ltd-member-updates/annual-conference"
        routine_url = "https://www.lseg.com/en/post-trade/clearing/membership/sa-membership/sa-member-updates/address-change"
        responses = self.empty_surfaces()
        responses[LCH_SURFACES[1]["url"]] = table(
            row("Join LCH at the Annual Clearing Conference", marketing_url, "September 9, 2026", "General", "Event"),
            entity="LCH Ltd",
        )
        responses[LCH_SURFACES[2]["url"]] = table(
            row("Member Change of Head Office Address", routine_url, "September 10, 2026", "General", "Administration"),
            entity="LCH SA",
        )
        responses[marketing_url] = detail("Register now to join us at the annual conference and meet our team.")
        responses[routine_url] = detail("This notice records a clearing member change of head office address and contact details.")

        _, filtered, meta = self.collect(responses)

        self.assertEqual(filtered, [])
        self.assertEqual(meta["source_local_rejected"], 2)
        self.assertEqual(meta["filtering_reasons"]["lch_marketing_content"], 1)
        self.assertEqual(meta["filtering_reasons"]["lch_routine_or_administrative"], 1)

    def test_parser_rejects_external_and_missing_date_rows(self):
        html = table(
            row("Valid Margin Rule Change", "/content/dam/post-trade/valid.pdf", "September 7, 2026")
            + row("External", "https://example.com/external", "September 7, 2026")
            + row("Missing Date", "/content/dam/post-trade/missing-date.pdf", "")
        )

        rows = parse_lch_surface(html, LCH_SURFACES[0])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://www.lseg.com/content/dam/post-trade/valid.pdf")

    def test_embedded_json_parses_rule_and_member_update_records(self):
        proposed = embedded_grid(
            [
                {
                    "Title": "LCH Ltd Self-Certification: SwapClear Fee Note Updates",
                    "Filing Date": "September 11, 2026",
                    "New URL": "/content/dam/post-trade/en_us/documents/lch/proposed-rule-changes/update.pdf",
                },
                {"Title": "Missing URL", "Filing Date": "September 11, 2026"},
            ]
        )
        member = embedded_grid(
            [
                {
                    "Title": "RepoClear Collateral Framework Update",
                    "Date": "September 10, 2026",
                    "URL": "/content/lseg/en_us/post-trade/clearing/membership/ltd-membership/ltd-member-updates/update.html?edition=1",
                    "Services": "RepoClear",
                    "Topic": "Collateral",
                }
            ]
        )

        proposed_rows = parse_lch_surface(proposed, LCH_SURFACES[0])
        member_rows = parse_lch_surface(member, LCH_SURFACES[1])

        self.assertEqual(len(proposed_rows), 1)
        self.assertEqual(proposed_rows[0]["date"], "September 11, 2026")
        self.assertEqual(proposed_rows[0]["entity"], "LCH Ltd")
        self.assertEqual(len(member_rows), 1)
        self.assertEqual(member_rows[0]["date"], "September 10, 2026")
        self.assertEqual(member_rows[0]["context"], "RepoClear | Collateral")
        self.assertTrue(member_rows[0]["url"].endswith("update.html?edition=1"))

    def test_empty_embedded_surfaces_do_not_claim_target_coverage(self):
        responses = {
            surface["url"]: embedded_grid([])
            for surface in LCH_SURFACES
        }

        raw, filtered, meta = self.collect(responses)

        self.assertEqual(raw, [])
        self.assertEqual(filtered, [])
        self.assertFalse(meta["target_period_reached"])
        self.assertEqual(meta["stopped_reason"], "incomplete_target_coverage")
        self.assertTrue(
            all(stats["stopped_reason"] == "no_dated_candidates" for stats in meta["feed_stats"])
        )

    def test_valid_dated_embedded_records_allow_pagination_end_coverage(self):
        responses = self.empty_surfaces()
        for surface in LCH_SURFACES:
            url = (
                "/content/dam/post-trade/dated.pdf"
                if not surface["detail_required"]
                else "/content/lseg/en_us/post-trade/clearing/membership/dated.html"
            )
            responses[surface["url"]] = embedded_grid(
                [{"Title": "LCH Collateral Framework Update", "Date": "September 6, 2026", "URL": url}]
            )

        _, _, meta = self.collect(responses, start=date(2026, 9, 7), end=date(2026, 9, 13))

        self.assertTrue(meta["target_period_reached"])
        self.assertTrue(all(stats["dated_candidates"] == 1 for stats in meta["feed_stats"]))
        self.assertTrue(all(stats["stopped_reason"] == "passed_target_start" for stats in meta["feed_stats"]))

    def test_calm_multi_regulator_filings_are_grouped_as_one_package(self):
        responses = self.empty_surfaces()
        cftc_url = "https://www.lseg.com/content/dam/post-trade/lch-sa-calm-cftc.pdf"
        sec_url = "https://www.lseg.com/content/dam/post-trade/lch-sa-calm-sec-19b-4.pdf"
        responses[LCH_SURFACES[0]["url"]] = table(
            row(
                "LCH SA_CaLM_CFTC Self Certification_Minimun Cash Collateral requirement",
                cftc_url,
                "July 29, 2026",
            )
            + row(
                "LCH SA-2026-007_CaLM_Minimum Cash Collateral requirement",
                sec_url,
                "July 31, 2026",
            ),
            entity="LCH SA",
        )

        _, filtered, meta = self.collect(
            responses, start=date(2026, 7, 27), end=date(2026, 8, 2)
        )

        self.assertEqual(len(filtered), 1)
        self.assertIn("CFTC", filtered[0]["title_original"])
        self.assertEqual(meta["before_package_grouping"], 2)
        self.assertEqual(meta["after_package_grouping"], 1)
        self.assertEqual(meta["grouped_items_count"], 1)
        self.assertEqual(len(meta["package_groups"]), 1)
        package = meta["package_groups"][0]
        self.assertEqual(package["grouped_count"], 1)
        self.assertEqual(package["regulatory_channels"], ["CFTC", "SEC"])
        self.assertEqual(package["drop_reason"], "lch_clearing_package_grouped")
        self.assertIn(
            "LCH SA-2026-007_CaLM_Minimum Cash Collateral requirement",
            package["grouped_titles"],
        )

    def test_unrelated_same_day_collateral_updates_are_not_grouped(self):
        responses = self.empty_surfaces()
        responses[LCH_SURFACES[0]["url"]] = table(
            row(
                "LCH Ltd Self-Certification: Extension of Maturity for Floating Rate Notes as Investment Collateral",
                "/content/dam/post-trade/collateral-maturity.pdf",
                "September 2, 2026",
            )
            + row(
                "LCH Ltd Self-Certification: Revised Collateral Haircut Schedule",
                "/content/dam/post-trade/collateral-haircut.pdf",
                "September 2, 2026",
            ),
            entity="LCH Ltd",
        )

        _, filtered, meta = self.collect(
            responses, start=date(2026, 8, 31), end=date(2026, 9, 6)
        )

        self.assertEqual(len(filtered), 2)
        self.assertEqual(meta["grouped_items_count"], 0)
        self.assertEqual(meta["package_groups"], [])


if __name__ == "__main__":
    unittest.main()
