import logging
import unittest
from datetime import date
from unittest.mock import patch

from crawler.adapters.sgx import SGX_RULEBOOK_URL, collect_sgx_rulebook


class FakeResponse:
    def __init__(self, text, url):
        self.text = text
        self.url = url


def row(title, href, context):
    return f"""
    <div class="views-row">
      <a href="{href}">{title}</a>
      <div class="context">{context}</div>
    </div>
    """


def page(rows, next_url=""):
    next_link = f'<a rel="next" href="{next_url}">Next</a>' if next_url else ""
    return f"<html><body><main>{rows}</main><nav>{next_link}</nav></body></html>"


def detail(body):
    return f"<html><body><main><p>{body}</p></main></body></html>"


class SGXAdapterTests(unittest.TestCase):
    def source(self):
        return {
            "id": "SRC-075",
            "name": "新加坡交易所",
            "url": SGX_RULEBOOK_URL,
            "crawl_url": SGX_RULEBOOK_URL,
            "method": "sgx_rulebook",
            "category": "Competitor",
            "subcategory": "交易与清算",
            "brand": "Eurex",
            "competitor_type": "international",
            "priority": 1,
            "official": True,
            "max_items": 10,
            "max_scan_candidates": 100,
        }

    def collect(self, pages, details=None, start=date(2026, 9, 7), end=date(2026, 9, 13)):
        details = details or {}

        def fake_get(url, **kwargs):
            if url in pages:
                return FakeResponse(pages[url], url)
            if url in details:
                return FakeResponse(details[url], url)
            raise AssertionError(f"Unexpected URL requested: {url}")

        with patch("crawler.adapters.sgx.request_get", side_effect=fake_get):
            return collect_sgx_rulebook(self.source(), start, end, logging.getLogger("test"))

    def test_sgx_rulebook_extracts_normal_update(self):
        rule_url = "https://rulebook.sgx.com/rulebook/appendix-1-final-settlement-price"
        html = page(
            row(
                "Appendix 1 — Final Settlement Price (7 September 2026)",
                "/rulebook/appendix-1-final-settlement-price",
                "SGX-DC Clearing Rules >> Appendices",
            )
        )

        raw, filtered, meta = self.collect(
            {SGX_RULEBOOK_URL: html},
            {
                rule_url: detail(
                    "This rulebook update sets out final settlement price arrangements for SGX-DC "
                    "clearing and derivatives contracts."
                )
            },
        )

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title_original"], "Appendix 1 — Final Settlement Price")
        self.assertEqual(filtered[0]["date"], "2026-09-07")
        self.assertEqual(filtered[0]["url"], rule_url)
        self.assertIn("final settlement price", filtered[0]["summary"].lower())
        self.assertIn("SGX Rulebook", filtered[0]["relevance_context"])
        self.assertEqual(meta["pages_scanned"], 1)
        self.assertEqual(meta["detail_pages_requested"], 1)
        self.assertEqual(meta["dated_candidates"], 1)
        self.assertEqual(meta["after_source_filter"], 1)

    def test_sgx_rulebook_pagination_reaches_target_boundary(self):
        page_two_url = "https://rulebook.sgx.com/latest-updates?items_per_page=20&page=1"
        html_one = page(
            row(
                "Regulatory Notice 4.1.11 — Negotiated Large Trades (10 September 2026)",
                "/rulebook/regulatory-notice-4111",
                "Futures Trading Rules >> Regulatory Notices",
            ),
            next_url="/latest-updates?items_per_page=20&page=1",
        )
        html_two = page(
            row(
                "Older Trading Rules Update (4 September 2026)",
                "/rulebook/older-trading-rules-update",
                "Futures Trading Rules",
            )
        )

        raw, filtered, meta = self.collect(
            {SGX_RULEBOOK_URL: html_one, page_two_url: html_two},
            {
                "https://rulebook.sgx.com/rulebook/regulatory-notice-4111": detail(
                    "The update changes negotiated large trade requirements under the futures trading rules."
                )
            },
        )

        self.assertEqual(len(raw), 2)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(meta["pages_scanned"], 2)
        self.assertTrue(meta["target_period_reached"])
        self.assertEqual(meta["stopped_reason"], "passed_target_start")
        self.assertEqual(meta["oldest_date_seen"], "2026-09-04")

    def test_sgx_rulebook_normalizes_absolute_and_relative_detail_urls(self):
        absolute = "https://rulebook.sgx.com/rulebook/42-eligible-securities?revision=1"
        html = page(
            row(
                "4.2 Eligible Securities (8 September 2026)",
                absolute,
                "CDP Depository Rules >> Deposit and Withdrawal of Securities",
            )
            + row(
                "External Navigation (8 September 2026)",
                "https://example.com/rulebook/external",
                "Navigation",
            )
        )

        raw, filtered, meta = self.collect(
            {SGX_RULEBOOK_URL: html},
            {
                absolute: detail(
                    "This depository rule update changes eligible securities settlement and custody treatment."
                )
            },
        )

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["url"], absolute)
        self.assertEqual(meta["candidates_discovered"], 1)

    def test_sgx_rulebook_keeps_effective_context_separate_from_list_date(self):
        rule_url = "https://rulebook.sgx.com/rulebook/new-options-contract-rules"
        html = page(
            row(
                "New Options Contract Rules (9 September 2026)",
                "/rulebook/new-options-contract-rules",
                "Futures Trading Rules >> Contract Specifications >> Effective 1 October 2026",
            )
        )

        raw, filtered, meta = self.collect(
            {SGX_RULEBOOK_URL: html},
            {
                rule_url: detail(
                    "The rulebook update introduces options contract specification changes effective 1 October 2026."
                )
            },
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["date"], "2026-09-09")
        self.assertIn("Effective 1 October 2026", filtered[0]["relevance_context"])
        self.assertEqual(meta["newest_date_seen"], "2026-09-09")

    def test_sgx_rulebook_rejects_administrative_update(self):
        html = page(
            row(
                "Administrative Rulebook Formatting Update (8 September 2026)",
                "/rulebook/admin-formatting-update",
                "Administrative housekeeping and formatting",
            )
        )

        raw, filtered, meta = self.collect({SGX_RULEBOOK_URL: html})

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(filtered), 0)
        self.assertEqual(meta["before_source_filter"], 1)
        self.assertEqual(meta["after_source_filter"], 0)
        self.assertEqual(
            meta["source_filter_rejected_samples"][0]["reason"],
            "sgx_rulebook_routine_update",
        )

    def test_sgx_rulebook_groups_supporting_documents_in_package(self):
        first_url = "https://rulebook.sgx.com/rulebook/pn-723-additional-margins"
        second_url = "https://rulebook.sgx.com/rulebook/pn-722-third-party-margins"
        third_url = "https://rulebook.sgx.com/rulebook/pn-730-collateral-protection"
        html = page(
            row(
                "Practice Note 7.23 — Additional Margins (31 July 2026)",
                "/rulebook/pn-723-additional-margins",
                "SGX-DC Clearing Rules >> Practice Notes",
            )
            + row(
                "Practice Note 7.22 — Margins of Third Parties (31 July 2026)",
                "/rulebook/pn-722-third-party-margins",
                "SGX-DC Clearing Rules >> Practice Notes",
            )
            + row(
                "Practice Note 7.30 — Enhanced Customer Collateral Protection (31 July 2026)",
                "/rulebook/pn-730-collateral-protection",
                "SGX-DC Clearing Rules >> Practice Notes",
            )
        )

        raw, filtered, meta = self.collect(
            {SGX_RULEBOOK_URL: html},
            {
                first_url: detail("The practice note updates SGX-DC margin and risk management arrangements."),
                second_url: detail("The practice note updates clearing margin treatment for third parties."),
                third_url: detail("The practice note updates collateral protection for SGX-DC clearing members."),
            },
            start=date(2026, 7, 27),
            end=date(2026, 8, 2),
        )

        self.assertEqual(len(raw), 3)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title_original"], "Practice Note 7.23 — Additional Margins")
        self.assertEqual(meta["after_source_filter"], 3)
        self.assertEqual(meta["after_package_grouping"], 1)
        self.assertEqual(meta["grouped_items_count"], 2)
        self.assertEqual(len(meta["package_groups"]), 1)
        self.assertEqual(
            meta["package_groups"][0]["package_key"],
            "2026-07-31|sgx-dc clearing rules|practice notes",
        )
        self.assertEqual(
            meta["package_groups"][0]["representative_title"],
            "Practice Note 7.23 — Additional Margins",
        )
        self.assertIn("Practice Note 7.22 — Margins of Third Parties", meta["package_groups"][0]["grouped_titles"])
        self.assertIn(
            "sgx_rulebook_package_grouped",
            {sample["reason"] for sample in meta["source_filter_rejected_samples"]},
        )

    def test_sgx_rulebook_prefers_primary_notice_over_appendix(self):
        notice_url = "https://rulebook.sgx.com/rulebook/regulatory-notice-4111"
        appendix_url = "https://rulebook.sgx.com/rulebook/appendix-regulatory-notice-4111"
        html = page(
            row(
                "Regulatory Notice 4.1.11 — Negotiated Large Trades (10 September 2026)",
                "/rulebook/regulatory-notice-4111",
                "Futures Trading Rules >> Regulatory Notices",
            )
            + row(
                "Appendix A to Regulatory Notice 4.1.11 — Negotiated Large Trades (10 September 2026)",
                "/rulebook/appendix-regulatory-notice-4111",
                "Futures Trading Rules >> Regulatory Notices",
            )
        )

        raw, filtered, meta = self.collect(
            {SGX_RULEBOOK_URL: html},
            {
                notice_url: detail("The regulatory notice changes negotiated large trade requirements."),
                appendix_url: detail("The appendix supports negotiated large trade implementation details."),
            },
        )

        self.assertEqual(len(raw), 2)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title_original"], "Regulatory Notice 4.1.11 — Negotiated Large Trades")
        self.assertEqual(meta["grouped_items_count"], 1)
        self.assertEqual(
            meta["package_groups"][0]["grouped_titles"],
            ["Appendix A to Regulatory Notice 4.1.11 — Negotiated Large Trades"],
        )

    def test_sgx_rulebook_does_not_group_unrelated_rule_families(self):
        first_url = "https://rulebook.sgx.com/rulebook/pn-723-additional-margins"
        second_url = "https://rulebook.sgx.com/rulebook/regulatory-notice-force-key"
        html = page(
            row(
                "Practice Note 7.23 — Additional Margins (31 July 2026)",
                "/rulebook/pn-723-additional-margins",
                "SGX-DC Clearing Rules >> Practice Notes",
            )
            + row(
                "Regulatory Notice 11.4.2(g) — Application of the Force Key (31 July 2026)",
                "/rulebook/regulatory-notice-force-key",
                "SGX-ST Rules >> Regulatory Notices",
            )
        )

        raw, filtered, meta = self.collect(
            {SGX_RULEBOOK_URL: html},
            {
                first_url: detail("The practice note updates SGX-DC margin and risk management arrangements."),
                second_url: detail("The regulatory notice changes trading access and market structure procedures."),
            },
            start=date(2026, 7, 27),
            end=date(2026, 8, 2),
        )

        self.assertEqual(len(raw), 2)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(meta["grouped_items_count"], 0)
        self.assertEqual(meta["package_groups"], [])

    def test_sgx_rulebook_rejects_reference_only_regulatory_notice_appendix(self):
        appendix_url = "https://rulebook.sgx.com/rulebook/appendix-regulatory-notice-4111"
        html = page(
            row(
                "Appendix A To Regulatory Notice 4.1.11 (8 September 2026)",
                "/rulebook/appendix-regulatory-notice-4111",
                "Futures Trading Rules >> Regulatory Notices",
            )
        )

        raw, filtered, meta = self.collect({SGX_RULEBOOK_URL: html})

        self.assertEqual(len(raw), 1)
        self.assertEqual(filtered, [])
        self.assertEqual(meta["detail_pages_requested"], 0)
        self.assertEqual(
            meta["source_filter_rejected_samples"][0]["reason"],
            "sgx_rulebook_package_grouped",
        )


if __name__ == "__main__":
    unittest.main()
