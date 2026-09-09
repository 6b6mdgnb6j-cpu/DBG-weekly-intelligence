import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from automation_pipeline import (
    AutomationValidationError,
    artifact_filename,
    artifact_path,
    publish_allowed_by_qa,
    review_artifact_name,
    review_artifact_ready,
    summary_highlight_count,
    translation_preflight,
    validate_bilingual_artifacts,
    validate_manifest,
    validate_published_diff_paths,
    validate_source_run_metadata,
    write_review_manifest,
    workflow_step_status,
)
from crawler.translator import LocalNLLBProvider, TitleTranslator, TranslationUnavailableError
from qa_gate import file_sha256


WEEK = "2026-01-05"
WEEK_END = "2026-01-11"
RUN_ID = "123456"
SHA = "abc123def456"


def weekly_payload(**overrides):
    payload = {
        "week_start": WEEK,
        "week_end": WEEK_END,
        "translation_mode": "bilingual",
        "source_count": 3,
        "registered_source_count": 3,
        "item_count": 1,
        "items": [
            {
                "date": WEEK,
                "title_original": "Market infrastructure update",
                "title_original_lang": "en",
                "title_en": "Market infrastructure update",
                "title_cn": "市场基础设施更新",
                "summary": "A clearing and settlement update.",
                "summary_original": "A clearing and settlement update.",
                "summary_original_lang": "en",
                "summary_en": "A clearing and settlement update.",
                "summary_cn": "一项清算和结算更新。",
                "url": "https://example.test/news",
                "source": "Source",
                "category": "Macro",
            }
        ],
        "highlights": [{"title_original": "Market infrastructure update"}],
    }
    payload.update(overrides)
    return payload


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def make_bundle(root, weekly_overrides=None, qa_overrides=None):
    root = Path(root)
    weekly = artifact_path(root, "weekly_data", WEEK)
    source_status = artifact_path(root, "source_status", WEEK)
    qa = artifact_path(root, "qa_report", WEEK)
    qa_md = artifact_path(root, "qa_markdown", WEEK)
    html = artifact_path(root, "html", WEEK)

    payload = weekly_payload(**(weekly_overrides or {}))
    write_json(weekly, payload)
    write_json(source_status, [{"source": "Source", "status": "success", "target_period_reached": True}])
    qa_payload = {
        "week_start": payload["week_start"],
        "week_end": payload["week_end"],
        "translation_mode": payload["translation_mode"],
        "status": "PASS",
        "summary": {"final_items": payload["item_count"], "highlights": len(payload["highlights"])},
        "checks": [],
        "input_artifacts": {
            "weekly_data": str(weekly),
            "weekly_data_sha256": file_sha256(weekly),
            "source_status": str(source_status),
            "source_status_sha256": file_sha256(source_status),
        },
    }
    qa_payload.update(qa_overrides or {})
    write_json(qa, qa_payload)
    qa_md.write_text("# QA\n", encoding="utf-8")
    html.write_text("<html>Market infrastructure update</html>\n", encoding="utf-8")
    manifest = write_review_manifest(root, WEEK, SHA, RUN_ID)
    return root, manifest


class AutomationPipelineContractTests(unittest.TestCase):
    def test_review_artifact_name_is_week_scoped(self):
        self.assertEqual(review_artifact_name(WEEK), "weekly-report-review-2026-01-05")
        self.assertEqual(artifact_filename("manifest", WEEK), "review_manifest_20260105.json")

    def test_valid_pass_bilingual_bundle_is_publish_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp)
            manifest = validate_manifest(tmp, WEEK, source_run_id=RUN_ID, generation_sha=SHA, current_main_sha=SHA)
            self.assertTrue(publish_allowed_by_qa(manifest["qa_status"]))

    def test_warning_without_approval_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp, qa_overrides={"status": "WARNING"})
            manifest = validate_manifest(tmp, WEEK, source_run_id=RUN_ID, generation_sha=SHA, current_main_sha=SHA)
            with self.assertRaises(AutomationValidationError):
                publish_allowed_by_qa(manifest["qa_status"], approve_warning=False)

    def test_warning_with_approval_is_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp, qa_overrides={"status": "WARNING"})
            manifest = validate_manifest(tmp, WEEK, source_run_id=RUN_ID, generation_sha=SHA, current_main_sha=SHA)
            self.assertTrue(publish_allowed_by_qa(manifest["qa_status"], approve_warning=True))

    def test_fail_blocks_even_with_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp, qa_overrides={"status": "FAIL"})
            manifest = validate_manifest(tmp, WEEK, source_run_id=RUN_ID, generation_sha=SHA, current_main_sha=SHA)
            with self.assertRaises(AutomationValidationError):
                publish_allowed_by_qa(manifest["qa_status"], approve_warning=True)

    def test_no_translate_artifact_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AutomationValidationError):
                make_bundle(tmp, weekly_overrides={"translation_mode": "no_translate"})

    def test_missing_title_cn_fails_before_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AutomationValidationError):
                make_bundle(tmp, weekly_overrides={"items": [dict(weekly_payload()["items"][0], title_cn="")]})

    def test_missing_summary_cn_fails_before_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = dict(weekly_payload()["items"][0])
            item["summary_cn"] = ""
            with self.assertRaises(AutomationValidationError):
                make_bundle(tmp, weekly_overrides={"items": [item]})

    def test_empty_original_summary_allows_empty_summary_cn(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = dict(weekly_payload()["items"][0])
            item["summary"] = ""
            item["summary_original"] = ""
            item["summary_cn"] = ""
            make_bundle(tmp, weekly_overrides={"items": [item]})
            self.assertTrue(validate_bilingual_artifacts(tmp, WEEK))

    def test_weekly_data_sha_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp)
            weekly = artifact_path(tmp, "weekly_data", WEEK)
            payload = json.loads(weekly.read_text(encoding="utf-8"))
            payload["item_count"] = 2
            write_json(weekly, payload)
            with self.assertRaises(AutomationValidationError):
                validate_manifest(tmp, WEEK, source_run_id=RUN_ID, generation_sha=SHA, current_main_sha=SHA)

    def test_manifest_artifact_hash_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp)
            artifact_path(tmp, "html", WEEK).write_text("<html>changed</html>\n", encoding="utf-8")
            with self.assertRaises(AutomationValidationError):
                validate_manifest(tmp, WEEK, source_run_id=RUN_ID, generation_sha=SHA, current_main_sha=SHA)

    def test_wrong_week_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp)
            with self.assertRaises(AutomationValidationError):
                validate_manifest(tmp, "2026-01-12", source_run_id=RUN_ID, generation_sha=SHA, current_main_sha=SHA)

    def test_wrong_generation_run_id_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp)
            with self.assertRaises(AutomationValidationError):
                validate_manifest(tmp, WEEK, source_run_id="999", generation_sha=SHA, current_main_sha=SHA)

    def test_stale_generation_sha_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp)
            with self.assertRaises(AutomationValidationError):
                validate_manifest(tmp, WEEK, source_run_id=RUN_ID, generation_sha=SHA, current_main_sha="newsha")

    def test_missing_manifest_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, manifest = make_bundle(tmp)
            manifest.unlink()
            with self.assertRaises(AutomationValidationError):
                validate_manifest(tmp, WEEK)

    def test_missing_artifact_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp)
            artifact_path(tmp, "source_status", WEEK).unlink()
            with self.assertRaises(AutomationValidationError):
                validate_manifest(tmp, WEEK)

    def test_malformed_qa_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp)
            qa = artifact_path(tmp, "qa_report", WEEK)
            qa.write_text("{bad", encoding="utf-8")
            with self.assertRaises(AutomationValidationError):
                validate_manifest(tmp, WEEK)

    def test_source_run_metadata_must_be_production_main_success(self):
        good = {
            "repository": "owner/repo",
            "workflow_name": "DBG Weekly Report - Production",
            "branch": "main",
            "conclusion": "success",
            "head_sha": SHA,
        }
        self.assertTrue(validate_source_run_metadata(good, "owner/repo"))
        for override in (
            {"repository": "other/repo"},
            {"workflow_name": "DBG Weekly Report - Phase 1"},
            {"branch": "feature"},
            {"conclusion": "failure"},
            {"head_sha": ""},
        ):
            bad = dict(good)
            bad.update(override)
            with self.subTest(override=override):
                with self.assertRaises(AutomationValidationError):
                    validate_source_run_metadata(bad, "owner/repo")

    def test_published_diff_path_guard(self):
        self.assertTrue(validate_published_diff_paths(["published/latest.json", "published/archive/weekly_20260105.json"]))
        with self.assertRaises(AutomationValidationError):
            validate_published_diff_paths(["published/latest.json", "crawler/content_filter.py"])

    def test_translation_preflight_success_allows_generation(self):
        class ReadyProvider:
            def translate(self, text, source_lang="en", target_lang="zh"):
                return "Clearstream 结算更新"

        with patch.dict(sys.modules, {"torch": types.SimpleNamespace(), "transformers": types.SimpleNamespace()}):
            self.assertTrue(translation_preflight(provider_factory=ReadyProvider, attempts=1, sleep_seconds=0))

    def test_translation_preflight_download_unavailable_blocks_before_generation(self):
        class BrokenProvider:
            load_error = "model download unavailable"

            def translate(self, text, source_lang="en", target_lang="zh"):
                return ""

        with patch.dict(sys.modules, {"torch": types.SimpleNamespace(), "transformers": types.SimpleNamespace()}):
            with self.assertRaises(AutomationValidationError):
                translation_preflight(provider_factory=BrokenProvider, attempts=2, sleep_seconds=0)

    def test_strict_translation_provider_unavailable_hard_fails(self):
        class EmptyProvider:
            model_name = "test-model"
            load_error = "model unavailable"

            def translate(self, text, source_lang="en", target_lang="zh"):
                return ""

        translator = TitleTranslator(enabled=True, provider=EmptyProvider(), strict=True)
        with self.assertRaises(TranslationUnavailableError):
            translator.translate([{"title_original": "Market infrastructure update", "summary": "", "source": "Source"}])

    def test_non_strict_translation_provider_unavailable_keeps_local_fallback(self):
        class EmptyProvider:
            model_name = "test-model"
            load_error = "model unavailable"

            def translate(self, text, source_lang="en", target_lang="zh"):
                return ""

        translator = TitleTranslator(enabled=True, provider=EmptyProvider(), strict=False)
        translated = translator.translate([{"title_original": "Market infrastructure update", "summary": "", "source": "Source"}])
        self.assertEqual(translated[0]["title_cn"], "")

    def test_local_provider_load_failure_is_not_retried_per_field(self):
        calls = {"tokenizer": 0}

        class BrokenTokenizer:
            @staticmethod
            def from_pretrained(*args, **kwargs):
                calls["tokenizer"] += 1
                raise OSError("cached files unavailable")

        fake_transformers = types.SimpleNamespace(
            AutoTokenizer=BrokenTokenizer,
            AutoModelForSeq2SeqLM=types.SimpleNamespace(from_pretrained=lambda *args, **kwargs: None),
        )
        provider = LocalNLLBProvider(local_files_only=True)
        with patch.dict(sys.modules, {"transformers": fake_transformers}):
            self.assertEqual(provider.translate("First title"), "")
            self.assertEqual(provider.translate("Second title"), "")
        self.assertEqual(calls["tokenizer"], 1)

    def test_summary_highlight_count_uses_qa_summary_when_weekly_has_no_highlights(self):
        weekly = {"highlights": []}
        qa = {"summary": {"highlights": 5}}
        self.assertEqual(summary_highlight_count(weekly, qa), 5)

    def test_review_artifact_ready_requires_full_bilingual_bundle_success(self):
        self.assertTrue(review_artifact_ready("true", "0", "0", "0"))
        self.assertFalse(review_artifact_ready("false", "0", "0", "0"))
        self.assertFalse(review_artifact_ready("true", "4", "0", "0"))
        self.assertFalse(review_artifact_ready("true", "0", "4", "0"))

    def test_workflow_step_status_distinguishes_not_run_from_failed(self):
        self.assertEqual(workflow_step_status("success", "0"), "PASS")
        self.assertEqual(workflow_step_status("skipped", ""), "NOT RUN")
        self.assertEqual(workflow_step_status("success", ""), "NOT RUN")
        self.assertEqual(workflow_step_status("success", "4"), "FAILED")

    def test_production_workflow_gates_require_outcome_and_exit_code(self):
        workflow = Path(".github/workflows/weekly-report-production.yml").read_text(encoding="utf-8")
        expected_gates = [
            "steps.tests.outcome == 'success' && steps.tests.outputs.exit_code == '0'",
            "steps.compile.outcome == 'success' && steps.compile.outputs.exit_code == '0'",
            "steps.translation_preflight.outcome == 'success' && steps.translation_preflight.outputs.exit_code == '0'",
            "steps.weekly.outcome == 'success' && steps.weekly.outputs.exit_code == '0'",
            "steps.bilingual_validation.outcome == 'success' && steps.bilingual_validation.outputs.exit_code == '0'",
            "steps.manifest.outcome == 'success' && steps.manifest.outputs.exit_code == '0'",
            "steps.bundle_validation.outcome == 'success' && steps.bundle_validation.outputs.exit_code == '0'",
        ]
        for gate in expected_gates:
            with self.subTest(gate=gate):
                self.assertIn(gate, workflow)

    def test_review_upload_requires_bundle_validation_success_and_exit_zero(self):
        workflow = Path(".github/workflows/weekly-report-production.yml").read_text(encoding="utf-8")
        self.assertIn(
            "if: steps.bundle_validation.outcome == 'success' && steps.bundle_validation.outputs.exit_code == '0'",
            workflow,
        )

    def test_summary_reports_not_run_for_skipped_downstream_steps(self):
        self.assertEqual(workflow_step_status("skipped", ""), "NOT RUN")


if __name__ == "__main__":
    unittest.main()
