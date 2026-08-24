import json
from pathlib import Path


def latest_weekly_data_file():
    output_dir = Path("output")
    files = sorted(output_dir.glob("weekly_data_*.json"))
    if files:
        return files[-1]
    return Path("data/news.json")


def load_news_payload():
    path = latest_weekly_data_file()
    with open(path, "r", encoding="utf-8") as f:
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
