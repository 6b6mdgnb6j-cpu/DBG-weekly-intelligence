import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publish_weekly
from qa_gate import file_sha256


def weekly_payload(**overrides):
    payload = {
        "week_start": "2020-01-01",
        "week_end": "2020-01-07",
        "translation_mode": "bilingual",
        "source_count": 5,
        "registered_source_count": 5,
        "item_count": 1,
        "items": [
            {
                "title_original": "Market infrastructure update",
                "date": "2020-01-01",
                "url": "https://example.test/news",
                "source": "Source",
                "category": "Macro",
            }
        ],
        "highlights": [],
        "sections": [],
    }
    payload.update(overrides)
    return payload


def write_weekly(root, payload=None):
    path = Path(root) / "weekly_data_20200101.json"
    path.write_text(json.dumps(payload or weekly_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_qa(root, weekly_path, status="PASS", **overrides):
    report = {
        "week_start": "2020-01-01",
        "week_end": "2020-01-07",
        "translation_mode": "bilingual",
        "status": status,
        "summary": {"final_items": 1, "highlights": 1},
        "checks": [],
        "input_artifacts": {
            "weekly_data": str(weekly_path),
            "weekly_data_sha256": file_sha256(weekly_path),
            "source_status": str(Path(root) / "source_status_20200101.json"),
            "source_status_sha256": "abc123",
        },
    }
    report.update(overrides)
    path = Path(root) / "qa_report_20200101.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def published_paths(root):
    published_dir = Path(root) / "published"
    archive_path = published_dir / "archive" / "weekly_20200101.json"
    latest_path = published_dir / "latest.json"
    return published_dir, archive_path, latest_path


def write_published_state(archive, latest, archive_payload=None, latest_payload=None):
    archive.parent.mkdir(parents=True, exist_ok=True)
    latest.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(
        json.dumps(archive_payload or weekly_payload(week_start="2019-12-25", week_end="2019-12-31"), ensure_ascii=False),
        encoding="utf-8",
    )
    latest.write_text(
        json.dumps(latest_payload or weekly_payload(week_start="2019-12-25", week_end="2019-12-31"), ensure_ascii=False),
        encoding="utf-8",
    )


def write_latest_state(latest, payload=None):
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(
        json.dumps(payload or weekly_payload(week_start="2019-12-25", week_end="2019-12-31"), ensure_ascii=False),
        encoding="utf-8",
    )


def write_exact_archive_state(archive, payload=None):
    archive.parent.mkdir(parents=True, exist_ok=True)
    published = publish_weekly.build_published_payload(payload or weekly_payload())
    archive.write_bytes(publish_weekly.serialize_published_payload(published))


def published_bytes(payload=None):
    published = publish_weekly.build_published_payload(payload or weekly_payload())
    return publish_weekly.serialize_published_payload(published)


def write_exact_published_state(archive, latest, payload=None):
    data = published_bytes(payload)
    archive.parent.mkdir(parents=True, exist_ok=True)
    latest.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(data)
    latest.write_bytes(data)
    return data


def temp_publish_files(published_dir):
    return list(Path(published_dir).glob("**/*.tmp"))


class PublishWeeklyGuardTests(unittest.TestCase):
    def test_pass_allows_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)

            _, _, _, report, wrote = publish_weekly.publish_weekly(
                weekly,
                qa_report_path=qa,
                published_dir=published_dir,
            )

            self.assertTrue(wrote)
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(archive.exists())
            self.assertTrue(latest.exists())
            self.assertEqual(archive.read_bytes(), latest.read_bytes())

    def test_warning_blocks_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "WARNING")
            published_dir, _, _ = published_paths(tmp)
            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)
            self.assertEqual(ctx.exception.exit_code, 2)

    def test_warning_with_approval_allows_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "WARNING")
            published_dir, archive, latest = published_paths(tmp)
            _, _, _, report, wrote = publish_weekly.publish_weekly(
                weekly,
                qa_report_path=qa,
                published_dir=published_dir,
                approve_warning=True,
            )
            self.assertTrue(wrote)
            self.assertEqual(report["status"], "WARNING")
            self.assertTrue(archive.exists())
            self.assertTrue(latest.exists())

    def test_no_translate_artifact_blocks_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp, weekly_payload(translation_mode="no_translate"))
            qa = write_qa(tmp, weekly, "PASS", translation_mode="no_translate")
            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=Path(tmp) / "published")
            self.assertEqual(ctx.exception.exit_code, 4)
            self.assertIn("not bilingual", str(ctx.exception))

    def test_warning_approval_does_not_allow_no_translate_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp, weekly_payload(translation_mode="no_translate"))
            qa = write_qa(tmp, weekly, "WARNING", translation_mode="no_translate")
            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(
                    weekly,
                    qa_report_path=qa,
                    published_dir=Path(tmp) / "published",
                    approve_warning=True,
                )
            self.assertEqual(ctx.exception.exit_code, 4)
            self.assertIn("not bilingual", str(ctx.exception))

    def test_legacy_artifact_without_translation_mode_blocks_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = weekly_payload()
            payload.pop("translation_mode")
            weekly = write_weekly(tmp, payload)
            qa = write_qa(tmp, weekly, "PASS", translation_mode="")
            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=Path(tmp) / "published")
            self.assertEqual(ctx.exception.exit_code, 4)
            self.assertIn("not bilingual", str(ctx.exception))

    def test_qa_translation_mode_mismatch_blocks_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS", translation_mode="no_translate")
            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=Path(tmp) / "published")
            self.assertEqual(ctx.exception.exit_code, 4)
            self.assertIn("translation mode", str(ctx.exception))

    def test_fail_blocks_even_with_warning_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "FAIL")
            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, approve_warning=True, published_dir=Path(tmp) / "published")
            self.assertEqual(ctx.exception.exit_code, 3)

    def test_missing_qa_report_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=Path(tmp) / "missing.json", published_dir=Path(tmp) / "published")
            self.assertEqual(ctx.exception.exit_code, 4)

    def test_malformed_qa_report_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = Path(tmp) / "qa_report_20200101.json"
            qa.write_text("{bad json", encoding="utf-8")
            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=Path(tmp) / "published")
            self.assertEqual(ctx.exception.exit_code, 4)

    def test_week_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS", week_start="2020-01-08")
            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=Path(tmp) / "published")
            self.assertEqual(ctx.exception.exit_code, 4)

    def test_hash_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            weekly.write_text(json.dumps(weekly_payload(item_count=2), ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=Path(tmp) / "published")
            self.assertEqual(ctx.exception.exit_code, 4)

    def test_unknown_qa_status_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "MAYBE")
            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=Path(tmp) / "published")
            self.assertEqual(ctx.exception.exit_code, 4)

    def test_legacy_qa_without_hash_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS", input_artifacts={})
            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=Path(tmp) / "published")
            self.assertEqual(ctx.exception.exit_code, 4)

    def test_blocked_publish_leaves_archive_and_latest_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "WARNING")
            published_dir, archive, latest = published_paths(tmp)
            archive.parent.mkdir(parents=True)
            archive.write_text("old archive", encoding="utf-8")
            latest.parent.mkdir(parents=True, exist_ok=True)
            latest.write_text("old latest", encoding="utf-8")
            with self.assertRaises(publish_weekly.PublishBlockedError):
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)
            self.assertEqual(archive.read_text(encoding="utf-8"), "old archive")
            self.assertEqual(latest.read_text(encoding="utf-8"), "old latest")

    def test_successful_publish_writes_expected_archive_and_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)
            publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)
            archive_payload = json.loads(archive.read_text(encoding="utf-8"))
            latest_payload = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(archive_payload["week_start"], "2020-01-01")
            self.assertEqual(latest_payload["week_start"], "2020-01-01")
            self.assertEqual(archive.read_bytes(), latest.read_bytes())

    def test_dry_run_allows_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)
            _, _, _, report, wrote = publish_weekly.publish_weekly(
                weekly,
                qa_report_path=qa,
                published_dir=published_dir,
                dry_run=True,
            )
            self.assertFalse(wrote)
            self.assertEqual(report["status"], "PASS")
            self.assertFalse(archive.exists())
            self.assertFalse(latest.exists())
            self.assertFalse(temp_publish_files(published_dir))

    def test_cli_missing_qa_blocks_without_publishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            code = publish_weekly.main([str(weekly), "--qa-report", str(Path(tmp) / "missing.json")])
            self.assertEqual(code, 4)

    def test_archive_temp_write_failure_leaves_existing_files_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)
            write_latest_state(latest)
            old_latest = latest.read_bytes()

            def fail_archive(target, data, expected_payload, stage):
                if stage == "archive_replace":
                    raise publish_weekly.PublishFailedError("archive temp write failed", stage)
                return publish_weekly.atomic_write_json_bytes(target, data, expected_payload, stage)

            with patch.object(publish_weekly, "atomic_write_json_bytes", side_effect=fail_archive):
                with self.assertRaises(publish_weekly.PublishFailedError) as ctx:
                    publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)

            self.assertEqual(ctx.exception.stage, "archive_replace")
            self.assertFalse(archive.exists())
            self.assertEqual(latest.read_bytes(), old_latest)
            self.assertFalse(temp_publish_files(published_dir))

    def test_archive_replace_failure_leaves_existing_files_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)
            write_latest_state(latest)
            old_latest = latest.read_bytes()
            original_replace = publish_weekly.os.replace

            def fail_archive_replace(src, dst):
                if Path(dst) == archive:
                    raise OSError("archive replace failed")
                return original_replace(src, dst)

            with patch.object(publish_weekly.os, "replace", side_effect=fail_archive_replace):
                with self.assertRaises(publish_weekly.PublishFailedError) as ctx:
                    publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)

            self.assertEqual(ctx.exception.stage, "archive_replace")
            self.assertFalse(archive.exists())
            self.assertEqual(latest.read_bytes(), old_latest)
            self.assertFalse(temp_publish_files(published_dir))

    def test_latest_temp_write_failure_rolls_back_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)
            write_latest_state(latest)
            old_latest = latest.read_bytes()
            real_writer = publish_weekly.atomic_write_json_bytes

            def fail_latest(target, data, expected_payload, stage):
                if stage == "latest_replace":
                    raise publish_weekly.PublishFailedError("latest temp write failed", stage)
                return real_writer(target, data, expected_payload, stage)

            with patch.object(publish_weekly, "atomic_write_json_bytes", side_effect=fail_latest):
                with self.assertRaises(publish_weekly.PublishFailedError) as ctx:
                    publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)

            self.assertEqual(ctx.exception.stage, "latest_replace")
            self.assertEqual(ctx.exception.rollback_status, "successful")
            self.assertFalse(archive.exists())
            self.assertEqual(latest.read_bytes(), old_latest)
            self.assertFalse(temp_publish_files(published_dir))

    def test_latest_replace_failure_rolls_back_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)
            write_latest_state(latest)
            old_latest = latest.read_bytes()
            original_replace = publish_weekly.os.replace

            def fail_latest_replace(src, dst):
                if Path(dst) == latest:
                    raise OSError("latest replace failed")
                return original_replace(src, dst)

            with patch.object(publish_weekly.os, "replace", side_effect=fail_latest_replace):
                with self.assertRaises(publish_weekly.PublishFailedError) as ctx:
                    publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)

            self.assertEqual(ctx.exception.stage, "latest_replace")
            self.assertEqual(ctx.exception.rollback_status, "successful")
            self.assertFalse(archive.exists())
            self.assertEqual(latest.read_bytes(), old_latest)
            self.assertFalse(temp_publish_files(published_dir))

    def test_rollback_failure_reports_partial_publish_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)
            write_exact_archive_state(archive)
            write_latest_state(latest)
            real_writer = publish_weekly.atomic_write_json_bytes

            def fail_latest_and_rollback(target, data, expected_payload, stage):
                if stage in {"latest_replace", "rollback_archive"}:
                    raise publish_weekly.PublishFailedError(f"{stage} failed", stage)
                return real_writer(target, data, expected_payload, stage)

            with patch.object(publish_weekly, "atomic_write_json_bytes", side_effect=fail_latest_and_rollback):
                with self.assertRaises(publish_weekly.PublishFailedError) as ctx:
                    publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)

            self.assertEqual(ctx.exception.exit_code, 6)
            self.assertEqual(ctx.exception.rollback_status, "failed")
            self.assertTrue(archive.exists())
            self.assertTrue(latest.exists())

    def test_cli_rollback_failure_reports_partial_publish_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")

            def fail_publish(*args, **kwargs):
                raise publish_weekly.PublishFailedError(
                    "latest failed; rollback failed",
                    stage="latest_replace",
                    exit_code=6,
                    rollback_status="failed",
                )

            output = io.StringIO()
            with patch.object(publish_weekly, "publish_weekly", side_effect=fail_publish):
                with contextlib.redirect_stdout(output):
                    code = publish_weekly.main([str(weekly), "--qa-report", str(qa)])

            self.assertEqual(code, 6)
            self.assertIn("PUBLISH FAILED", output.getvalue())
            self.assertIn("PARTIAL PUBLISH RISK", output.getvalue())
            self.assertIn("Rollback failed", output.getvalue())

    def test_invalid_temp_json_never_replaces_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "published" / "latest.json"
            target.parent.mkdir(parents=True)
            target.write_text('{"old": true}', encoding="utf-8")
            old_latest = target.read_bytes()

            with self.assertRaises(publish_weekly.PublishFailedError):
                publish_weekly.atomic_write_json_bytes(target, b"{bad json", weekly_payload(), "latest_replace")

            self.assertEqual(target.read_bytes(), old_latest)
            self.assertFalse(temp_publish_files(target.parent))

    def test_qa_guard_failure_creates_no_publish_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            published_dir, _, _ = published_paths(tmp)

            with self.assertRaises(publish_weekly.PublishBlockedError):
                publish_weekly.publish_weekly(
                    weekly,
                    qa_report_path=Path(tmp) / "missing.json",
                    published_dir=published_dir,
                )

            self.assertFalse(published_dir.exists())

    def test_existing_archive_different_blocks_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)
            write_published_state(archive, latest)

            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)

            self.assertIn("archive", str(ctx.exception))

    def test_same_week_differs_without_replace_flag_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = weekly_payload(item_count=2)
            incoming["items"] = incoming["items"] + [{"title_original": "Second item", "date": "2020-01-02"}]
            weekly = write_weekly(tmp, incoming)
            qa = write_qa(tmp, weekly, "PASS", summary={"final_items": 2, "highlights": 1})
            published_dir, archive, latest = published_paths(tmp)
            old_data = write_exact_published_state(archive, latest, weekly_payload(item_count=1))

            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)

            self.assertIn("differs from artifact", str(ctx.exception))
            self.assertEqual(archive.read_bytes(), old_data)
            self.assertEqual(latest.read_bytes(), old_data)

    def test_same_week_differs_with_replace_flag_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = weekly_payload(item_count=2)
            incoming["items"] = incoming["items"] + [{"title_original": "Second item", "date": "2020-01-02"}]
            weekly = write_weekly(tmp, incoming)
            qa = write_qa(tmp, weekly, "PASS", summary={"final_items": 2, "highlights": 1})
            published_dir, archive, latest = published_paths(tmp)
            write_exact_published_state(archive, latest, weekly_payload(item_count=1))
            expected = published_bytes(incoming)

            _, _, _, _, wrote = publish_weekly.publish_weekly(
                weekly,
                qa_report_path=qa,
                published_dir=published_dir,
                replace_same_week=True,
            )

            self.assertTrue(wrote)
            self.assertEqual(archive.read_bytes(), expected)
            self.assertEqual(latest.read_bytes(), expected)

    def test_replace_same_week_blocks_when_archive_and_latest_disagree(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = weekly_payload(item_count=2)
            incoming["items"] = incoming["items"] + [{"title_original": "Second item", "date": "2020-01-02"}]
            weekly = write_weekly(tmp, incoming)
            qa = write_qa(tmp, weekly, "PASS", summary={"final_items": 2, "highlights": 1})
            published_dir, archive, latest = published_paths(tmp)
            old_archive = published_bytes(weekly_payload(item_count=1))
            old_latest = published_bytes(weekly_payload(item_count=3))
            archive.parent.mkdir(parents=True, exist_ok=True)
            latest.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(old_archive)
            latest.write_bytes(old_latest)

            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(
                    weekly,
                    qa_report_path=qa,
                    published_dir=published_dir,
                    replace_same_week=True,
                )

            self.assertIn("archive and latest disagree", str(ctx.exception))
            self.assertEqual(archive.read_bytes(), old_archive)
            self.assertEqual(latest.read_bytes(), old_latest)

    def test_replace_same_week_blocks_when_latest_is_newer_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = weekly_payload(item_count=2)
            incoming["items"] = incoming["items"] + [{"title_original": "Second item", "date": "2020-01-02"}]
            weekly = write_weekly(tmp, incoming)
            qa = write_qa(tmp, weekly, "PASS", summary={"final_items": 2, "highlights": 1})
            published_dir, archive, latest = published_paths(tmp)
            old_archive = published_bytes(weekly_payload(item_count=1))
            archive.parent.mkdir(parents=True, exist_ok=True)
            latest.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(old_archive)
            latest.write_bytes(
                published_bytes(weekly_payload(week_start="2020-01-08", week_end="2020-01-14"))
            )

            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(
                    weekly,
                    qa_report_path=qa,
                    published_dir=published_dir,
                    replace_same_week=True,
                )

            self.assertIn("older than published latest", str(ctx.exception))
            self.assertEqual(archive.read_bytes(), old_archive)

    def test_replace_same_week_identical_artifact_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)
            existing = write_exact_published_state(archive, latest, weekly_payload())

            _, _, _, _, wrote = publish_weekly.publish_weekly(
                weekly,
                qa_report_path=qa,
                published_dir=published_dir,
                replace_same_week=True,
            )

            self.assertFalse(wrote)
            self.assertEqual(archive.read_bytes(), existing)
            self.assertEqual(latest.read_bytes(), existing)

    def test_replace_same_week_warning_without_approval_blocks_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = weekly_payload(item_count=2)
            incoming["items"] = incoming["items"] + [{"title_original": "Second item", "date": "2020-01-02"}]
            weekly = write_weekly(tmp, incoming)
            qa = write_qa(tmp, weekly, "WARNING", summary={"final_items": 2, "highlights": 1})
            published_dir, archive, latest = published_paths(tmp)
            old_data = write_exact_published_state(archive, latest, weekly_payload(item_count=1))

            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(
                    weekly,
                    qa_report_path=qa,
                    published_dir=published_dir,
                    replace_same_week=True,
                )

            self.assertEqual(ctx.exception.exit_code, 2)
            self.assertEqual(archive.read_bytes(), old_data)
            self.assertEqual(latest.read_bytes(), old_data)

    def test_replace_same_week_fail_artifact_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = weekly_payload(item_count=2)
            incoming["items"] = incoming["items"] + [{"title_original": "Second item", "date": "2020-01-02"}]
            weekly = write_weekly(tmp, incoming)
            qa = write_qa(tmp, weekly, "FAIL", summary={"final_items": 2, "highlights": 1})
            published_dir, archive, latest = published_paths(tmp)
            old_data = write_exact_published_state(archive, latest, weekly_payload(item_count=1))

            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(
                    weekly,
                    qa_report_path=qa,
                    published_dir=published_dir,
                    replace_same_week=True,
                    approve_warning=True,
                )

            self.assertEqual(ctx.exception.exit_code, 3)
            self.assertEqual(archive.read_bytes(), old_data)
            self.assertEqual(latest.read_bytes(), old_data)

    def test_replace_same_week_modifies_only_target_archive_and_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = weekly_payload(item_count=2)
            incoming["items"] = incoming["items"] + [{"title_original": "Second item", "date": "2020-01-02"}]
            weekly = write_weekly(tmp, incoming)
            qa = write_qa(tmp, weekly, "PASS", summary={"final_items": 2, "highlights": 1})
            published_dir, archive, latest = published_paths(tmp)
            write_exact_published_state(archive, latest, weekly_payload(item_count=1))
            other_archive = Path(published_dir) / "archive" / "weekly_20191225.json"
            other_archive.write_bytes(
                published_bytes(weekly_payload(week_start="2019-12-25", week_end="2019-12-31"))
            )
            before = {
                path.relative_to(published_dir): path.read_bytes()
                for path in Path(published_dir).glob("**/*.json")
            }

            publish_weekly.publish_weekly(
                weekly,
                qa_report_path=qa,
                published_dir=published_dir,
                replace_same_week=True,
            )
            after = {
                path.relative_to(published_dir): path.read_bytes()
                for path in Path(published_dir).glob("**/*.json")
            }
            changed = {path for path, old in before.items() if after[path] != old}

            self.assertEqual(changed, {Path("archive/weekly_20200101.json"), Path("latest.json")})
            self.assertEqual(after[Path("archive/weekly_20191225.json")], before[Path("archive/weekly_20191225.json")])

    def test_existing_archive_and_latest_identical_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)
            archive.parent.mkdir(parents=True)
            latest.parent.mkdir(parents=True, exist_ok=True)
            published_payload = publish_weekly.build_published_payload(weekly_payload())
            data = publish_weekly.serialize_published_payload(published_payload)
            archive.write_bytes(data)
            latest.write_bytes(data)

            _, _, _, _, wrote = publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)

            self.assertFalse(wrote)
            self.assertEqual(archive.read_bytes(), data)
            self.assertEqual(latest.read_bytes(), data)

    def test_older_week_than_latest_blocks_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)
            latest.parent.mkdir(parents=True)
            latest.write_text(
                json.dumps(weekly_payload(week_start="2020-01-08", week_end="2020-01-14"), ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaises(publish_weekly.PublishBlockedError) as ctx:
                publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)

            self.assertIn("older than published latest", str(ctx.exception))
            self.assertFalse(archive.exists())

    def test_new_archive_creation_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            qa = write_qa(tmp, weekly, "PASS")
            published_dir, archive, latest = published_paths(tmp)

            publish_weekly.publish_weekly(weekly, qa_report_path=qa, published_dir=published_dir)

            self.assertTrue(archive.exists())
            self.assertTrue(latest.exists())
            self.assertEqual(archive.read_bytes(), latest.read_bytes())

    def test_interrupted_write_cannot_half_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "published" / "archive" / "weekly_20200101.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({"old": True}), encoding="utf-8")
            old_archive = target.read_bytes()
            original_fsync = publish_weekly.os.fsync

            def fail_fsync(fd):
                raise OSError("interrupted write")

            with patch.object(publish_weekly.os, "fsync", side_effect=fail_fsync):
                with self.assertRaises(publish_weekly.PublishFailedError):
                    publish_weekly.atomic_write_json_bytes(
                        target,
                        publish_weekly.serialize_published_payload(weekly_payload()),
                        weekly_payload(),
                        "archive_replace",
                    )

            self.assertEqual(target.read_bytes(), old_archive)
            self.assertFalse(temp_publish_files(target.parent))
            self.assertIsNotNone(original_fsync)


if __name__ == "__main__":
    unittest.main()
