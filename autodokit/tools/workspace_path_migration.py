"""工作区路径迁移工具。

用于在工作区迁移到新设备或新目录后，统一重写配置、产物与 SQLite 中写死的旧绝对路径。
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class PathMapping:
    """路径映射配置。

    Args:
        old_root: 旧根路径。
        new_root: 新根路径。

    Returns:
        None

    Raises:
        ValueError: 当旧根或新根为空时抛出。

    Examples:
        >>> PathMapping(old_root='/old/workspace', new_root='/new/workspace')
        PathMapping(old_root='/old/workspace', new_root='/new/workspace')
    """

    old_root: str
    new_root: str

    def __post_init__(self) -> None:
        if not self.old_root or not self.new_root:
            raise ValueError("old_root/new_root 不能为空")


@dataclass(frozen=True)
class MappingVariants:
    """映射的分隔符变体缓存。"""

    old_forward: str
    old_backward: str
    new_forward: str
    new_backward: str


TEXT_EXTENSIONS = {".md", ".txt", ".jsonl", ".log", ".py"}
DEFAULT_SCAN_DIRS = ("config", "tasks", "steps", "knowledge", "views", "batches", "references")
DEFAULT_SQLITE_PATHS = (
    "database/content/content.db",
    "database/decision/decision.db",
    "database/logs/aok_log.db",
    "database/tasks/tasks.db",
)
DEFAULT_EXCLUDED_PREFIXES = (
    str(Path.home() / ".copilot"),
)

DEFAULT_EXCLUDED_REGEX_PATTERNS = (
    re.compile(r"^[A-Z]:[/\\]Windows", flags=re.IGNORECASE),
    re.compile(r"^[A-Z]:[/\\]Program Files", flags=re.IGNORECASE),
    re.compile(r"^[D-Z]:[/\\]", flags=re.IGNORECASE),
)


def _normalize_root(path_text: str) -> str:
    raw = str(path_text).strip()
    if re.match(r"^[A-Za-z]:[/\\]", raw) or raw.startswith("\\\\"):
        return raw.rstrip("/\\")
    return str(Path(raw).expanduser().resolve()).rstrip("/\\")


def _build_variants(mapping: PathMapping) -> MappingVariants:
    old_root = _normalize_root(mapping.old_root)
    new_root = _normalize_root(mapping.new_root)
    return MappingVariants(
        old_forward=old_root.replace("\\", "/"),
        old_backward=old_root.replace("/", "\\"),
        new_forward=new_root.replace("\\", "/"),
        new_backward=new_root.replace("/", "\\"),
    )


def _starts_with_ci(text: str, prefix: str) -> bool:
    return text.lower().startswith(prefix.lower())


def _looks_like_path_text(value: str) -> bool:
    if not value:
        return False
    if value.startswith("http://") or value.startswith("https://"):
        return False
    if value.startswith("\\\\"):
        return True
    if ":/" in value or ":\\" in value:
        return True
    return "/" in value or "\\" in value


def _normalize_mapped_path(path_text: str, item: MappingVariants, token: str) -> str | None:
    normalized = path_text
    if "\\\\" in token:
        normalized = normalized.replace("\\\\", "/")
    else:
        normalized = normalized.replace("\\", "/")

    if not _starts_with_ci(normalized, item.old_forward):
        return None

    suffix = normalized[len(item.old_forward) :]
    return item.new_forward + suffix


def _normalize_target_path(path_text: str, item: MappingVariants, token: str) -> str | None:
    normalized = path_text
    if "\\\\" in token:
        normalized = normalized.replace("\\\\", "/")
    else:
        normalized = normalized.replace("\\", "/")

    if not _starts_with_ci(normalized, item.new_forward):
        return None

    return normalized


def _replace_embedded_paths(value: str, variants: Sequence[MappingVariants]) -> Tuple[str, int]:
    updated = value
    replaced = 0

    for item in variants:
        token_specs = (
            (item.old_forward, "old"),
            (item.old_backward, "old"),
            (item.old_backward.replace("\\", "\\\\"), "old"),
            (item.new_backward, "target"),
            (item.new_backward.replace("\\", "\\\\"), "target"),
        )
        seen_tokens = set()
        for token, kind in token_specs:
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
            pattern = re.compile(re.escape(token) + r"[^\"'\s,\]\}\)]*")

            def _repl(match: re.Match[str]) -> str:
                nonlocal replaced
                if kind == "target":
                    mapped = _normalize_target_path(match.group(0), item, token)
                else:
                    mapped = _normalize_mapped_path(match.group(0), item, token)
                if mapped is None:
                    return match.group(0)
                replaced += 1
                return mapped

            updated = pattern.sub(_repl, updated)

    return updated, replaced


def _replace_prefix(value: str, variants: Sequence[MappingVariants], excluded_prefixes: Sequence[str]) -> Tuple[str, bool, str]:
    """按映射规则替换字符串中的路径。

    Args:
        value: 待替换字符串。
        variants: 路径映射变体列表。
        excluded_prefixes: 不允许替换的前缀列表。

    Returns:
        三元组 (new_value, replaced, reason)。

    Raises:
        None.

    Examples:
        >>> v, changed, _ = _replace_prefix('/old/workspace/a.txt', [MappingVariants('/old/workspace', '\\\\old\\\\workspace', '/new/workspace', '\\\\new\\\\workspace')], [])
        >>> changed
        True
    """

    if not value:
        return value, False, "empty"

    for prefix in excluded_prefixes:
        if prefix and _starts_with_ci(value, prefix):
            return value, False, "excluded"

    for pattern in DEFAULT_EXCLUDED_REGEX_PATTERNS:
        if pattern.match(value):
            return value, False, "excluded"

    for item in variants:
        if _starts_with_ci(value, item.old_forward):
            suffix = value[len(item.old_forward) :].replace("\\", "/")
            return item.new_forward + suffix, True, "mapped"
        if _starts_with_ci(value, item.old_backward):
            normalized = value.replace("\\", "/")
            suffix = normalized[len(item.old_forward) :]
            return item.new_forward + suffix, True, "mapped"
        escaped_old_backward = item.old_backward.replace("\\", "\\\\")
        if escaped_old_backward != item.old_backward and _starts_with_ci(value, escaped_old_backward):
            normalized = value.replace("\\\\", "/")
            suffix = normalized[len(item.old_forward) :]
            return item.new_forward + suffix, True, "mapped"
        if _starts_with_ci(value, item.new_backward):
            normalized = value.replace("\\", "/")
            return normalized, True, "normalized"
        escaped_new_backward = item.new_backward.replace("\\", "\\\\")
        if escaped_new_backward != item.new_backward and _starts_with_ci(value, escaped_new_backward):
            normalized = value.replace("\\\\", "/")
            return normalized, True, "normalized"

    updated, replaced = _replace_embedded_paths(value, variants)
    if replaced:
        return updated, True, "mapped"

    return value, False, "not-mapped"


def _rewrite_json_node(node: Any, variants: Sequence[MappingVariants], excluded_prefixes: Sequence[str], counters: Dict[str, int]) -> Any:
    if isinstance(node, dict):
        return {k: _rewrite_json_node(v, variants, excluded_prefixes, counters) for k, v in node.items()}
    if isinstance(node, list):
        return [_rewrite_json_node(item, variants, excluded_prefixes, counters) for item in node]
    if isinstance(node, str):
        updated, changed, reason = _replace_prefix(node, variants, excluded_prefixes)
        if changed:
            counters["json_replaced_values"] = counters.get("json_replaced_values", 0) + 1
            return updated
        if reason == "excluded":
            counters["excluded_values"] = counters.get("excluded_values", 0) + 1
    return node


def _scan_json_paths(node: Any, path: str = "") -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            next_path = f"{path}.{key}" if path else str(key)
            matches.extend(_scan_json_paths(value, next_path))
        return matches
    if isinstance(node, list):
        for index, item in enumerate(node):
            matches.extend(_scan_json_paths(item, f"{path}[{index}]"))
        return matches
    if isinstance(node, str) and _looks_like_path_text(node):
        matches.append({"path": path, "value": node})
    return matches


def _collect_files(workspace_root: Path, scan_dirs: Sequence[str]) -> List[Path]:
    files: List[Path] = []
    for rel_dir in scan_dirs:
        candidate = workspace_root / rel_dir
        if not candidate.exists() or not candidate.is_dir():
            continue
        files.extend(path for path in candidate.rglob("*") if path.is_file())
    return sorted(files)


def _rewrite_json_file(path: Path, variants: Sequence[MappingVariants], excluded_prefixes: Sequence[str], dry_run: bool) -> Dict[str, Any]:
    counters: Dict[str, int] = {}
    try:
        original = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"file": str(path), "type": "json", "changed": False, "error": str(exc)}

    updated = _rewrite_json_node(original, variants, excluded_prefixes, counters)
    changed = updated != original
    if changed and not dry_run:
        path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "file": str(path),
        "type": "json",
        "changed": changed,
        "replaced_values": counters.get("json_replaced_values", 0),
        "excluded_values": counters.get("excluded_values", 0),
        "path_hits": _scan_json_paths(original),
    }


def _rewrite_csv_file(path: Path, variants: Sequence[MappingVariants], excluded_prefixes: Sequence[str], dry_run: bool) -> Dict[str, Any]:
    replaced = 0
    excluded = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as rf:
            rows = list(csv.reader(rf))
    except Exception as exc:
        return {"file": str(path), "type": "csv", "changed": False, "error": str(exc)}

    new_rows: List[List[str]] = []
    changed = False
    for row in rows:
        new_row: List[str] = []
        for cell in row:
            updated, did_change, reason = _replace_prefix(cell, variants, excluded_prefixes)
            if did_change:
                replaced += 1
                changed = True
            elif reason == "excluded":
                excluded += 1
            new_row.append(updated)
        new_rows.append(new_row)

    if changed and not dry_run:
        with path.open("w", encoding="utf-8", newline="") as wf:
            csv.writer(wf).writerows(new_rows)

    return {
        "file": str(path),
        "type": "csv",
        "changed": changed,
        "replaced_values": replaced,
        "excluded_values": excluded,
        "path_hits": [cell for row in rows for cell in row if _looks_like_path_text(cell)],
    }


def _rewrite_text_file(path: Path, variants: Sequence[MappingVariants], excluded_prefixes: Sequence[str], dry_run: bool) -> Dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return {"file": str(path), "type": "text", "changed": False, "error": str(exc)}

    updated, changed, reason = _replace_prefix(text, variants, excluded_prefixes)
    replaced = 1 if changed else 0

    if changed and not dry_run:
        path.write_text(updated, encoding="utf-8")

    return {
        "file": str(path),
        "type": "text",
        "changed": changed,
        "replaced_values": replaced,
        "excluded_values": 1 if reason == "excluded" else 0,
        "path_hits": [line for line in text.splitlines() if _looks_like_path_text(line)],
    }


def _iter_sqlite_text_columns(conn: sqlite3.Connection) -> Iterable[Tuple[str, str]]:
    table_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for (table_name,) in table_rows:
        pragma_rows = conn.execute(f"PRAGMA table_info('{table_name.replace("'", "''")}')").fetchall()
        for row in pragma_rows:
            column_name = str(row[1])
            column_type = str(row[2] or "").upper()
            if any(token in column_type for token in ("TEXT", "CHAR", "CLOB")):
                yield table_name, column_name


def _rewrite_sqlite_file(path: Path, variants: Sequence[MappingVariants], excluded_prefixes: Sequence[str], dry_run: bool) -> Dict[str, Any]:
    if not path.exists():
        return {"db": str(path), "changed": False, "skipped": True, "reason": "missing"}

    updated_cells = 0
    touched_columns: Dict[str, int] = {}
    path_hits: List[Dict[str, Any]] = []
    skipped_columns: List[Dict[str, str]] = []

    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
    except Exception as exc:
        return {"db": str(path), "changed": False, "error": str(exc)}

    try:
        conn.execute("BEGIN")
        for table_name, column_name in _iter_sqlite_text_columns(conn):
            escaped_table = table_name.replace('"', '""')
            escaped_col = column_name.replace('"', '""')
            query = f'SELECT rowid AS "__path_migration_rowid__", "{escaped_col}" AS value FROM "{escaped_table}" WHERE "{escaped_col}" IS NOT NULL'
            try:
                rows = conn.execute(query).fetchall()
            except sqlite3.OperationalError as exc:
                skipped_columns.append({"table": table_name, "column": column_name, "error": str(exc)})
                continue
            for row in rows:
                raw_value = row["value"]
                if not isinstance(raw_value, str):
                    continue
                if _looks_like_path_text(raw_value):
                    path_hits.append({"table": table_name, "column": column_name, "rowid": row["__path_migration_rowid__"], "value": raw_value})
                new_value, changed, reason = _replace_prefix(raw_value, variants, excluded_prefixes)
                if not changed:
                    continue
                update_sql = f'UPDATE "{escaped_table}" SET "{escaped_col}" = ? WHERE rowid = ?'
                conn.execute(update_sql, (new_value, row["__path_migration_rowid__"]))
                updated_cells += 1
                key = f"{table_name}.{column_name}"
                touched_columns[key] = touched_columns.get(key, 0) + 1

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception as exc:
        conn.rollback()
        return {"db": str(path), "changed": False, "error": str(exc)}
    finally:
        conn.close()

    return {
        "db": str(path),
        "changed": updated_cells > 0,
        "updated_cells": updated_cells,
        "touched_columns": touched_columns,
        "skipped_columns": skipped_columns,
        "path_hits": path_hits,
    }


def migrate_workspace_paths(
    *,
    workspace_root: str | Path,
    mappings: Sequence[PathMapping],
    dry_run: bool = True,
    inventory_only: bool = False,
    scan_dirs: Sequence[str] = DEFAULT_SCAN_DIRS,
    sqlite_rel_paths: Sequence[str] = DEFAULT_SQLITE_PATHS,
    excluded_prefixes: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """迁移工作区中的绝对路径。

    Args:
        workspace_root: 工作区根目录。
        mappings: 路径映射列表，按顺序匹配。
        dry_run: 是否只预览不落盘。
        inventory_only: 是否仅扫描输出命中清单，不执行替换判断之外的变更写入。
        scan_dirs: 文本与结构化文件扫描目录（相对 workspace_root）。
        sqlite_rel_paths: 需要处理的 SQLite 路径（相对 workspace_root）。
        excluded_prefixes: 需要忽略替换的前缀。

    Returns:
        迁移结果摘要。

    Raises:
        ValueError: 当 workspace_root 不存在或 mappings 为空时抛出。

    Examples:
        >>> result = migrate_workspace_paths(
        ...     workspace_root='/repo/workspace',
        ...     mappings=[PathMapping('/repo/workspace', '/mnt/data/workspace')],
        ...     dry_run=True,
        ... )
        >>> isinstance(result, dict)
        True
    """

    root = Path(workspace_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"workspace_root 不存在或不是目录：{root}")
    if not mappings:
        raise ValueError("mappings 不能为空")

    variants = [_build_variants(item) for item in mappings]
    normalized_excluded = [str(Path(prefix).expanduser()).rstrip("/\\") for prefix in ((excluded_prefixes or []) + list(DEFAULT_EXCLUDED_PREFIXES)) if prefix]

    file_reports: List[Dict[str, Any]] = []
    files = _collect_files(root, scan_dirs)
    for file_path in files:
        suffix = file_path.suffix.lower()
        if suffix == ".json":
            file_reports.append(_rewrite_json_file(file_path, variants, normalized_excluded, dry_run))
        elif suffix == ".csv":
            file_reports.append(_rewrite_csv_file(file_path, variants, normalized_excluded, dry_run))
        elif suffix in TEXT_EXTENSIONS:
            file_reports.append(_rewrite_text_file(file_path, variants, normalized_excluded, dry_run))

    db_reports: List[Dict[str, Any]] = []
    for rel_db in sqlite_rel_paths:
        db_reports.append(
            _rewrite_sqlite_file(
                path=(root / rel_db),
                variants=variants,
                excluded_prefixes=normalized_excluded,
                dry_run=dry_run,
            )
        )

    changed_files = [item for item in file_reports if item.get("changed")]
    changed_dbs = [item for item in db_reports if item.get("changed")]
    path_hit_count = sum(len(item.get("path_hits") or []) for item in file_reports) + sum(len(item.get("path_hits") or []) for item in db_reports)

    return {
        "workspace_root": str(root),
        "dry_run": dry_run,
        "scan_dirs": list(scan_dirs),
        "sqlite_rel_paths": list(sqlite_rel_paths),
        "mapping_count": len(mappings),
        "inventory_only": inventory_only,
        "file_reports": file_reports,
        "db_reports": db_reports,
        "summary": {
            "scanned_files": len(file_reports),
            "changed_files": len(changed_files),
            "changed_databases": len(changed_dbs),
            "path_hits": path_hit_count,
            "changed": bool(changed_files or changed_dbs),
        },
    }


def _parse_mapping_items(mapping_args: Sequence[str]) -> List[PathMapping]:
    mappings: List[PathMapping] = []
    for item in mapping_args:
        if "=>" not in item:
            raise ValueError(f"映射参数格式错误（应为 old=>new）：{item}")
        old_root, new_root = item.split("=>", 1)
        mappings.append(PathMapping(old_root=old_root.strip(), new_root=new_root.strip()))
    return mappings


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""

    parser = argparse.ArgumentParser(description="迁移工作区中写死的绝对路径（支持 SQLite）。")
    parser.add_argument("--workspace-root", required=True, help="工作区根目录。")
    parser.add_argument(
        "--mapping",
        action="append",
        required=True,
        help="路径映射，格式 old=>new。可多次传入。",
    )
    parser.add_argument("--apply", action="store_true", help="默认是 dry-run；传入后才真正写入。")
    parser.add_argument("--inventory-only", action="store_true", help="仅扫描并输出命中清单，不执行改写。")
    parser.add_argument(
        "--scan-dir",
        action="append",
        default=[],
        help="附加扫描目录（相对 workspace_root）。",
    )
    parser.add_argument(
        "--sqlite-rel-path",
        action="append",
        default=[],
        help="附加 SQLite 相对路径（相对 workspace_root）。",
    )
    parser.add_argument(
        "--exclude-prefix",
        action="append",
        default=[],
        help="不允许替换的绝对路径前缀。",
    )
    parser.add_argument("--report-path", default="", help="报告输出路径（JSON）。")
    return parser


def main() -> None:
    """CLI 入口。"""

    args = build_parser().parse_args()
    mappings = _parse_mapping_items(args.mapping)
    scan_dirs = list(DEFAULT_SCAN_DIRS)
    if args.scan_dir:
        scan_dirs.extend(item for item in args.scan_dir if item)
    sqlite_rel_paths = list(DEFAULT_SQLITE_PATHS)
    if args.sqlite_rel_path:
        sqlite_rel_paths.extend(item for item in args.sqlite_rel_path if item)

    result = migrate_workspace_paths(
        workspace_root=args.workspace_root,
        mappings=mappings,
        dry_run=not args.apply,
        inventory_only=args.inventory_only,
        scan_dirs=scan_dirs,
        sqlite_rel_paths=sqlite_rel_paths,
        excluded_prefixes=args.exclude_prefix,
    )

    if args.report_path:
        report_path = Path(args.report_path).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
