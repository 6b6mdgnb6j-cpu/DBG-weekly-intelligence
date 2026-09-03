import unittest

from crawler.content_filter import score_item
from crawler.highlight_ranker import build_highlight_text, highlight_score, select_highlights


def make_item(
    title,
    summary="",
    *,
    source="测试源",
    category="Macro",
    subcategory="美国",
    brand="",
    official=True,
    priority=1,
):
    item = {
        "date": "2026-08-24",
        "title_original": title,
        "title_cn": "",
        "title_en": "",
        "summary": summary,
        "summary_original": summary,
        "relevance_context": "",
        "source": source,
        "category": category,
        "subcategory": subcategory,
        "brand": brand,
        "priority": priority,
        "official": official,
        "url": f"https://example.test/{abs(hash(title))}",
    }
    score, reason = score_item(item)
    item["relevance_score"] = score
    item["relevance_reason"] = reason
    return item


class HighlightRankerRegressionTests(unittest.TestCase):
    def test_build_highlight_text_preserves_existing_field_set(self):
        item = {
            "title_original": "Original Highlight Title",
            "title_cn": "中文标题不参与",
            "title_en": "English Title Not Included",
            "summary": "Visible summary",
            "relevance_context": "Internal relevance context not included",
            "source": "Source Name",
            "subcategory": "Subcategory",
            "brand": "Brand Name",
        }
        text = build_highlight_text(item)
        self.assertEqual(text, "original highlight title visible summary")
        self.assertNotIn("internal relevance context", text)
        self.assertNotIn("source name", text)
        self.assertNotIn("brand name", text)

    def test_individual_enforcement_helper_semantics(self):
        cases = [
            (
                make_item("SEC fines company for violations", source="证券交易委员会"),
                True,
            ),
            (
                make_item(
                    "ICE Global Sugar Markets Hit Record Open Interest",
                    "The benchmark for refined sugar reached record open interest.",
                    source="洲际交易所",
                    category="Competitor",
                    brand="ICE",
                ),
                False,
            ),
            (make_item("Fine-tuning an AI model for surveillance", source="测试源"), False),
            (
                make_item(
                    "Nasdaq Verafin Partners with Q6 Cyber for Fraud Prevention",
                    "A fraud prevention technology partnership for financial institutions.",
                    source="纳斯达克公司",
                    category="Competitor",
                    brand="Nasdaq",
                ),
                False,
            ),
        ]
        for item, expect_downrank in cases:
            with self.subTest(title=item["title_original"]):
                score = highlight_score(item)
                baseline = int(item.get("relevance_score") or 0)
                if expect_downrank:
                    self.assertLess(score, baseline + 10)
                else:
                    self.assertNotIn("downrank:individual_enforcement", item["relevance_reason"])

    def test_low_signal_items_do_not_enter_top_five(self):
        high_value = [
            make_item(
                "Agencies Issue Final Rule to Prioritize Material Financial Risks",
                "Federal agencies issue a final rule for supervision of material financial risks.",
                source="联邦存款保险公司",
                category="Macro",
            ),
            make_item(
                "Eurex expands cross-product clearing infrastructure",
                "Eurex launches clearing expansion and harmonisation for derivatives.",
                source="Eurex",
                category="DBG",
                brand="Eurex",
            ),
            make_item(
                "ICE announces major acquisition of MarketAxess",
                "The acquisition creates a fixed income marketplace.",
                source="洲际交易所",
                category="Competitor",
                brand="ICE",
            ),
            make_item(
                "Clearstream supports ECB DLT settlement infrastructure",
                "Clearstream tests settlement infrastructure solution with the ECB using DLT.",
                source="明讯银行",
                category="DBG",
                brand="Clearstream",
            ),
            make_item(
                "HashKey announces interim results for 2026",
                "HashKey reports half-year financial results and derivatives business growth.",
                source="HashKey",
                category="Competitor",
                brand="HashKey",
            ),
        ]
        low_signal = [
            make_item("HKMA training program for students", "A training program and seminar."),
            make_item("Generic investor sentiment survey", "Survey from a research institute."),
            make_item("ICE mortgage performance report", "Routine mortgage performance data."),
        ]
        highlights = select_highlights(high_value + low_signal)
        titles = [item["title_original"] for item in highlights]
        self.assertEqual(len(highlights), 5)
        for item in low_signal:
            self.assertNotIn(item["title_original"], titles)

    def test_20260824_semantic_fixture_highlights(self):
        items = [
            make_item(
                "Agencies Issue Final Rule to Prioritize Material Financial Risks",
                "Federal agencies issue a final rule for supervision and material financial risks.",
                source="联邦存款保险公司",
                category="Macro",
            ),
            make_item(
                "Eurex Clearing expands cross-product clearing for derivatives",
                "Eurex launches clearing expansion and harmonisation for derivatives contracts.",
                source="Eurex",
                category="DBG",
                brand="Eurex",
            ),
            make_item(
                "HashKey Digital Asset Derivatives business expands",
                "HashKey announces financial results and derivatives business expansion.",
                source="HashKey",
                category="Competitor",
                brand="HashKey",
            ),
            make_item(
                "FTSE UK Index Series - Indicative Quarterly Review Changes September 2026",
                "The index series quarterly review changes were announced.",
                source="伦敦证券交易所集团",
                category="Competitor",
                brand="LSEG",
            ),
            make_item(
                "OCC updates supervisory standards for market risk",
                "The OCC issues supervisory standards for financial risk and market infrastructure.",
                source="货币监理署",
                category="Macro",
            ),
            make_item("HKMA training program for students", "A training program and seminar."),
            make_item("ICE mortgage performance report", "Routine mortgage performance data."),
        ]
        highlights = select_highlights(items)
        titles = [item["title_original"] for item in highlights]
        expected = {
            "Agencies Issue Final Rule to Prioritize Material Financial Risks",
            "Eurex Clearing expands cross-product clearing for derivatives",
            "HashKey Digital Asset Derivatives business expands",
            "FTSE UK Index Series - Indicative Quarterly Review Changes September 2026",
            "OCC updates supervisory standards for market risk",
        }
        self.assertEqual(set(titles), expected)
        self.assertNotIn("HKMA training program for students", titles)
        self.assertNotIn("ICE mortgage performance report", titles)


if __name__ == "__main__":
    unittest.main()
