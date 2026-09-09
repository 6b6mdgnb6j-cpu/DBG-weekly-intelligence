import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from crawler.highlight_ranker import select_highlights
from generate_weekly import build_group_config
from qa_gate import FAIL, PASS, WARNING, file_sha256


BASE_DIR = Path(__file__).resolve().parent
PUBLISHED_DIR = BASE_DIR / "published"
ARCHIVE_DIR = PUBLISHED_DIR / "archive"

SOURCE_REQUIRED_FIELDS = ("week_start", "week_end", "items", "source_count")
PUBLISHED_REQUIRED_FIELDS = ("week_start", "week_end", "translation_mode", "items", "highlights", "sections", "source_count")
VALID_QA_STATUSES = {PASS, WARNING, FAIL}
PUBLISHABLE_TRANSLATION_MODE = "bilingual"


class PublishBlockedError(Exception):
    def __init__(self, message, exit_code):
        super().__init__(message)
        self.exit_code = exit_code


class PublishFailedError(Exception):
    def __init__(self, message, stage, exit_code=5, rollback_status=None):
        super().__init__(message)
        self.stage = stage
        self.exit_code = exit_code
        self.rollback_status = rollback_status


def load_json(path):
    if not path.exists():
        raise ValueError(f"Source weekly JSON not found: {path}")
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("Source weekly JSON must contain a JSON object.")
    return payload


def validate_source_payload(payload):
    missing = [field for field in SOURCE_REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"Source weekly JSON is missing required fields: {', '.join(missing)}")
    if not isinstance(payload.get("items"), list):
        raise ValueError("Source weekly JSON field 'items' must be a list.")
    if not payload.get("week_start") or not payload.get("week_end"):
        raise ValueError("Source weekly JSON must include non-empty week_start and week_end.")
    if payload.get("translation_mode") != PUBLISHABLE_TRANSLATION_MODE:
        raise PublishBlockedError("weekly artifact is not bilingual production output", 4)


def build_published_payload(payload):
    items = payload.get("items", [])
    published = {
        "week_start": payload.get("week_start"),
        "week_end": payload.get("week_end"),
        "translation_mode": payload.get("translation_mode"),
        "source_count": payload.get("source_count"),
        "registered_source_count": payload.get("registered_source_count", payload.get("source_count")),
        "item_count": payload.get("item_count", len(items)),
        "items": items,
        "highlights": payload.get("highlights") or select_highlights(items),
        "sections": payload.get("sections") or build_group_config(items),
    }
    missing = [field for field in PUBLISHED_REQUIRED_FIELDS if field not in published]
    if missing:
        raise ValueError(f"Published payload is missing required fields: {', '.join(missing)}")
    return published


def serialize_published_payload(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def validate_published_payload(payload, expected):
    if not isinstance(payload, dict):
        raise ValueError("Published temp JSON must contain a JSON object.")
    missing = [field for field in PUBLISHED_REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"Published temp JSON is missing required fields: {', '.join(missing)}")
    if payload.get("week_start") != expected.get("week_start"):
        raise ValueError("Published temp JSON week_start mismatch.")
    if payload.get("week_end") != expected.get("week_end"):
        raise ValueError("Published temp JSON week_end mismatch.")
    if not isinstance(payload.get("items"), list):
        raise ValueError("Published temp JSON field 'items' must be a list.")
    if len(payload["items"]) != len(expected.get("items", [])):
        raise ValueError("Published temp JSON item count mismatch.")
    if payload.get("item_count", len(payload["items"])) != expected.get("item_count", len(expected.get("items", []))):
        raise ValueError("Published temp JSON item_count mismatch.")


def validate_published_bytes(data, expected):
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Published temp JSON is invalid: {exc}") from exc
    validate_published_payload(payload, expected)


def atomic_write_json_bytes(target_path, data, expected_payload, stage):
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        with temp_path.open("rb") as f:
            validate_published_bytes(f.read(), expected_payload)
        os.replace(temp_path, target_path)
    except PublishFailedError:
        raise
    except Exception as exc:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise PublishFailedError(str(exc), stage=stage, exit_code=5) from exc


def read_existing_bytes(path):
    path = Path(path)
    if not path.exists():
        return None
    return path.read_bytes()


def restore_published_path(path, old_data, old_expected_payload, stage):
    path = Path(path)
    if old_data is None:
        if path.exists():
            path.unlink()
        return
    atomic_write_json_bytes(path, old_data, old_expected_payload, stage)


def default_qa_report_path(payload):
    week_key = str(payload.get("week_start", "")).replace("-", "")
    return BASE_DIR / "output" / f"qa_report_{week_key}.json"


def load_qa_report(path):
    if not Path(path).exists():
        raise PublishBlockedError("QA report missing", 4)
    try:
        with Path(path).open(encoding="utf-8") as f:
            report = json.load(f)
    except Exception as exc:
        raise PublishBlockedError(f"QA report malformed: {exc}", 4) from exc
    if not isinstance(report, dict):
        raise PublishBlockedError("QA report malformed: root must be a JSON object", 4)
    return report


def validate_qa_guard(payload, source_path, approve_warning=False, qa_report_path=None):
    report_path = Path(qa_report_path) if qa_report_path else default_qa_report_path(payload)
    report = load_qa_report(report_path)

    status = report.get("status")
    if status not in VALID_QA_STATUSES:
        raise PublishBlockedError(f"QA report has unknown status: {status}", 4)

    if payload.get("week_start") != report.get("week_start") or payload.get("week_end") != report.get("week_end"):
        raise PublishBlockedError("QA report week does not match weekly data", 4)
    if report.get("translation_mode") != payload.get("translation_mode"):
        raise PublishBlockedError("QA report translation mode does not match weekly artifact", 4)

    artifacts = report.get("input_artifacts") or {}
    expected_hash = artifacts.get("weekly_data_sha256")
    if not expected_hash:
        raise PublishBlockedError("QA report missing weekly_data_sha256 binding", 4)
    actual_hash = file_sha256(source_path)
    if actual_hash != expected_hash:
        raise PublishBlockedError("weekly artifact changed after QA", 4)

    if status == FAIL:
        raise PublishBlockedError("QA status FAIL", 3)
    if status == WARNING and not approve_warning:
        raise PublishBlockedError("QA status WARNING requires --approve-warning", 2)

    return report_path, report


def publish_weekly(source_path, approve_warning=False, dry_run=False, qa_report_path=None, published_dir=PUBLISHED_DIR):
    payload = load_json(source_path)
    validate_source_payload(payload)
    published = build_published_payload(payload)
    qa_report_path, qa_report = validate_qa_guard(
        payload,
        source_path,
        approve_warning=approve_warning,
        qa_report_path=qa_report_path,
    )

    archive_dir = Path(published_dir) / "archive"
    latest_path = Path(published_dir) / "latest.json"

    week_key = str(published["week_start"]).replace("-", "")
    archive_path = archive_dir / f"weekly_{week_key}.json"

    if dry_run:
        return archive_path, latest_path, qa_report_path, qa_report, False

    serialized = serialize_published_payload(published)
    validate_published_bytes(serialized, published)

    old_archive = read_existing_bytes(archive_path)
    old_archive_payload = json.loads(old_archive.decode("utf-8")) if old_archive is not None else None

    archive_written = False
    try:
        atomic_write_json_bytes(archive_path, serialized, published, "archive_replace")
        archive_written = True
        atomic_write_json_bytes(latest_path, serialized, published, "latest_replace")
    except PublishFailedError as exc:
        if archive_written:
            try:
                restore_published_path(archive_path, old_archive, old_archive_payload, "rollback_archive")
                exc.rollback_status = "successful"
            except Exception as rollback_exc:
                raise PublishFailedError(
                    f"{exc}; rollback failed: {rollback_exc}",
                    stage=exc.stage,
                    exit_code=6,
                    rollback_status="failed",
                ) from rollback_exc
        raise
    return archive_path, latest_path, qa_report_path, qa_report, True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Publish a QA-approved weekly report artifact.")
    parser.add_argument("weekly_json", help="Path to output/weekly_data_<YYYYMMDD>.json")
    parser.add_argument("--approve-warning", action="store_true", help="Allow publishing a WARNING QA report after manual review.")
    parser.add_argument("--dry-run", action="store_true", help="Run QA guard without writing published files.")
    parser.add_argument("--qa-report", help="Override QA report path for testing or review.")
    return parser.parse_args(argv)


def print_guard_summary(report, report_path, approved_warning=False):
    print(f"QA GUARD: {report['status']}")
    print(f"Week: {report.get('week_start')} to {report.get('week_end')}")
    print(f"QA report: {report_path}")
    if report["status"] == WARNING and approved_warning:
        print("Manual override supplied; proceeding with publish.")


def main(argv=None):
    args = parse_args(argv)
    try:
        archive_path, latest_path, qa_path, qa_report, wrote = publish_weekly(
            Path(args.weekly_json),
            approve_warning=args.approve_warning,
            dry_run=args.dry_run,
            qa_report_path=args.qa_report,
        )
    except PublishBlockedError as exc:
        print("PUBLISH BLOCKED")
        print(f"Reason: {exc}")
        if "WARNING" in str(exc):
            print("To publish after review: --approve-warning")
        return exc.exit_code
    except PublishFailedError as exc:
        print("PUBLISH FAILED")
        print(f"Stage: {exc.stage}")
        print(f"Reason: {exc}")
        if exc.rollback_status == "successful":
            print("Rollback: successful")
            print("Published state restored.")
        elif exc.rollback_status == "failed":
            print("PARTIAL PUBLISH RISK")
            print("Rollback failed")
        return exc.exit_code
    except Exception as exc:
        print("PUBLISH ERROR")
        print(str(exc))
        return 5

    print_guard_summary(qa_report, qa_path, approved_warning=args.approve_warning and qa_report["status"] == WARNING)
    if args.dry_run:
        print("DRY RUN")
        print("Publish would be allowed.")
        print(f"Archive: {archive_path}")
        print(f"Latest: {latest_path}")
        return 0

    print("Publishing...")
    print(f"Archive: updated ({archive_path})")
    print("Latest: updated")
    print("PUBLISH SUCCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
