"""知识数据库兼容工具。

本模块当前定位为 SQLite 主库时代的 DataFrame/Markdown 兼容层：

1. 负责 Markdown frontmatter 与内存态索引表之间的同步；
2. 提供知识附件关系、文献标准笔记绑定等纯内存处理能力；
3. 不再把 `knowledge_index.csv` 视为运行时主库，主库存取应优先使用
    `knowledgedb_sqlite.py` 或 `storage_backend.py`。
"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

import pandas as pd

from autodokit.tools.obsidian_note_timezone_tools import get_current_time_iso
from autodokit.tools.task_docs import split_frontmatter


DEFAULT_KNOWLEDGE_INDEX_COLUMNS: List[str] = [
    "uid_knowledge",
    "note_name",
    "note_path",
    "note_type",
    "title",
    "status",
    "tags",
    "aliases",
    "source_type",
    "evidence_uids",
    "uid_literature",
    "cite_key",
    "attachment_uids",
    "created_at",
    "updated_at",
]

DEFAULT_KNOWLEDGE_ATTACHMENT_COLUMNS: List[str] = [
    "uid_attachment",
    "uid_knowledge",
    "attachment_name",
    "attachment_type",
    "file_ext",
    "storage_path",
    "source_path",
    "checksum",
    "status",
    "created_at",
    "updated_at",
]

REQUIRED_FRONTMATTER_FIELDS: Tuple[str, ...] = (
    "title",
    "uid_knowledge",
    "note_type",
    "status",
    "evidence_uids",
    "tags",
)


def _note_now_iso() -> str:
    """返回知识笔记默认时区下的 ISO 时间字符串。

    Returns:
        默认知识笔记时间字符串。
    """

    return get_current_time_iso()


def _stringify(value: Any) -> str:
    """把任意值安全转换为字符串。

    Args:
        value: 任意输入值。

    Returns:
        去除首尾空白后的字符串。
    """

    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _split_inline_list(value: str) -> List[str]:
    """拆分 Markdown/frontmatter 中的轻量列表值。

    Args:
        value: 原始文本。

    Returns:
        去空后的字符串列表。
    """

    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    parts = [segment.strip().strip('"').strip("'") for segment in text.replace("，", ",").split(",")]
    return [segment for segment in parts if segment]


def _parse_simple_frontmatter(frontmatter: str) -> Dict[str, Any]:
    """解析轻量 YAML frontmatter。

    约束：
    - 仅支持顶层 `key: value`；
    - 支持顶层列表 `key:` 后接多行 `- value`；
    - 对 AOK 知识笔记所需字段足够。

    Args:
        frontmatter: 不含包裹线的 frontmatter 文本。

    Returns:
        解析结果字典。
    """

    result: Dict[str, Any] = {}
    current_key = ""
    for raw_line in str(frontmatter or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if line.startswith("  - ") or line.startswith("- "):
            if current_key:
                result.setdefault(current_key, [])
                if not isinstance(result[current_key], list):
                    result[current_key] = _split_inline_list(_stringify(result[current_key]))
                result[current_key].append(stripped.lstrip("-").strip().strip('"').strip("'"))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        value_text = value.strip()
        if not value_text:
            result[current_key] = []
            continue
        result[current_key] = value_text.strip('"').strip("'")
    return result


def _read_markdown_note(note_path: Path) -> Tuple[Dict[str, Any], str]:
    """读取 Markdown 笔记并返回 frontmatter 与正文。

    Args:
        note_path: Markdown 笔记绝对路径。

    Returns:
        `(frontmatter_dict, body_text)`。
    """

    text = note_path.read_text(encoding="utf-8")
    _, frontmatter, body = split_frontmatter(text)
    return _parse_simple_frontmatter(frontmatter), body


def _serialize_yaml_scalar(value: str) -> str:
    """序列化 YAML 标量字符串。

    Args:
        value: 原始字符串。

    Returns:
        YAML 安全字符串。
    """

    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _dump_frontmatter(data: Dict[str, Any]) -> str:
    """将 frontmatter 字典序列化为 YAML 字符串。

    Args:
        data: frontmatter 字典。

    Returns:
        YAML 文本（不含前后 `---`）。
    """

    lines: List[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_serialize_yaml_scalar(_stringify(item))}")
        else:
            lines.append(f"{key}: {_serialize_yaml_scalar(_stringify(value))}")
    return "\n".join(lines)


def _build_default_note_body(uid_knowledge: str, title: str) -> str:
    """构建默认知识笔记正文模板。

    Args:
        uid_knowledge: 知识 UID。
        title: 标题。

    Returns:
        Markdown 正文。
    """

    return "\n".join(
        [
            f"# {title}",
            "",
            "> [!abstract] 核心命题",
            "> 在这里填写该知识条目的核心命题。",
            "",
            "## 证据",
            "",
            "- 对应文献：[[某文献标准笔记]]",
            "- 文献 UID：lit-xxxx",
            "",
            "> [!quote] 关键摘录",
            "> 在这里填写关键证据段。",
            "",
            f"这段证据对应知识条目 {uid_knowledge}。 ^evidence-001",
            "",
            "## 关联知识",
            "",
            "- [[相关知识笔记A]]",
            "- [[相关知识笔记B#某个标题]]",
            "",
            "## 附件",
            "",
            "![[knowledge/attachments/example.png|600]]",
            "",
            "## 说明与结论",
            "",
            "在这里补充边界、推论和后续待办。",
            "",
        ]
    )


def generate_knowledge_uid(note_path: str, title: str) -> str:
    """生成稳定知识笔记 UID。

    Args:
        note_path: 笔记路径。
        title: 笔记标题。

    Returns:
        稳定知识 UID。
    """

    seed = f"{note_path}|{title}"
    return f"kn-{sha1(seed.encode('utf-8')).hexdigest()[:16]}"


def init_empty_knowledge_index_table() -> pd.DataFrame:
    """初始化空知识索引表。

    Returns:
        空知识索引 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_KNOWLEDGE_INDEX_COLUMNS))


def init_empty_knowledge_attachments_table() -> pd.DataFrame:
    """初始化空知识附件表。

    Returns:
        空知识附件 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_KNOWLEDGE_ATTACHMENT_COLUMNS))


def _ensure_columns(table: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    """确保表包含目标列集合。

    Args:
        table: 原始表。
        columns: 目标列。

    Returns:
        补齐后的 DataFrame。
    """

    result = table.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = ""
    return result


def _normalize_index_record(record: Dict[str, Any], *, existing: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """规范化单条知识索引记录。

    Args:
        record: 原始记录。
        existing: 已存在记录。

    Returns:
        规范化后的记录。
    """

    base = dict(existing or {})
    raw = dict(record)
    note_path = _stringify(raw.get("note_path") or base.get("note_path"))
    title = _stringify(raw.get("title") or base.get("title"))
    uid_knowledge = _stringify(raw.get("uid_knowledge") or base.get("uid_knowledge"))
    if not uid_knowledge:
        uid_knowledge = generate_knowledge_uid(note_path=note_path, title=title)

    def _join_list(value: Any) -> str:
        if isinstance(value, list):
            return "|".join(_stringify(item) for item in value if _stringify(item))
        return _stringify(value)

    created_at = _stringify(base.get("created_at")) or _stringify(raw.get("created_at")) or _note_now_iso()
    updated_at = _stringify(raw.get("updated_at")) or _note_now_iso()
    return {
        "uid_knowledge": uid_knowledge,
        "note_name": _stringify(raw.get("note_name") or base.get("note_name")) or Path(note_path).name,
        "note_path": note_path,
        "note_type": _stringify(raw.get("note_type") or base.get("note_type")) or "knowledge_note",
        "title": title,
        "status": _stringify(raw.get("status") or base.get("status")) or "active",
        "tags": _join_list(raw.get("tags") if raw.get("tags") is not None else base.get("tags")),
        "aliases": _join_list(raw.get("aliases") if raw.get("aliases") is not None else base.get("aliases")),
        "source_type": _stringify(raw.get("source_type") or base.get("source_type")) or "obsidian_markdown",
        "evidence_uids": _join_list(raw.get("evidence_uids") if raw.get("evidence_uids") is not None else base.get("evidence_uids")),
        "uid_literature": _stringify(raw.get("uid_literature") or base.get("uid_literature")),
        "cite_key": _stringify(raw.get("cite_key") or base.get("cite_key")),
        "attachment_uids": _join_list(raw.get("attachment_uids") if raw.get("attachment_uids") is not None else base.get("attachment_uids")),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def knowledge_upsert(index_table: pd.DataFrame, record: Dict[str, Any], overwrite: bool = True) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """插入或更新知识索引记录。

    Args:
        index_table: 知识索引表。
        record: 原始记录。
        overwrite: 是否覆盖已存在字段。

    Returns:
        `(更新后的表, 规范化记录, 动作)`。
    """

    working = _ensure_columns(index_table, list(DEFAULT_KNOWLEDGE_INDEX_COLUMNS))
    incoming = _normalize_index_record(record)
    uid_knowledge = incoming["uid_knowledge"]
    matches = working.index[working["uid_knowledge"].astype(str) == uid_knowledge].tolist()
    if not matches and incoming["note_path"]:
        matches = working.index[working["note_path"].astype(str) == incoming["note_path"]].tolist()

    if not matches:
        row_to_add = {column: incoming.get(column, "") for column in DEFAULT_KNOWLEDGE_INDEX_COLUMNS}
        working = pd.concat([working, pd.DataFrame([row_to_add])], ignore_index=True)
        return working, row_to_add, "inserted"

    idx = matches[0]
    current = dict(working.loc[idx])
    normalized = _normalize_index_record(incoming, existing=current)
    merged: Dict[str, Any] = {}
    for column in DEFAULT_KNOWLEDGE_INDEX_COLUMNS:
        current_value = current.get(column, "")
        incoming_value = normalized.get(column, "")
        if overwrite:
            merged[column] = incoming_value if _stringify(incoming_value) else current_value
        else:
            merged[column] = current_value if _stringify(current_value) else incoming_value
    for column, value in merged.items():
        working.at[idx, column] = value
    return working, merged, "updated"


def knowledge_sync_note(index_table: pd.DataFrame, note_path: str | Path, *, workspace_root: str | Path | None = None) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """从 Markdown 笔记同步知识索引。

    Args:
        index_table: 知识索引表。
        note_path: 笔记绝对路径。
        workspace_root: 工作区根目录，用于写相对路径。

    Returns:
        `(更新后的表, 规范化记录, 动作)`。
    """

    path = Path(note_path).resolve()
    frontmatter, _ = _read_markdown_note(path)
    root = Path(workspace_root).resolve() if workspace_root is not None else None
    if root is not None:
        try:
            note_path_value = path.relative_to(root).as_posix()
        except ValueError:
            note_path_value = path.as_posix()
    else:
        note_path_value = path.as_posix()

    title = _stringify(frontmatter.get("title")) or path.stem
    record = {
        "uid_knowledge": _stringify(frontmatter.get("uid_knowledge")),
        "note_name": path.name,
        "note_path": note_path_value,
        "note_type": _stringify(frontmatter.get("note_type")) or "knowledge_note",
        "title": title,
        "status": _stringify(frontmatter.get("status")) or "active",
        "tags": frontmatter.get("tags") if isinstance(frontmatter.get("tags"), list) else _split_inline_list(_stringify(frontmatter.get("tags"))),
        "aliases": frontmatter.get("aliases") if isinstance(frontmatter.get("aliases"), list) else _split_inline_list(_stringify(frontmatter.get("aliases"))),
        "source_type": "obsidian_markdown",
        "evidence_uids": frontmatter.get("evidence_uids") if isinstance(frontmatter.get("evidence_uids"), list) else _split_inline_list(_stringify(frontmatter.get("evidence_uids"))),
        "uid_literature": _stringify(frontmatter.get("uid_literature")),
        "cite_key": _stringify(frontmatter.get("cite_key")),
        "attachment_uids": frontmatter.get("attachment_uids") if isinstance(frontmatter.get("attachment_uids"), list) else _split_inline_list(_stringify(frontmatter.get("attachment_uids"))),
    }
    return knowledge_upsert(index_table=index_table, record=record, overwrite=True)


def knowledge_attach_file(
    index_table: pd.DataFrame,
    attachments_table: pd.DataFrame,
    *,
    uid_knowledge: str,
    attachment_name: str,
    attachment_type: str = "asset",
    storage_path: str = "",
    source_path: str = "",
    checksum: str = "",
    status: str = "active",
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """为知识笔记绑定附件记录。

    Args:
        index_table: 知识索引表。
        attachments_table: 知识附件表。
        uid_knowledge: 知识笔记 UID。
        attachment_name: 附件名或路径。
        attachment_type: 附件类型。
        storage_path: 内部存储路径。
        source_path: 来源路径。
        checksum: 校验值。
        status: 附件状态。

    Returns:
        `(更新后的索引表, 更新后的附件表, 附件记录)`。
    """

    working_index = _ensure_columns(index_table, list(DEFAULT_KNOWLEDGE_INDEX_COLUMNS))
    working_attachments = _ensure_columns(attachments_table, list(DEFAULT_KNOWLEDGE_ATTACHMENT_COLUMNS))

    if uid_knowledge not in set(working_index["uid_knowledge"].astype(str).tolist()):
        raise KeyError(f"未找到知识记录：{uid_knowledge}")

    attachment_file_name = Path(attachment_name).name
    uid_attachment = f"kna-{sha1(f'{uid_knowledge}|{attachment_file_name}|{attachment_type}'.encode('utf-8')).hexdigest()[:16]}"
    now = _note_now_iso()
    relation = {
        "uid_attachment": uid_attachment,
        "uid_knowledge": uid_knowledge,
        "attachment_name": attachment_file_name,
        "attachment_type": attachment_type,
        "file_ext": Path(attachment_file_name).suffix.lstrip("."),
        "storage_path": _stringify(storage_path),
        "source_path": _stringify(source_path) or _stringify(attachment_name),
        "checksum": _stringify(checksum),
        "status": _stringify(status) or "active",
        "created_at": now,
        "updated_at": now,
    }

    mask = (
        (working_attachments["uid_knowledge"].astype(str) == uid_knowledge)
        & (working_attachments["attachment_name"].astype(str) == attachment_file_name)
        & (working_attachments["attachment_type"].astype(str) == attachment_type)
    )
    matches = working_attachments.index[mask].tolist()
    if matches:
        for column, value in relation.items():
            working_attachments.at[matches[0], column] = value
    else:
        working_attachments = pd.concat([working_attachments, pd.DataFrame([relation])], ignore_index=True)

    idx = working_index.index[working_index["uid_knowledge"].astype(str) == uid_knowledge].tolist()[0]
    existing_attachment_uids = [item for item in _stringify(working_index.at[idx, "attachment_uids"]).split("|") if item]
    if uid_attachment not in existing_attachment_uids:
        existing_attachment_uids.append(uid_attachment)
    working_index.at[idx, "attachment_uids"] = "|".join(existing_attachment_uids)
    working_index.at[idx, "updated_at"] = now
    return working_index, working_attachments, relation


def knowledge_get(index_table: pd.DataFrame, attachments_table: pd.DataFrame, *, uid_knowledge: str) -> Dict[str, Any]:
    """读取单条知识记录及其附件。

    Args:
        index_table: 知识索引表。
        attachments_table: 知识附件表。
        uid_knowledge: 目标 UID。

    Returns:
        记录字典，附带 `attachments` 列表。
    """

    working_index = _ensure_columns(index_table, list(DEFAULT_KNOWLEDGE_INDEX_COLUMNS))
    working_attachments = _ensure_columns(attachments_table, list(DEFAULT_KNOWLEDGE_ATTACHMENT_COLUMNS))
    matches = working_index.index[working_index["uid_knowledge"].astype(str) == str(uid_knowledge)].tolist()
    if not matches:
        raise KeyError(f"未找到知识记录：{uid_knowledge}")
    row = dict(working_index.loc[matches[0]])
    attachments = working_attachments.loc[
        working_attachments["uid_knowledge"].astype(str) == str(uid_knowledge)
    ].to_dict(orient="records")
    row["attachments"] = attachments
    return row


def knowledge_find_by_literature(index_table: pd.DataFrame, *, uid_literature: str = "", cite_key: str = "", note_type: str = "") -> List[Dict[str, Any]]:
    """按文献绑定信息查找知识笔记。

    Args:
        index_table: 知识索引表。
        uid_literature: 文献 UID。
        cite_key: 引用键。
        note_type: 可选笔记类型过滤。

    Returns:
        命中的知识记录列表。
    """

    working = _ensure_columns(index_table, list(DEFAULT_KNOWLEDGE_INDEX_COLUMNS))
    mask = pd.Series([True] * len(working), index=working.index)
    if _stringify(uid_literature):
        mask &= working["uid_literature"].astype(str) == _stringify(uid_literature)
    if _stringify(cite_key):
        mask &= working["cite_key"].astype(str) == _stringify(cite_key)
    if _stringify(note_type):
        mask &= working["note_type"].astype(str) == _stringify(note_type)
    return working.loc[mask].to_dict(orient="records")


def knowledge_note_register(
    note_path: str | Path,
    title: str,
    *,
    uid_knowledge: str = "",
    note_type: str = "knowledge_note",
    status: str = "draft",
    source_task_uid: str = "",
    evidence_uids: List[str] | None = None,
    tags: List[str] | None = None,
    aliases: List[str] | None = None,
    uid_literature: str = "",
    cite_key: str = "",
    body: str = "",
) -> Dict[str, Any]:
    """创建或更新知识笔记。

    Args:
        note_path: 笔记文件绝对路径。
        title: 笔记标题。
        uid_knowledge: 可选知识 UID。
        note_type: 笔记类型。
        status: 状态。
        source_task_uid: 来源任务 UID。
        evidence_uids: 证据文献 UID 列表。
        tags: 标签列表。
        aliases: 别名列表。
        uid_literature: 文献 UID。
        cite_key: 引文键。
        body: 正文内容；为空时使用默认模板。

    Returns:
        创建结果字典。
    """

    path = Path(note_path)
    if not path.is_absolute():
        raise ValueError(f"note_path 必须为绝对路径：{path}")

    normalized_uid = _stringify(uid_knowledge) or generate_knowledge_uid(path.as_posix(), title)
    now = _note_now_iso()
    frontmatter: Dict[str, Any] = {
        "title": _stringify(title) or path.stem,
        "aliases": [item for item in (aliases or []) if _stringify(item)],
        "tags": [item for item in (tags or ["aok/knowledge"]) if _stringify(item)],
        "uid_knowledge": normalized_uid,
        "note_type": _stringify(note_type) or "knowledge_note",
        "status": _stringify(status) or "draft",
        "source_task_uid": _stringify(source_task_uid),
        "evidence_uids": [item for item in (evidence_uids or ["lit-xxxx"]) if _stringify(item)],
        "uid_literature": _stringify(uid_literature),
        "cite_key": _stringify(cite_key),
        "created": now,
        "updated": now,
    }

    final_body = body.strip() if _stringify(body) else _build_default_note_body(uid_knowledge=normalized_uid, title=frontmatter["title"])
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(["---", _dump_frontmatter(frontmatter), "---", "", final_body])
    path.write_text(content, encoding="utf-8")
    return {
        "note_path": str(path),
        "uid_knowledge": normalized_uid,
        "title": frontmatter["title"],
        "note_type": frontmatter["note_type"],
        "status": frontmatter["status"],
    }


def knowledge_note_validate_obsidian(note_path: str | Path) -> Dict[str, Any]:
    """校验知识笔记是否满足 Obsidian 与 AOK 最小约束。

    Args:
        note_path: 笔记绝对路径。

    Returns:
        校验结果字典，包含错误与警告列表。
    """

    path = Path(note_path)
    if not path.exists():
        return {
            "valid": False,
            "errors": [f"笔记文件不存在：{path}"],
            "warnings": [],
            "frontmatter": {},
        }

    frontmatter, body = _read_markdown_note(path)
    errors: List[str] = []
    warnings: List[str] = []

    for required_field in REQUIRED_FRONTMATTER_FIELDS:
        value = frontmatter.get(required_field)
        if isinstance(value, list):
            if not value:
                errors.append(f"必填列表字段为空：{required_field}")
        elif not _stringify(value):
            errors.append(f"缺少必填字段：{required_field}")

    note_type = _stringify(frontmatter.get("note_type"))
    if note_type not in {"knowledge_note", "literature_standard_note"}:
        errors.append("note_type 必须为 knowledge_note 或 literature_standard_note")

    evidence_uids = frontmatter.get("evidence_uids")
    evidence_list = evidence_uids if isinstance(evidence_uids, list) else _split_inline_list(_stringify(evidence_uids))
    if not evidence_list:
        errors.append("evidence_uids 至少需要 1 项")

    if note_type == "literature_standard_note" and not _stringify(frontmatter.get("uid_literature")):
        errors.append("文献标准笔记必须包含 uid_literature")

    if "![[" in body and "knowledge/attachments/" not in body:
        warnings.append("检测到 embed 语法但未使用 knowledge/attachments/ 约定路径")

    if "[[" not in body:
        warnings.append("正文中未检测到任何 wikilink，可根据需要补充关联知识链接")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "frontmatter": frontmatter,
    }


def knowledge_bind_literature_standard_note(note_path: str | Path, uid_literature: str, cite_key: str) -> Dict[str, Any]:
    """将知识笔记绑定为文献标准笔记。

    Args:
        note_path: 笔记绝对路径。
        uid_literature: 文献 UID。
        cite_key: 引文键。

    Returns:
        更新后的前置信息摘要。
    """

    path = Path(note_path)
    if not path.exists():
        raise FileNotFoundError(f"笔记文件不存在：{path}")

    frontmatter, body = _read_markdown_note(path)
    frontmatter["note_type"] = "literature_standard_note"
    frontmatter["uid_literature"] = _stringify(uid_literature)
    frontmatter["cite_key"] = _stringify(cite_key)
    frontmatter["updated"] = _note_now_iso()

    content = "\n".join(["---", _dump_frontmatter(frontmatter), "---", "", body.lstrip("\n")])
    path.write_text(content, encoding="utf-8")
    return {
        "note_path": str(path),
        "uid_knowledge": _stringify(frontmatter.get("uid_knowledge")),
        "note_type": "literature_standard_note",
        "uid_literature": _stringify(uid_literature),
        "cite_key": _stringify(cite_key),
    }


def knowledge_base_generate(view_dir: str | Path) -> List[Path]:
    """生成 Obsidian Bases 视图文件。

    Args:
        view_dir: `.base` 输出目录绝对路径。

    Returns:
        生成的 `.base` 文件路径列表。
    """

    path = Path(view_dir)
    if not path.is_absolute():
        raise ValueError(f"view_dir 必须为绝对路径：{path}")
    path.mkdir(parents=True, exist_ok=True)

    all_base = "\n".join(
        [
            "filters:",
            "  and:",
            "    - 'file.inFolder(\"knowledge/notes\")'",
            "views:",
            "  - type: table",
            "    name: \"knowledge_all\"",
            "    order:",
            "      - file.name",
            "      - uid_knowledge",
            "      - note_type",
            "      - status",
            "      - source_task_uid",
            "      - evidence_uids",
        ]
    )
    review_base = "\n".join(
        [
            "filters:",
            "  and:",
            "    - 'file.inFolder(\"knowledge/notes\")'",
            "    - 'status == \"draft\" || status == \"review\"'",
            "views:",
            "  - type: table",
            "    name: \"knowledge_review\"",
            "    order:",
            "      - file.name",
            "      - uid_knowledge",
            "      - status",
            "      - updated",
        ]
    )

    all_path = path / "knowledge_all.base"
    review_path = path / "knowledge_review.base"
    all_path.write_text(all_base + "\n", encoding="utf-8")
    review_path.write_text(review_base + "\n", encoding="utf-8")
    return [all_path, review_path]


def knowledge_index_sync_from_note(index_table: pd.DataFrame, note_path: str | Path, *, workspace_root: str | Path | None = None) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """兼容接口：从单篇笔记同步到知识索引表。

    Args:
        index_table: 现有 `knowledge_index.csv` 对应表。
        note_path: 笔记绝对路径。
        workspace_root: 工作区根目录。

    Returns:
        `(更新后的索引表, 同步行)`。
    """

    updated_table, row, _ = knowledge_sync_note(index_table=index_table, note_path=note_path, workspace_root=workspace_root)
    return updated_table, row


def knowledge_attachment_register(
    attachments_table: pd.DataFrame,
    *,
    attachment_path: str,
    attachment_type: str,
    uid_knowledge: str,
    note: str = "",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """兼容接口：登记知识附件索引关系。

    Args:
        attachments_table: 现有附件索引表。
        attachment_path: 附件路径。
        attachment_type: 附件类型。
        uid_knowledge: 知识 UID。
        note: 备注。

    Returns:
        `(更新后的附件索引表, 附件行)`。
    """

    index_stub = pd.DataFrame([{"uid_knowledge": uid_knowledge, "attachment_uids": ""}])
    updated_index, updated_attachments, relation = knowledge_attach_file(
        index_table=index_stub,
        attachments_table=attachments_table,
        uid_knowledge=uid_knowledge,
        attachment_name=attachment_path,
        attachment_type=attachment_type,
        source_path=attachment_path,
        status="active",
    )
    _ = updated_index
    relation["note"] = _stringify(note)
    return updated_attachments, relation


__all__ = [
    "DEFAULT_KNOWLEDGE_INDEX_COLUMNS",
    "DEFAULT_KNOWLEDGE_ATTACHMENT_COLUMNS",
    "generate_knowledge_uid",
    "init_empty_knowledge_index_table",
    "init_empty_knowledge_attachments_table",
    "knowledge_upsert",
    "knowledge_note_register",
    "knowledge_note_validate_obsidian",
    "knowledge_bind_literature_standard_note",
    "knowledge_base_generate",
    "knowledge_index_sync_from_note",
    "knowledge_attachment_register",
    "knowledge_sync_note",
    "knowledge_attach_file",
    "knowledge_get",
    "knowledge_find_by_literature",
]