import argparse
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import run_weekly
from crawler.translator import TranslationUnavailableError
from qa_gate import QAExecutionError


def fake_collect_result(tmp_path):
    weekly = tmp_path / "weekly_data_20200101.json"
    status = tmp_path / "source_status_20200101.json"
    html = tmp_path / "weekly_report_20200101.html"
    raw = tmp_path / "raw.json"
    log = tmp_path / "collect.log"
    rejected = tmp_path / "relevance_rejected.json"
    for path in (weekly, status, html, raw, log, rejected):
        path.write_text("artifact", encoding="utf-8")
    return {
        "week_start": "2020-01-01",
        "week_end": "2020-01-07",
        "source_count": 5,
        "registered_source_count": 5,
        "items": [{"title_original": "Market update"}],
        "raw_path": raw,
        "log_path": log,
        "source_status_path": status,
        "relevance_rejected_path": rejected,
        "pipeline_counts": {
            "candidates": 1,
            "candidates_scanned": 1,
            "list_items_with_date": 1,
            "detail_pages_requested": 1,
            "valid_dates": 1,
            "within_target_week": 1,
            "after_relevance_filter": 1,
            "after_dedupe": 1,
            "same_event_clustered_count": 0,
            "after_same_event_cluster": 1,
            "final_weekly_items": 1,
        },
        "source_status_summary": {"success": 1},
        "_weekly_path": weekly,
        "_html_path": html,
    }


def qa_result(status="PASS", exit_code=0):
    return {
        "status": status,
        "exit_code": exit_code,
        "report": {
            "checks": [],
            "known_gaps": [],
        },
        "json_path": Path("output/qa_report_20200101.json"),
        "md_path": Path("output/qa_report_20200101.md"),
        "blocking_count": 0,
        "warning_count": 0 if status == "PASS" else 1,
        "known_gap_count": 0,
        "publish_recommendation": "ready_for_manual_review" if status == "PASS" else "manual_review_required",
    }


class RunWeeklyIntegrationTests(unittest.TestCase):
    def args(self, **overrides):
        defaults = {
            "start": "2020-01-01",
            "no_translate": False,
            "skip_qa": False,
            "fail_on_warning": False,
            "output_dir": "output",
            "require_translation": False,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def run_with_mocks(self, tmp_path, qa=None, qa_side_effect=None, args=None):
        result = fake_collect_result(tmp_path)
        qa_mock = Mock(return_value=qa or qa_result(), side_effect=qa_side_effect)
        with patch.object(run_weekly, "collect_week", return_value=result) as collect_mock, patch.object(
            run_weekly, "render_report", return_value=(result["_html_path"], result["_weekly_path"], 5)
        ) as render_mock, patch.object(run_weekly, "run_qa", qa_mock), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            code = run_weekly.run_weekly(args or self.args())
        return code, result, collect_mock, render_mock, qa_mock, stdout.getvalue()

    def test_generation_completed_and_qa_pass_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, _, _, qa_mock, output = self.run_with_mocks(Path(tmp), qa=qa_result("PASS", 0))
        self.assertEqual(code, 0)
        self.assertIn("QA:", output)
        self.assertIn("Status: PASS", output)
        qa_mock.assert_called_once()

    def test_qa_warning_returns_zero_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, _, _, _, output = self.run_with_mocks(Path(tmp), qa=qa_result("WARNING", 0))
        self.assertEqual(code, 0)
        self.assertIn("Status: WARNING", output)

    def test_qa_fail_returns_two(self):
        result = qa_result("FAIL", 2)
        result["blocking_count"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            code, artifacts, _, _, _, output = self.run_with_mocks(Path(tmp), qa=result)
            self.assertTrue(artifacts["_weekly_path"].exists())
            self.assertTrue(artifacts["source_status_path"].exists())
            self.assertTrue(artifacts["_html_path"].exists())
        self.assertEqual(code, 2)
        self.assertIn("Status: FAIL", output)
        self.assertIn("Weekly artifacts were preserved.", output)

    def test_qa_execution_exception_returns_nonzero_and_preserves_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, artifacts, _, _, _, output = self.run_with_mocks(
                Path(tmp),
                qa_side_effect=QAExecutionError("missing source_status"),
            )
            self.assertTrue(artifacts["_weekly_path"].exists())
            self.assertTrue(artifacts["source_status_path"].exists())
        self.assertEqual(code, 3)
        self.assertIn("QA EXECUTION ERROR", output)

    def test_unexpected_qa_exception_returns_nonzero_and_preserves_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, artifacts, _, _, _, output = self.run_with_mocks(
                Path(tmp),
                qa_side_effect=RuntimeError("corrupt qa payload"),
            )
            self.assertTrue(artifacts["_weekly_path"].exists())
            self.assertTrue(artifacts["source_status_path"].exists())
        self.assertEqual(code, 3)
        self.assertIn("QA EXECUTION ERROR", output)

    def test_skip_qa_does_not_call_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, _, _, qa_mock, output = self.run_with_mocks(Path(tmp), args=self.args(skip_qa=True))
        self.assertEqual(code, 0)
        qa_mock.assert_not_called()
        self.assertIn("QA: skipped by user", output)

    def test_fail_on_warning_returns_nonzero_when_qa_requests_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, _, _, qa_mock, _ = self.run_with_mocks(
                Path(tmp),
                qa=qa_result("WARNING", 1),
                args=self.args(fail_on_warning=True),
            )
        self.assertEqual(code, 1)
        self.assertTrue(qa_mock.call_args.kwargs["fail_on_warning"])

    def test_no_translate_does_not_skip_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, collect_mock, _, qa_mock, _ = self.run_with_mocks(
                Path(tmp),
                args=self.args(no_translate=True),
            )
        self.assertEqual(code, 0)
        collect_mock.assert_called_once_with(
            start_arg="2020-01-01",
            translate=False,
            output_dir="output",
            require_translation=False,
        )
        qa_mock.assert_called_once()

    def test_output_dir_is_passed_to_generation_render_and_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = str(Path(tmp) / "ci" / "20200101")
            code, _, collect_mock, render_mock, qa_mock, _ = self.run_with_mocks(
                Path(tmp),
                args=self.args(output_dir=output_dir),
        )
        self.assertEqual(code, 0)
        collect_mock.assert_called_once_with(
            start_arg="2020-01-01",
            translate=True,
            output_dir=output_dir,
            require_translation=False,
        )
        render_mock.assert_called_once_with("2020-01-01", output_dir=output_dir)
        self.assertEqual(qa_mock.call_args.kwargs["output_dir"], output_dir)

    def test_require_translation_failure_returns_nonzero_before_render_and_qa(self):
        qa_mock = Mock(return_value=qa_result())
        with patch.object(
            run_weekly,
            "collect_week",
            side_effect=TranslationUnavailableError("model unavailable"),
        ) as collect_mock, patch.object(run_weekly, "render_report") as render_mock, patch.object(
            run_weekly, "run_qa", qa_mock
        ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            code = run_weekly.run_weekly(self.args(require_translation=True))

        self.assertEqual(code, 4)
        collect_mock.assert_called_once_with(
            start_arg="2020-01-01",
            translate=True,
            output_dir="output",
            require_translation=True,
        )
        render_mock.assert_not_called()
        qa_mock.assert_not_called()
        self.assertIn("TRANSLATION REQUIRED BUT UNAVAILABLE", stdout.getvalue())

    def test_qa_report_paths_are_surfaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, _, _, _, output = self.run_with_mocks(Path(tmp), qa=qa_result())
        self.assertIn("QA JSON: output/qa_report_20200101.json", output)
        self.assertIn("QA Markdown: output/qa_report_20200101.md", output)

    def test_run_weekly_does_not_call_publish(self):
        self.assertFalse(hasattr(run_weekly, "publish_weekly"))


class RunWeeklyCLITests(unittest.TestCase):
    def test_parse_start_flag(self):
        with patch("sys.argv", ["run_weekly.py", "--start", "2020-01-01"]):
            args = run_weekly.parse_args()
        self.assertEqual(args.start, "2020-01-01")

    def test_parse_skip_qa_flag(self):
        with patch("sys.argv", ["run_weekly.py", "--skip-qa"]):
            args = run_weekly.parse_args()
        self.assertTrue(args.skip_qa)

    def test_parse_no_translate_flag(self):
        with patch("sys.argv", ["run_weekly.py", "--no-translate"]):
            args = run_weekly.parse_args()
        self.assertTrue(args.no_translate)

    def test_parse_fail_on_warning_flag(self):
        with patch("sys.argv", ["run_weekly.py", "--fail-on-warning"]):
            args = run_weekly.parse_args()
        self.assertTrue(args.fail_on_warning)

    def test_parse_output_dir_flag(self):
        with patch("sys.argv", ["run_weekly.py", "--output-dir", "output/ci/20200101"]):
            args = run_weekly.parse_args()
        self.assertEqual(args.output_dir, "output/ci/20200101")


if __name__ == "__main__":
    unittest.main()
