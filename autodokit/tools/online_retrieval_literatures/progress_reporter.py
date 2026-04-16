"""在线检索批处理进度输出工具。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _normalize_text(value: Any) -> str:
	return re.sub(r"\s+", " ", str(value or "")).strip()


def _clip_text(value: Any, max_length: int = 80) -> str:
	text = _normalize_text(value)
	if len(text) <= max_length:
		return text
	return text[: max(0, max_length - 3)] + "..."


def format_progress_line(
	*,
	prefix: str,
	total: int,
	completed: int,
	current_label: str,
	current_status: str,
	counters: dict[str, Any] | None = None,
	bar_width: int = 24,
) -> str:
	"""格式化批处理进度行。"""

	total_count = max(int(total or 0), 0)
	done_count = min(max(int(completed or 0), 0), total_count if total_count > 0 else int(completed or 0))
	pending_count = max(total_count - done_count, 0)
	ratio = (done_count / total_count) if total_count > 0 else 1.0

	width = max(int(bar_width or 24), 8)
	filled = min(int(round(width * ratio)), width)
	bar = "#" * filled + "-" * (width - filled)

	kv_text = ""
	if counters:
		parts = [f"{_normalize_text(k)}={_normalize_text(v)}" for k, v in counters.items()]
		kv_text = " | " + ", ".join(parts)

	return (
		f"[{_clip_text(prefix, 24)}] "
		f"|{bar}| {done_count}/{total_count} "
		f"({ratio * 100:5.1f}%) remain={pending_count} "
		f"current={_clip_text(current_label, 72)} "
		f"status={_clip_text(current_status, 24)}"
		f"{kv_text}"
	)


def print_progress_line(
	*,
	prefix: str,
	total: int,
	completed: int,
	current_label: str,
	current_status: str,
	counters: dict[str, Any] | None = None,
) -> str:
	"""打印一行进度信息并返回该文本。"""

	line = format_progress_line(
		prefix=prefix,
		total=total,
		completed=completed,
		current_label=current_label,
		current_status=current_status,
		counters=counters,
	)
	print(line, flush=True)
	return line


def write_progress_snapshot(path: Path, payload: dict[str, Any]) -> None:
	"""写入批处理实时快照。"""

	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
