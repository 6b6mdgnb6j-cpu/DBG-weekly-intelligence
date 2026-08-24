import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from crawler.highlight_ranker import select_highlights

OUTPUT_DIR = BASE_DIR / "output"
CONFIG_FILE = BASE_DIR / "config" / "sources.json"

ADAPTER_SOURCE_IDS = {
    "SRC-006",
    "SRC-007",
    "SRC-023",
    "SRC-026",
    "SRC-040",
    "SRC-045",
    "SRC-064",
    "SRC-073",
    "SRC-089",
    "SRC-143",
    "SRC-144",
    "SRC-152",
}

FAILURE_STATUSES = {
    "network_error",
    "blocked",
    "js_required",
    "date_parse_failed",
    "parser_failed",
    "invalid_config",
    "no_candidates",
}

USABLE_ZERO_STATUSES = {
    "success",
    "true_no_updates",
    "all_outside_period",
    "relevance_filtered",
}

CRITICAL_TERMS = [
    "fomc",
    "federal open market committee",
    "proposed rule",
    "proposed rulemaking",
    "notice of proposed rulemaking",
    "rulemaking",
    "nprm",
    "monetary policy",
    "financial regulation",
    "financial regulatory working group",
    "joint statement",
    "capital market",
    "financial results",
    "earnings",
    "quarterly results",
    "clearing",
    "settlement",
    "derivatives",
    "market infrastructure",
    "cross-border",
    "market access",
    "ownership datasets",
    "sovereign bonds",
    "insurance funds",
    "exchange product",
    "trading volume",
    "clearing volume",
    "partnership",
    "market-wide",
    "systemic",
]


def week_key(value):
    return value.replace("-", "")


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_source_maps():
    sources = load_json(CONFIG_FILE, [])
    by_name = {source.get("name", ""): source for source in sources}
    adapter_names = {
        source.get("name", "")
        for source in sources
        if source.get("id") in ADAPTER_SOURCE_IDS and source.get("enabled")
    }
    return by_name, adapter_names


def summarize_week(week_start, source_by_name, adapter_names):
    key = week_key(week_start)
    weekly = load_json(OUTPUT_DIR / f"weekly_data_{key}.json", {})
    statuses = load_json(OUTPUT_DIR / f"source_status_{key}.json", [])
    rejected = load_json(OUTPUT_DIR / f"relevance_rejected_{key}.json", [])
    pipeline = weekly.get("pipeline_counts", {})
    highlights = select_highlights(weekly.get("items", []))
    status_counter = Counter(status.get("status", "") for status in statuses)
    successful_sources = sum(1 for status in statuses if status.get("status") in USABLE_ZERO_STATUSES)
    failed_sources = sum(1 for status in statuses if status.get("status") in FAILURE_STATUSES)

    adapter_performance = {}
    for status in statuses:
        name = status.get("source", "")
        if name not in adapter_names:
            continue
        adapter_performance[name] = {
            "status": status.get("status", ""),
            "candidates_discovered": status.get("candidates_discovered", 0),
            "candidates_scanned": status.get("candidates_scanned", 0),
            "list_items_with_date": status.get("list_items_with_date", 0),
            "detail_pages_requested": status.get("detail_pages_requested", 0),
            "dated_candidates": status.get("dated_candidates", 0),
            "within_period": status.get("within_period", 0),
            "after_relevance": status.get("after_relevance", 0),
            "final_items": status.get("final_items", 0),
            "target_period_reached": status.get("target_period_reached", False),
            "stopped_reason": status.get("stopped_reason", ""),
            "newest_date_seen": status.get("newest_date_seen", ""),
            "oldest_date_seen": status.get("oldest_date_seen", ""),
        }

    return {
        "week_start": week_start,
        "week_end": weekly.get("week_end", ""),
        "registered_sources": weekly.get("registered_source_count", len(source_by_name)),
        "enabled_sources": weekly.get("source_count", len(statuses)),
        "candidates": pipeline.get("candidates", 0),
        "candidates_scanned": pipeline.get("candidates_scanned", 0),
        "list_items_with_date": pipeline.get("list_items_with_date", 0),
        "detail_pages_requested": pipeline.get("detail_pages_requested", 0),
        "date_parsed": pipeline.get("valid_dates", 0),
        "within_period": pipeline.get("within_target_week", 0),
        "after_relevance": pipeline.get("after_relevance_filter", 0),
        "after_dedupe": pipeline.get("after_dedupe", 0),
        "final_items": pipeline.get("final_weekly_items", weekly.get("item_count", 0)),
        "highlights": len(highlights),
        "highlight_titles": [
            item.get("title_cn") or item.get("title_original", "")
            for item in highlights
        ],
        "source_status_distribution": dict(sorted(status_counter.items())),
        "successful_sources": successful_sources,
        "failed_sources": failed_sources,
        "adapter_performance": adapter_performance,
        "relevance_rejected": len(rejected),
        "rejection_categories": dict(sorted(Counter(item.get("rejection_category", "other") for item in rejected).items())),
    }


def build_relevance_audit(weeks):
    weekly = []
    category_totals = Counter()
    source_totals = Counter()
    possible_false_rejections = []

    for week_start in weeks:
        key = week_key(week_start)
        data = load_json(OUTPUT_DIR / f"weekly_data_{key}.json", {})
        rejected = load_json(OUTPUT_DIR / f"relevance_rejected_{key}.json", [])
        pipeline = data.get("pipeline_counts", {})
        within = int(pipeline.get("within_target_week", 0) or 0)
        retained = int(pipeline.get("after_relevance_filter", 0) or 0)
        rejected_count = len(rejected)
        categories = Counter(item.get("rejection_category", "other") for item in rejected)
        for category, count in categories.items():
            category_totals[category] += count
        for item in rejected:
            source_totals[item.get("source", "")] += 1
            text = " ".join(
                [
                    item.get("title", ""),
                    item.get("relevance_reason", ""),
                    " ".join(item.get("positive_signals", [])),
                ]
            ).lower()
            if any(term in text for term in CRITICAL_TERMS) and item.get("rejection_category") not in {
                "routine enforcement",
                "personnel",
                "conference/event",
                "generic marketing",
                "false candidate",
            }:
                possible_false_rejections.append(item | {"week_start": week_start})

        weekly.append(
            {
                "week_start": week_start,
                "total_within_period_items": within,
                "retained": retained,
                "rejected": rejected_count,
                "rejection_rate": round(rejected_count / within, 4) if within else 0,
                "rejection_categories": dict(sorted(categories.items())),
            }
        )

    return {
        "weeks": weekly,
        "total_within_period_items": sum(item["total_within_period_items"] for item in weekly),
        "retained": sum(item["retained"] for item in weekly),
        "rejected": sum(item["rejected"] for item in weekly),
        "rejection_rate": round(
            sum(item["rejected"] for item in weekly)
            / max(sum(item["total_within_period_items"] for item in weekly), 1),
            4,
        ),
        "rejection_categories": dict(sorted(category_totals.items())),
        "rejections_by_source": dict(sorted(source_totals.items())),
        "possible_false_rejections": possible_false_rejections[:25],
    }


def build_regression_summary(weeks):
    source_by_name, adapter_names = load_source_maps()
    week_summaries = [summarize_week(week, source_by_name, adapter_names) for week in weeks]

    source_weeks = defaultdict(list)
    for summary in week_summaries:
        key = week_key(summary["week_start"])
        statuses = load_json(OUTPUT_DIR / f"source_status_{key}.json", [])
        for status in statuses:
            source_weeks[status.get("source", "")].append(status.get("status", ""))

    stable_sources = [
        source
        for source, statuses in source_weeks.items()
        if len(statuses) == len(weeks) and all(status in USABLE_ZERO_STATUSES for status in statuses)
    ]
    needs_attention = {
        source: Counter(statuses)
        for source, statuses in source_weeks.items()
        if source not in stable_sources
    }

    adapter_cross_week = defaultdict(dict)
    for summary in week_summaries:
        for source, performance in summary["adapter_performance"].items():
            adapter_cross_week[source][summary["week_start"]] = performance

    return {
        "weeks": week_summaries,
        "adapter_cross_week_performance": adapter_cross_week,
        "stable_usable_sources": len(stable_sources),
        "stable_usable_source_names": stable_sources,
        "sources_needing_attention": {
            source: dict(counter)
            for source, counter in sorted(needs_attention.items())
        },
    }


def main(argv):
    weeks = argv or ["2026-07-27", "2026-08-03", "2026-08-10", "2026-08-17"]
    regression = build_regression_summary(weeks)
    relevance = build_relevance_audit(weeks)
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "regression_summary.json").write_text(
        json.dumps(regression, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "relevance_audit_summary.json").write_text(
        json.dumps(relevance, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("Saved output/regression_summary.json")
    print("Saved output/relevance_audit_summary.json")


if __name__ == "__main__":
    main(sys.argv[1:])
