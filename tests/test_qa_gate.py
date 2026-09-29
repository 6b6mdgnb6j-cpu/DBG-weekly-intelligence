import json
import tempfile
import unittest
from pathlib import Path

from qa_gate import FAIL, INFO, PASS, WARNING, evaluate_qa, file_sha256, load_policy, load_sources, run_qa


def item(index, **overrides):
    value = {
        "title_original": f"Market infrastructure update {index}",
        "url": f"https://example.test/news/{index}",
        "source": "Expected Healthy Source",
        "category": "Macro",
        "date": "2020-01-01",
    }
    value.update(overrides)
    return value


def payload(items=None, highlights=None):
    items = items if items is not None else [item(i) for i in range(1, 26)]
    return {
        "week_start": "2020-01-01",
        "week_end": "2020-01-07",
        "translation_mode": "bilingual",
        "source_count": 5,
        "registered_source_count": 5,
        "item_count": len(items),
        "items": items,
        "highlights": highlights if highlights is not None else items[:5],
    }


def source_status(source_id, status="success", **overrides):
    value = {
        "source_id": source_id,
        "source": source_id,
        "status": status,
        "target_period_reached": True,
        "within_period": 1,
        "requests_total": 1,
        "request_attempts_total": 1,
        "retried_requests": 0,
        "last_network_error": "",
        "final_network_error": "",
    }
    value.update(overrides)
    return value


def base_policy():
    return {
        "thresholds": {
            "critical_unexpected_failures_fail": 3,
            "systemic_failure_warning_ratio": 0.5,
            "systemic_failure_fail_ratio": 0.8,
            "retry_hotspot_min_retried_requests": 3,
            "retry_hotspot_warning_ratio": 0.3,
            "global_retry_min_requests": 20,
            "global_retry_warning_ratio": 0.15,
            "global_retry_fail_ratio": 0.35,
        },
        "sources": {
            "KNOWN_BLOCKED": {"policy": "known_gap", "tier": "high", "expected_failures": ["blocked"]},
            "KNOWN_NETWORK": {"policy": "known_gap", "tier": "high", "expected_failures": ["network_error"]},
            "CRIT1": {"policy": "expected_healthy", "tier": "critical"},
            "CRIT2": {"policy": "expected_healthy", "tier": "critical"},
            "CRIT3": {"policy": "expected_healthy", "tier": "critical"},
            "HEALTHY": {"policy": "expected_healthy", "tier": "normal"},
            "FLAKY": {"policy": "flaky_watch", "tier": "high"},
        },
    }


class QAGateTests(unittest.TestCase):
    def evaluate(self, weekly=None, statuses=None, policy=None):
        return evaluate_qa(
            weekly or payload(),
            statuses if statuses is not None else [source_status("HEALTHY")],
            policy or base_policy(),
            [],
        )

    def check(self, report, check_id):
        return next(check for check in report["checks"] if check["id"] == check_id)

    def test_clean_pass(self):
        report = self.evaluate()
        self.assertEqual(report["status"], PASS)
        self.assertEqual(report["publish_recommendation"], "ready_for_manual_review")
        self.assertEqual(report["translation_mode"], "bilingual")
        self.assertEqual(report["summary"]["translation_mode"], "bilingual")

    def test_known_blocked_source_does_not_warn_or_fail(self):
        report = self.evaluate(statuses=[source_status("KNOWN_BLOCKED", "blocked")])
        self.assertEqual(report["status"], PASS)
        self.assertEqual(len(report["known_gaps"]), 1)

    def test_known_network_gap_source_does_not_warn_or_fail(self):
        report = self.evaluate(statuses=[source_status("KNOWN_NETWORK", "network_error", target_period_reached=False)])
        self.assertEqual(report["status"], PASS)
        self.assertEqual(len(report["known_gaps"]), 1)

    def test_expected_healthy_single_network_error_warns(self):
        statuses = [
            source_status("HEALTHY", "network_error", target_period_reached=False),
            source_status("CRIT1"),
            source_status("CRIT2"),
            source_status("CRIT3"),
        ]
        report = self.evaluate(statuses=statuses)
        self.assertEqual(report["status"], WARNING)
        self.assertEqual(self.check(report, "unexpected_source_failures")["result"], WARNING)

    def test_three_critical_healthy_failures_fail(self):
        statuses = [
            source_status("CRIT1", "network_error", target_period_reached=False),
            source_status("CRIT2", "parser_failed", target_period_reached=False),
            source_status("CRIT3", "date_parse_failed", target_period_reached=False),
        ]
        report = self.evaluate(statuses=statuses)
        self.assertEqual(report["status"], FAIL)
        self.assertEqual(self.check(report, "critical_unexpected_failures_below_limit")["result"], FAIL)

    def test_retry_hotspot_warns(self):
        status = source_status("HEALTHY", requests_total=10, request_attempts_total=16, retried_requests=4)
        report = self.evaluate(statuses=[status])
        self.assertEqual(report["status"], WARNING)
        self.assertEqual(self.check(report, "retry_hotspots")["result"], WARNING)

    def test_retry_success_is_not_network_failure(self):
        status = source_status(
            "HEALTHY",
            "success",
            requests_total=2,
            request_attempts_total=3,
            retried_requests=1,
            last_retry_error="status:502",
            last_network_error="",
            final_network_error="",
        )
        report = self.evaluate(statuses=[status])
        self.assertNotEqual(self.check(report, "unexpected_source_failures")["result"], WARNING)

    def test_final_items_zero_fails(self):
        report = self.evaluate(weekly=payload(items=[], highlights=[]))
        self.assertEqual(report["status"], FAIL)
        self.assertEqual(self.check(report, "final_items_not_empty")["result"], FAIL)

    def test_final_items_low_warns(self):
        items = [item(i) for i in range(1, 5)]
        report = self.evaluate(weekly=payload(items=items, highlights=items[:4]))
        self.assertEqual(report["status"], WARNING)
        self.assertEqual(self.check(report, "final_items_low")["result"], WARNING)

    def test_outside_week_item_fails(self):
        report = self.evaluate(weekly=payload(items=[item(1, date="2020-01-08")], highlights=[]))
        self.assertEqual(report["status"], FAIL)
        self.assertEqual(self.check(report, "final_item_dates_valid")["result"], FAIL)

    def test_malformed_date_fails(self):
        report = self.evaluate(weekly=payload(items=[item(1, date="not-a-date")], highlights=[]))
        self.assertEqual(report["status"], FAIL)
        self.assertEqual(self.check(report, "final_item_dates_valid")["result"], FAIL)

    def test_missing_url_fails(self):
        report = self.evaluate(weekly=payload(items=[item(1, url="")], highlights=[]))
        self.assertEqual(report["status"], FAIL)
        self.assertEqual(self.check(report, "required_item_fields_present")["result"], FAIL)

    def test_missing_title_source_category_fails(self):
        report = self.evaluate(
            weekly=payload(items=[item(1, title_original="", source="", category="")], highlights=[])
        )
        self.assertEqual(report["status"], FAIL)
        self.assertEqual(self.check(report, "required_item_fields_present")["result"], FAIL)

    def test_exact_duplicate_url_fails(self):
        items = [item(1), item(2, url="https://example.test/news/1")]
        report = self.evaluate(weekly=payload(items=items, highlights=[]))
        self.assertEqual(report["status"], FAIL)
        self.assertEqual(self.check(report, "no_duplicate_urls")["result"], FAIL)

    def test_five_highlights_is_normal(self):
        weekly = payload(items=[item(i) for i in range(1, 8)], highlights=[item(i) for i in range(1, 6)])
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "highlights_count_normal")["result"], PASS)

    def test_no_highlights_with_enough_final_items_fails(self):
        report = self.evaluate(weekly=payload(items=[item(i) for i in range(1, 8)], highlights=[]))
        self.assertEqual(report["status"], FAIL)
        self.assertEqual(self.check(report, "highlights_present")["result"], FAIL)

    def test_missing_network_diagnostics_fields_is_info_only(self):
        status = {
            "source_id": "HEALTHY",
            "source": "Healthy",
            "status": "success",
            "target_period_reached": True,
            "within_period": 1,
            "request_attempts_total": 1,
        }
        report = self.evaluate(statuses=[status])
        info_checks = [check for check in report["checks"] if check["id"] == "network_diagnostics_optional_fields"]
        self.assertEqual(report["status"], PASS)
        self.assertEqual(info_checks[0]["result"], INFO)

    def test_known_gap_recovery_is_info_not_warning(self):
        report = self.evaluate(statuses=[source_status("KNOWN_BLOCKED", "success")])
        self.assertEqual(report["status"], PASS)
        self.assertEqual(len(report["recovered_sources"]), 1)

    def test_translation_quality_proper_noun_mismatch_fails(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="Indonesia and Singapore sign financial cooperation memorandum",
                    title_cn="印尼和新加拿大签署金融合作备忘录",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertIn("translation_proper_noun_mismatch", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_quality_proper_noun_mismatch_fails_even_when_correct_name_also_present(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="Bank Indonesia and the Monetary Authority of Singapore operationalise framework",
                    title_cn="印尼银行和新加坡金融管理局启动框架",
                    summary_original="Transactions between Indonesia and Singapore will settle in local currencies.",
                    summary_cn="印尼和新加拿大之间的交易将以本地货币结算。",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertIn("translation_proper_noun_mismatch", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_quality_material_entity_and_term_errors_fail(self):
        weekly = payload(
            items=[
                item(
                    1,
                    source="Euronext",
                    title_original="Euronext announces volumes for August 2026",
                    title_cn="欧联网宣布2026年8月份的交易量",
                ),
                item(
                    2,
                    title_original="Financial Market Infrastructures (FMIs) need robust risk management",
                    title_cn="国际货币基金组织需要稳健的风险管理",
                ),
                item(
                    3,
                    source="国际证监会组织",
                    title_original="IOSCO published a market report",
                    title_cn="国际证券委员会组织发布市场报告",
                ),
                item(
                    4,
                    source="货币监理署",
                    title_original="The Office of the Comptroller of the Currency issued a supervisory update",
                    title_cn="欧盟委员会发布监管更新",
                ),
                item(
                    5,
                    title_original="CFTC proposed portfolio margining rules",
                    title_cn="CFTC提出投资组合的利率规则",
                ),
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        issue_ids = [issue["issue_id"] for issue in report["content_issues"]]
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertIn("translation_entity_conflict", issue_ids)
        self.assertIn("translation_material_term_conflict", issue_ids)

    def test_bilingual_summary_original_requires_summary_cn(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="Ontario Securities Commission brings together capital markets leaders to advise on future priorities",
                    title_cn="安大略省证券委员会召集资本市场领导者就未来优先事项提供建议",
                    summary_original="The Ontario Securities Commission announced the membership of its newly established Capital Markets Advisory Council.",
                    summary_cn="",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertIn("translation_summary_missing", [issue["issue_id"] for issue in report["content_issues"]])

    def test_empty_original_summary_allows_empty_summary_cn_in_bilingual_qa(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="Clearstream monthly figures",
                    title_cn="Clearstream月度数据",
                    summary_original="",
                    summary_cn="",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_minor_awkward_translation_remains_non_blocking(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="EEX introduces freight data products in its market data portfolio",
                    title_cn="EEX在其市场数据组合中引入货运数据产品",
                    summary_original="EEX expanded its market data offering with freight data products.",
                    summary_cn="EEX扩大其市场数据服务，加入货运数据产品。",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_translation_quality_short_title_proposition_missing_fails(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="July saw inflows into funds despite domestic political changes and conflict in the Middle East",
                    title_cn="尽管国内政治变化和中东冲突",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertIn("translation_title_proposition_missing", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_quality_correct_inflow_title_passes(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="July saw inflows into funds despite domestic political changes and conflict in the Middle East",
                    title_cn="尽管国内政治变化和中东冲突，7月基金仍出现资金流入",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_translation_quality_rescission_direction_missing_fails(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="SEC Proposes Rescission of Political Contribution Rule for Investment Advisers",
                    title_cn="SEC提议禁止投资顾问进行政治捐款",
                    summary_original="The rule currently prohibits certain pay-to-play activity.",
                    summary_cn="该规则目前禁止某些活动。",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertIn("translation_action_direction_missing", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_quality_correct_rescission_direction_passes(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="SEC Proposes Rescission of Political Contribution Rule for Investment Advisers",
                    title_cn="SEC拟取消投资顾问政治捐款规则",
                    summary_original="The SEC proposes to rescind the rule that currently prohibits certain pay-to-play activity.",
                    summary_cn="SEC提议取消目前禁止某些付费参与活动的规则。",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_translation_quality_rescission_with_current_prohibition_context_passes_when_cancel_signal_exists(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="SEC Proposes Rescission of Political Contribution Rule for Investment Advisers",
                    title_cn="SEC拟取消投资顾问政治捐款规则",
                    summary_original="The SEC proposes to rescind the rule that currently prohibits investment advisers from certain activity.",
                    summary_cn="SEC提议取消目前禁止投资顾问从事某些活动的规则。",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_translation_quality_accepts_common_sec_chinese_name_with_acronym(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="SEC and FDA Announce MOU to Bolster Cooperation and Ensure Market Integrity",
                    title_cn="SEC和FDA宣布签署谅解备忘录",
                    summary_original="The SEC and FDA announced a memorandum of understanding.",
                    summary_cn="美国证券交易委员会（SEC）和美国食品药品监督管理局宣布签署谅解备忘录。",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_translation_quality_accepts_common_nasdaq_chinese_rendering(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="Nasdaq Reports August 2026 Volumes",
                    title_cn="纳斯达克报告2026年8月交易量",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_translation_quality_weak_report_verb_can_drop_when_object_preserved(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="Nasdaq Reports August 2026 Volumes",
                    title_cn="2026年8月Nasdaq交易量",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_translation_quality_acquisition_still_fails_when_substantive_action_missing(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="Company reports acquisition of X",
                    title_cn="公司报告X",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertIn("translation_title_proposition_missing", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_quality_launch_still_fails_when_missing(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="EEX launches new freight data products",
                    title_cn="EEX新的货运数据产品",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertIn("translation_title_proposition_missing", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_quality_launch_accepts_startup_equivalent(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="JJ-Link Phase 2 Launches Offering Forward Transactions Based on the Electricity Futures Market",
                    title_cn="启动JJ-Link第二阶段 提供远期交易 基于电力期货市场",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_translation_quality_launch_missing_still_fails_for_jj_link(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="JJ-Link Phase 2 Launches Offering Forward Transactions Based on the Electricity Futures Market",
                    title_cn="基于电力期货市场的交易",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertIn("translation_title_proposition_missing", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_quality_consultation_on_proposed_amendments_is_not_action_warning(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="MAS consults on legislative amendments",
                    title_cn="MAS就立法修订展开咨询",
                    summary_original="MAS published a consultation paper on proposed legislative amendments to the framework.",
                    summary_cn="MAS发布了一份关于框架立法修正案的咨询文件。",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        issue_ids = [issue["issue_id"] for issue in report["content_issues"]]
        self.assertNotIn("translation_action_direction_missing", issue_ids)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)
        self.assertEqual(self.check(report, "translation_quality_warnings")["result"], PASS)

    def test_translation_quality_rescission_action_still_fails_when_missing(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="SEC proposes rescission of a political contribution rule",
                    title_cn="SEC提议政治捐款规则",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertIn("translation_title_proposition_missing", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_quality_currency_corruption_fails(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="Canadian Dollar- and Mexican Peso-Denominated Interest Rate Swaps",
                    title_cn="加拿大美元和墨西哥指利率互换",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertIn("translation_proper_noun_mismatch", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_quality_summary_later_substantive_clause_missing_fails(self):
        weekly = payload(
            items=[
                item(
                    1,
                    source="FINRA",
                    title_original="FINRA replaces pattern day trader rule",
                    title_cn="FINRA取代日内交易者规则",
                    summary_original=(
                        "On this episode of FINRA Unscripted, learn why FINRA replaced the decades-old "
                        "Pattern Day Trader rule — including the $25,000 minimum equity requirement — "
                        "with a modern, risk-based intraday margin standard, and what the change means "
                        "for investors and member firms."
                    ),
                    summary_cn="在本期FINRA节目中，了解FINRA为何取代已有数十年历史的日内交易者规则，包括25,000美元的最低股权要求。",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertIn("translation_suspicious_compression", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_quality_summary_preserving_later_clause_passes(self):
        weekly = payload(
            items=[
                item(
                    1,
                    source="FINRA",
                    title_original="FINRA replaces pattern day trader rule",
                    title_cn="FINRA取代日内交易者规则",
                    summary_original=(
                        "On this episode of FINRA Unscripted, learn why FINRA replaced the decades-old "
                        "Pattern Day Trader rule — including the $25,000 minimum equity requirement — "
                        "with a modern, risk-based intraday margin standard, and what the change means "
                        "for investors and member firms."
                    ),
                    summary_cn="本期FINRA节目介绍其为何取代旧的日内交易者规则，包括25,000美元最低权益要求，并采用现代、基于风险的日内保证金标准，以及该变化对投资者和会员公司的影响。",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_translation_safe_fallback_warning_when_title_replaces_bad_rescind_summary(self):
        weekly = payload(
            items=[
                item(
                    1,
                    source="证券交易委员会",
                    title_original="SEC Proposes Rescission of Political Contribution Rule for Investment Advisers",
                    title_cn="SEC拟取消投资顾问政治贡献规则",
                    summary_original="The Securities and Exchange Commission today issued a proposal to rescind its pay-to-play rule that prohibits investment advisers.",
                    summary_cn="SEC拟取消投资顾问政治贡献规则",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)
        self.assertEqual(self.check(report, "translation_quality_warnings")["result"], WARNING)
        self.assertIn("translation_safe_fallback_used", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_safe_fallback_not_used_when_title_also_omits_action(self):
        weekly = payload(
            items=[
                item(
                    1,
                    source="Regulator",
                    title_original="Agency Proposes Rescission of Market Rule",
                    title_cn="机构提议市场规则",
                    summary_original="The agency issued a proposal to rescind the market rule that prohibits activity.",
                    summary_cn="机构提议市场规则",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertNotIn("translation_safe_fallback_used", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_safe_fallback_not_used_for_different_title_action(self):
        weekly = payload(
            items=[
                item(
                    1,
                    source="Regulator",
                    title_original="Agency Approves Market Rule",
                    title_cn="机构批准市场规则",
                    summary_original="The agency issued a proposal to rescind the market rule that prohibits activity.",
                    summary_cn="机构批准市场规则",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], FAIL)
        self.assertNotIn("translation_safe_fallback_used", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_safe_fallback_not_used_for_good_summary(self):
        weekly = payload(
            items=[
                item(
                    1,
                    source="Regulator",
                    title_original="Agency Proposes Rescission of Market Rule",
                    title_cn="机构拟取消市场规则",
                    summary_original="The agency issued a proposal to rescind the market rule that prohibits activity.",
                    summary_cn="机构发布一项拟取消该市场规则的提议，该规则禁止相关活动。",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)
        self.assertEqual(self.check(report, "translation_quality_warnings")["result"], PASS)

    def test_translation_quality_short_simple_summary_does_not_trigger_compression(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="Nasdaq Reports August 2026 Volumes",
                    title_cn="2026年8月Nasdaq交易量",
                    summary_original="Nasdaq reported August 2026 trading volumes.",
                    summary_cn="Nasdaq公布2026年8月交易量。",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_translation_quality_stox_bad_variant_uses_ascii_boundaries(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="STOXX Blue-Chip Indices Composition Changes",
                    title_cn="STOXX蓝筹指数组成变化",
                    summary_original="ISS STOXX announced index changes.",
                    summary_cn="ISSSTOXX宣布指数调整。",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        issue_ids = [issue["issue_id"] for issue in report["content_issues"]]
        self.assertNotIn("translation_entity_conflict", issue_ids)

    def test_translation_quality_entity_duplicate_is_warning_not_fail(self):
        weekly = payload(
            items=[
                item(
                    1,
                    title_original="FINRA's Intraday Margin Standard",
                    title_cn="FINRA (FINRA) 日内保证金标准",
                )
            ],
            highlights=[],
        )
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)
        self.assertEqual(self.check(report, "translation_quality_warnings")["result"], WARNING)
        self.assertIn("translation_entity_duplicate", [issue["issue_id"] for issue in report["content_issues"]])

    def test_translation_quality_normal_title_without_configured_anchor_does_not_false_positive(self):
        weekly = payload(items=[item(1, title_original="Market structure update for regulated firms", title_cn="受监管机构市场结构更新")], highlights=[])
        report = self.evaluate(weekly=weekly)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_mks_pamp_approval_title_accepts_clear_approval_equivalents(self):
        original = (
            "MKS PAMP Has Been Approved as an Approved Person in the Chain of Custody "
            "Related to the Issuance of Warehouse Receipts for Precious Metals"
        )
        for translated in (
            "MKS PAMP 已获批成为与贵金属仓单发行相关的托管链认可参与方",
            "MKS PAMP 被批准成为与贵金属仓单发行相关的托管链认可参与方",
            "MKS PAMP 被认可为与贵金属仓单发行相关的托管链认可参与方",
        ):
            with self.subTest(translated=translated):
                report = self.evaluate(weekly=payload(items=[item(1, title_original=original, title_cn=translated)], highlights=[]))
                issue_ids = [issue["issue_id"] for issue in report["content_issues"]]
                self.assertNotIn("translation_title_proposition_missing", issue_ids)
                self.assertNotIn("translation_action_direction_missing", issue_ids)

    def test_mks_pamp_approval_title_still_fails_when_approval_is_omitted(self):
        original = (
            "MKS PAMP Has Been Approved as an Approved Person in the Chain of Custody "
            "Related to the Issuance of Warehouse Receipts for Precious Metals"
        )
        report = self.evaluate(
            weekly=payload(items=[item(1, title_original=original, title_cn="MKS PAMP 与贵金属仓单发行相关的托管链参与方")], highlights=[])
        )
        issue_ids = [issue["issue_id"] for issue in report["content_issues"]]
        self.assertIn("translation_title_proposition_missing", issue_ids)
        self.assertIn("translation_action_direction_missing", issue_ids)

    def test_hashkey_obita_partnership_omission_fails_qa(self):
        report = self.evaluate(
            weekly=payload(
                items=[
                    item(
                        1,
                        source="HashKey",
                        title_original="HashKey Exchange Partners with Obita to Provide Institutional-Grade Digital Asset Custody Support",
                        title_cn="HashKey Exchange与Obita合作提供机构级数字资产托管支持",
                        summary_original=(
                            "HashKey Exchange announced that it has reached a partnership with Obita "
                            "to provide institutional-grade digital asset custody support."
                        ),
                        summary_cn="HashKey Exchange为机构客户提供数字资产托管支持。",
                    )
                ],
                highlights=[],
            )
        )
        self.assertIn("translation_relationship_missing", [issue["issue_id"] for issue in report["content_issues"]])

    def test_sec_ipo_increase_title_accepts_growth_equivalence(self):
        report = self.evaluate(
            weekly=payload(
                items=[
                    item(
                        1,
                        source="SEC",
                        title_original=(
                            "SEC Publishes Updated Market Statistics, Highlighting Increase in IPOs "
                            "and Proceeds Raised"
                        ),
                        title_cn="SEC发布了最新的市场统计数据,突出了IPO增长和收益增长",
                    )
                ],
                highlights=[],
            )
        )
        issue_ids = [issue["issue_id"] for issue in report["content_issues"]]

        self.assertNotIn("translation_title_proposition_missing", issue_ids)
        self.assertNotIn("translation_action_direction_missing", issue_ids)
        self.assertEqual(self.check(report, "translation_quality_failures")["result"], PASS)

    def test_descriptive_decrease_in_is_content_not_agentive_action(self):
        report = self.evaluate(
            weekly=payload(
                items=[
                    item(
                        1,
                        title_original="Statistics show a notable decline in settlement failures",
                        title_cn="统计数据显示结算失败显著下降",
                    )
                ],
                highlights=[],
            )
        )
        issue_ids = [issue["issue_id"] for issue in report["content_issues"]]

        self.assertNotIn("translation_title_proposition_missing", issue_ids)
        self.assertNotIn("translation_action_direction_missing", issue_ids)

    def test_agentive_increase_and_decrease_still_require_direction(self):
        cases = (
            ("SEC increases filing fees", "SEC调整申报费用", "increase"),
            ("Regulator raises capital requirements", "监管机构调整资本要求", "increase"),
            ("Authority reduces margin requirements", "主管机构调整保证金要求", "decrease"),
            ("Central bank cuts the policy rate", "中央银行调整政策利率", "decrease"),
        )
        for original, translated, action in cases:
            with self.subTest(original=original):
                report = self.evaluate(
                    weekly=payload(
                        items=[item(1, title_original=original, title_cn=translated)],
                        highlights=[],
                    )
                )
                self.assertTrue(any(
                    issue["issue_id"] == "translation_action_direction_missing"
                    and issue.get("evidence", {}).get("action") == action
                    for issue in report["content_issues"]
                ))

    def test_noun_form_policy_trends_remain_action_direction_sensitive(self):
        cases = (
            ("SEC Announces Increase in Filing Fees", "SEC宣布调整申报费用", "increase"),
            (
                "Regulator Approves Reduction in Margin Requirements",
                "监管机构批准调整保证金要求",
                "decrease",
            ),
            (
                "Authority Imposes an Increase in Capital Requirements",
                "主管机构实施资本要求调整",
                "increase",
            ),
            (
                "Central Bank Announces a Decrease in the Policy Rate",
                "中央银行宣布调整政策利率",
                "decrease",
            ),
        )
        for original, translated, action in cases:
            with self.subTest(original=original):
                report = self.evaluate(
                    weekly=payload(
                        items=[item(1, title_original=original, title_cn=translated)],
                        highlights=[],
                    )
                )
                self.assertTrue(any(
                    issue["issue_id"] == "translation_action_direction_missing"
                    and issue.get("evidence", {}).get("action") == action
                    for issue in report["content_issues"]
                ))

    def test_reporting_context_noun_form_trends_remain_descriptive(self):
        cases = (
            ("Statistics show an increase in issuance", "统计数据显示发行量增长"),
            ("Report reveals a decline in trading volume", "报告显示交易量下降"),
        )
        for original, translated in cases:
            with self.subTest(original=original):
                report = self.evaluate(
                    weekly=payload(
                        items=[item(1, title_original=original, title_cn=translated)],
                        highlights=[],
                    )
                )
                issue_ids = [issue["issue_id"] for issue in report["content_issues"]]
                self.assertNotIn("translation_title_proposition_missing", issue_ids)
                self.assertNotIn("translation_action_direction_missing", issue_ids)

    def test_summary_missing_descriptive_increase_is_nonblocking_warning(self):
        report = self.evaluate(
            weekly=payload(
                items=[
                    item(
                        1,
                        source="SEC",
                        summary_original=(
                            "SEC economic analysts published updated statistics covering key parts "
                            "of U.S. capital markets, including a notable increase in the number of "
                            "initial public offerings."
                        ),
                        summary_cn="SEC经济分析部门发布了更新的统计数据，涵盖美国资本市场的关键部分。",
                    )
                ],
                highlights=[],
            )
        )
        trend_issues = [
            issue for issue in report["content_issues"]
            if issue["issue_id"] == "translation_trend_proposition_missing"
        ]
        action_issues = [
            issue for issue in report["content_issues"]
            if issue["issue_id"] == "translation_action_direction_missing"
            and issue.get("evidence", {}).get("action") == "increase"
        ]

        self.assertEqual(len(trend_issues), 1)
        self.assertEqual(trend_issues[0]["severity"], WARNING)
        self.assertEqual(action_issues, [])

    def test_unresolved_hard_entity_remains_reviewable_and_fails_qa(self):
        weekly = payload(
            items=[
                item(
                    1,
                    source="Partior",
                    title_original="Partior launches a settlement platform",
                    title_cn="该公司推出结算平台",
                )
            ],
            highlights=[],
        )

        report = self.evaluate(weekly=weekly)

        self.assertEqual(weekly["items"][0]["title_cn"], "该公司推出结算平台")
        self.assertEqual(report["status"], FAIL)
        self.assertEqual(report["publish_recommendation"], "do_not_publish")
        self.assertIn(
            "translation_entity_alignment_failure",
            [issue["issue_id"] for issue in report["content_issues"]],
        )

    def test_mixed_review_artifact_with_finra_and_entity_failures_is_blocked(self):
        finra_original = (
            "Agreement establishes a pathway built on SEC-registered broker-dealer infrastructure "
            "through HashKey’s licensed exchange network. Prometheum Capital is an SEC-registered, "
            "FINRA member crypto asset custodian."
        )
        weekly = payload(
            items=[
                item(
                    1,
                    source="HashKey",
                    title_cn="HashKey与Prometheum达成合作",
                    summary_original=finra_original,
                    summary_cn="该协议通过HashKey持牌交易网络向合格国际投资者提供美国股票。",
                    translation_quality_issues=[
                        {
                            "issue_id": "translation_sanity_quality_failure",
                            "severity": "FAIL",
                            "evidence": {
                                "reason": "critical_term_missing:FINRA",
                                "field": "summary",
                                "source": "HashKey",
                            },
                        }
                    ],
                ),
                item(
                    2,
                    source="Partior",
                    title_original="Partior launches a settlement platform",
                    title_cn="该公司推出结算平台",
                ),
                item(3, title_cn="市场基础设施更新"),
            ],
            highlights=[],
        )

        report = self.evaluate(weekly=weekly)
        issue_ids = [issue["issue_id"] for issue in report["content_issues"]]
        sanity_reasons = [
            issue.get("evidence", {}).get("sanity_reason")
            for issue in report["content_issues"]
        ]

        self.assertEqual(len(weekly["items"]), 3)
        self.assertTrue(weekly["items"][0]["summary_cn"])
        self.assertEqual(report["status"], FAIL)
        self.assertEqual(report["publish_recommendation"], "do_not_publish")
        self.assertIn("critical_term_missing:FINRA", sanity_reasons)
        self.assertIn("translation_entity_alignment_failure", issue_ids)

    def test_artifact_entity_and_term_conflicts_fail_qa(self):
        records = [
            ("RepoClear updates collateral rules", "雷波克莱尔更新抵押品规则"),
            ("FTSE Russell announces index changes", "瑞士证券交易所 (FTSE Russell) 宣布指数调整"),
            ("ISS publishes a governance report", "国际空间站发布治理报告"),
            ("OSC publishes a capital markets update", "欧安组织发布资本市场更新"),
            ("Partior partners with LSEG", "企业与LSEG合作"),
            ("Gold-i launches a platform", "黄金-i推出平台"),
            ("Fiat and digital assets", "菲亚特与数字资产"),
            ("Spot market trading", "零点市场交易"),
            ("Digital asset custody support", "数字资产监管支持"),
            ("CCP Default Fund Contribution", "CCP默认基金贡献"),
        ]
        report = self.evaluate(
            weekly=payload(
                items=[item(index, title_original=original, title_cn=translated) for index, (original, translated) in enumerate(records, 1)],
                highlights=[],
            )
        )
        issue_ids = [issue["issue_id"] for issue in report["content_issues"]]
        self.assertIn("translation_entity_conflict", issue_ids)
        self.assertIn("translation_material_term_conflict", issue_ids)

    def test_impossible_translated_date_fails_qa(self):
        report = self.evaluate(
            weekly=payload(
                items=[item(1, title_original="Rulebook amendment history", title_cn="规则修订历史：2026年13月42日")],
                highlights=[],
            )
        )
        self.assertIn("translation_date_corruption", [issue["issue_id"] for issue in report["content_issues"]])

    def test_allow_action_accepts_licensed_and_permitted_business_language(self):
        original = "Within the scope of its licensed and permitted business, the exchange will provide custody support."
        translated = "该交易所在经营许可和许可的业务范围内提供托管支持。"
        report = self.evaluate(
            weekly=payload(items=[item(1, summary_original=original, summary_cn=translated)], highlights=[])
        )
        allow_issues = [
            issue for issue in report["content_issues"]
            if issue["issue_id"] == "translation_action_direction_missing"
            and issue.get("evidence", {}).get("action") == "allow"
        ]
        self.assertEqual(allow_issues, [])

    def test_allow_action_still_fails_when_permission_meaning_is_missing(self):
        original = "Within the scope of its licensed and permitted business, the exchange will provide custody support."
        translated = "该交易所提供托管支持。"
        report = self.evaluate(
            weekly=payload(items=[item(1, summary_original=original, summary_cn=translated)], highlights=[])
        )
        self.assertTrue(any(
            issue["issue_id"] == "translation_action_direction_missing"
            and issue.get("evidence", {}).get("action") == "allow"
            for issue in report["content_issues"]
        ))


class QAPolicyTests(unittest.TestCase):
    def test_policy_source_ids_exist_in_sources_json(self):
        policy = load_policy()
        sources = load_sources()
        source_ids = {source.get("id") for source in sources}
        missing = sorted(set(policy.get("sources", {})) - source_ids)
        self.assertEqual(missing, [])

    def test_policy_json_can_be_loaded_from_custom_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "qa_policy.json"
            path.write_text(json.dumps(base_policy()), encoding="utf-8")
            self.assertIn("sources", load_policy(path))

    def test_run_qa_report_includes_artifact_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_path = root / "weekly.json"
            status_path = root / "source_status.json"
            policy_path = root / "qa_policy.json"
            sources_path = root / "sources.json"
            weekly_path.write_text(json.dumps(payload()), encoding="utf-8")
            status_path.write_text(json.dumps([source_status("HEALTHY")]), encoding="utf-8")
            policy_path.write_text(json.dumps(base_policy()), encoding="utf-8")
            sources_path.write_text("[]", encoding="utf-8")

            result = run_qa(
                weekly_data_path=weekly_path,
                source_status_path=status_path,
                policy_path=policy_path,
                sources_path=sources_path,
                write_report_files=False,
            )

            artifacts = result["report"]["input_artifacts"]
            self.assertEqual(artifacts["weekly_data"], str(weekly_path))
            self.assertEqual(artifacts["weekly_data_sha256"], file_sha256(weekly_path))
            self.assertEqual(artifacts["source_status"], str(status_path))
            self.assertEqual(artifacts["source_status_sha256"], file_sha256(status_path))

    def test_run_qa_writes_report_files_to_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_path = root / "weekly.json"
            status_path = root / "source_status.json"
            policy_path = root / "qa_policy.json"
            sources_path = root / "sources.json"
            output_dir = root / "ci" / "20200101"
            weekly_path.write_text(json.dumps(payload()), encoding="utf-8")
            status_path.write_text(json.dumps([source_status("HEALTHY")]), encoding="utf-8")
            policy_path.write_text(json.dumps(base_policy()), encoding="utf-8")
            sources_path.write_text("[]", encoding="utf-8")

            result = run_qa(
                weekly_data_path=weekly_path,
                source_status_path=status_path,
                policy_path=policy_path,
                sources_path=sources_path,
                output_dir=output_dir,
            )

            self.assertEqual(result["json_path"].parent, output_dir)
            self.assertEqual(result["md_path"].parent, output_dir)
            self.assertEqual(result["report"]["translation_mode"], "bilingual")


if __name__ == "__main__":
    unittest.main()
