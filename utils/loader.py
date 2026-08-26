import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
PUBLISHED_DIR = BASE_DIR / "published"
ARCHIVE_DIR = PUBLISHED_DIR / "archive"
LATEST_FILE = PUBLISHED_DIR / "latest.json"


def list_published_reports():
    reports = []
    seen = set()

    if LATEST_FILE.exists():
        latest_payload = load_news_payload(LATEST_FILE)
        latest_key = (latest_payload.get("week_start"), latest_payload.get("week_end"))
        reports.append(LATEST_FILE)
        seen.add(latest_key)

    if ARCHIVE_DIR.exists():
        for path in sorted(ARCHIVE_DIR.glob("weekly_*.json"), reverse=True):
            payload = load_news_payload(path)
            key = (payload.get("week_start"), payload.get("week_end"))
            if key in seen:
                continue
            reports.append(path)
            seen.add(key)
    return reports


def report_label(path):
    payload = load_news_payload(path)
    start = payload.get("week_start", "")
    end = payload.get("week_end", "")
    return f"{start} – {end}" if start and end else path.stem


def latest_weekly_data_file():
    if LATEST_FILE.exists():
        return LATEST_FILE
    reports = list_published_reports()
    if reports:
        return reports[0]
    return None


def load_news_payload(path=None):
    target = Path(path) if path else latest_weekly_data_file()
    if target is None or not target.exists():
        return {
            "week_start": "",
            "week_end": "",
            "source_count": 0,
            "registered_source_count": 0,
            "item_count": 0,
            "items": [],
            "highlights": [],
            "sections": [],
        }

    with target.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        return data

    return {
        "week_start": "",
        "week_end": "",
        "source_count": "",
        "item_count": len(data),
        "items": data,
    }


def load_news():
    return load_news_payload()["items"]
