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
