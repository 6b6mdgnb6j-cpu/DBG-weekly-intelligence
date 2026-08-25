from datetime import datetime, time, timedelta
from email.utils import parsedate_to_datetime
import re


DISPLAY_DATE_FORMAT = "%Y-%m-%d"


def parse_week_start(value=None):
    if value:
        start = datetime.strptime(value, DISPLAY_DATE_FORMAT).date()
    else:
        today = datetime.today().date()
        this_monday = today - timedelta(days=today.weekday())
        start = this_monday - timedelta(days=7)

    if start.weekday() != 0:
        raise ValueError("--start must be a Monday in YYYY-MM-DD format")

    end = start + timedelta(days=6)
    return start, end


def week_file_key(start):
    return start.strftime("%Y%m%d")


def in_week(date_value, start, end):
    parsed = parse_any_date(date_value)
    if not parsed:
        return False
    return start <= parsed.date() <= end


US_MM_DD_YYYY_SOURCE_IDS = {"SRC-013", "SRC-014", "SRC-016"}
US_MM_DD_YYYY_SOURCE_NAMES = {"商品期货交易委员会", "CFTC", "货币监理署", "全国信用社管理局"}


def source_uses_us_numeric_dates(source=None):
    if not source:
        return False
    source_id = source.get("id", "")
    source_name = source.get("name", "")
    return source_id in US_MM_DD_YYYY_SOURCE_IDS or source_name in US_MM_DD_YYYY_SOURCE_NAMES


def normalize_date(date_value, source=None):
    parsed = parse_date_for_source(date_value, source)
    if not parsed:
        return ""
    return parsed.strftime(DISPLAY_DATE_FORMAT)


def parse_date_for_source(value, source=None):
    if source_uses_us_numeric_dates(source):
        parsed = parse_us_numeric_date(value)
        if parsed:
            return parsed
    return parse_any_date(value)


def parse_us_numeric_date(value):
    text = str(value or "").strip()
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if not match:
        return None
    month, day, year = match.groups()
    try:
        return datetime(int(year), int(month), int(day))
    except ValueError:
        return None


def parse_any_date(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = parsedate_to_datetime(text)
        if parsed:
            return parsed.replace(tzinfo=None)
    except Exception:
        pass

    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%d %b, %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(fmt))], fmt)
        except Exception:
            continue

    return None


def week_bounds_datetimes(start, end):
    return (
        datetime.combine(start, time.min),
        datetime.combine(end, time.max),
    )
