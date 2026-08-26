import json
import shutil
import sys
from pathlib import Path

from crawler.highlight_ranker import select_highlights
from generate_weekly import build_group_config


BASE_DIR = Path(__file__).resolve().parent
PUBLISHED_DIR = BASE_DIR / "published"
ARCHIVE_DIR = PUBLISHED_DIR / "archive"

SOURCE_REQUIRED_FIELDS = ("week_start", "week_end", "items", "source_count")
PUBLISHED_REQUIRED_FIELDS = ("week_start", "week_end", "items", "highlights", "sections", "source_count")


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


def build_published_payload(payload):
    items = payload.get("items", [])
    published = {
        "week_start": payload.get("week_start"),
        "week_end": payload.get("week_end"),
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


def publish_weekly(source_path):
    payload = load_json(source_path)
    validate_source_payload(payload)
    published = build_published_payload(payload)

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    week_key = str(published["week_start"]).replace("-", "")
    archive_path = ARCHIVE_DIR / f"weekly_{week_key}.json"
    latest_path = PUBLISHED_DIR / "latest.json"

    archive_path.write_text(json.dumps(published, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(archive_path, latest_path)
    return archive_path, latest_path


def main(argv):
    if len(argv) != 2:
        raise SystemExit("Usage: python3 publish_weekly.py <weekly_json>")
    archive_path, latest_path = publish_weekly(Path(argv[1]))
    print(f"Published archive: {archive_path}")
    print(f"Updated latest: {latest_path}")


if __name__ == "__main__":
    main(sys.argv)
