#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from crawler.date_utils import parse_week_start, week_file_key
from crawler.manual_translations import ManualTranslationError, apply_workbook


BASE_DIR = REPO_ROOT


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Validate and approve manually supplied translations.")
    parser.add_argument("--week-start", required=True, help="Target week Monday in YYYY-MM-DD format.")
    parser.add_argument("--input", help="Optional manual translation workbook path.")
    parser.add_argument("--output", help="Optional approved JSON output path.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        week_start, _ = parse_week_start(args.week_start)
        compact = week_file_key(week_start)
        input_path = Path(args.input) if args.input else (
            BASE_DIR / "manual_translations" / "inbox" / f"manual_translation_queue_{compact}.xlsx"
        )
        output_path = Path(args.output) if args.output else (
            BASE_DIR / "manual_translations" / "approved" / f"weekly_{compact}.json"
        )
        if not input_path.exists():
            raise ManualTranslationError(f"Manual translation workbook not found: {input_path}")
        payload = apply_workbook(input_path, week_start.isoformat(), output_path)
    except (ManualTranslationError, ValueError) as exc:
        print(f"MANUAL TRANSLATION ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Approved manual translations: {len(payload['overrides'])}")
    print(f"Approved JSON: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
