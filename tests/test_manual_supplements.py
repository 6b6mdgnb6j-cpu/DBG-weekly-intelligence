import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import snapshot_replay
from automation_pipeline import AutomationValidationError, validate_bilingual_artifacts, validate_manifest, write_review_manifest
from crawler.manual_supplements import ManualSupplementError, canonical_url, load_supplements, record_hash, supplement_id
from crawler.manual_translations import apply_approved_overrides_with_report, approved_payload, stable_item_id, original_sha256
from qa_gate import run_qa


WEEK = "2026-10-05"
DRAFT = Path("manual_supplements/drafts/weekly_20261005.json")


class ManualSupplementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = json.loads(DRAFT.read_text(encoding="utf-8"))
        self.data["approval_status"] = "APPROVED"
        self.data["approval"] = {"reviewed_by": "unit-test fixture only", "approved_at": "2026-10-12T00:00:00Z"}
        self.rehash()

    def rehash(self):
        for record in self.data["records"]:
            record["approval_status"] = self.data["approval_status"]
            record["supplement_id"] = supplement_id(record)
            record["content_sha256"] = record_hash(record)

    def document(self, directory="approved"):
        path = self.root / directory / "weekly_20261005.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def load(self, existing=()):
        path, digest = self.document()
        return load_supplements(path, digest, WEEK, existing)

    def replay(self, supplements=True):
        # 39 originals with 57 exact field approvals exercise preservation at real baseline size.
        items = [{
            "date": WEEK, "source": "Fixture Source", "url": f"https://example.test/item/{n}",
            "category": "Macro", "subcategory": "国际组织", "official": True,
            "priority": 1, "relevance_score": 8,
            "title_original": f"Clearing infrastructure rule update {n}", "title_original_lang": "en",
            "title_cn": f"清算基础设施规则更新{n}", "title_en": f"Clearing infrastructure rule update {n}",
            "summary": "Clearing rules change.", "summary_original": "Clearing rules change.",
            "summary_original_lang": "en", "summary_en": "Clearing rules change.", "summary_cn": "清算规则调整。",
        } for n in range(39)]
        registry = json.loads(Path("config/sources.json").read_text(encoding="utf-8"))
        statuses = [{"source_id": source["id"], "source": source["name"],
                     "status": "true_no_updates", "target_period_reached": True}
                    for source in registry if source.get("enabled")]
        for status in statuses:
            if status["source_id"] in {"SRC-150", "SRC-186"}:
                status.update(status="network_error" if status["source_id"] == "SRC-150" else "blocked",
                              target_period_reached=False)
        weekly = {"week_start": WEEK, "week_end": "2026-10-11", "translation_mode": "bilingual",
                  "source_count": len(statuses), "registered_source_count": len(registry), "item_count": 39, "items": items}
        archive = self.root / "snapshot.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("weekly_data_20261005.json", json.dumps(weekly))
            bundle.writestr("source_status_20261005.json", json.dumps(statuses))
        original_zip = archive.read_bytes()
        rows = []
        for n, item in enumerate(items):
            for field in ("title", "summary") if n < 18 else ("title",):
                original = item[field + "_original"]
                rows.append({"item_id": stable_item_id(item, field, original), "source": item["source"],
                             "date": item["date"], "url": item["url"], "field": field,
                             "original_sha256": original_sha256(original), "manual_translation": item[field + "_cn"]})
        approvals = self.root / "translations.json"
        approvals.write_text(json.dumps(approved_payload(rows, WEEK)), encoding="utf-8")
        extra = {}
        if supplements:
            path, digest = self.document()
            extra = {"supplement_file": path, "supplement_sha256": digest}
        out = self.root / ("output" if supplements else "baseline")
        result = snapshot_replay.replay_snapshot(
            archive, hashlib.sha256(original_zip).hexdigest(), WEEK, out, approvals,
            "46", "collection-sha", "117", "original-debug", "99", "generation-sha", **extra,
        )
        self.assertEqual(archive.read_bytes(), original_zip)
        self.assertEqual(approvals.read_text(), json.dumps(approved_payload(rows, WEEK)))
        reviewed_baseline = copy.deepcopy(weekly)
        apply_approved_overrides_with_report(reviewed_baseline, approved_payload(rows, WEEK))
        return result, out, reviewed_baseline, statuses

    def test_four_approved_supplements_and_existing_39_items_57_translations_preserved(self):
        result, out, original, statuses = self.replay()
        weekly = json.loads((out / "weekly_data_20261005.json").read_text())
        self.assertEqual(weekly["items"][:39], original["items"][:39])
        self.assertEqual(len(weekly["items"]), 43)
        self.assertEqual({key: len(value) for key, value in result["overrides"].items()},
                         {"applied": 57, "absent": 0, "identity_hash_conflict": 0, "ambiguous": 0})
        self.assertEqual(json.loads((out / "source_status_20261005.json").read_text()), statuses)
        self.assertEqual((out / "source_status_20261005.json").read_bytes(), json.dumps(statuses).encode())
        self.assertEqual(result["qa"]["blocking_count"], 0)
        self.assertTrue(any(c["id"] == "unexpected_source_failures" and c["result"] == "WARNING"
                            for c in result["qa"]["report"]["checks"]))
        validate_bilingual_artifacts(out, WEEK)
        manifest = validate_manifest(out, WEEK, source_run_id="99", generation_sha="generation-sha", current_main_sha="generation-sha")
        self.assertEqual(manifest["snapshot_provenance"]["collection"]["run_id"], "46")
        self.assertEqual(manifest["generation_run_id"], "99")
        self.assertEqual(manifest["snapshot_provenance"]["editorial_supplements"]["inserted_count"], 4)

    def test_no_explicit_file_does_not_consume_existing_draft(self):
        _, out, original, _ = self.replay(supplements=False)
        weekly = json.loads((out / "weekly_data_20261005.json").read_text())
        self.assertEqual(weekly["items"], original["items"])
        self.assertFalse((out / "editorial_supplements_20261005.json").exists())

    def test_source_health_warnings_identical_with_and_without_supplements(self):
        baseline, _, _, _ = self.replay(supplements=False)
        supplemented, _, _, _ = self.replay()
        for key in ("unexpected_source_failures", "retry_hotspots"):
            before = next(c for c in baseline["qa"]["report"]["checks"] if c["id"] == key)
            after = next(c for c in supplemented["qa"]["report"]["checks"] if c["id"] == key)
            self.assertEqual(before, after)

    def test_digest_flag_without_file_rejected(self):
        with self.assertRaisesRegex(snapshot_replay.SnapshotReplayError, "supplied together"):
            snapshot_replay.replay_snapshot(self.root / "missing.zip", "0" * 64, WEEK,
                                           self.root / "out", self.root / "translations.json",
                                           "46", "old", "117", "debug", "99", "new", supplement_sha256="0" * 64)

    def test_draft_document_rejected(self):
        self.data["approval_status"] = "DRAFT"
        self.rehash()
        with self.assertRaisesRegex(ManualSupplementError, "approval"):
            self.load()

    def test_draft_directory_rejected_even_when_document_marked_approved(self):
        path, digest = self.document("drafts")
        with self.assertRaisesRegex(ManualSupplementError, "draft"):
            load_supplements(path, digest, WEEK, [])

    def test_unapproved_record_rejected(self):
        self.data["records"][0]["approval_status"] = "DRAFT"
        with self.assertRaisesRegex(ManualSupplementError, "not approved"):
            self.load()

    def test_missing_approval_metadata_rejected(self):
        self.data["approval"] = {}
        with self.assertRaisesRegex(ManualSupplementError, "approval"):
            self.load()

    def test_missing_explicit_file_rejected_without_output(self):
        with self.assertRaises(FileNotFoundError):
            load_supplements(self.root / "missing.json", "0" * 64, WEEK, [])
        self.assertFalse((self.root / "output").exists())

    def test_duplicate_url_rejected(self):
        record = self.data["records"][0]
        with self.assertRaisesRegex(ManualSupplementError, "duplicate"):
            self.load([{"url": record["url"]}])

    def test_duplicate_canonical_url_rejected(self):
        record = self.data["records"][0]
        with self.assertRaisesRegex(ManualSupplementError, "canonical_url"):
            self.load([{"url": record["url"] + "?utm_source=test#top"}])

    def test_distinct_urls_keep_meaningful_query_and_escaped_path_differences(self):
        self.assertNotEqual(canonical_url("https://ir.theice.com/article?id=1"),
                            canonical_url("https://ir.theice.com/article?id=2"))
        self.assertNotEqual(canonical_url("https://ir.theice.com/a%2Fb"),
                            canonical_url("https://ir.theice.com/a/b"))
        self.assertEqual(canonical_url("https://ir.theice.com/index%2Ephp/article/"),
                         canonical_url("https://ir.theice.com/index.php/article"))

    def test_duplicate_title_and_same_event_rejected(self):
        record = self.data["records"][0]
        with self.assertRaisesRegex(ManualSupplementError, "same_source"):
            self.load([{"url": "https://ir.theice.com/other", "source": record["source_name"],
                        "date": record["publication_date"], "title_original": record["title_en"],
                        "summary_original": record["summary_en"]}])

    def test_two_distinct_same_day_ice_events_preserved(self):
        items, _ = self.load()
        self.assertNotEqual(items[0]["url"], items[1]["url"])
        self.assertEqual(items[0]["date"], items[1]["date"])

    def test_duplicate_supplement_records_rejected(self):
        self.data["records"].append(copy.deepcopy(self.data["records"][0]))
        with self.assertRaisesRegex(ManualSupplementError, "duplicate"):
            self.load()

    def test_wrong_document_week_rejected(self):
        self.data["week_start"] = "2026-09-28"
        with self.assertRaisesRegex(ManualSupplementError, "week"):
            self.load()

    def test_wrong_publication_week_rejected(self):
        record = self.data["records"][0]
        record["publication_date"] = "2026-09-28"
        self.rehash()
        with self.assertRaisesRegex(ManualSupplementError, "outside target week"):
            self.load()

    def test_unknown_registry_source_rejected(self):
        self.data["records"][0]["source_id"] = "SRC-999"
        self.rehash()
        with self.assertRaisesRegex(ManualSupplementError, "registered official source"):
            self.load()

    def test_disabled_registry_source_rejected(self):
        registry = json.loads(Path("config/sources.json").read_text())
        for source in registry:
            if source["id"] == "SRC-150":
                source["enabled"] = False
        path = self.root / "sources.json"
        path.write_text(json.dumps(registry))
        document, digest = self.document()
        with self.assertRaisesRegex(ManualSupplementError, "registered official source"):
            load_supplements(document, digest, WEEK, [], sources_path=path)

    def test_registry_metadata_mismatch_rejected(self):
        self.data["records"][0]["source_name"] = "Different organization"
        self.rehash()
        with self.assertRaisesRegex(ManualSupplementError, "registry metadata"):
            self.load()

    def test_unofficial_url_rejected(self):
        record = self.data["records"][0]
        record["url"] = "https://example.test/article"
        record["canonical_url"] = canonical_url(record["url"])
        self.rehash()
        with self.assertRaisesRegex(ManualSupplementError, "official domains"):
            self.load()

    def test_missing_source_verification_rejected(self):
        self.data["records"][0].pop("source_verification")
        self.rehash()
        with self.assertRaisesRegex(ManualSupplementError, "source verification"):
            self.load()

    def test_file_hash_mismatch_rejected(self):
        path, _ = self.document()
        with self.assertRaisesRegex(ManualSupplementError, "SHA-256"):
            load_supplements(path, "0" * 64, WEEK, [])

    def test_record_hash_mismatch_rejected(self):
        self.data["records"][0]["summary_cn"] += "未经复核的内容。"
        with self.assertRaisesRegex(ManualSupplementError, "content hash"):
            self.load()

    def test_manifest_provenance_tampering_rejected(self):
        _, out, _, _ = self.replay()
        path = out / "review_manifest_20261005.json"
        manifest = json.loads(path.read_text())
        manifest["snapshot_provenance"]["editorial_supplements"]["records"][0]["url"] = "https://ir.theice.com/other"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(AutomationValidationError, "provenance is inconsistent"):
            validate_manifest(out, WEEK)

    def test_missing_manifest_supplement_provenance_rejected(self):
        _, out, _, _ = self.replay()
        path = out / "review_manifest_20261005.json"
        manifest = json.loads(path.read_text())
        manifest["snapshot_provenance"].pop("editorial_supplements")
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(AutomationValidationError, "lack manifest provenance"):
            validate_manifest(out, WEEK)

    def test_original_item_tampering_rejected_even_with_updated_output_hashes(self):
        _, out, _, _ = self.replay()
        manifest = json.loads((out / "review_manifest_20261005.json").read_text())
        weekly_path = out / "weekly_data_20261005.json"
        weekly = json.loads(weekly_path.read_text())
        weekly["items"][0]["summary_cn"] += "这是额外文字。"
        weekly_path.write_text(json.dumps(weekly, ensure_ascii=False))
        run_qa(weekly_data_path=weekly_path, source_status_path=out / "source_status_20261005.json", output_dir=out, expected_week_start=WEEK)
        write_review_manifest(out, WEEK, "generation-sha", "99", snapshot_provenance=manifest["snapshot_provenance"])
        with self.assertRaisesRegex(AutomationValidationError, "original items changed"):
            validate_manifest(out, WEEK)

    def test_supplement_file_tampering_rejected(self):
        _, out, _, _ = self.replay()
        with (out / "editorial_supplements_20261005.json").open("a") as file:
            file.write(" ")
        with self.assertRaisesRegex(AutomationValidationError, "SHA-256 mismatch"):
            validate_manifest(out, WEEK)

    def test_supplement_content_tampering_rejected_even_with_updated_output_hashes(self):
        _, out, _, _ = self.replay()
        manifest = json.loads((out / "review_manifest_20261005.json").read_text())
        weekly_path = out / "weekly_data_20261005.json"
        weekly = json.loads(weekly_path.read_text())
        weekly["items"][-1]["summary_cn"] += "这是额外文字。"
        weekly_path.write_text(json.dumps(weekly, ensure_ascii=False))
        run_qa(weekly_data_path=weekly_path, source_status_path=out / "source_status_20261005.json", output_dir=out, expected_week_start=WEEK)
        write_review_manifest(out, WEEK, "generation-sha", "99", snapshot_provenance=manifest["snapshot_provenance"])
        with self.assertRaisesRegex(AutomationValidationError, "tampered"):
            validate_manifest(out, WEEK)

    def test_no_network_or_model_invocation(self):
        with patch("crawler.collector.collect_week", side_effect=AssertionError("live collection forbidden")), \
             patch("crawler.translator.TitleTranslator.translate", side_effect=AssertionError("model forbidden")):
            self.replay()

    def test_workflow_supplements_opt_in_and_publish_guards_unchanged(self):
        workflow = Path(".github/workflows/weekly-report-production.yml").read_text()
        self.assertIn("apply_editorial_supplements:", workflow)
        self.assertIn("supplement_args=()", workflow)
        self.assertIn("--supplement-file", workflow)
        self.assertIn("manual_supplements/approved/weekly_", workflow)
        self.assertIn('"$GENERATION_MODE" != "snapshot"', workflow)
        self.assertNotIn("manual_supplements/drafts", workflow)
        self.assertIn("editorial_supplements_${{", workflow)

    def test_workflow_rejects_invalid_selection_before_translation_preflight(self):
        workflow = Path(".github/workflows/weekly-report-production.yml").read_text()
        block = workflow.split("      - name: Prepare manual week input", 1)[1].split("      - name: Run permanent tests", 1)[0]
        script = textwrap.dedent(block.split("          python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0])
        for mode, selected, digest, week, success in (
            ("live", "false", "", WEEK, True),
            ("snapshot", "true", "0" * 64, WEEK, True),
            ("live", "true", "0" * 64, WEEK, False),
            ("snapshot", "false", "0" * 64, WEEK, False),
            ("snapshot", "true", "", WEEK, False),
            ("snapshot", "true", "0" * 64, "", False),
        ):
            with self.subTest(mode=mode, selected=selected, digest=digest, week=week):
                env = {**os.environ, "GENERATION_MODE": mode, "APPLY_SUPPLEMENTS": selected,
                       "SUPPLEMENT_SHA256": digest, "RAW_WEEK_START": week,
                       "GITHUB_OUTPUT": str(self.root / "workflow-output")}
                result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, success, result.stderr)


if __name__ == "__main__":
    unittest.main()
