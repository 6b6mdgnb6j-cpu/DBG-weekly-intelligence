import html
import json
from pathlib import Path

from crawler.date_utils import parse_week_start, week_file_key
from crawler.highlight_ranker import select_highlights


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATE_FILE = BASE_DIR / "templates" / "report_template.html"


CATEGORY_ORDER = [
    ("Macro", "宏观政策与监管动态", "Macro Policy & Regulatory Updates"),
    ("DBG", "德交所集团内部动态", "DBG Internal Updates"),
    ("Competitor", "竞争对手动态", "Competitor News"),
]


SUBCATEGORY_ORDER = {
    "Macro": ["中国", "美国", "英国", "欧洲", "国际组织", "亚太", "其他地区"],
    "DBG": ["集团要闻", "交易与清算", "投资管理解决方案", "证券与基金服务", "信息技术"],
}


BRAND_ORDER = [
    "Eurex",
    "EEX",
    "360T",
    "Crypto Finance",
    "SimCorp",
    "ISS STOXX",
    "STOXX",
    "Clearstream",
    "DBG Market Data",
    "7 Market Technology",
]


def load_weekly_data(start):
    path = OUTPUT_DIR / f"weekly_data_{week_file_key(start)}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f), path


def build_group_config(items):
    config = []
    for category, label_cn, label_en in CATEGORY_ORDER:
        category_items = [item for item in items if item.get("category") == category]
        if category == "Competitor":
            groups = BRAND_ORDER[:]
            for item in category_items:
                brand = item.get("brand")
                if brand and brand not in groups:
                    groups.append(brand)
        else:
            groups = SUBCATEGORY_ORDER.get(category, [])[:]
            for item in category_items:
                subcategory = item.get("subcategory")
                if subcategory and subcategory not in groups:
                    groups.append(subcategory)

        config.append({
            "key": category,
            "label_cn": label_cn,
            "label_en": label_en,
            "groups": groups,
        })
    return config


def render_report(start_arg=None):
    week_start, _ = parse_week_start(start_arg)
    payload, weekly_data_path = load_weekly_data(week_start)
    items = payload.get("items", [])

    with open(TEMPLATE_FILE, encoding="utf-8") as f:
        template = f.read()

    highlights = select_highlights(items)
    report_data = {
        "week_start": payload.get("week_start"),
        "week_end": payload.get("week_end"),
        "source_count": payload.get("source_count", 0),
        "registered_source_count": payload.get("registered_source_count", payload.get("source_count", 0)),
        "item_count": payload.get("item_count", len(items)),
        "items": items,
        "highlights": highlights,
        "sections": build_group_config(items),
    }

    rendered = template.replace(
        "__REPORT_DATA__",
        html.escape(json.dumps(report_data, ensure_ascii=False), quote=False),
    )

    output_path = OUTPUT_DIR / f"weekly_report_{week_file_key(week_start)}.html"
    output_path.write_text(rendered, encoding="utf-8")

    return output_path, weekly_data_path, len(highlights)


if __name__ == "__main__":
    path, _, _ = render_report()
    print(path)
