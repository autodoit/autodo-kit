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


def convert_timestamp_to_timezone(
    timestamp: str,
    *,
    target_timezone: str | None = None,
    assume_timezone: str = "UTC",
) -> str:
    """把时间字符串转换到目标时区。

    Args:
        timestamp: 待转换的时间字符串（ISO 8601）；结尾为 `Z` 时按 UTC 处理。
        target_timezone: 目标时区名；省略时用默认时区。
        assume_timezone: 原字符串不带时区信息时的假定时区。

    Returns:
        str: 目标时区下的 ISO 时间字符串；输入为空时返回空串。

    Raises:
        ValueError: 时间字符串无法解析。

    Examples:
        convert_timestamp_to_timezone("2026-01-01T00:00:00Z")
    """

    raw = str(timestamp or "").strip()
    if not raw:
        return ""

    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=resolve_timezone(assume_timezone))
    return parsed.astimezone(resolve_timezone(target_timezone)).isoformat()


__all__ = [
    "DEFAULT_TIMEZONE_NAME",
    "convert_timestamp_to_timezone",
    "now_compact",
    "now_dt",
    "now_iso",
    "now_year",
    "resolve_timezone",
    "resolve_timezone_name",
]
