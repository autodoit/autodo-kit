"""解析资产迁移与全量重写对齐工具。

本工具用于把外部 workspace 中的 MonkeyOCR 解析资产迁移到当前 workspace，
并尽可能覆盖目录名、文件名、JSON 字段以及文本内路径引用的重写，减少手工
导回资产时的错位风险。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from autodokit.tools import bibliodb_sqlite
from autodokit.tools.contentdb_sqlite import infer_workspace_root_from_content_db
from autodokit.tools.ocr.classic.pdf_parse_asset_manager import (
    UNIFIED_PARSE_LEVEL,
    UNIFIED_PARSE_ROOT_NAME,
)
from autodokit.tools.time_utils import now_iso


TEXT_FILE_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".txt",
    ".csv",
    ".yaml",
    ".yml",
    ".log",
}

PATH_KEY_HINTS = (
    "path",
    "dir",
    "file",
    "root",
    "output",
    "asset",
)

REQUIRED_PARSE_FILES = (
    "normalized.structured.json",
    "parse_record.json",
    "quality_report.json",
)


@dataclass
class CandidateMatch:
    """候选目录匹配结果。

    Args:
        matched_dir: 匹配到的源目录。
        hit_key: 命中的候选键。
    """

    matched_dir: Path
    hit_key: str


def _stringify(value: Any) -> str:
    """把任意值转成去空白字符串。

    Args:
        value: 原始值。

    Returns:
        str: 规范化字符串。
    """

    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _coerce_bool(value: Any, default: bool = False) -> bool:
    """把配置值转成布尔值。

    Args:
        value: 原始值。
        default: 默认值。

    Returns:
        bool: 布尔结果。
    """

    if isinstance(value, bool):
        return value
    text = _stringify(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disable", "disabled"}:
        return False
    return default


def _coerce_list(value: Any) -> list[str]:
    """把配置值转成字符串列表。

    Args:
        value: 原始值。

    Returns:
        list[str]: 字符串列表。
    """

    if value is None:
        return []
    if isinstance(value, list):
        return [_stringify(item) for item in value if _stringify(item)]
    if isinstance(value, tuple):
        return [_stringify(item) for item in value if _stringify(item)]
    if isinstance(value, str):
        return [_stringify(item) for item in value.split(",") if _stringify(item)]
    text = _stringify(value)
    return [text] if text else []


def _safe_stem(text: str) -> str:
    """生成文件系统安全的 stem。

    Args:
        text: 原始文本。

    Returns:
        str: 安全 stem。
    """

    value = _stringify(text)
    if not value:
        return "untitled"
    illegal = '\\/:*?"<>|'
    value = "".join("_" if ch in illegal else ch for ch in value)
    value = "_".join(value.split())
    value = value.strip("._")
    return value or "untitled"


def _normalize_lookup_key(text: str) -> str:
    """构建宽松匹配键。

    Args:
        text: 原始文本。

    Returns:
        str: 归一化键。
    """

    raw = _stringify(text).lower()
    if not raw:
        return ""
    raw = raw.replace(" ", "")
    keep = []
    for ch in raw:
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":
            keep.append(ch)
    return "".join(keep)


def _read_json(path: Path) -> dict[str, Any]:
    """读取 JSON 文件。

    Args:
        path: JSON 路径。

    Returns:
        dict[str, Any]: JSON 对象。

    Raises:
        ValueError: 当 JSON 不是对象时抛出。
    """

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any], *, dry_run: bool) -> bool:
    """写回 JSON 文件。

    Args:
        path: 目标路径。
        payload: 对象。
        dry_run: 是否仅预演。

    Returns:
        bool: 是否实际写入。
    """

    if dry_run:
        return False
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _collect_candidate_keys(literature_row: dict[str, Any], attachment_row: dict[str, Any]) -> list[str]:
    """构建源目录候选键。

    Args:
        literature_row: 文献记录。
        attachment_row: 附件记录。

    Returns:
        list[str]: 候选键列表。
    """

    source_path = Path(_stringify(attachment_row.get("source_path")))
    storage_path = Path(_stringify(attachment_row.get("storage_path")))
    attachment_name = Path(_stringify(attachment_row.get("attachment_name")))
    keys = [
        source_path.stem,
        storage_path.stem,
        attachment_name.stem,
        _stringify(literature_row.get("title")),
        _stringify(literature_row.get("cite_key")),
        _stringify(literature_row.get("uid_literature")),
    ]
    seen: set[str] = set()
    resolved: list[str] = []
    for item in keys:
        if not item:
            continue
        norm = _normalize_lookup_key(item)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        resolved.append(item)
    return resolved


def _build_external_index(external_root: Path) -> dict[str, list[Path]]:
    """构建外部解析目录索引。

    Args:
        external_root: 外部根目录。

    Returns:
        dict[str, list[Path]]: 归一化键到目录列表。
    """

    index: dict[str, list[Path]] = {}
    if not external_root.exists() or not external_root.is_dir():
        return index
    for child in external_root.iterdir():
        if not child.is_dir():
            continue
        norm = _normalize_lookup_key(child.name)
        if not norm:
            continue
        index.setdefault(norm, []).append(child.resolve())
    return index


def _match_external_dir(
    *,
    candidate_keys: list[str],
    external_index: dict[str, list[Path]],
    strict_single_match: bool,
) -> tuple[CandidateMatch | None, str]:
    """从索引中匹配外部目录。

    Args:
        candidate_keys: 候选键。
        external_index: 外部索引。
        strict_single_match: 是否要求唯一。

    Returns:
        tuple[CandidateMatch | None, str]: 匹配结果与失败原因。
    """

    hits: list[tuple[str, Path]] = []
    for key in candidate_keys:
        norm = _normalize_lookup_key(key)
        for matched in external_index.get(norm, []):
            hits.append((key, matched))

    unique_hits: dict[str, tuple[str, Path]] = {}
    for key, path in hits:
        unique_hits[str(path).lower()] = (key, path)

    if not unique_hits:
        return None, "no_match"
    if strict_single_match and len(unique_hits) > 1:
        return None, "multiple_matches"

    first_key, first_path = list(unique_hits.values())[0]
    return CandidateMatch(matched_dir=first_path, hit_key=first_key), ""


def _is_parse_asset_complete(source_dir: Path) -> tuple[bool, str]:
    """判断源解析目录是否已完成。

    完成标准采用保守规则：必须至少包含核心结构化文件，且 parse_record
    中若存在状态字段，则应为成功/就绪态。

    Args:
        source_dir: 源解析目录。

    Returns:
        tuple[bool, str]: (是否完成, 原因)。
    """

    for filename in REQUIRED_PARSE_FILES:
        path = source_dir / filename
        if not path.exists() or not path.is_file():
            return False, f"incomplete_parse_missing_{filename}"

    record_path = source_dir / "parse_record.json"
    try:
        payload = _read_json(record_path)
    except Exception:
        return False, "incomplete_parse_invalid_parse_record"

    status_keys = ("parse_status", "status", "final_status")
    status_value = ""
    for key in status_keys:
        value = _stringify(payload.get(key))
        if value:
            status_value = value.lower()
            break

    if status_value and status_value not in {"ready", "success", "succeeded", "done", "completed", "ok", "pass"}:
        return False, f"incomplete_parse_status_{status_value}"

    return True, ""


def _copy_tree(src: Path, dst: Path, *, dry_run: bool) -> tuple[int, int]:
    """复制目录树。

    Args:
        src: 源目录。
        dst: 目标目录。
        dry_run: 是否预演。

    Returns:
        tuple[int, int]: (复制文件数, 新建目录数)。
    """

    copied = 0
    created_dirs = 0
    for path in src.rglob("*"):
        relative = path.relative_to(src)
        target = dst / relative
        if path.is_dir():
            if not target.exists():
                created_dirs += 1
                if not dry_run:
                    target.mkdir(parents=True, exist_ok=True)
            continue
        if not target.parent.exists() and not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            copied += 1
            if not dry_run:
                shutil.copy2(path, target)
    return copied, created_dirs


def _is_text_file(path: Path) -> bool:
    """判断文件是否按文本处理。

    Args:
        path: 文件路径。

    Returns:
        bool: 是否文本。
    """

    return path.suffix.lower() in TEXT_FILE_SUFFIXES


def _replace_text_payload(text: str, replacements: list[tuple[str, str]]) -> str:
    """批量替换文本。

    Args:
        text: 原始文本。
        replacements: 替换对。

    Returns:
        str: 新文本。
    """

    result = text
    for old, new in replacements:
        if old and old in result:
            result = result.replace(old, new)
    return result


def _rewrite_json_paths(
    value: Any,
    *,
    key: str,
    replacements: list[tuple[str, str]],
    old_pdf_name: str,
    new_pdf_name: str,
    old_pdf_abs_path: str,
    new_pdf_abs_path: str,
) -> Any:
    """递归重写 JSON 中的路径相关字段。

    Args:
        value: 当前值。
        key: 当前键名。
        replacements: 替换对。
        old_pdf_name: 旧 PDF 名。
        new_pdf_name: 新 PDF 名。
        old_pdf_abs_path: 旧 PDF 绝对路径。
        new_pdf_abs_path: 新 PDF 绝对路径。

    Returns:
        Any: 重写后的值。
    """

    if isinstance(value, dict):
        rewritten: dict[str, Any] = {}
        for child_key, child_val in value.items():
            rewritten[child_key] = _rewrite_json_paths(
                child_val,
                key=str(child_key),
                replacements=replacements,
                old_pdf_name=old_pdf_name,
                new_pdf_name=new_pdf_name,
                old_pdf_abs_path=old_pdf_abs_path,
                new_pdf_abs_path=new_pdf_abs_path,
            )
        return rewritten

    if isinstance(value, list):
        return [
            _rewrite_json_paths(
                item,
                key=key,
                replacements=replacements,
                old_pdf_name=old_pdf_name,
                new_pdf_name=new_pdf_name,
                old_pdf_abs_path=old_pdf_abs_path,
                new_pdf_abs_path=new_pdf_abs_path,
            )
            for item in value
        ]

    if isinstance(value, str):
        normalized_key = key.lower()
        result = value
        if normalized_key == "pdf_abs_path" and new_pdf_abs_path:
            return new_pdf_abs_path
        if normalized_key == "pdf_name" and new_pdf_name:
            return new_pdf_name
        if normalized_key.endswith("_path") or normalized_key.endswith("_dir") or any(hint in normalized_key for hint in PATH_KEY_HINTS):
            result = _replace_text_payload(result, replacements)
            if old_pdf_abs_path and new_pdf_abs_path and old_pdf_abs_path in result:
                result = result.replace(old_pdf_abs_path, new_pdf_abs_path)
        else:
            # 兜底：即便键名不带 path，只要字符串包含已知旧路径也替换。
            result = _replace_text_payload(result, replacements)
        if old_pdf_name and new_pdf_name and old_pdf_name in result:
            result = result.replace(old_pdf_name, new_pdf_name)
        return result

    return value


def _rewrite_target_directory(
    *,
    target_dir: Path,
    old_dir: Path,
    old_pdf_name: str,
    new_pdf_name: str,
    old_pdf_abs_path: str,
    new_pdf_abs_path: str,
    target_stem: str,
    dry_run: bool,
) -> dict[str, int]:
    """重写目标目录内的文件名和文件内容。

    Args:
        target_dir: 目标目录。
        old_dir: 旧目录。
        old_pdf_name: 旧 PDF 名。
        new_pdf_name: 新 PDF 名。
        old_pdf_abs_path: 旧 PDF 绝对路径。
        new_pdf_abs_path: 新 PDF 绝对路径。
        target_stem: 新目录 stem。
        dry_run: 是否预演。

    Returns:
        dict[str, int]: 统计信息。
    """

    rename_count = 0
    dedup_removed_count = 0
    rename_conflict_count = 0
    text_rewrite_count = 0
    json_rewrite_count = 0

    replacements = [
        (str(old_dir), str(target_dir)),
        (str(old_dir).replace("\\", "/"), str(target_dir).replace("\\", "/")),
    ]
    if old_pdf_abs_path and new_pdf_abs_path:
        replacements.append((old_pdf_abs_path, new_pdf_abs_path))
        replacements.append((old_pdf_abs_path.replace("\\", "/"), new_pdf_abs_path.replace("\\", "/")))

    # 先改文件名，避免后续内容替换遗漏文件路径。
    for path in sorted(target_dir.rglob("*"), key=lambda p: len(str(p)), reverse=True):
        if not path.is_file():
            continue
        new_name = path.name
        old_dir_name = old_dir.name
        # 仅在目录名确实变化时按目录名替换，避免重复 apply 叠加前缀。
        if old_dir_name and old_dir_name != target_stem and old_dir_name in new_name and target_stem not in new_name:
            new_name = new_name.replace(old_dir_name, target_stem)
        # 仅在 PDF 文件名实际变化且尚未替换时执行，保证幂等。
        if (
            old_pdf_name
            and new_pdf_name
            and old_pdf_name != new_pdf_name
            and old_pdf_name in new_name
            and new_pdf_name not in new_name
        ):
            new_name = new_name.replace(old_pdf_name, new_pdf_name)
        if new_name != path.name:
            rename_count += 1
            if not dry_run:
                rename_target = path.with_name(new_name)
                if rename_target.exists():
                    try:
                        # 冲突文件若内容一致，删除旧名冗余文件；否则保留两者并跳过重命名。
                        if path.read_bytes() == rename_target.read_bytes():
                            path.unlink(missing_ok=True)
                            dedup_removed_count += 1
                        else:
                            rename_conflict_count += 1
                    except Exception:
                        rename_conflict_count += 1
                else:
                    try:
                        path.rename(rename_target)
                    except OSError:
                        # 路径过长或平台文件系统限制时，保留原文件并继续处理。
                        rename_conflict_count += 1

    for path in target_dir.rglob("*"):
        if not path.is_file() or not _is_text_file(path):
            continue
        if path.suffix.lower() == ".json":
            try:
                payload = _read_json(path)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                rewritten = _rewrite_json_paths(
                    payload,
                    key="",
                    replacements=replacements,
                    old_pdf_name=old_pdf_name,
                    new_pdf_name=new_pdf_name,
                    old_pdf_abs_path=old_pdf_abs_path,
                    new_pdf_abs_path=new_pdf_abs_path,
                )
                if rewritten != payload:
                    json_rewrite_count += 1
                    _write_json(path, rewritten, dry_run=dry_run)
                    continue
        try:
            original = path.read_text(encoding="utf-8-sig")
        except Exception:
            continue
        rewritten_text = _replace_text_payload(original, replacements)
        if old_pdf_name and new_pdf_name and old_pdf_name in rewritten_text:
            rewritten_text = rewritten_text.replace(old_pdf_name, new_pdf_name)
        if rewritten_text != original:
            text_rewrite_count += 1
            if not dry_run:
                path.write_text(rewritten_text, encoding="utf-8")

    return {
        "renamed_files": rename_count,
        "dedup_removed_files": dedup_removed_count,
        "rename_conflicts": rename_conflict_count,
        "rewritten_text_files": text_rewrite_count,
        "rewritten_json_files": json_rewrite_count,
    }


def _select_primary_attachment(attachments_df: pd.DataFrame, uid_literature: str) -> dict[str, Any] | None:
    """选择文献主附件。

    Args:
        attachments_df: 附件表。
        uid_literature: 文献 UID。

    Returns:
        dict[str, Any] | None: 主附件记录。
    """

    rows = attachments_df[attachments_df["uid_literature"].astype(str) == uid_literature].copy()
    if rows.empty:
        return None
    rows["is_primary"] = rows["is_primary"].fillna(0).astype(int)
    rows = rows.sort_values(by=["is_primary", "attachment_name"], ascending=[False, True])
    for _, row in rows.iterrows():
        storage_path = Path(_stringify(row.get("storage_path")))
        source_path = Path(_stringify(row.get("source_path")))
        if storage_path.exists() and storage_path.is_file():
            return row.to_dict()
        if source_path.exists() and source_path.is_file():
            return row.to_dict()
    return rows.iloc[0].to_dict()


def _pick_current_pdf_path(attachment_row: dict[str, Any]) -> Path:
    """解析附件当前可用 PDF 路径。

    Args:
        attachment_row: 附件记录。

    Returns:
        Path: 可用路径。

    Raises:
        FileNotFoundError: 当路径都不可用时抛出。
    """

    storage_path = Path(_stringify(attachment_row.get("storage_path")))
    if storage_path.exists() and storage_path.is_file():
        return storage_path.resolve()
    source_path = Path(_stringify(attachment_row.get("source_path")))
    if source_path.exists() and source_path.is_file():
        return source_path.resolve()
    raise FileNotFoundError(
        f"附件路径不存在: uid_attachment={_stringify(attachment_row.get('uid_attachment'))}, "
        f"storage_path={storage_path}, source_path={source_path}"
    )


def migrate_parse_assets_with_full_rewrite(payload: dict[str, Any]) -> dict[str, Any]:
    """迁移外部解析资产并执行全量路径重写。

    该工具用于“外部已解析、手工回传”场景：根据 content.db 中的文献和主附件事实，
    在外部解析目录中定位对应资产目录，复制到当前 workspace 的统一解析目录后，执行
    文件名、JSON 字段和文本内容内的路径重写，并登记 `literature_parse_assets` 当前态。

    Args:
        payload: 运行参数，常用字段如下：
            - content_db: 当前 workspace content.db 绝对路径。
            - external_parse_root: 外部解析资产根目录。
            - target_parse_root: 可选，默认 workspace/references/structured_monkeyocr_full。
            - mode: `preview` 或 `apply`。
            - strict_single_match: 是否严格单匹配，默认 true。
            - scope.uid_literatures / scope.cite_keys: 可选范围。
            - update_db: 是否回写 parse asset，默认 true。
            - parse_level: 可选，默认 monkeyocr_full。
            - target_dir_name_mode: 可选，`attachment_stem`(默认) / `cite_key` / `uid_literature`。
            - require_complete_parse: 可选，默认 true；true 时仅迁移已完成解析的目录。

    Returns:
        dict[str, Any]: 执行摘要与逐文献明细。

    Raises:
        ValueError: 参数缺失或路径非法。

    Examples:
        >>> payload = {
        ...   "content_db": "C:/repo/workspace/database/content/content.db",
        ...   "external_parse_root": "D:/old_workspace/references/structured_monkeyocr_full",
        ...   "mode": "preview"
        ... }
        >>> result = migrate_parse_assets_with_full_rewrite(payload)
        >>> result["status"]
        'PASS'
    """

    content_db_raw = _stringify(payload.get("content_db"))
    external_root_raw = _stringify(payload.get("external_parse_root"))
    if not content_db_raw:
        raise ValueError("content_db 不能为空")
    if not external_root_raw:
        raise ValueError("external_parse_root 不能为空")

    content_db = Path(content_db_raw).expanduser().resolve()
    external_root = Path(external_root_raw).expanduser().resolve()
    if not content_db.exists() or not content_db.is_file():
        raise ValueError(f"content_db 不存在: {content_db}")
    if not external_root.exists() or not external_root.is_dir():
        raise ValueError(f"external_parse_root 不存在或不是目录: {external_root}")

    workspace_root = infer_workspace_root_from_content_db(content_db)
    target_parse_root_raw = _stringify(payload.get("target_parse_root"))
    target_parse_root = (
        Path(target_parse_root_raw).expanduser().resolve()
        if target_parse_root_raw
        else (workspace_root / "references" / UNIFIED_PARSE_ROOT_NAME).resolve()
    )

    mode = _stringify(payload.get("mode") or "preview").lower()
    if mode not in {"preview", "apply"}:
        mode = "preview"
    dry_run = mode != "apply"
    strict_single_match = _coerce_bool(payload.get("strict_single_match"), True)
    update_db = _coerce_bool(payload.get("update_db"), True)
    parse_level = _stringify(payload.get("parse_level")) or UNIFIED_PARSE_LEVEL
    target_dir_name_mode = _stringify(payload.get("target_dir_name_mode") or "attachment_stem").lower()
    if target_dir_name_mode not in {"attachment_stem", "cite_key", "uid_literature"}:
        target_dir_name_mode = "attachment_stem"
    require_complete_parse = _coerce_bool(payload.get("require_complete_parse"), True)

    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    uid_scope = set(_coerce_list(scope.get("uid_literatures") or payload.get("uid_literatures")))
    cite_scope = set(_coerce_list(scope.get("cite_keys") or payload.get("cite_keys")))

    literatures_df = bibliodb_sqlite.load_literatures_df(content_db).fillna("")
    attachments_df = bibliodb_sqlite.load_attachments_df(content_db).fillna("")
    external_index = _build_external_index(external_root)

    if not dry_run:
        target_parse_root.mkdir(parents=True, exist_ok=True)

    detail_rows: list[dict[str, Any]] = []
    parse_asset_rows: list[dict[str, Any]] = []

    scanned = 0
    migrated = 0
    skipped = 0
    failed = 0

    for _, lit_row in literatures_df.iterrows():
        row = lit_row.to_dict()
        uid_literature = _stringify(row.get("uid_literature"))
        cite_key = _stringify(row.get("cite_key"))
        title = _stringify(row.get("title"))

        if uid_scope and uid_literature not in uid_scope:
            continue
        if cite_scope and cite_key not in cite_scope:
            continue

        scanned += 1
        base_detail = {
            "uid_literature": uid_literature,
            "cite_key": cite_key,
            "title": title,
            "status": "",
            "reason": "",
            "source_dir": "",
            "target_dir": "",
        }

        try:
            attachment = _select_primary_attachment(attachments_df, uid_literature)
            if attachment is None:
                skipped += 1
                detail_rows.append({**base_detail, "status": "SKIPPED", "reason": "no_attachment"})
                continue

            current_pdf_path = _pick_current_pdf_path(attachment)
            if target_dir_name_mode == "cite_key":
                target_stem = _safe_stem(cite_key or uid_literature or current_pdf_path.stem)
            elif target_dir_name_mode == "uid_literature":
                target_stem = _safe_stem(uid_literature or cite_key or current_pdf_path.stem)
            else:
                target_stem = _safe_stem(current_pdf_path.stem or cite_key or uid_literature)
            target_dir = (target_parse_root / target_stem).resolve()

            candidate_keys = _collect_candidate_keys(row, attachment)
            matched, reason = _match_external_dir(
                candidate_keys=candidate_keys,
                external_index=external_index,
                strict_single_match=strict_single_match,
            )
            if matched is None:
                skipped += 1
                detail_rows.append({**base_detail, "status": "SKIPPED", "reason": reason})
                continue

            source_dir = matched.matched_dir
            if require_complete_parse:
                is_complete, incomplete_reason = _is_parse_asset_complete(source_dir)
                if not is_complete:
                    skipped += 1
                    detail_rows.append(
                        {
                            **base_detail,
                            "status": "SKIPPED",
                            "reason": incomplete_reason,
                            "source_dir": str(source_dir),
                        }
                    )
                    continue

            copied_files, created_dirs = _copy_tree(source_dir, target_dir, dry_run=dry_run)

            # 优先从已复制目录读取旧 JSON 元信息，构建更精确替换上下文。
            target_normalized = target_dir / "normalized.structured.json"
            old_pdf_abs_path = ""
            old_pdf_name = ""
            if target_normalized.exists() and target_normalized.is_file():
                try:
                    normalized_payload = _read_json(target_normalized)
                    source_meta = normalized_payload.get("source") if isinstance(normalized_payload.get("source"), dict) else {}
                    old_pdf_abs_path = _stringify(source_meta.get("pdf_abs_path"))
                    old_pdf_name = _stringify(source_meta.get("pdf_name"))
                except Exception:
                    old_pdf_abs_path = ""
                    old_pdf_name = ""

            old_pdf_abs_path = old_pdf_abs_path or _stringify(attachment.get("source_path"))
            old_pdf_name = old_pdf_name or Path(_stringify(attachment.get("source_path"))).name
            new_pdf_abs_path = str(current_pdf_path)
            new_pdf_name = current_pdf_path.name

            rewrite_stats = _rewrite_target_directory(
                target_dir=target_dir,
                old_dir=source_dir,
                old_pdf_name=old_pdf_name,
                new_pdf_name=new_pdf_name,
                old_pdf_abs_path=old_pdf_abs_path,
                new_pdf_abs_path=new_pdf_abs_path,
                target_stem=target_stem,
                dry_run=dry_run,
            )

            normalized_path = (target_dir / "normalized.structured.json").resolve()
            reconstructed_path = (target_dir / "reconstructed_content.md").resolve()
            linear_index_path = (target_dir / "linear_index.json").resolve()
            elements_path = (target_dir / "elements.json").resolve()
            chunks_path = (target_dir / "chunks.jsonl").resolve()
            parse_record_path = (target_dir / "parse_record.json").resolve()
            quality_report_path = (target_dir / "quality_report.json").resolve()

            backend = "monkeyocr_windows"
            model_name = "external_preparsed"
            if parse_record_path.exists() and parse_record_path.is_file():
                try:
                    parse_record_payload = _read_json(parse_record_path)
                    backend = _stringify(parse_record_payload.get("llm_backend")) or backend
                    model_name = _stringify(parse_record_payload.get("llm_model")) or model_name
                except Exception:
                    pass

            parse_asset_row = {
                "asset_uid": hashlib.md5(
                    f"{uid_literature}|{cite_key}|{parse_level}|{normalized_path}".encode("utf-8")
                ).hexdigest(),
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "uid_attachment": _stringify(attachment.get("uid_attachment")),
                "parse_level": parse_level,
                "backend": backend,
                "model_name": model_name,
                "asset_dir": str(target_dir),
                "normalized_structured_path": str(normalized_path),
                "reconstructed_markdown_path": str(reconstructed_path),
                "linear_index_path": str(linear_index_path),
                "elements_path": str(elements_path),
                "chunks_jsonl_path": str(chunks_path),
                "parse_record_path": str(parse_record_path),
                "quality_report_path": str(quality_report_path),
                "parse_status": "ready",
                "last_run_uid": _stringify(payload.get("run_uid")),
                "is_current": 1,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }

            if update_db:
                parse_asset_rows.append(parse_asset_row)

            migrated += 1
            detail_rows.append(
                {
                    **base_detail,
                    "status": "MIGRATED" if not dry_run else "PREVIEW_OK",
                    "reason": "",
                    "source_dir": str(source_dir),
                    "target_dir": str(target_dir),
                    "hit_key": matched.hit_key,
                    "copied_files": copied_files,
                    "created_dirs": created_dirs,
                    **rewrite_stats,
                }
            )
        except Exception as exc:
            failed += 1
            detail_rows.append({**base_detail, "status": "ERROR", "reason": str(exc)})

    if update_db and parse_asset_rows and not dry_run:
        bibliodb_sqlite.upsert_parse_asset_rows(content_db, parse_asset_rows)

    status = "PASS"
    if failed > 0:
        status = "PARTIAL_PASS" if migrated > 0 else "FAIL"

    return {
        "status": status,
        "mode": mode,
        "content_db": str(content_db),
        "external_parse_root": str(external_root),
        "target_parse_root": str(target_parse_root),
        "parse_level": parse_level,
        "target_dir_name_mode": target_dir_name_mode,
        "require_complete_parse": require_complete_parse,
        "update_db": update_db,
        "scanned": scanned,
        "migrated": migrated,
        "skipped": skipped,
        "failed": failed,
        "rows": detail_rows,
    }
