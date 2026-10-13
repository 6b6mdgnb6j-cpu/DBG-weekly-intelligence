# Editorial supplements for snapshot replay

This is an optional, week-scoped addition to immutable historical snapshot replay. Routine live collection never loads these files. A draft file alone has no effect. No approved supplement file is included in this PR.

## Review and approval

1. Review `drafts/weekly_20261005.json` together with `review_20261005.md`. Verify the official release dates, selected facts and both languages. Revise drafts as needed.
2. Only after explicit human approval, create `approved/weekly_20261005.json` in a separate reviewed change. Set the document and every record's `approval_status` to `APPROVED`. Set document `approval.reviewed_by` to the actual reviewer and `approval.approved_at` to the actual timezone-aware ISO timestamp. Do not use test-only approval metadata.
3. Retain identities and verification evidence. Recompute each `content_sha256` with `crawler.manual_supplements.record_hash(record)` after approval/status or content changes. The `supplement_id` binds registered source ID, publication date and canonical URL; identity changes require renewed review. The file digest is the SHA-256 of the exact approved JSON bytes.
4. Review and merge that approval change before generating an official Review Artifact on current main. An implementation PR containing drafts is not editorial approval.

## Contract

Document: schema_version=1, week_start, week_end, approval_status, approval, records.
Records explicitly contain registered source ID/name, official URL/title/date, canonical URL, bilingual titles/summaries, category/subcategory, business relevance, source_verification, editorial_origin, approval_status, supplement_id and content_sha256. HTTPS URLs must belong to the registered enabled official source. Meaningful query parameters remain part of identity; fragments, trailing slashes and UTM tracking normalize for duplicate checks.

The weekly item uses existing title/summary fields and one documented addition, `editorial_provenance`. Its origin is `manual_editorial_supplement`; `summary_basis=editorial_paraphrase_of_official_release` makes clear that summary_original/summary_en are an editor's English paraphrase, not a verbatim collected article excerpt. The provenance binds the supplement identity, content hash, source verification and human approval. Automated originals receive no such marker.

Weekly counts are updated only for appended articles: item_count, pipeline_counts.final_weekly_items and the documented pipeline_counts.editorial_supplements. Earlier collection counts and source_status bytes remain unchanged. Mapping, relevance scores, highlight selection and QA use existing logic.

## Explicit offline replay

Use the usual immutable snapshot/provenance arguments plus:

```text
--supplement-file manual_supplements/approved/weekly_20261005.json
--supplement-sha256 <SHA-256 of the exact human-approved file>
```

Both flags are required together. Missing files, draft paths/status, incomplete approval metadata, unknown/disabled sources, unofficial URLs, wrong dates, hashes, identities or duplicates fail closed. All existing translation approvals must match before supplements are applied. No failure falls back to collection or model inference.

## Production Review Artifact after approval

Run the existing Production workflow manually on current main with:

```yaml
week_start: '2026-10-05'
generation_mode: snapshot
snapshot_artifact_id: '11724736313'
snapshot_artifact_name: weekly-report-debug-38196887790-1
snapshot_sha256: 27045723754fd37a611d436c95c74120a3940c9588a9b34317969b5b6f431eec
collection_run_id: '38196887790'
collection_sha: a2b550e8b903a339c74eb8302148cb94637aabb3
apply_editorial_supplements: true
supplement_sha256: <approved file SHA-256>
```

This creates a new GitHub run with its own generation SHA/run ID. Run #49 is a reference baseline, not reused generation provenance. The original Run #46 ZIP stays immutable. Remote artifact expiry still applies; a local backup does not automatically replace the workflow's remote input.

The Review Bundle includes the exact approved document as editorial_supplements_20261005.json. Its file hash, all record identities/content hashes, human approval, original-item digest and appended weekly content are checked by the existing bundle-validation path. Provenance distinguishes original collection, translations, supplements and the new replay generation. Without supplements the old replay behavior and manifest remain unchanged.

No source-health warning is cleared by supplementation. A successful new Review Artifact may retain WARNING. Approved Publish remains separate and manual, requiring a successful current-main run, valid integrity checks and explicit WARNING approval. Generating a review does not publish it.
