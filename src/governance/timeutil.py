"""跨时区时点处理。

系统内一切先后判断都以 UTC 时刻为准，本地日期只用于展示。
这样跨时区换日（同一时刻在不同时区落在不同日历日）不会影响
任期、法定人数、表决窗口等判断。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .errors import ValidationError


def require_aware(value: datetime, field: str = "时间") -> datetime:
    """拒绝不带时区的时刻，避免隐式解释。"""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{field}必须携带时区信息")
    return value


def to_utc(value: datetime) -> datetime:
    """把任意带时区的时刻归一到 UTC。"""
    return require_aware(value).astimezone(timezone.utc)


def local_date(value: datetime, zone: str) -> date:
    """时刻在指定时区的本地日期，仅用于展示与议程排版。"""
    return to_utc(value).astimezone(ZoneInfo(zone)).date()


def covers(start: datetime, end: datetime, instant: datetime) -> bool:
    """半开区间 [start, end) 是否覆盖指定时刻（按 UTC 比较）。"""
    return to_utc(start) <= to_utc(instant) < to_utc(end)
