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
