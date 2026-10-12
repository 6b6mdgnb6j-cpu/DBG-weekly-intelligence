import copy
import hashlib
import json
import tempfile
import os
import subprocess
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import snapshot_replay
from crawler.manual_translations import original_sha256, stable_item_id


WEEK = "2026-09-28"


def item(url="https://example.test/article", original="Market infrastructure update"):
    return {
        "date": WEEK, "source": "Source", "url": url, "category": "Macro",
        "title_original": original, "title_original_lang": "en", "title_cn": "错误译文",
        "summary_original": "Clearing update.", "summary_original_lang": "en", "summary_cn": "清算更新。",
    }


def approval(record, field="title", translation="市场基础设施更新"):
    original = record[f"{field}_original"]
    return {
        "item_id": stable_item_id(record, field, original), "source": record["source"],
        "date": record["date"], "url": record["url"], "field": field,
        "original_sha256": original_sha256(original), "manual_translation": translation,
    }


class SnapshotReplayTests(unittest.TestCase):
    def workflow_enforcement(self, **env_overrides):
        workflow = Path(".github/workflows/weekly-report-production.yml").read_text(encoding="utf-8")
        block = workflow.split("      - name: Enforce workflow result", 1)[1]
        script = block.split("        run: |\n", 1)[1]
        script = "\n".join(line[10:] if line.startswith("          ") else line for line in script.splitlines())
        defaults = {
            "GENERATION_MODE": "live", "TEST_EXIT_CODE": "0", "COMPILE_EXIT_CODE": "0",
            "PREFLIGHT_EXIT_CODE": "0", "SNAPSHOT_DOWNLOAD_OUTCOME": "skipped",
            "WEEKLY_EXIT_CODE": "0", "BILINGUAL_VALIDATION_EXIT_CODE": "0",
            "MANIFEST_EXIT_CODE": "0", "BUNDLE_VALIDATION_EXIT_CODE": "0",
            "PUBLISHED_SAFETY_EXIT_CODE": "0",
        }
        defaults.update(env_overrides)
        return subprocess.run(["bash", "-c", script], env={**os.environ, **defaults}, capture_output=True, text=True)

    def make_snapshot(self, root, records=None, week=WEEK):
        root = Path(root)
        source = root / "source"
        data = source / "output" / "production" / week.replace("-", "")
        data.mkdir(parents=True)
        payload = {
            "week_start": week, "week_end": "2026-10-04", "translation_mode": "bilingual",
            "source_count": 1, "registered_source_count": 1,
            "item_count": len(records or [item()]), "items": records or [item()],
        }
        (data / f"weekly_data_{week.replace('-', '')}.json").write_text(json.dumps(payload), encoding="utf-8")
        (data / f"source_status_{week.replace('-', '')}.json").write_text(
            json.dumps([{"source": "Source", "status": "network_error", "target_period_reached": False}]),
            encoding="utf-8",
        )
        archive = root / "snapshot.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for path in data.iterdir():
                bundle.write(path, path.relative_to(source))
        return archive, hashlib.sha256(archive.read_bytes()).hexdigest(), payload

    def run_replay(self, root, records=None, approved_rows=None, **overrides):
        root = Path(root)
        archive, digest, payload = self.make_snapshot(root, records)
        approved = root / "approved.json"
        approved.write_text(json.dumps({
            "schema_version": 1, "week_start": WEEK,
            "overrides": approved_rows if approved_rows is not None else [approval(payload["items"][0])],
        }), encoding="utf-8")
        args = dict(
            snapshot_zip=archive, expected_snapshot_sha256=digest, week_start=WEEK,
            output_dir=root / "out", approved_file=approved, collection_run_id="44",
            collection_sha="oldsha", collection_artifact_id="115", collection_artifact_name="debug",
            generation_run_id="99", generation_sha="newsha",
        )
        args.update(overrides)
        qa = {"status": "WARNING", "blocking_count": 0}
        with patch.object(snapshot_replay, "render_report"), patch.object(snapshot_replay, "run_qa", return_value=qa), \
             patch.object(snapshot_replay, "write_review_manifest", return_value=root / "out" / "manifest.json"), \
             patch.object(snapshot_replay, "validate_manifest"):
            result = snapshot_replay.replay_snapshot(**args)
        return result, archive.read_bytes()

    def test_replay_applies_approval_and_preserves_source_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, before = self.run_replay(tmp)
            self.assertEqual(len(result["overrides"]["applied"]), 1)
            self.assertEqual(Path(tmp, "snapshot.zip").read_bytes(), before)
            statuses = json.loads(Path(tmp, "out", "source_status_20260928.json").read_text())
            self.assertEqual(statuses[0]["status"], "network_error")

    def test_hash_corruption_is_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(snapshot_replay.SnapshotReplayError, "SHA-256"):
                self.run_replay(tmp, expected_snapshot_sha256="0" * 64)

    def test_wrong_week_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(snapshot_replay.SnapshotReplayError):
                self.run_replay(tmp, week_start="2026-09-21")

    def test_missing_required_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, digest, _ = self.make_snapshot(tmp)
            broken = Path(tmp, "broken.zip")
            with zipfile.ZipFile(archive) as source, zipfile.ZipFile(broken, "w") as target:
                name = source.namelist()[0]
                target.writestr(name, source.read(name))
            approved = Path(tmp, "approved.json")
            approved.write_text(json.dumps({"schema_version": 1, "week_start": WEEK, "overrides": []}))
            with self.assertRaisesRegex(snapshot_replay.SnapshotReplayError, "source_status"):
                snapshot_replay.replay_snapshot(
                    broken, hashlib.sha256(broken.read_bytes()).hexdigest(), WEEK, Path(tmp, "out"), approved,
                    "44", "old", "115", "debug", "99", "new",
                )

    def test_identity_hash_conflict_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = item()
            bad = approval(record)
            bad["original_sha256"] = "0" * 64
            with self.assertRaisesRegex(snapshot_replay.SnapshotReplayError, "identity conflict"):
                self.run_replay(tmp, records=[record], approved_rows=[bad])

    def test_ambiguous_equivalent_approvals_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = item(
                url="https://www.theia.org/index%2Ephp/news/press-releases/article",
                original="Investment Association update",
            )
            record["source"] = "Investment Association"
            first = approval(record)
            first["url"] = "https://www.theia.org/news/press-releases/article"
            first["item_id"] = stable_item_id({**record, "url": first["url"]}, "title", record["title_original"])
            second = copy.deepcopy(first)
            second["url"] = "https://www.theia.org/index.php/news/press-releases/article"
            second["item_id"] = stable_item_id({**record, "url": second["url"]}, "title", record["title_original"])
            with self.assertRaisesRegex(snapshot_replay.SnapshotReplayError, "ambiguity"):
                self.run_replay(tmp, records=[record], approved_rows=[first, second])

    def test_duplicate_item_id_conflicting_translation_is_rejected_before_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = item()
            first = approval(record)
            second = {**first, "manual_translation": "冲突译文"}
            with self.assertRaisesRegex(snapshot_replay.SnapshotReplayError, "ambiguous"):
                self.run_replay(tmp, records=[record], approved_rows=[first, second])
            self.assertEqual(record["title_cn"], "错误译文")

    def test_duplicate_item_id_conflicting_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = item()
            first = approval(record)
            second = {**first, "url": "https://example.test/other"}
            with self.assertRaisesRegex(snapshot_replay.SnapshotReplayError, "ambiguous"):
                self.run_replay(tmp, records=[record], approved_rows=[first, second])

    def test_absent_same_source_date_field_article_is_not_hash_conflict(self):
        present = item(url="https://example.test/present", original="Present article")
        missing = item(url="https://example.test/missing", original="Missing article")
        payload = {"week_start": WEEK, "items": [present]}
        report = snapshot_replay.apply_approved_overrides_with_report(
            payload, {"schema_version": 1, "week_start": WEEK, "overrides": [approval(missing)]}
        )
        self.assertEqual(len(report["absent"]), 1)
        self.assertEqual(report["identity_hash_conflict"], [])

    def test_same_article_changed_original_is_hash_conflict(self):
        present = item(url="https://example.test/article", original="Changed original")
        approved_record = item(url=present["url"], original="Approved original")
        report = snapshot_replay.apply_approved_overrides_with_report(
            {"week_start": WEEK, "items": [present]},
            {"schema_version": 1, "week_start": WEEK, "overrides": [approval(approved_record)]},
        )
        self.assertEqual(len(report["identity_hash_conflict"]), 1)
        self.assertEqual(report["absent"], [])

    def test_workflow_enforcement_live_and_snapshot_boundaries(self):
        self.assertEqual(self.workflow_enforcement().returncode, 0)
        self.assertNotEqual(self.workflow_enforcement(PREFLIGHT_EXIT_CODE="4").returncode, 0)
        self.assertEqual(self.workflow_enforcement(
            GENERATION_MODE="snapshot", PREFLIGHT_EXIT_CODE="", SNAPSHOT_DOWNLOAD_OUTCOME="success"
        ).returncode, 0)
        self.assertNotEqual(self.workflow_enforcement(
            GENERATION_MODE="snapshot", PREFLIGHT_EXIT_CODE="", SNAPSHOT_DOWNLOAD_OUTCOME="failure"
        ).returncode, 0)
        self.assertNotEqual(self.workflow_enforcement(
            GENERATION_MODE="snapshot", PREFLIGHT_EXIT_CODE="", SNAPSHOT_DOWNLOAD_OUTCOME="success",
            WEEKLY_EXIT_CODE="4"
        ).returncode, 0)
        self.assertNotEqual(self.workflow_enforcement(
            GENERATION_MODE="snapshot", PREFLIGHT_EXIT_CODE="", SNAPSHOT_DOWNLOAD_OUTCOME="success",
            BUNDLE_VALIDATION_EXIT_CODE="4"
        ).returncode, 0)

    def test_qa_fail_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, digest, payload = self.make_snapshot(root)
            approved = root / "approved.json"
            approved.write_text(json.dumps({"schema_version": 1, "week_start": WEEK, "overrides": [approval(payload["items"][0])]}))
            with patch.object(snapshot_replay, "render_report"), patch.object(
                snapshot_replay, "run_qa", return_value={"status": "FAIL", "blocking_count": 1}
            ):
                with self.assertRaisesRegex(snapshot_replay.SnapshotReplayError, "QA failed"):
                    snapshot_replay.replay_snapshot(
                        archive, digest, WEEK, root / "out", approved, "44", "old", "115", "debug", "99", "new"
                    )

    def test_module_has_no_collector_or_translator_dependency(self):
        source = Path(snapshot_replay.__file__).read_text(encoding="utf-8")
        self.assertNotIn("collect_week", source)
        self.assertNotIn("translator", source)

    def test_production_workflow_snapshot_mode_is_explicit_and_never_calls_run_weekly(self):
        workflow = Path(".github/workflows/weekly-report-production.yml").read_text(encoding="utf-8")
        self.assertIn("generation_mode:", workflow)
        self.assertIn("python3 snapshot_replay.py", workflow)
        self.assertIn("inputs.generation_mode == 'snapshot'", workflow)
        snapshot_block = workflow.split('if [ "$GENERATION_MODE" = "snapshot" ]; then', 1)[1].split("elif", 1)[0]
        self.assertNotIn("run_weekly.py", snapshot_block)
        self.assertIn("--snapshot-sha256", snapshot_block)
        self.assertIn("--collection-run-id", snapshot_block)
        self.assertIn("snapshot artifact provenance mismatch", workflow)
        self.assertIn('artifact.get("expired")', workflow)
        debug = workflow.split("      - name: Upload debug artifacts", 1)[1].split("      - name:", 1)[0]
        self.assertIn("inputs.generation_mode != 'snapshot'", debug)
        self.assertIn("steps.snapshot_download.outcome != 'success'", debug)


if __name__ == "__main__":
    unittest.main()
