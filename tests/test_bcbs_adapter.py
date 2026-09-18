import logging
import unittest
from datetime import date
from unittest.mock import patch

from crawler.adapters.bcbs import BCBS_SURFACES, bcbs_filter_reason, parse_bcbs_surface
from crawler.adapters.prudential_publications import collect_prudential_publications


class FakeResponse:
    def __init__(self, text, url):
        self.text = text
        self.url = url


def publication(title, href, published, document_type, topic, summary, **attrs):
    attributes = " ".join(f'data-{key.replace("_", "-")}="{value}"' for key, value in attrs.items())
    return f"""
    <article class="publication-item" data-document-type="{document_type}" {attributes}>
      <span class="type">{document_type}</span>
      <time datetime="{published}">{published}</time>
      <a href="{href}">{title}</a>
      <span class="topic">{topic}</span>
      <p class="summary">{summary}</p>
    </article>
    """


def page(*items, next_href=""):
    next_link = f'<a class="next" rel="next" href="{next_href}">Next</a>' if next_href else ""
    return f"<html><body><main>{''.join(items)}{next_link}</main></body></html>"


def live_card(title, href, published, document_type="", topic="", summary=""):
    badges = '<span class="badge">Publication</span>'
    if document_type:
        badges += f'<span class="badge">{document_type}</span>'
    topic_html = f'<div class="card-topic">{topic}</div>' if topic else ""
    summary_html = f'<div class="card-description">{summary}</div>' if summary else ""
    return f"""
    <div class="card-wrapper">
      <a class="card-link" href="{href}">
        <div class="card">
          <div class="card-body">
            <div class="card-header">{badges}<span class="card-date">{published}</span></div>
            <h5 class="card-heading">{title}</h5>
            {summary_html}{topic_html}
          </div>
        </div>
      </a>
    </div>
    """


class BCBSAdapterTests(unittest.TestCase):
    def source(self):
        return {
            "id": "SRC-010",
            "name": "Basel Committee on Banking Supervision",
            "url": "https://www.bis.org/committees/bcbs/",
            "method": "prudential_publications",
            "category": "Macro",
            "subcategory": "国际组织",
            "priority": 1,
            "official": True,
            "max_items": 10,
            "max_pages": 3,
        }

    def empty_surfaces(self):
        return {surface["url"]: page() for surface in BCBS_SURFACES}

    def collect(self, responses, start=date(2026, 9, 7), end=date(2026, 9, 13)):
        def fake_get(url, **kwargs):
            if url not in responses:
                raise AssertionError(f"Unexpected URL requested: {url}")
            return FakeResponse(responses[url], url)

        with patch("crawler.adapters.prudential_publications.request_get", side_effect=fake_get):
            return collect_prudential_publications(
                self.source(), start, end, logging.getLogger("test.bcbs")
            )

    def test_publication_parsing_extracts_contract_fields(self):
        html = page(
            publication(
                "Finalisation of capital requirements technical amendment",
                "/publications/finalisation-capital-requirements",
                "2026-09-10",
                "Standards",
                "Capital",
                "The Basel Committee finalised an amendment to capital requirements.",
            )
        )

        records, next_url = parse_bcbs_surface(html, BCBS_SURFACES[0], BCBS_SURFACES[0]["url"])

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["publication_date_text"], "2026-09-10")
        self.assertEqual(records[0]["document_type"], "Standards")
        self.assertEqual(records[0]["topic"], "Capital")
        self.assertIn("finalised", records[0]["summary"])
        self.assertEqual(
            records[0]["url"],
            "https://www.bis.org/publications/finalisation-capital-requirements",
        )
        self.assertEqual(next_url, "")

    def test_live_card_wrapper_extracts_official_fields(self):
        html = f"<html><body>{live_card(
            'Finalisation of Basel capital requirements',
            '/publications/202609-standards-capital-requirements',
            '10 Sep 2026',
            'Standards',
            'Capital',
            'The Committee finalises amendments to the Basel Framework.',
        )}</body></html>"

        records, _ = parse_bcbs_surface(html, BCBS_SURFACES[0], BCBS_SURFACES[0]["url"])

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "Finalisation of Basel capital requirements")
        self.assertEqual(records[0]["publication_date_text"], "10 Sep 2026")
        self.assertEqual(records[0]["document_type"], "Standards")
        self.assertEqual(records[0]["topic"], "Capital")
        self.assertIn("Basel Framework", records[0]["summary"])

    def test_live_card_allows_missing_optional_summary_and_topic(self):
        html = f"<html><body>{live_card(
            'Basel Committee issues supervisory guidance',
            '/publications/202609-guidance-supervision',
            '11 Sep 2026',
            'Guidelines',
        )}</body></html>"

        records, _ = parse_bcbs_surface(html, BCBS_SURFACES[0], BCBS_SURFACES[0]["url"])

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["summary"], "")
        self.assertEqual(records[0]["topic"], "")

    def test_live_card_rejects_non_publication_link(self):
        html = f"<html><body>{live_card(
            'Careers at the Bank for International Settlements',
            '/about/careers',
            '10 Sep 2026',
            'Careers',
        )}</body></html>"

        records, _ = parse_bcbs_surface(html, BCBS_SURFACES[0], BCBS_SURFACES[0]["url"])

        self.assertEqual(records, [])

    def test_standalone_event_is_rejected(self):
        candidate = {
            "title": "Basel Committee event on banking supervision",
            "summary": "Registration details for the event.",
            "document_type": "Media release",
            "topic": "Banking supervision",
        }

        self.assertEqual(bcbs_filter_reason(candidate), "bcbs_event_or_speech")

    def test_standalone_events_is_rejected(self):
        candidate = {
            "title": "Basel Committee events for banking supervisors",
            "summary": "Upcoming events and registration details.",
            "document_type": "Media release",
            "topic": "Banking supervision",
        }

        self.assertEqual(bcbs_filter_reason(candidate), "bcbs_event_or_speech")

    def test_developments_does_not_match_event_exclusion(self):
        candidate = {
            "title": "Basel Committee reviews recent market developments",
            "summary": "The Committee publishes a report on operational risk requirements.",
            "document_type": "Implementation reports",
            "topic": "Operational risk",
        }

        self.assertEqual(bcbs_filter_reason(candidate), "")

    def test_hyphenated_event_word_does_not_match_standalone_event(self):
        candidate = {
            "title": "Event-driven developments in operational resilience",
            "summary": "The Committee publishes guidance on operational risk requirements.",
            "document_type": "Guidelines",
            "topic": "Operational risk",
        }

        self.assertEqual(bcbs_filter_reason(candidate), "")

    def test_material_publication_with_developments_is_retained(self):
        candidate = {
            "title": "Recent developments in liquidity risk supervision",
            "summary": "The Committee issues supervisory guidance on liquidity requirements.",
            "document_type": "Guidelines",
            "topic": "Liquidity",
        }

        self.assertEqual(bcbs_filter_reason(candidate), "")

    def test_existing_speech_exclusion_is_unchanged(self):
        candidate = {
            "title": "Keynote speech on the Basel Framework",
            "summary": "A keynote speech at the annual conference.",
            "document_type": "Media release",
            "topic": "Capital",
        }

        self.assertEqual(bcbs_filter_reason(candidate), "bcbs_event_or_speech")

    def test_conference_announcement_remains_rejected(self):
        candidate = {
            "title": "Conference on the Basel Framework",
            "summary": "Registration and agenda details for the annual conference.",
            "document_type": "Media release",
            "topic": "Capital",
        }

        self.assertEqual(bcbs_filter_reason(candidate), "bcbs_event_or_speech")

    def test_incidental_conference_does_not_suppress_prudential_content(self):
        candidate = {
            "title": (
                "Basel Committee discusses recent market developments and targeted review "
                "of cryptoasset standard"
            ),
            "summary": (
                "Discusses vulnerabilities in government bond-backed repo markets. "
                "Discusses progress of a targeted review of the prudential standard for "
                "banks' cryptoasset exposures. Announces date and location of the "
                "International Conference of Banking Supervisors."
            ),
            "document_type": "Media release",
            "topic": "",
        }

        self.assertEqual(bcbs_filter_reason(candidate), "")

    def test_valid_html_publication_date_enters_weekly_filtering(self):
        responses = self.empty_surfaces()
        responses[BCBS_SURFACES[0]["url"]] = page(
            publication(
                "Basel Committee finalises liquidity requirements",
                "/publications/liquidity-requirements",
                "10 September 2026",
                "Standards",
                "Liquidity",
                "The Committee finalises a Basel Framework liquidity standard.",
            ),
            publication(
                "Older capital implementation report",
                "/publications/older-capital-report",
                "30 August 2026",
                "Implementation reports",
                "Capital",
                "A report on Basel capital implementation.",
            ),
        )

        raw, filtered, meta = self.collect(responses)

        self.assertEqual(len(raw), 2)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["date"], "2026-09-10")
        self.assertIn("liquidity", filtered[0]["relevance_context"].lower())
        self.assertEqual(meta["date_source_counts"]["html_publication_date"], 2)
        self.assertTrue(meta["feed_stats"][0]["target_period_reached"])

    def test_official_abbreviated_month_date_is_accepted(self):
        responses = self.empty_surfaces()
        responses[BCBS_SURFACES[0]["url"]] = page(
            publication(
                "Basel Committee publishes operational risk report",
                "/publications/operational-risk-report",
                "10 Sep 2026",
                "Implementation reports",
                "Operational risk",
                "The Committee publishes a report on operational resilience.",
            )
        )

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["date"], "2026-09-10")
        self.assertEqual(meta["date_parse_failed"], 0)

    def test_official_document_date_is_bounded_fallback(self):
        responses = self.empty_surfaces()
        responses[BCBS_SURFACES[0]["url"]] = page(
            publication(
                "Basel Committee issues operational risk guidance",
                "/publications/operational-risk-guidance",
                "",
                "Guidelines",
                "Operational risk",
                "The Committee issues supervisory guidance.",
                document_date="2026-09-11",
            )
        )

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["date"], "2026-09-11")
        self.assertEqual(meta["date_source_counts"]["official_document_date"], 1)

    def test_effective_date_is_not_used_as_publication_date(self):
        responses = self.empty_surfaces()
        responses[BCBS_SURFACES[0]["url"]] = page(
            publication(
                "Basel Framework capital chapter update",
                "/publications/capital-chapter-update",
                "",
                "Standards",
                "Capital",
                "The chapter is effective on 10 September 2026.",
            )
        )

        raw, filtered, meta = self.collect(responses)

        self.assertEqual(raw, [])
        self.assertEqual(filtered, [])
        self.assertEqual(meta["date_parse_failed"], 1)

    def test_media_release_parsing_and_material_filtering(self):
        responses = self.empty_surfaces()
        responses[BCBS_SURFACES[1]["url"]] = page(
            publication(
                "Basel Committee consults on operational resilience standard",
                "/media-releases/20260909-operational-resilience",
                "09 September 2026",
                "Media release",
                "Operational risk",
                "The Committee consults on supervisory requirements for banks.",
            ),
            publication(
                "Secretary General speaks at annual banking conference",
                "/media-releases/20260908-annual-conference",
                "08 September 2026",
                "Media release",
                "",
                "A keynote speech at an industry event.",
            ),
        )

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 1)
        self.assertIn("operational resilience", filtered[0]["title_original"].lower())
        self.assertEqual(meta["source_local_rejected"], 1)
        self.assertEqual(meta["filtering_reasons"]["bcbs_event_or_speech"], 1)

    def test_generic_personnel_announcement_is_rejected(self):
        responses = self.empty_surfaces()
        responses[BCBS_SURFACES[1]["url"]] = page(
            publication(
                "New Secretary General appointed to the Basel Committee",
                "/media-releases/20260910-secretary-general-appointed",
                "10 September 2026",
                "Media release",
                "",
                "The Committee announced an appointment.",
            )
        )

        _, filtered, meta = self.collect(responses)

        self.assertEqual(filtered, [])
        self.assertEqual(meta["filtering_reasons"]["bcbs_career_or_personnel"], 1)

    def test_pagination_is_bounded_and_reaches_target_boundary(self):
        responses = self.empty_surfaces()
        second = "https://www.bis.org/committees/bcbs/publications?page=1"
        responses[BCBS_SURFACES[0]["url"]] = page(
            publication(
                "Basel Committee consults on market risk requirements",
                "/publications/market-risk-consultation",
                "12 September 2026",
                "Consultative",
                "Market risk",
                "The Committee consults on market risk requirements.",
            ),
            next_href="?page=1",
        )
        responses[second] = page(
            publication(
                "Earlier Basel capital implementation report",
                "/publications/earlier-capital-report",
                "01 September 2026",
                "Implementation reports",
                "Capital",
                "The report assesses Basel capital implementation.",
            )
        )

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(meta["feed_stats"][0]["pages_scanned"], 2)
        self.assertTrue(meta["feed_stats"][0]["target_period_reached"])

    def test_duplicate_publication_representation_is_suppressed(self):
        responses = self.empty_surfaces()
        item = publication(
            "Basel Committee publishes capital standard",
            "/publications/capital-standard",
            "10 September 2026",
            "Standards",
            "Capital",
            "The Committee publishes a Basel capital standard.",
        )
        responses[BCBS_SURFACES[0]["url"]] = page(item, item)

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(meta["candidates_discovered"], 1)

    def test_cross_surface_duplicate_is_counted(self):
        responses = self.empty_surfaces()
        title = "Basel Committee publishes capital and liquidity standard"
        responses[BCBS_SURFACES[0]["url"]] = page(
            publication(
                title,
                "/publications/capital-liquidity-standard",
                "10 September 2026",
                "Standards",
                "Capital",
                "The Committee publishes capital and liquidity requirements.",
            )
        )
        responses[BCBS_SURFACES[1]["url"]] = page(
            publication(
                title,
                "/media-releases/20260910-capital-liquidity-standard",
                "10 September 2026",
                "Media release",
                "Capital",
                "The Committee publishes capital and liquidity requirements.",
            )
        )

        _, filtered, meta = self.collect(responses)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(meta["duplicates_suppressed"], 1)

    def test_non_bcbs_navigation_links_are_ignored(self):
        html = page(
            '<article><time datetime="2026-09-10">2026-09-10</time>'
            '<a href="/about/careers">Careers at the BIS</a></article>'
        )

        records, _ = parse_bcbs_surface(html, BCBS_SURFACES[0], BCBS_SURFACES[0]["url"])

        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
