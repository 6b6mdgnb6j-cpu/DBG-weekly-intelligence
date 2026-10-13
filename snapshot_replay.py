import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from automation_pipeline import AutomationValidationError, validate_manifest, write_review_manifest
from crawler.manual_translations import apply_approved_overrides_with_report, atomic_write_json
from crawler.manual_supplements import load_supplements, supplement_provenance
from crawler.manual_editorial_summaries import load_editorial_summaries, summary_provenance
from generate_weekly import render_report
from qa_gate import FAIL, run_qa


class SnapshotReplayError(RuntimeError):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if destination != target and destination not in target.parents:
                raise SnapshotReplayError(f"unsafe snapshot member: {member.filename}")
        bundle.extractall(destination)


def _find_required(root, filename):
    matches = list(Path(root).rglob(filename))
    if len(matches) != 1:
        raise SnapshotReplayError(f"snapshot must contain exactly one {filename}; found {len(matches)}")
    return matches[0]


def replay_snapshot(
    snapshot_zip, expected_snapshot_sha256, week_start, output_dir, approved_file,
    collection_run_id, collection_sha, collection_artifact_id, collection_artifact_name,
    generation_run_id, generation_sha,
    supplement_file=None, supplement_sha256=None,
    editorial_summary_file=None, editorial_summary_sha256=None,
):
    snapshot_zip = Path(snapshot_zip)
    output_dir = Path(output_dir)
    approved_file = Path(approved_file)
    if bool(supplement_file) != bool(supplement_sha256):
        raise SnapshotReplayError("supplement file and SHA-256 must be supplied together")
    if bool(editorial_summary_file) != bool(editorial_summary_sha256):
        raise SnapshotReplayError("editorial summary file and SHA-256 must be supplied together")
    actual_archive_hash = sha256(snapshot_zip)
    if actual_archive_hash != expected_snapshot_sha256:
        raise SnapshotReplayError("snapshot ZIP SHA-256 mismatch")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SnapshotReplayError("output directory must be absent or empty")
    if not approved_file.exists():
        raise SnapshotReplayError("approved translations file is missing")

    compact = week_start.replace("-", "")
    with tempfile.TemporaryDirectory(prefix="weekly-snapshot-") as temp:
        _safe_extract(snapshot_zip, temp)
        weekly_input = _find_required(temp, f"weekly_data_{compact}.json")
        status_input = _find_required(temp, f"source_status_{compact}.json")
        weekly = json.loads(weekly_input.read_text(encoding="utf-8"))
        statuses = json.loads(status_input.read_text(encoding="utf-8"))
        if weekly.get("week_start") != week_start:
            raise SnapshotReplayError("snapshot week_start mismatch")
        if not isinstance(weekly.get("items"), list) or not isinstance(statuses, list):
            raise SnapshotReplayError("snapshot data structure is invalid")
        approved = json.loads(approved_file.read_text(encoding="utf-8"))
        if approved.get("week_start") != week_start:
            raise SnapshotReplayError("approved translations week_start mismatch")

        report = apply_approved_overrides_with_report(weekly, approved)
        if report["identity_hash_conflict"] or report["ambiguous"]:
            conflicts = [row.get("item_id") for row in report["identity_hash_conflict"]]
            ambiguities = [row.get("item_id") for row in report["ambiguous"]]
            raise SnapshotReplayError(
                "approved translation identity conflict or ambiguity: "
                f"conflicts={conflicts}, ambiguous={ambiguities}"
            )
        summaries = None
        if editorial_summary_file:
            if report["absent"]:
                raise SnapshotReplayError("editorial replay requires all translation approvals to match")
            enriched, summary_data = load_editorial_summaries(
                editorial_summary_file, editorial_summary_sha256, week_start, weekly["items"]
            )
            summaries = summary_provenance(editorial_summary_file, editorial_summary_sha256,
                                           summary_data, weekly["items"])
            weekly["items"] = enriched
        supplements = None
        if supplement_file:
            if report["absent"]:
                raise SnapshotReplayError("supplement replay requires all existing translation approvals to match")
            additions, supplement_data = load_supplements(
                supplement_file, supplement_sha256, week_start, weekly["items"]
            )
            supplements = supplement_provenance(supplement_file, supplement_sha256, supplement_data, weekly["items"])
            weekly["items"].extend(additions)
            weekly["item_count"] = len(weekly["items"])
            counts = dict(weekly.get("pipeline_counts") or {})
            counts["editorial_supplements"] = len(additions)
            counts["final_weekly_items"] = len(weekly["items"])
            weekly["pipeline_counts"] = counts
        output_dir.mkdir(parents=True, exist_ok=True)
        weekly_output = output_dir / weekly_input.name
        status_output = output_dir / status_input.name
        shutil.copyfile(status_input, status_output)
        if summaries:
            shutil.copyfile(editorial_summary_file, output_dir / summaries["artifact_filename"])
        if supplements:
            # Bind the exact approved document, not a regenerated representation.
            shutil.copyfile(supplement_file, output_dir / supplements["artifact_filename"])
        atomic_write_json(weekly_output, weekly)
        render_report(week_start, output_dir=output_dir)
        qa_result = run_qa(
            weekly_data_path=weekly_output,
            source_status_path=status_output,
            expected_week_start=week_start,
            output_dir=output_dir,
        )
        if qa_result["status"] == FAIL or qa_result["blocking_count"]:
            raise SnapshotReplayError("snapshot replay QA failed")

        provenance = {
            "mode": "snapshot_replay",
            "collection": {
                "run_id": str(collection_run_id), "commit_sha": collection_sha,
                "artifact_id": str(collection_artifact_id), "artifact_name": collection_artifact_name,
                "artifact_sha256": actual_archive_hash,
                "input_files": {
                    weekly_input.name: sha256(weekly_input),
                    status_input.name: sha256(status_input),
                },
            },
            "replay": {
                "run_id": str(generation_run_id), "generation_sha": generation_sha,
                "approved_translations_file": approved_file.name,
                "approved_translations_sha256": sha256(approved_file),
                "override_results": report,
            },
        }
        if supplements:
            provenance["editorial_supplements"] = supplements
        if summaries:
            provenance["editorial_summaries"] = summaries
        manifest_path = write_review_manifest(
            output_dir, week_start, generation_sha, generation_run_id,
            snapshot_provenance=provenance,
        )
        validate_manifest(
            output_dir, week_start, source_run_id=generation_run_id,
            generation_sha=generation_sha, current_main_sha=generation_sha,
        )
        return {"qa": qa_result, "overrides": report, "manifest": str(manifest_path)}


def cli(argv=None):
    parser = argparse.ArgumentParser(description="Replay an immutable weekly collection snapshot offline.")
    parser.add_argument("--snapshot-zip", required=True)
    parser.add_argument("--snapshot-sha256", dest="expected_snapshot_sha256", required=True)
    parser.add_argument("--week-start", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--approved-file", required=True)
    parser.add_argument("--collection-run-id", required=True)
    parser.add_argument("--collection-sha", required=True)
    parser.add_argument("--collection-artifact-id", required=True)
    parser.add_argument("--collection-artifact-name", required=True)
    parser.add_argument("--generation-run-id", required=True)
    parser.add_argument("--generation-sha", required=True)
    parser.add_argument("--supplement-file", help="Explicit approved editorial supplement JSON (snapshot only).")
    parser.add_argument("--supplement-sha256", help="Required SHA-256 when --supplement-file is supplied.")
    parser.add_argument("--editorial-summary-file", help="Explicit approved empty-source summary file (snapshot only).")
    parser.add_argument("--editorial-summary-sha256", help="Required SHA-256 for the editorial summary file.")
    args = parser.parse_args(argv)
    try:
        result = replay_snapshot(**vars(args))
    except (SnapshotReplayError, AutomationValidationError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"SNAPSHOT REPLAY BLOCKED: {exc}")
        return 4
    print(json.dumps({
        "status": "REVIEW_READY",
        "qa_status": result["qa"]["status"],
        "applied": len(result["overrides"]["applied"]),
        "absent": len(result["overrides"]["absent"]),
        "identity_hash_conflict": len(result["overrides"]["identity_hash_conflict"]),
        "ambiguous": len(result["overrides"]["ambiguous"]),
        "manifest": result["manifest"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
