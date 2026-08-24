import argparse

from crawler.collector import collect_week
from generate_weekly import render_report


def parse_args():
    parser = argparse.ArgumentParser(description="Generate DBG weekly intelligence report.")
    parser.add_argument("--start", help="Target week Monday in YYYY-MM-DD format.")
    parser.add_argument("--no-translate", action="store_true", help="Skip title translation.")
    return parser.parse_args()


def main():
    args = parse_args()
    result = collect_week(start_arg=args.start, translate=not args.no_translate)
    html_path, weekly_data_path, highlight_count = render_report(args.start)

    print("\nWeekly report generated")
    print(f"Week: {result['week_start']} to {result['week_end']}")
    print(f"Sources: {result['source_count']}")
    print(f"Registered sources: {result['registered_source_count']}")
    print(f"Items: {len(result['items'])}")
    print(f"Raw: {result['raw_path']}")
    print(f"Log: {result['log_path']}")
    print(f"Weekly data: {weekly_data_path}")
    print(f"Source status: {result['source_status_path']}")
    print(f"Relevance rejected: {result['relevance_rejected_path']}")
    print(f"HTML: {html_path}")
    print("Pipeline counts:")
    labels = [
        ("Candidates", "candidates"),
        ("Candidates scanned", "candidates_scanned"),
        ("List items with date", "list_items_with_date"),
        ("Detail pages requested", "detail_pages_requested"),
        ("Date parsed", "valid_dates"),
        ("Within target week", "within_target_week"),
        ("After relevance filter", "after_relevance_filter"),
        ("After dedupe", "after_dedupe"),
        ("Same-event clustered", "same_event_clustered_count"),
        ("After same-event cluster", "after_same_event_cluster"),
        ("Final weekly items", "final_weekly_items"),
    ]
    for label, key in labels:
        print(f"  {label}: {result['pipeline_counts'][key]}")
    print(f"  Highlights: {highlight_count}")
    print("Source summary:")
    for status, count in sorted(result["source_status_summary"].items()):
        print(f"  {status}: {count}")


if __name__ == "__main__":
    main()
