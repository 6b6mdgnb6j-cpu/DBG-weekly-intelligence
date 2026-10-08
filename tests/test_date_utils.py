import unittest
from datetime import datetime as real_datetime
from unittest.mock import patch

from crawler.date_utils import parse_any_date, parse_date_for_source


class DateUtilsTests(unittest.TestCase):
    def assert_date(self, value, expected):
        parsed = parse_any_date(value)
        self.assertIsNotNone(parsed, value)
        self.assertEqual(parsed.date().isoformat(), expected)

    def test_textual_month_lengths_parse_deterministically(self):
        cases = {
            "10 September 2026": "2026-09-10",
            "05 October 2026": "2026-10-05",
            "03 February 2026": "2026-02-03",
            "01 May 2026": "2026-05-01",
            "10 Sep 2026": "2026-09-10",
            "05 Oct 2026": "2026-10-05",
            "03 Feb 2026": "2026-02-03",
            "01 May 2026": "2026-05-01",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assert_date(value, expected)

    def test_parsing_never_uses_current_clock_to_size_input(self):
        class ClockForbiddenDateTime:
            strptime = staticmethod(real_datetime.strptime)

            @classmethod
            def now(cls, *args, **kwargs):
                raise AssertionError("parse_any_date must not consult the current clock")

            @classmethod
            def today(cls, *args, **kwargs):
                raise AssertionError("parse_any_date must not consult the current clock")

        with patch("crawler.date_utils.datetime", ClockForbiddenDateTime), patch(
            "crawler.date_utils.parsedate_to_datetime", side_effect=ValueError("force format loop")
        ):
            september = parse_any_date("10 September 2026")
            may = parse_any_date("05 May 2026")

        self.assertEqual(september, real_datetime(2026, 9, 10))
        self.assertEqual(may, real_datetime(2026, 5, 5))

    def test_existing_exact_formats_remain_supported(self):
        cases = {
            "2026-09-10": "2026-09-10",
            "2026/09/10": "2026-09-10",
            "10.09.2026": "2026-09-10",
            "10/09/2026": "2026-09-10",
            "10 Sep 2026": "2026-09-10",
            "10 Sep, 2026": "2026-09-10",
            "September 10, 2026": "2026-09-10",
            "Sep 10, 2026": "2026-09-10",
            "2026-09-10T12:30:45": "2026-09-10",
            "2026-09-10T12:30:45Z": "2026-09-10",
            "2026-09-10 12:30:45": "2026-09-10",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assert_date(value, expected)

    def test_us_numeric_source_path_remains_month_first(self):
        source = {"id": "SRC-013", "name": "商品期货交易委员会"}
        parsed = parse_date_for_source("09/10/2026", source)

        self.assertEqual(parsed, real_datetime(2026, 9, 10))

    def test_invalid_and_embedded_inputs_fail_closed(self):
        for value in ("", "not a date", "31 February 2026", "Published 10 September 2026"):
            with self.subTest(value=value):
                self.assertIsNone(parse_any_date(value))


if __name__ == "__main__":
    unittest.main()
