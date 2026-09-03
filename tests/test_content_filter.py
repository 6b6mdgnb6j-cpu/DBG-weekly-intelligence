import unittest

from crawler.content_filter import (
    INDIVIDUAL_ENFORCEMENT_TERMS,
    build_relevance_text,
    contains_individual_enforcement_term,
    score_item,
)


MIN_SCORE = 3


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
    return {
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
        "url": "https://example.test/news",
    }


def relevance(item):
    score, reason = score_item(item)
    return score, reason


def current_individual_enforcement_match(text):
    text = text.lower()
    return any(
        contains_individual_enforcement_term(text, term)
        for term in INDIVIDUAL_ENFORCEMENT_TERMS
    )


class ContentFilterRegressionTests(unittest.TestCase):
    def test_build_relevance_text_preserves_existing_field_set(self):
        item = {
            "title_original": "Original Title",
            "title_cn": "中文标题",
            "title_en": "English Title",
            "summary": "Visible summary",
            "summary_original": "Summary original should not be included separately",
            "relevance_context": "Internal relevance context",
            "source": "Source Name",
            "subcategory": "Subcategory",
            "brand": "Brand Name",
        }
        text = build_relevance_text(item)
        expected = (
            "original title 中文标题 english title visible summary "
            "internal relevance context source name subcategory brand name"
        )
        self.assertEqual(text, expected)
        self.assertNotIn("summary original should not be included separately", text)
        self.assertNotIn("none", text)

    def test_fine_lexical_safety(self):
        should_match = [
            "SEC fines company for violations",
            "civil fine",
            "regulator imposed fines",
        ]
        for text in should_match:
            with self.subTest(text=text):
                self.assertTrue(current_individual_enforcement_match(text))

        should_not_match = [
            "refined sugar",
            "fine-tuning",
            "financial",
            "refinery",
            "final settlement",
        ]
        for text in should_not_match:
            with self.subTest(text=text):
                self.assertFalse(
                    any(
                        contains_individual_enforcement_term(text.lower(), term)
                        for term in ("fine", "fines")
                    )
                )

    def test_fraud_lexical_and_context_safety(self):
        should_match = [
            "fraudulent website alert",
            "fraudulent document warning",
            "fraudsters impersonating financial institutions",
            "securities fraud enforcement action",
        ]
        for text in should_match:
            with self.subTest(text=text):
                score, reason = relevance(make_item(text))
                self.assertIn("downrank:individual_enforcement", reason)

        should_not_downrank = [
            "fraud prevention technology platform",
            "fraud detection software partnership",
            "Nasdaq Verafin fraud prevention partnership",
            "anti-fraud technology product launch",
        ]
        for text in should_not_downrank:
            with self.subTest(text=text):
                score, reason = relevance(make_item(text))
                self.assertNotIn("downrank:individual_enforcement", reason)

    def test_known_retained_positive_controls(self):
        cases = [
            (
                make_item(
                    "Market surveillance of AI: BaFin granted new powers",
                    "BaFin receives new supervisory powers for market surveillance of artificial intelligence.",
                    source="德国联邦金融监管局",
                ),
                "source_signal:bafin_ai_market_surveillance",
            ),
            (
                make_item(
                    "Clearstream Pontes supports ECB DLT settlement trials",
                    "Clearstream launches settlement infrastructure solution with the ECB using DLT.",
                    source="明讯银行",
                    category="DBG",
                    subcategory="证券与基金服务",
                    brand="Clearstream",
                ),
                "source_signal:clearstream_dlt_settlement",
            ),
            (
                make_item(
                    "LCH clears first POLSTR Overnight Index Swaps",
                    "LCH has cleared the first OIS in a new currency benchmark.",
                    source="伦敦证券交易所集团",
                    category="Competitor",
                    subcategory="Trading / Clearing",
                    brand="LSEG",
                ),
                "source_signal:lch_ois_clearing",
            ),
            (
                make_item(
                    "Agencies Issue Final Rule to Prioritize Material Financial Risks",
                    "Federal banking agencies issue a final rule on supervision and material financial risks.",
                    source="联邦存款保险公司",
                ),
                "hard_signal:regulatory_final_rule",
            ),
            (
                make_item(
                    "FDIC Issues Interim Final Rule Regarding Reciprocal Deposits",
                    "The FDIC issued an interim final rule regarding reciprocal deposits.",
                    source="联邦存款保险公司",
                ),
                "hard_signal:regulatory_final_rule",
            ),
            (
                make_item(
                    "LSEG announces H1 2026 interim results",
                    "LSEG reports financial results for the first half of 2026.",
                    source="伦敦证券交易所集团",
                    category="Competitor",
                    subcategory="Other",
                    brand="LSEG",
                ),
                "hard_signal:interim_results",
            ),
            (
                make_item(
                    "HashKey Group announces 2026 interim results",
                    "HashKey reports half-year financial results.",
                    source="HashKey",
                    category="Competitor",
                    subcategory="Other",
                    brand="HashKey",
                ),
                "hard_signal:interim_results",
            ),
            (
                make_item(
                    "ICE Global Sugar Markets Hit Record Open Interest on Strong Demand for Hedging",
                    "ICE global refined sugar futures and options markets reached record open interest.",
                    source="洲际交易所",
                    category="Competitor",
                    subcategory="Trading / Clearing",
                    brand="ICE",
                ),
                "source_signal:ice_commodity_market",
            ),
        ]
        for item, expected_reason in cases:
            with self.subTest(title=item["title_original"]):
                score, reason = relevance(item)
                self.assertGreaterEqual(score, MIN_SCORE)
                self.assertIn(expected_reason, reason)

    def test_known_negative_controls(self):
        cases = [
            (
                make_item(
                    "Nasdaq Announces Mid-Month Open Short Interest Positions in Nasdaq Stocks",
                    "Open short interest positions in Nasdaq stocks as of settlement date.",
                    source="纳斯达克公司",
                    category="Competitor",
                    brand="Nasdaq",
                ),
                "downrank:nasdaq_routine_short_interest",
            ),
            (
                make_item(
                    "Generic final settlement price notice",
                    "Final settlement price for routine contracts.",
                    source="Eurex",
                    category="DBG",
                    brand="Eurex",
                ),
                "downrank:routine_operational",
            ),
            (
                make_item(
                    "Final research results published by institute",
                    "A research institute published final results of a survey.",
                    official=False,
                    priority=99,
                ),
                "",
            ),
            (
                make_item(
                    "Interim research findings on investor sentiment",
                    "A survey discusses investor sentiment.",
                    official=False,
                    priority=99,
                ),
                "",
            ),
            (
                make_item("AI webinar invitation for market participants", "Join a webinar about AI."),
                "downrank:webinar invitation",
            ),
            (
                make_item("AI conference agenda announced", "Speakers and conference agenda."),
                "downrank:agenda",
            ),
            (
                make_item(
                    "HKICL alerts public of fraudulent website",
                    "HKICL noted fraudulent websites.",
                    source="香港金融管理局",
                ),
                "downrank:individual_enforcement",
            ),
            (
                make_item(
                    "TA Tuesday: Bitcoin market deep dive",
                    "Routine market deep dive commentary.",
                    source="Crypto Finance",
                    category="DBG",
                    brand="Crypto Finance",
                ),
                "downrank:recurring_market_commentary",
            ),
        ]
        for item, expected_reason in cases:
            with self.subTest(title=item["title_original"]):
                score, reason = relevance(item)
                if expected_reason:
                    self.assertIn(expected_reason, reason)
                else:
                    self.assertLess(score, MIN_SCORE)


if __name__ == "__main__":
    unittest.main()
