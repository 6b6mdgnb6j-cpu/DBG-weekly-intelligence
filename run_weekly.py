import argparse
import sys

from crawler.collector import collect_week
from generate_weekly import render_report
from qa_gate import FAIL, WARNING, run_qa


def parse_args():
    parser = argparse.ArgumentParser(description="Generate DBG weekly intelligence report.")
    parser.add_argument("--start", help="Target week Monday in YYYY-MM-DD format.")
    parser.add_argument("--no-translate", action="store_true", help="Skip title translation.")
    parser.add_argument("--skip-qa", action="store_true", help="Skip post-generation QA gate.")
    parser.add_argument("--fail-on-warning", action="store_true", help="Return non-zero when QA status is WARNING.")
    return parser.parse_args()


def print_generation_summary(result, html_path, weekly_data_path, highlight_count):
    print("\nWeekly generation complete.")
    print(f"Week: {result['week_start']} -> {result['week_end']}")
    print(f"Sources: {result['source_count']}")
    print(f"Registered sources: {result['registered_source_count']}")
    print(f"Final items: {len(result['items'])}")
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


def print_qa_summary(qa_result):
    report = qa_result["report"]
    failed = [check for check in report["checks"] if check["result"] == FAIL]
    warnings = [check for check in report["checks"] if check["result"] == WARNING]

    print("\nQA:")
    print(f"  Status: {qa_result['status']}")
    print(f"  Blocking issues: {qa_result['blocking_count']}")
    print(f"  Warnings: {qa_result['warning_count']}")
    print(f"  Known gaps: {qa_result['known_gap_count']}")
    if failed:
        print("  Blocking issue summary:")
        for check in failed[:5]:
            print(f"    - {check['id']}: {check['message']}")
    if warnings:
        print("  Warning summary:")
        for check in warnings[:5]:
            print(f"    - {check['id']}: {check['message']}")
    print(f"  Recommendation: {qa_result['publish_recommendation']}")
    print(f"  QA JSON: {qa_result['json_path']}")
    print(f"  QA Markdown: {qa_result['md_path']}")


def run_weekly(args):
    result = collect_week(start_arg=args.start, translate=not args.no_translate)
    html_path, weekly_data_path, highlight_count = render_report(args.start)

    print_generation_summary(result, html_path, weekly_data_path, highlight_count)

    if args.skip_qa:
        print("\nQA: skipped by user")
        return 0

    try:
        qa_result = run_qa(
            weekly_data_path=weekly_data_path,
            source_status_path=result["source_status_path"],
            fail_on_warning=args.fail_on_warning,
            expected_week_start=result["week_start"],
        )
    except Exception as exc:
        print("\nQA EXECUTION ERROR")
        print(str(exc))
        print("Weekly artifacts were preserved.")
        return 3

    print_qa_summary(qa_result)
    print("Weekly artifacts were preserved.")
    return qa_result["exit_code"]


def main():
    args = parse_args()
    return run_weekly(args)


if __name__ == "__main__":
    raise SystemExit(main())
