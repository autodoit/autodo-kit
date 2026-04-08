"""统一时间工具（默认北京时间）。

本模块用于统一生成带时区的时间字符串，默认使用中国大陆标准时区
`Asia/Shanghai`。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE_NAME = "Asia/Shanghai"


def resolve_timezone_name(timezone_name: str | None = None) -> str:
    """解析时区名称。"""

    text = str(timezone_name or "").strip()
    return text or DEFAULT_TIMEZONE_NAME


def resolve_timezone(timezone_name: str | None = None) -> ZoneInfo:
    """解析时区对象。"""

    return ZoneInfo(resolve_timezone_name(timezone_name))


def now_dt(timezone_name: str | None = None) -> datetime:
    """返回指定时区下当前时间。"""

    return datetime.now(tz=resolve_timezone(timezone_name))


def now_iso(timezone_name: str | None = None, *, timespec: str | None = None) -> str:
    """返回 ISO8601 时间字符串。"""

    current = now_dt(timezone_name)
    if timespec:
        return current.isoformat(timespec=timespec)
    return current.isoformat()


def now_compact(timezone_name: str | None = None, fmt: str = "%Y%m%d%H%M%S") -> str:
    """返回紧凑时间字符串。"""

    return now_dt(timezone_name).strftime(fmt)


def now_year(timezone_name: str | None = None) -> int:
    """返回当前年份。"""

    return now_dt(timezone_name).year


__all__ = [
    "DEFAULT_TIMEZONE_NAME",
    "resolve_timezone_name",
    "resolve_timezone",
    "now_dt",
    "now_iso",
    "now_compact",
    "now_year",
]
