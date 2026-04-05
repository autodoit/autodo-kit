"""Obsidian 笔记时间元数据工具。

用于统一处理 Markdown frontmatter 中的 `created`、`updated` 等时间字段，
默认以北京时间 `Asia/Shanghai` 作为输出时区，同时允许国际用户显式指定其它时区。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo


DEFAULT_OBSIDIAN_NOTE_TIMEZONE = "Asia/Shanghai"
DEFAULT_OBSIDIAN_TIME_FIELDS: tuple[str, ...] = ("created", "updated")


def _split_frontmatter(text: str) -> tuple[str, str, str]:
    """拆分 Markdown frontmatter 与正文。"""

    raw_text = str(text or "")
    if not raw_text.startswith("---"):
        return "", "", raw_text

    marker = raw_text.find("\n---\n")
    if marker < 0:
        return "", "", raw_text

    frontmatter = raw_text[4:marker]
    body = raw_text[marker + 5 :]
    return "---\n", frontmatter, body


def _resolve_timezone(timezone_name: str | None = None) -> ZoneInfo:
    """解析时区对象。"""

    return ZoneInfo(str(timezone_name or DEFAULT_OBSIDIAN_NOTE_TIMEZONE).strip() or DEFAULT_OBSIDIAN_NOTE_TIMEZONE)


def get_current_time_iso(timezone_name: str = DEFAULT_OBSIDIAN_NOTE_TIMEZONE) -> str:
    """返回指定时区下的当前 ISO 时间字符串。"""

    return datetime.now(tz=_resolve_timezone(timezone_name)).isoformat()


def convert_timestamp_to_timezone(
    timestamp: str,
    *,
    target_timezone: str = DEFAULT_OBSIDIAN_NOTE_TIMEZONE,
    assume_timezone: str = "UTC",
) -> str:
    """把单个时间字符串转换到目标时区。"""

    raw = str(timestamp or "").strip()
    if not raw:
        return ""

    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_resolve_timezone(assume_timezone))
    return parsed.astimezone(_resolve_timezone(target_timezone)).isoformat()


def rewrite_obsidian_note_timestamps(
    note_path: str | Path,
    *,
    target_timezone: str = DEFAULT_OBSIDIAN_NOTE_TIMEZONE,
    fields: Sequence[str] = DEFAULT_OBSIDIAN_TIME_FIELDS,
    assume_timezone: str = "UTC",
    fill_missing: bool = False,
) -> dict[str, Any]:
    """重写单篇 Obsidian 笔记的时间元数据。"""

    path = Path(note_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"笔记文件不存在：{path}")

    text = path.read_text(encoding="utf-8")
    prefix, frontmatter, body = _split_frontmatter(text)
    if not frontmatter.strip():
        return {
            "note_path": str(path),
            "changed": False,
            "target_timezone": target_timezone,
            "updated_fields": {},
            "missing_frontmatter": True,
        }

    remaining_fields = list(fields)
    updated_fields: dict[str, str] = {}
    changed = False
    rewritten_lines: list[str] = []
    for line in frontmatter.splitlines():
        replaced = False
        for field in list(remaining_fields):
            match = re.match(rf"^(\s*{re.escape(field)}\s*:\s*)(.*)$", line)
            if not match:
                continue
            prefix_text, raw_value = match.groups()
            current_value = raw_value.strip().strip('"').strip("'")
            if current_value:
                new_value = convert_timestamp_to_timezone(
                    current_value,
                    target_timezone=target_timezone,
                    assume_timezone=assume_timezone,
                )
            elif fill_missing:
                new_value = get_current_time_iso(target_timezone)
            else:
                new_value = current_value
            rewritten_line = f'{prefix_text}"{new_value}"' if new_value else line
            rewritten_lines.append(rewritten_line)
            if rewritten_line != line:
                changed = True
            if new_value:
                updated_fields[field] = new_value
            remaining_fields.remove(field)
            replaced = True
            break
        if not replaced:
            rewritten_lines.append(line)

    if fill_missing and remaining_fields:
        for field in remaining_fields:
            new_value = get_current_time_iso(target_timezone)
            rewritten_lines.append(f'{field}: "{new_value}"')
            updated_fields[field] = new_value
            changed = True

    if changed:
        content = f"{prefix}---\n" + "\n".join(rewritten_lines).rstrip() + f"\n---\n\n{body.lstrip()}"
        path.write_text(content, encoding="utf-8")

    return {
        "note_path": str(path),
        "changed": changed,
        "target_timezone": target_timezone,
        "updated_fields": updated_fields,
        "missing_frontmatter": False,
    }


def batch_rewrite_obsidian_note_timestamps(
    *,
    note_paths: Iterable[str | Path] | None = None,
    note_dir: str | Path | None = None,
    glob_pattern: str = "**/*.md",
    target_timezone: str = DEFAULT_OBSIDIAN_NOTE_TIMEZONE,
    fields: Sequence[str] = DEFAULT_OBSIDIAN_TIME_FIELDS,
    assume_timezone: str = "UTC",
    fill_missing: bool = False,
) -> dict[str, Any]:
    """批量重写 Obsidian 笔记时间元数据。"""

    resolved_paths: list[Path] = []
    seen: set[str] = set()
    for raw_path in note_paths or []:
        path = Path(raw_path).expanduser().resolve()
        key = str(path)
        if key not in seen:
            seen.add(key)
            resolved_paths.append(path)
    if note_dir is not None:
        for path in Path(note_dir).expanduser().resolve().glob(glob_pattern):
            if not path.is_file():
                continue
            key = str(path.resolve())
            if key not in seen:
                seen.add(key)
                resolved_paths.append(path.resolve())

    results: list[dict[str, Any]] = []
    changed_count = 0
    for path in resolved_paths:
        result = rewrite_obsidian_note_timestamps(
            path,
            target_timezone=target_timezone,
            fields=fields,
            assume_timezone=assume_timezone,
            fill_missing=fill_missing,
        )
        results.append(result)
        if result.get("changed"):
            changed_count += 1

    return {
        "target_timezone": target_timezone,
        "processed_count": len(resolved_paths),
        "changed_count": changed_count,
        "results": results,
    }


__all__ = [
    "DEFAULT_OBSIDIAN_NOTE_TIMEZONE",
    "DEFAULT_OBSIDIAN_TIME_FIELDS",
    "get_current_time_iso",
    "convert_timestamp_to_timezone",
    "rewrite_obsidian_note_timestamps",
    "batch_rewrite_obsidian_note_timestamps",
]