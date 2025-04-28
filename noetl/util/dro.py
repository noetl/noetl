"""
dro.py - დრო (Time)
"""

from datetime import datetime, timedelta, timezone

def get_duration_seconds(start_date, end_date) -> int | None:
    return int((start_date - end_date).total_seconds())

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def today_utc() -> datetime:
    now = now_utc()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)

def start_of_week_utc(reference: datetime = None) -> datetime:
    if reference is None:
        reference = now_utc()
    monday = reference - timedelta(days=reference.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)

def add_days(base: datetime, days: int) -> datetime:
    return base + timedelta(days=days)

def add_weeks(base: datetime, weeks: int) -> datetime:
    return base + timedelta(weeks=weeks)

def end_month(date: datetime) -> datetime:
    next_month = date.replace(day=28) + timedelta(days=4)
    last_day = next_month - timedelta(days=next_month.day)
    return last_day.replace(hour=23, minute=59, second=59, microsecond=999999)

def format_iso8601(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()

def format_readable(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%d %H:%M:%S UTC')

def parse_iso8601(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str)

def days_between(start: datetime, end: datetime) -> int:
    delta = end - start
    return delta.days

def is_weekend(date: datetime) -> bool:
    return date.weekday() >= 5

def next_weekday(date: datetime, weekday: int) -> datetime:
    days_ahead = weekday - date.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return date + timedelta(days=days_ahead)