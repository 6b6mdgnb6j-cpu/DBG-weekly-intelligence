import json
import tempfile
import unittest
from pathlib import Path

import publish_weekly
from qa_gate import file_sha256


def weekly_payload(**overrides):
    payload = {
        "week_start": "2020-01-01",
        "week_end": "2020-01-07",
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

    def test_cli_missing_qa_blocks_without_publishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly = write_weekly(tmp)
            code = publish_weekly.main([str(weekly), "--qa-report", str(Path(tmp) / "missing.json")])
            self.assertEqual(code, 4)


if __name__ == "__main__":
    unittest.main()
