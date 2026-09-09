import unittest

from crawler.competitor_mapping import map_competitor_item
from crawler.content_filter import apply_relevance, score_item
from crawler.event_cluster import cluster_same_event_items
from crawler.geography import macro_region_for_item
from crawler.highlight_ranker import highlight_score, select_highlights
from crawler.news_model import standardize_news
from qa_gate import WARNING, evaluate_qa


MIN_SCORE = 3


def item(
    title,
    summary="",
    *,
    source="测试源",
    category="Macro",
    subcategory="美国",
    brand="",
    official=True,
    priority=1,
    date="2026-08-24",
    url=None,
):
    return {
        "date": date,
        "title_original": title,
        "title_cn": "",
        "title_en": title,
        "summary": summary,
        "summary_original": summary,
        "relevance_context": "",
        "source": source,
        "category": category,
        "subcategory": subcategory,
        "brand": brand,
        "priority": priority,
        "official": official,
        "url": url or f"https://example.test/{abs(hash((title, source, date)))}",
    }


def competitor(title, summary="", *, source="竞争者", brand="", date="2026-08-24"):
    return item(title, summary, source=source, category="Competitor", subcategory="交易与清算", brand=brand, date=date)


def scored(value):
    clean = dict(value)
    score, reason = score_item(clean)
    clean["relevance_score"] = score
    clean["relevance_reason"] = reason
    return clean


class CompetitorMappingGoldCases(unittest.TestCase):
    def assert_mapping(self, value, expected, forbidden=None):
        mapping = map_competitor_item(value)
        self.assertEqual(mapping["mapped_dbg_business"], expected)
        if forbidden:
            self.assertNotEqual(mapping["mapped_dbg_business"], forbidden)
        return mapping

    def test_lch_polstr_ois_maps_to_eurex_not_iss_stoxx(self):
        value = competitor(
            "LCH clears first POLSTR Overnight Index Swaps",
            "LCH SwapClear clears first POLSTR OIS, supporting PLN benchmark transition.",
            source="伦敦证券交易所集团",
            brand="LSEG",
        )

        mapping = self.assert_mapping(value, "Eurex", forbidden="ISS STOXX / STOXX")
        self.assertIn("LSEG clearing-house", mapping["mapping_reason"])

    def test_ice_interest_rate_futures_maps_to_eurex_not_eex(self):
        value = competitor(
            "ICE’s Interest Rate Futures Markets Hit Record Open Interest",
            "Interest rate futures, Euribor and €STR futures hit record open interest.",
            source="洲际交易所",
            brand="ICE",
        )

        self.assert_mapping(value, "Eurex", forbidden="EEX")

    def test_cboe_group_disposal_maps_cross_business(self):
        value = competitor(
            "Cboe Completes Sale of Cboe Australia to TMX Group",
            "Corporate disposal and group strategy update.",
            source="芝加哥期权交易所",
            brand="Cboe",
        )

        self.assert_mapping(value, "Other / Cross-business", forbidden="Eurex")

    def test_hkex_etf_market_access_without_derivatives_maps_cross_business(self):
        value = competitor(
            "HKEX Welcomes Mainland Insurance Funds to Invest in Hong Kong ETFs",
            "Cash equity, ETF and securities market-access signal without derivatives content.",
            source="香港交易所",
            brand="HKEX",
        )

        self.assert_mapping(value, "Other / Cross-business", forbidden="Eurex")

    def test_energy_futures_map_to_eex_before_generic_derivatives(self):
        value = competitor(
            "JJ-Link Phase 2 Launches Offering Forward Transactions Based on the Electricity Futures Market",
            "The offering is based on the electricity futures market.",
            source="日本交易所集团",
            brand="JPX",
        )

        self.assert_mapping(value, "EEX", forbidden="Eurex")

    def test_cash_listing_exchange_figures_without_derivatives_map_cross_business(self):
        value = competitor(
            "SIX Exchanges Figures: August 2026",
            "Monthly key figures of SIX Swiss Exchange and BME Exchange on trading and listing activities.",
            source="瑞士交易所",
            brand="SIX",
        )

        self.assert_mapping(value, "Other / Cross-business", forbidden="Eurex")

    def test_broad_multi_business_mou_maps_cross_business(self):
        value = competitor(
            "The New York Stock Exchange and Korea Exchange Agree to Memorandum of Understanding for Business Collaboration",
            "The collaboration covers settlement-cycle modernization, extended trading hours, ETFs, market data and index products.",
            source="洲际交易所",
            brand="ICE",
        )

        self.assert_mapping(value, "Other / Cross-business", forbidden="DBG Market Data")

    def test_derivatives_controls_still_map_to_eurex(self):
        for value in (
            competitor(
                "ICE’s Interest Rate Futures Markets Hit Record Open Interest",
                "Interest rate futures, Euribor and €STR futures hit record open interest.",
                source="洲际交易所",
                brand="ICE",
            ),
            competitor(
                "Exchange launches new equity index derivatives",
                "New futures and options on an equity index.",
                source="日本交易所集团",
                brand="JPX",
            ),
        ):
            with self.subTest(title=value["title_original"]):
                self.assert_mapping(value, "Eurex", forbidden="EEX")


class RelevanceGoldCases(unittest.TestCase):
    def assert_dropped(self, value, reason_part=None):
        score, reason = score_item(value)
        self.assertLess(score, MIN_SCORE, reason)
        if reason_part:
            self.assertIn(reason_part, reason)

    def assert_kept(self, value, reason_part=None):
        score, reason = score_item(value)
        self.assertGreaterEqual(score, MIN_SCORE, reason)
        if reason_part:
            self.assertIn(reason_part, reason)

    def test_low_value_recurring_content_drops(self):
        self.assert_dropped(
            item("FIA calls for Hall of Fame nominations", "Award nomination notice.", source="FIA"),
            "downrank:low_value_event",
        )
        self.assert_dropped(
            item(
                "Philip R. Lane: Diversity at the European Central Bank",
                "Speech about diversity at the European Central Bank.",
                source="欧洲中央银行",
                subcategory="欧洲",
            ),
            "downrank:low_value_event",
        )
        self.assert_dropped(
            item("Podcasts: FINRA Unscripted", "Podcast listing page.", source="FINRA"),
            "downrank:podcast",
        )

    def test_generic_action_requires_financial_market_object(self):
        self.assert_dropped(
            item(
                "Treasury, IRS Move to End Tax-Exempt Status for Discriminatory Practices in Private Schools",
                "The proposed regulations concern private schools and racial discrimination.",
                source="美国财政部",
            ),
            "downrank:non_financial_policy",
        )
        self.assert_dropped(
            item(
                "Treasury Takes Action Against Violent Far-Left Terrorist Networks",
                "Treasury announces sanctions against terrorist networks.",
                source="美国财政部",
            ),
            "downrank:non_financial_policy",
        )
        self.assert_kept(
            item(
                "SEC Proposes to Modernize Rules for Registered Transfer Agents",
                "The proposal concerns clearance and settlement infrastructure in securities markets.",
                source="证券交易委员会",
            ),
            "hard_signal:proposes",
        )
        self.assert_kept(
            item(
                "CFTC Issues Final Rule to Modify Clearing Requirement for CAD/MXN Interest Rate Swaps",
                "The final rule modifies clearing requirements for interest rate swaps.",
                source="商品期货交易委员会",
            ),
            "hard_signal:regulatory_final_rule",
        )
        self.assert_kept(
            item(
                "MAS stablecoin regulatory framework",
                "The framework covers stablecoin regulation and financial market infrastructure.",
                source="新加坡金融管理局",
                subcategory="亚太",
            )
        )
        self.assert_kept(
            item(
                "Clearstream’s July 2026 figures",
                "",
                source="明讯银行",
                category="DBG",
                subcategory="证券与基金服务",
                brand="Clearstream",
            ),
            "source_signal:clearstream_monthly_figures",
        )
        self.assert_kept(
            item(
                "Treasury proposes regulations for tax-exempt bonds",
                "The proposed regulation concerns municipal securities and tax-exempt bonds.",
                source="美国财政部",
            )
        )

    def test_settlement_requires_financial_market_context(self):
        score, reason = score_item(
            item(
                "ASIC warns insurers cash settlements should not short-change homeowners in need",
                "Home insurers may be using cash settlements in a significant percentage of insurance claims.",
                source="澳大利亚证券和投资委员会",
                subcategory="亚太",
            )
        )
        self.assertNotIn("settlement", reason)
        self.assertNotIn("important:settlement", reason)
        self.assertLess(score, MIN_SCORE)

        positive_controls = [
            item(
                "SEC Proposes to Modernize Rules for Registered Transfer Agents",
                "Transfer agents are a key component of the national clearance and settlement system.",
                source="证券交易委员会",
            ),
            item(
                "DTCC advances T+1 securities settlement",
                "The update covers securities settlement and post-trade market infrastructure.",
                source="DTCC",
                category="Competitor",
                brand="DTCC",
            ),
            item(
                "Crypto Finance expands institutional digital asset trading and settlement",
                "The product enables regulated institutional digital-asset settlement.",
                source="Crypto Finance",
                category="DBG",
                brand="Crypto Finance",
            ),
            item(
                "BI and MAS operationalise local-currency transaction settlement framework",
                "The framework supports settlement of bilateral local-currency transactions.",
                source="新加坡金融管理局",
                subcategory="亚太",
            ),
        ]
        for value in positive_controls:
            with self.subTest(title=value["title_original"]):
                score, reason = score_item(value)
                self.assertGreaterEqual(score, MIN_SCORE, reason)
                self.assertIn("settlement", reason)

    def test_acquisition_requires_event_context(self):
        score, reason = score_item(
            item(
                "Federal Reserve Board announces termination of enforcement actions with United Texas Bank, Quontic Bank Acquisition Corp., and Quontic Bank Holdings Corp.",
                "The Board announced termination of routine enforcement actions.",
                source="联邦储备系统",
            )
        )
        self.assertNotIn("important:acquisition", reason)
        self.assertNotIn("hard_signal:business_development", reason)
        self.assertIn("downrank:routine_enforcement_termination", reason)
        self.assertLess(score, MIN_SCORE)

        score, reason = score_item(
            competitor(
                "Nasdaq Completes Acquisition of Dasseti",
                "Nasdaq completed the acquisition of Dasseti to expand private markets capabilities.",
                source="纳斯达克公司",
                brand="Nasdaq",
            )
        )
        self.assertGreaterEqual(score, MIN_SCORE, reason)
        self.assertIn("acquisition", reason)

    def test_consumer_phishing_payment_alert_drops_without_material_impact(self):
        self.assert_dropped(
            item(
                "HKMA reminds public to stay alert to phishing scams targeting binding of payment cards to contactless mobile payments",
                "The alert reminds retail customers to stay alert to phishing scams involving card binding.",
                source="香港金融管理局",
                subcategory="中国",
            ),
            "downrank:consumer_scam_alert",
        )
        self.assert_kept(
            item(
                "Central bank reports large-scale operational incident affecting payment infrastructure",
                "The notice covers systemic payment infrastructure disruption and market-infrastructure change.",
                source="香港金融管理局",
                subcategory="中国",
            )
        )


class HighlightGoldCases(unittest.TestCase):
    def test_cftc_sef_rule_ranks_above_generic_spot_consultation(self):
        cftc = scored(
            item(
                "CFTC Seeks Public Comments on Proposed Elimination of SEF Order Book Requirement for Permitted Transactions",
                "The proposal affects SEF market structure and derivatives trading.",
                source="商品期货交易委员会",
            )
        )
        croatia = scored(
            item(
                "Croatia consults on SPOT market for unlisted shares",
                "A public consultation on a SPOT market proposal.",
                source="克罗地亚金融监管局",
                subcategory="欧洲",
            )
        )

        self.assertGreater(highlight_score(cftc), highlight_score(croatia))

    def test_ice_rates_ranks_above_routine_ftse_review(self):
        ice = scored(
            competitor(
                "ICE’s Interest Rate Futures Markets Hit Record Open Interest",
                "Euribor and €STR interest rate futures reached record open interest.",
                source="洲际交易所",
                brand="ICE",
            )
        )
        ftse = scored(
            competitor(
                "FTSE UK Index Series - Indicative Quarterly Review Changes September 2026",
                "Routine quarterly review changes for index constituents.",
                source="伦敦证券交易所集团",
                brand="LSEG",
            )
        )

        self.assertGreater(highlight_score(ice), highlight_score(ftse))

    def test_lch_ois_clearing_has_strong_highlight_score(self):
        lch = scored(
            competitor(
                "LCH clears first POLSTR Overnight Index Swaps",
                "LCH SwapClear clears first POLSTR OIS.",
                source="伦敦证券交易所集团",
                brand="LSEG",
            )
        )

        self.assertGreaterEqual(highlight_score(lch), 18)

    def test_low_signal_highlights_do_not_dominate_top_five(self):
        values = [
            scored(item("FOMC Minutes", "The Federal Open Market Committee published minutes.", source="联邦储备系统")),
            scored(item("CFTC proposed SEF order book rule", "SEF market structure rule proposal.", source="商品期货交易委员会")),
            scored(competitor("LCH clears first POLSTR Overnight Index Swaps", "LCH SwapClear clears first POLSTR OIS.", source="伦敦证券交易所集团", brand="LSEG")),
            scored(competitor("ICE’s Interest Rate Futures Markets Hit Record Open Interest", "Euribor and €STR futures hit record OI.", source="洲际交易所", brand="ICE")),
            scored(item("Clearstream DLT settlement infrastructure launch", "Clearstream launches DLT settlement infrastructure.", source="明讯银行", category="DBG", brand="Clearstream")),
            scored(competitor("FTSE UK Index Series - Indicative Quarterly Review Changes September 2026", "Routine quarterly review changes.", source="伦敦证券交易所集团", brand="LSEG")),
        ]
        highlights = select_highlights(values)
        titles = [value["title_original"] for value in highlights]

        self.assertNotIn("FTSE UK Index Series - Indicative Quarterly Review Changes September 2026", titles)


class SameEventAndGeographyGoldCases(unittest.TestCase):
    def test_mas_primary_kept_aima_repost_clustered(self):
        mas = item(
            "MAS Introduces Measures to Strengthen Singapore’s Competitiveness as a Leading Asset Management Hub",
            "Singapore measures for fund management and asset management.",
            source="新加坡金融管理局",
            subcategory="亚太",
            date="2026-08-19",
            url="https://example.test/mas",
        )
        aima = item(
            "MAS announce set of measures to strengthen Singapore's position as a leading asset management hub",
            "AIMA commentary on MAS Singapore asset management hub measures.",
            source="另类投资管理协会",
            subcategory="英国",
            date="2026-08-19",
            url="https://example.test/aima",
        )

        kept, clustered = cluster_same_event_items([aima, mas])
        self.assertEqual([value["source"] for value in kept], ["新加坡金融管理局"])
        self.assertEqual(clustered[0]["drop_reason"], "same_event_clustered")

    def test_primary_official_kept_over_trade_association_repost(self):
        sec = item(
            "SEC Proposes to Modernize Rules for Registered Transfer Agents",
            "The proposal covers transfer agents in securities market infrastructure.",
            source="证券交易委员会",
            subcategory="美国",
            date="2026-08-19",
            url="https://example.test/sec",
        )
        association = item(
            "Industry association comments on SEC proposed rule for transfer agents",
            "Association update on the SEC transfer agents rulemaking.",
            source="金融市场协会",
            subcategory="美国",
            date="2026-08-19",
            url="https://example.test/association",
        )

        kept, clustered = cluster_same_event_items([association, sec])
        self.assertEqual([value["source"] for value in kept], ["证券交易委员会"])
        self.assertEqual(clustered[0]["drop_reason"], "same_event_clustered")

    def test_separate_cftc_rules_do_not_cluster(self):
        first = item("CFTC proposed rule on SEF order books", "SEF order book rule.", source="商品期货交易委员会")
        second = item("CFTC proposed rule on margin models", "Margin model proposal.", source="商品期货交易委员会")

        kept, clustered = cluster_same_event_items([first, second])
        self.assertEqual(len(kept), 2)
        self.assertEqual(clustered, [])

    def test_subject_based_macro_geography_overrides_source_fallback(self):
        aima_mas = item(
            "MAS announce set of measures to strengthen Singapore's position as a leading asset management hub",
            "AIMA article about MAS Singapore policy.",
            source="另类投资管理协会",
            subcategory="英国",
        )
        self.assertEqual(macro_region_for_item(aima_mas), "亚太")

        weak_uk = item("Investment association publishes quarterly note", "General association update.", source="英国投资管理协会", subcategory="英国")
        self.assertEqual(macro_region_for_item(weak_uk), "英国")


class SummaryHygieneGoldCases(unittest.TestCase):
    def test_jpx_website_boilerplate_removed(self):
        source = {"name": "日本交易所集团", "category": "Competitor", "subcategory": "交易与清算", "priority": 1, "official": True}
        value = standardize_news(
            source,
            "JPXI Adds New Ownership Datasets to J-Quants Pro | Japan Exchange Group",
            "https://example.test/jpx",
            "2026-07-27",
            "JPXI Adds New Ownership Datasets to J-Quants Pro | This is the website of Japan Exchange Group (JPX), which operates Tokyo Stock Exchange, Osaka Exchange, and Tokyo Commodity Exchange.",
        )

        self.assertEqual(value["summary"], "JPXI Adds New Ownership Datasets to J-Quants Pro")
        self.assertNotIn("This is the website", value["summary"])

    def test_html_break_noise_removed(self):
        source = {"name": "Cboe", "category": "Competitor", "subcategory": "交易与清算", "priority": 1, "official": True}
        value = standardize_news(
            source,
            "Cboe Completes Sale",
            "https://example.test/cboe",
            "2026-08-24",
            "Cboe completes sale.<br /><br /><br />Transaction closed.",
        )

        self.assertEqual(value["summary"], "Cboe completes sale. Transaction closed.")


class EditorialQAWarningsGoldCases(unittest.TestCase):
    def test_container_page_and_mapping_warnings_are_non_blocking(self):
        weekly = {
            "week_start": "2026-08-24",
            "week_end": "2026-08-30",
            "translation_mode": "bilingual",
            "source_count": 1,
            "registered_source_count": 1,
            "item_count": 2,
            "items": [
                item("Podcasts: FINRA Unscripted", "Podcast listing page.", date="2026-08-24"),
                {
                    **competitor(
                        "HKEX Welcomes Mainland Insurance Funds to Invest in Hong Kong ETFs",
                        "ETF market access without derivatives.",
                        source="香港交易所",
                        brand="HKEX",
                        date="2026-08-24",
                    ),
                    "competitor_group": "HKEX",
                    "mapped_dbg_business": "Eurex",
                },
            ],
            "highlights": [],
        }
        report = evaluate_qa(
            weekly,
            [{"source_id": "HEALTHY", "source": "HEALTHY", "status": "success", "target_period_reached": True, "within_period": 1}],
            {"thresholds": {}, "sources": {}},
            [],
        )
        results = {check["id"]: check["result"] for check in report["checks"]}

        self.assertEqual(results["no_obvious_container_pages"], WARNING)
        self.assertEqual(results["competitor_mapping_signals_consistent"], WARNING)


if __name__ == "__main__":
    unittest.main()
