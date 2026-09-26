"""时间工具：所有内部时刻都以 UTC 保存，展示与“当地日期”才换算。

跨时区换日时，会议是否召开、任期是否有效只取决于 UTC 时刻的先后，
不会因为观察地点不同而改变；需要按当地日期排列议程时再用 ``local_date``。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

#: 统一的时刻文本格式，尾部固定 Z，表示 UTC。
MOMENT = "%Y-%m-%dT%H:%M:%SZ"


def parse_moment(value: str) -> datetime:
    """把文本解析为 UTC ``datetime``；接受 Z 或显式偏移。"""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"时刻必须带时区信息: {value!r}")
    return dt.astimezone(timezone.utc)


def now() -> datetime:
    """当前 UTC 时刻。测试可通过构造参数注入时钟。"""
    return datetime.now(timezone.utc)


def to_text(dt: datetime) -> str:
    """格式化为规范的 UTC 文本。"""
    return dt.astimezone(timezone.utc).strftime(MOMENT)


def local_date(moment: datetime | str, zone: str) -> date:
    """返回某时刻在指定 IANA 时区下的当地日期，用于跨时区议程排序。"""
    dt = parse_moment(moment) if isinstance(moment, str) else moment
    return dt.astimezone(ZoneInfo(zone)).date()
