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
                    "Treasury requests comment on proposed regulation for financial institutions",
                    "The proposed regulation would update compliance obligations for banks and securities markets.",
                    source="美国财政部",
                    priority=2,
                ),
                "hard_signal:proposed regulation",
            ),
            (
                make_item(
                    "Tax-Exempt Municipal Bond Market Regulation",
                    "The proposal addresses tax-exempt bonds and municipal securities disclosure in capital markets.",
                    source="美国财政部",
                    priority=2,
                ),
                "capital market",
            ),
            (
                make_item(
                    "School District Bonds Disclosure Rule for Municipal Securities Markets",
                    "The rule concerns school district bonds traded in municipal securities markets.",
                    source="美国财政部",
                    priority=2,
                ),
                "securities",
            ),
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
                    "Treasury, IRS Move to End Tax-Exempt Status for Discriminatory Practices in Private Schools",
                    "The Treasury and IRS issued proposed regulations to end federal tax-exempt status for schools that engage in racial discrimination.",
                    source="美国财政部",
                    priority=2,
                ),
                "downrank:non_financial_policy",
            ),
            (
                make_item(
                    "Treasury proposes regulations for charitable organizations in education",
                    "The proposed regulation updates tax administration for nonprofit schools and charitable organizations.",
                    source="美国财政部",
                    priority=2,
                ),
                "downrank:non_financial_policy",
            ),
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
                    if expected_reason == "downrank:non_financial_policy":
                        self.assertLess(score, MIN_SCORE)
                else:
                    self.assertLess(score, MIN_SCORE)

    def test_cboe_conference_boilerplate_does_not_create_relevance(self):
        item = make_item(
            "Cboe Global Markets to Present at the Barclays Global Financial Services Conference on September 16",
            (
                "Cboe executives will present at the Barclays Global Financial Services Conference. "
                "About Cboe Global Markets Cboe is a leading derivatives exchange. "
                "Since launching the world's first listed options exchange in 1973, "
                "Cboe has pursued a global strategy across equity and index derivatives."
            ),
            source="Cboe",
            category="Competitor",
            subcategory="Trading / Clearing",
            brand="Cboe",
        )
        score, reason = relevance(item)
        self.assertLess(score, MIN_SCORE, reason)
        self.assertIn("downrank:conference", reason)

    def test_real_product_launch_stays_relevant(self):
        item = make_item(
            "Cboe launches new index options product",
            "The exchange launched new index options to expand listed derivatives trading.",
            source="Cboe",
            category="Competitor",
            subcategory="Trading / Clearing",
            brand="Cboe",
        )
        score, reason = relevance(item)
        self.assertGreaterEqual(score, MIN_SCORE, reason)
        self.assertIn("hard_signal:launches", reason)

    def test_ccp_resolution_meeting_survives_meeting_downrank(self):
        item = make_item(
            "Joint Readout of Principals’ Meeting of U.S. and UK Authorities Regarding Central Counterparty Resolution",
            "Authorities discussed central counterparty resolution and clearing-house resilience.",
            source="证券交易委员会",
            category="Macro",
            subcategory="美国",
        )
        score, reason = relevance(item)
        self.assertGreaterEqual(score, MIN_SCORE, reason)
        self.assertIn("hard_signal:ccp_resolution", reason)
        self.assertIn("downrank:meeting", reason)

    def test_ordinary_conference_agenda_remains_rejected(self):
        item = make_item(
            "CFTC Chairman Selig and Kansas State University Announce Agenda for October 22-23 AgCon Conference in Overland Park",
            "The announcement lists speakers and agenda items for the conference.",
            source="商品期货交易委员会",
            category="Macro",
            subcategory="美国",
        )
        score, reason = relevance(item)
        self.assertLess(score, MIN_SCORE, reason)
        self.assertIn("downrank:agenda", reason)

    def test_financial_market_connectivity_working_group_is_relevant(self):
        item = make_item(
            "HKEX, HKMA, DFSA and Nasdaq Dubai Form Strategic Working Group to Strengthen Hong Kong-Dubai Financial Market Connectivity",
            "The group aims to strengthen cross-market connectivity between financial markets.",
            source="香港交易所",
            category="Competitor",
            subcategory="Trading / Clearing",
            brand="HKEX",
        )
        score, reason = relevance(item)
        self.assertGreaterEqual(score, MIN_SCORE, reason)
        self.assertIn("hard_signal:financial_market_connectivity", reason)

    def test_generic_working_group_without_market_connectivity_remains_rejected(self):
        item = make_item(
            "Agency forms strategic working group for internal communications",
            "The working group will coordinate routine internal communications.",
            source="测试源",
            category="Macro",
            subcategory="美国",
        )
        score, reason = relevance(item)
        self.assertLess(score, MIN_SCORE, reason)
        self.assertNotIn("hard_signal:financial_market_connectivity", reason)

    def test_pboc_financial_infrastructure_supervision_measures_are_relevant(self):
        item = make_item(
            "中国人民银行公告〔2026〕第24号",
            (
                "为顺应我国支付清算市场发展变化，《中国人民银行关于印发"
                "〈农信银资金清算中心有限责任公司监督管理办法〉的通知》"
                "自本公告发布之日起废止。相关事项按照《金融基础设施监督管理办法》"
                "等现行相关管理制度执行。"
            ),
            source="中国人民银行",
            category="Macro",
            subcategory="中国",
            official=True,
            priority=1,
        )
        score, reason = relevance(item)
        self.assertGreaterEqual(score, MIN_SCORE, reason)
        self.assertIn("hard_signal:financial_infrastructure_regulation", reason)

    def test_routine_pboc_meeting_remains_rejected(self):
        item = make_item(
            "中国人民银行副行长宣昌能会见新加坡金融管理局副行长梁新松",
            "双方就当前经济金融形势和中新金融合作等议题进行了交流。",
            source="中国人民银行",
            category="Macro",
            subcategory="中国",
            official=True,
            priority=1,
        )
        score, reason = relevance(item)
        self.assertLess(score, MIN_SCORE, reason)
        self.assertNotIn("hard_signal:financial_infrastructure_regulation", reason)

    def test_general_pboc_announcement_without_infrastructure_rule_is_not_automatic(self):
        item = make_item(
            "中国人民银行公告〔2026〕第25号",
            "中国人民银行发布一般工作安排公告。",
            source="中国人民银行",
            category="Macro",
            subcategory="中国",
            official=True,
            priority=1,
        )
        score, reason = relevance(item)
        self.assertLess(score, MIN_SCORE, reason)
        self.assertNotIn("hard_signal:financial_infrastructure_regulation", reason)

    def test_safe_meeting_unchanged_by_financial_infrastructure_signal(self):
        item = make_item(
            "朱鹤新局长会见新加坡金管局副行长梁新松",
            "双方就全球经济金融形势、深化中新金融领域合作等议题进行了交流。",
            source="国家外汇管理局",
            category="Macro",
            subcategory="中国",
            official=True,
            priority=1,
        )
        score, reason = relevance(item)
        self.assertLess(score, MIN_SCORE, reason)
        self.assertNotIn("hard_signal:financial_infrastructure_regulation", reason)

    def test_routine_executive_event_wording_remains_rejected(self):
        cases = [
            "CEO participates in a fireside chat at Barclays Global Financial Services Conference",
            "Executives will speak at Barclays Global Financial Services Conference",
            "Company management to attend investor conference",
        ]
        for title in cases:
            with self.subTest(title=title):
                item = make_item(
                    title,
                    "Routine executive event announcement.",
                    source="Cboe",
                    category="Competitor",
                    subcategory="Trading / Clearing",
                    brand="Cboe",
                )
                score, reason = relevance(item)
                self.assertLess(score, MIN_SCORE, reason)
                self.assertIn("downrank:low_value_event", reason)

    def test_shfe_trading_management_rule_revision_is_relevant(self):
        item = make_item(
            "关于发布《上海期货交易所交易管理办法》（修订案）的公告",
            "《上海期货交易所交易管理办法》（修订案）已经发布，涉及交易规则和市场管理安排。",
            source="上海期货交易所",
            category="Competitor",
            subcategory="交易与清算",
            brand="SHFE",
            official=True,
            priority=1,
        )
        score, reason = relevance(item)
        self.assertGreaterEqual(score, MIN_SCORE, reason)
        self.assertIn("hard_signal:exchange_market_structure_change", reason)

    def test_routine_shfe_system_test_notice_remains_rejected(self):
        item = make_item(
            "关于交易系统测试的通知",
            "上海期货交易所将于周末开展交易系统测试。",
            source="上海期货交易所",
            category="Competitor",
            subcategory="交易与清算",
            brand="SHFE",
            official=True,
            priority=1,
        )
        score, reason = relevance(item)
        self.assertLess(score, MIN_SCORE, reason)
        self.assertNotIn("hard_signal:exchange_market_structure_change", reason)

    def test_shfe_warehouse_approval_notice_remains_rejected(self):
        item = make_item(
            "关于同意上港云仓（上海）仓储管理有限公司调整铜期货存放点的公告",
            "上海期货交易所同意交割仓库存放点调整。",
            source="上海期货交易所",
            category="Competitor",
            subcategory="交易与清算",
            brand="SHFE",
            official=True,
            priority=1,
        )
        score, reason = relevance(item)
        self.assertLess(score, MIN_SCORE, reason)
        self.assertNotIn("hard_signal:exchange_market_structure_change", reason)

    def test_exchange_contract_rule_change_is_relevant(self):
        item = make_item(
            "CME amends contract specifications for interest rate futures",
            "CME adopted rule amendments changing contract specifications and margin requirements for futures contracts.",
            source="芝加哥商品交易所集团",
            category="Competitor",
            subcategory="Trading / Clearing",
            brand="CME",
            official=True,
            priority=1,
        )
        score, reason = relevance(item)
        self.assertGreaterEqual(score, MIN_SCORE, reason)
        self.assertIn("hard_signal:exchange_market_structure_change", reason)


if __name__ == "__main__":
    unittest.main()
