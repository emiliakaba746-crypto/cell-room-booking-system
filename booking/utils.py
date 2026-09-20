"""Shared helpers for the cell-room booking application."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
SLOT_MINUTES = 30
DAY_MINUTES = 24 * 60


def combine_local(day: date, hour: int, minute: int = 0) -> datetime:
    """Return an aware Shanghai datetime for a calendar day and clock time."""
    return datetime.combine(day, time(hour=hour, minute=minute), tzinfo=SHANGHAI)


def build_datetime_range(day: date, start_minutes: int, end_minutes: int) -> tuple[datetime, datetime]:
    """Convert minute offsets from midnight into an aware half-open range.

    ``end_minutes`` may equal 1440 (24:00), which is represented as midnight
    on the following calendar day.
    """
    if start_minutes < 0 or start_minutes >= DAY_MINUTES:
        raise ValueError("开始时间必须在 00:00 到 23:59 之间")
    if end_minutes <= 0 or end_minutes > DAY_MINUTES:
        raise ValueError("结束时间必须在 00:01 到 24:00 之间")
    if end_minutes <= start_minutes:
        raise ValueError("结束时间必须晚于开始时间")

    start = combine_local(day, start_minutes // 60, start_minutes % 60)
    end_day = day + timedelta(days=1) if end_minutes == DAY_MINUTES else day
    end = combine_local(end_day, (end_minutes // 60) % 24, end_minutes % 60)
    return start, end


def minute_offset(value: str) -> int:
    """Parse ``HH:MM`` or ``24:00`` into minutes from midnight."""
    if value == "24:00":
        return DAY_MINUTES
    parsed = datetime.strptime(value, "%H:%M")
    return parsed.hour * 60 + parsed.minute


def format_minutes(value: int) -> str:
    if value == DAY_MINUTES:
        return "24:00"
    return f"{value // 60:02d}:{value % 60:02d}"


def parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def format_local(value: str | datetime, pattern: str = "%m-%d %H:%M") -> str:
    return parse_timestamp(value).strftime(pattern)


def duration_minutes(start: str | datetime, end: str | datetime) -> int:
    delta = parse_timestamp(end) - parse_timestamp(start)
    return max(0, int(delta.total_seconds() // 60))


def is_same_local_day(start: str | datetime, end: str | datetime) -> bool:
    start_local = parse_timestamp(start)
    end_local = parse_timestamp(end)
    # A booking ending exactly at 24:00 has its end instant at the next day's
    # midnight, but it still belongs to the selected day.
    if end_local.hour == 0 and end_local.minute == 0 and end_local.second == 0:
        end_local = end_local - timedelta(microseconds=1)
    return start_local.date() == end_local.date()


def validate_booking_range(day: date, start_minutes: int, end_minutes: int) -> tuple[datetime, datetime]:
    start, end = build_datetime_range(day, start_minutes, end_minutes)
    if not is_same_local_day(start, end):
        raise ValueError("预约必须位于同一天内")
    if duration_minutes(start, end) > DAY_MINUTES:
        raise ValueError("单次预约不能超过 24 小时")
    return start, end
