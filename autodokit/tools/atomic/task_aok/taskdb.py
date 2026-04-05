"""AOK 任务管理系统（003）隔离工具。

本模块只服务 AOK 独立任务管理系统，不复用旧版面向 AOE 的任务数据库语义。

设计目标：
1. 使用 `tasks.csv` + `task_artifacts.csv` 形成最小闭环。
2. 通过 `aok_task_uid` 串联任务主表、任务目录、任务产物。
3. 任务只做“组织和引用”，不复制文献与知识对象事实。
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path
import sqlite3
import shutil
from typing import Any, Callable, Dict, List, Tuple

import pandas as pd

from ...contentdb_sqlite import CONTENT_DB_DIRECTORY_NAME, DEFAULT_CONTENT_DB_NAME, resolve_content_db_path


DEFAULT_AOK_TASK_COLUMNS: List[str] = [
    "aok_task_uid",
    "task_name",
    "task_goal",
    "task_status",
    "workspace_dir",
    "literature_uids",
    "knowledge_uids",
    "created_at",
    "updated_at",
]

DEFAULT_AOK_TASK_ARTIFACT_COLUMNS: List[str] = [
    "aok_task_uid",
    "artifact_name",
    "artifact_type",
    "artifact_path",
    "note",
    "created_at",
]

DEFAULT_AOK_TASK_STATUS_LOG_COLUMNS: List[str] = [
    "aok_task_uid",
    "from_status",
    "to_status",
    "trigger_gate_uid",
    "decision",
    "reason",
    "created_at",
]

DEFAULT_AOK_TASK_GATE_DECISION_COLUMNS: List[str] = [
    "aok_task_uid",
    "gate_uid",
    "gate_review_path",
    "agent_recommendation",
    "human_decision",
    "next_step",
    "next_task_action",
    "created_successor_task_uid",
    "note",
    "created_at",
]

DEFAULT_AOK_TASK_HANDOFF_COLUMNS: List[str] = [
    "aok_task_uid",
    "handoff_role",
    "receiver",
    "manifest_path",
    "status",
    "note",
    "created_at",
]

DEFAULT_AOK_TASK_RELATION_COLUMNS: List[str] = [
    "aok_task_uid",
    "related_task_uid",
    "relation_type",
    "note",
    "created_at",
]

DEFAULT_AOK_TASK_ROUND_VIEW_COLUMNS: List[str] = [
    "aok_task_uid",
    "source_round",
    "view_name",
    "artifact_path",
    "source_affair",
    "status",
    "note",
    "created_at",
]

DEFAULT_AOK_TASK_RELEASE_COLUMNS: List[str] = [
    "aok_task_uid",
    "artifact_name",
    "artifact_path",
    "release_level",
    "promoted_to",
    "note",
    "created_at",
]

DEFAULT_AOK_TASK_LITERATURE_BINDING_COLUMNS: List[str] = [
    "aok_task_uid",
    "uid_literature",
    "binding_role",
    "source_affair",
    "source_gate_uid",
    "release_level",
    "created_at",
]

DEFAULT_AOK_TASK_KNOWLEDGE_BINDING_COLUMNS: List[str] = [
    "aok_task_uid",
    "uid_knowledge",
    "binding_role",
    "source_affair",
    "source_gate_uid",
    "release_level",
    "created_at",
]


def _resolve_aok_roots(
    project_root: str | Path = ".",
    *,
    tasks_db_root: str | Path | None = None,
    tasks_workspace_root: str | Path | None = None,
) -> Tuple[Path, Path, Path]:
    """解析 AOK 任务数据库与任务工作区路径。

    Args:
        project_root: 项目根目录。
        tasks_db_root: 自定义任务数据库目录。
        tasks_workspace_root: 自定义任务工作区目录。

    Returns:
        `(项目根目录, 任务数据库目录, 任务工作区目录)`。

    Examples:
        >>> root, db_root, workspace_root = _resolve_aok_roots('.')
        >>> db_root.name
        'tasks'
    """

    root = Path(project_root).resolve()
    if tasks_db_root is not None:
        resolved_tasks_db_root = Path(tasks_db_root).resolve()
    else:
        legacy_root = root / "database" / "tasks"
        preferred_root = root / "database" / "tasking"
        resolved_tasks_db_root = legacy_root if legacy_root.exists() or not preferred_root.exists() else preferred_root
    resolved_tasks_workspace_root = (
        Path(tasks_workspace_root).resolve() if tasks_workspace_root is not None else root / "tasks"
    )
    return root, resolved_tasks_db_root, resolved_tasks_workspace_root


def _utc_now_iso() -> str:
    """返回 UTC ISO 时间字符串。

    Returns:
        当前 UTC 时间字符串。

    Examples:
        >>> _utc_now_iso().endswith("+00:00")
        True
    """

    return datetime.now(tz=UTC).isoformat()


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


def _ensure_columns(table: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    """确保 DataFrame 含有目标列。

    Args:
        table: 原始数据表。
        columns: 目标字段列表。

    Returns:
        补齐字段后的数据表。
    """

    result = table.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = ""
    return result


def _normalize_uid_list(uid_values: List[str] | str | None) -> List[str]:
    """将 UID 输入归一化为唯一列表。

    Args:
        uid_values: UID 列表、分隔字符串或空。

    Returns:
        去重、去空后的 UID 列表。

    Examples:
        >>> _normalize_uid_list("a|b|a")
        ['a', 'b']
    """

    if uid_values is None:
        return []
    if isinstance(uid_values, list):
        raw_items = [_stringify(item) for item in uid_values]
    else:
        text = _stringify(uid_values).replace(",", "|").replace("；", "|").replace(";", "|")
        raw_items = [_stringify(item) for item in text.split("|")]
    deduplicated: List[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        deduplicated.append(item)
    return deduplicated


def _join_uid_list(uid_values: List[str]) -> str:
    """将 UID 列表编码为分隔字符串。

    Args:
        uid_values: UID 列表。

    Returns:
        以 `|` 连接的字符串。
    """

    return "|".join(_normalize_uid_list(uid_values))


def _generate_task_uid(task_name: str, task_goal: str) -> str:
    """生成稳定任务 UID。

    Args:
        task_name: 任务名称。
        task_goal: 任务目标。

    Returns:
        以 `task-` 开头的任务 UID。

    Examples:
        >>> _generate_task_uid("任务A", "目标A").startswith("task-")
        True
    """

    seed = f"{_stringify(task_name)}|{_stringify(task_goal)}"
    return f"task-{sha1(seed.encode('utf-8')).hexdigest()[:16]}"


def init_empty_tasks_table() -> pd.DataFrame:
    """初始化空任务主表。

    Returns:
        含任务主表字段的空 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_AOK_TASK_COLUMNS))


def init_empty_task_artifacts_table() -> pd.DataFrame:
    """初始化空任务产物表。

    Returns:
        含任务产物字段的空 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_AOK_TASK_ARTIFACT_COLUMNS))


def init_empty_task_status_log_table() -> pd.DataFrame:
    """初始化空任务状态日志表。

    Returns:
        含状态日志字段的空 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_AOK_TASK_STATUS_LOG_COLUMNS))


def init_empty_task_gate_decisions_table() -> pd.DataFrame:
    """初始化空闸门决策表。

    Returns:
        含闸门决策字段的空 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_AOK_TASK_GATE_DECISION_COLUMNS))


def init_empty_task_handoffs_table() -> pd.DataFrame:
    """初始化空交接表。

    Returns:
        含交接字段的空 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_AOK_TASK_HANDOFF_COLUMNS))


def init_empty_task_relations_table() -> pd.DataFrame:
    """初始化空任务关系表。

    Returns:
        含关系字段的空 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_AOK_TASK_RELATION_COLUMNS))


def init_empty_task_round_views_table() -> pd.DataFrame:
    """初始化空轮次视图表。

    Returns:
        含轮次视图字段的空 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_AOK_TASK_ROUND_VIEW_COLUMNS))


def init_empty_task_releases_table() -> pd.DataFrame:
    """初始化空发布记录表。

    Returns:
        含发布字段的空 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_AOK_TASK_RELEASE_COLUMNS))


def init_empty_task_literature_bindings_table() -> pd.DataFrame:
    """初始化空任务文献绑定表。

    Returns:
        含任务文献绑定字段的空 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_AOK_TASK_LITERATURE_BINDING_COLUMNS))


def init_empty_task_knowledge_bindings_table() -> pd.DataFrame:
    """初始化空任务知识绑定表。

    Returns:
        含任务知识绑定字段的空 DataFrame。
    """

    return pd.DataFrame(columns=list(DEFAULT_AOK_TASK_KNOWLEDGE_BINDING_COLUMNS))


def _build_workspace_dir(
    workspace_root: str | Path | None,
    aok_task_uid: str,
    workspace_dir: str,
) -> str:
    """生成并规范任务工作目录路径。

    Args:
        workspace_root: 工作区根目录。
        aok_task_uid: 任务 UID。
        workspace_dir: 传入目录。

    Returns:
        绝对目录路径字符串。
    """

    if _stringify(workspace_dir):
        return str(Path(workspace_dir).resolve())
    if workspace_root is None:
        return ""
    return str((Path(workspace_root).resolve() / "tasks" / aok_task_uid).resolve())


def task_create_or_update(
    tasks: pd.DataFrame,
    task: Dict[str, Any],
    *,
    workspace_root: str | Path | None = None,
    overwrite: bool = True,
    ensure_workspace_dir: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """创建或更新 AOK 任务主表记录。

    Args:
        tasks: 任务主表数据。
        task: 任务字段字典。
        workspace_root: 工作区根目录，用于生成默认任务目录。
        overwrite: 已存在记录时是否覆盖非空字段。
        ensure_workspace_dir: 是否自动创建任务工作目录。

    Returns:
        `(更新后的表, 规范化记录, 动作)`，动作为 `inserted` 或 `updated`。

    Raises:
        ValueError: 任务名为空时抛出异常。

    Examples:
        >>> table = init_empty_tasks_table()
        >>> table, row, action = task_create_or_update(table, {"task_name": "任务A"})
        >>> action in {"inserted", "updated"}
        True
    """

    working = _ensure_columns(tasks, list(DEFAULT_AOK_TASK_COLUMNS))
    payload = dict(task or {})

    task_name = _stringify(payload.get("task_name"))
    if not task_name:
        raise ValueError("task_name 不能为空")

    task_goal = _stringify(payload.get("task_goal"))
    input_uid = _stringify(payload.get("aok_task_uid"))
    aok_task_uid = input_uid or _generate_task_uid(task_name=task_name, task_goal=task_goal)

    matches = working.index[working["aok_task_uid"].astype(str) == aok_task_uid].tolist()
    now = _utc_now_iso()

    incoming = {
        "aok_task_uid": aok_task_uid,
        "task_name": task_name,
        "task_goal": task_goal,
        "task_status": _stringify(payload.get("task_status")) or "draft",
        "workspace_dir": _build_workspace_dir(
            workspace_root=workspace_root,
            aok_task_uid=aok_task_uid,
            workspace_dir=_stringify(payload.get("workspace_dir")),
        ),
        "literature_uids": _join_uid_list(_normalize_uid_list(payload.get("literature_uids"))),
        "knowledge_uids": _join_uid_list(_normalize_uid_list(payload.get("knowledge_uids"))),
        "created_at": _stringify(payload.get("created_at")) or now,
        "updated_at": now,
    }

    if not matches:
        row = {column: incoming.get(column, "") for column in DEFAULT_AOK_TASK_COLUMNS}
        working = pd.concat([working, pd.DataFrame([row])], ignore_index=True)
        action = "inserted"
    else:
        idx = matches[0]
        current = dict(working.loc[idx])
        merged: Dict[str, Any] = {}
        for column in DEFAULT_AOK_TASK_COLUMNS:
            current_value = _stringify(current.get(column))
            incoming_value = _stringify(incoming.get(column))
            if overwrite:
                merged[column] = incoming_value if incoming_value else current_value
            else:
                merged[column] = current_value if current_value else incoming_value
        if not _stringify(merged.get("created_at")):
            merged["created_at"] = now
        merged["updated_at"] = now
        working.loc[idx, DEFAULT_AOK_TASK_COLUMNS] = [merged.get(column, "") for column in DEFAULT_AOK_TASK_COLUMNS]
        row = merged
        action = "updated"

    workspace_dir_value = _stringify(row.get("workspace_dir"))
    if ensure_workspace_dir and workspace_dir_value:
        Path(workspace_dir_value).mkdir(parents=True, exist_ok=True)

    return working, row, action


def _bind_uids(
    tasks: pd.DataFrame,
    *,
    aok_task_uid: str,
    field_name: str,
    uid_values: List[str] | str,
    validate_exists: Callable[[str], bool] | None = None,
) -> Tuple[pd.DataFrame, Dict[str, Any], List[str]]:
    """绑定任务 UID 列表字段的通用逻辑。

    Args:
        tasks: 任务主表。
        aok_task_uid: 任务 UID。
        field_name: 目标字段名。
        uid_values: 待绑定 UID 列表。
        validate_exists: 可选存在性校验函数。

    Returns:
        `(更新后的表, 任务记录, 无效 UID 列表)`。

    Raises:
        KeyError: 任务不存在时抛出异常。
    """

    working = _ensure_columns(tasks, list(DEFAULT_AOK_TASK_COLUMNS))
    task_uid = _stringify(aok_task_uid)
    matches = working.index[working["aok_task_uid"].astype(str) == task_uid].tolist()
    if not matches:
        raise KeyError(f"任务不存在: {task_uid}")

    requested = _normalize_uid_list(uid_values)
    invalid: List[str] = []
    valid: List[str] = []
    for uid in requested:
        if validate_exists is not None and not validate_exists(uid):
            invalid.append(uid)
            continue
        valid.append(uid)

    idx = matches[0]
    current_text = _stringify(working.loc[idx, field_name])
    merged = _normalize_uid_list(_normalize_uid_list(current_text) + valid)
    working.loc[idx, field_name] = _join_uid_list(merged)
    working.loc[idx, "updated_at"] = _utc_now_iso()
    row = dict(working.loc[idx])
    return working, row, invalid


def task_bind_literatures(
    tasks: pd.DataFrame,
    *,
    aok_task_uid: str,
    literature_uids: List[str] | str,
    validate_exists: Callable[[str], bool] | None = None,
) -> Tuple[pd.DataFrame, Dict[str, Any], List[str]]:
    """为任务绑定文献 UID 列表。

    Args:
        tasks: 任务主表。
        aok_task_uid: 任务 UID。
        literature_uids: 待绑定文献 UID。
        validate_exists: 可选文献存在性校验函数。

    Returns:
        `(更新后的表, 任务记录, 无效 UID 列表)`。
    """

    return _bind_uids(
        tasks,
        aok_task_uid=aok_task_uid,
        field_name="literature_uids",
        uid_values=literature_uids,
        validate_exists=validate_exists,
    )


def task_bind_knowledges(
    tasks: pd.DataFrame,
    *,
    aok_task_uid: str,
    knowledge_uids: List[str] | str,
    validate_exists: Callable[[str], bool] | None = None,
) -> Tuple[pd.DataFrame, Dict[str, Any], List[str]]:
    """为任务绑定知识 UID 列表。

    Args:
        tasks: 任务主表。
        aok_task_uid: 任务 UID。
        knowledge_uids: 待绑定知识 UID。
        validate_exists: 可选知识存在性校验函数。

    Returns:
        `(更新后的表, 任务记录, 无效 UID 列表)`。
    """

    return _bind_uids(
        tasks,
        aok_task_uid=aok_task_uid,
        field_name="knowledge_uids",
        uid_values=knowledge_uids,
        validate_exists=validate_exists,
    )


def _append_row(table: pd.DataFrame, row: Dict[str, Any], columns: List[str]) -> pd.DataFrame:
    """向指定表追加一行并补齐字段。

    Args:
        table: 原始数据表。
        row: 待追加记录。
        columns: 目标列集合。

    Returns:
        追加后的数据表。
    """

    working = _ensure_columns(table, columns)
    normalized_row = {column: _stringify(row.get(column)) for column in columns}
    return pd.concat([working, pd.DataFrame([normalized_row])], ignore_index=True)


def task_status_append(
    status_log: pd.DataFrame,
    *,
    aok_task_uid: str,
    from_status: str,
    to_status: str,
    trigger_gate_uid: str = "",
    decision: str = "",
    reason: str = "",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """记录一次任务状态流转。

    Args:
        status_log: 状态日志表。
        aok_task_uid: 任务 UID。
        from_status: 原状态。
        to_status: 新状态。
        trigger_gate_uid: 触发闸门 UID。
        decision: 关联决策。
        reason: 状态变化原因。

    Returns:
        `(更新后的表, 新增记录)`。
    """

    row = {
        "aok_task_uid": aok_task_uid,
        "from_status": from_status,
        "to_status": to_status,
        "trigger_gate_uid": trigger_gate_uid,
        "decision": decision,
        "reason": reason,
        "created_at": _utc_now_iso(),
    }
    return _append_row(status_log, row, list(DEFAULT_AOK_TASK_STATUS_LOG_COLUMNS)), row


def task_gate_decision_record(
    gate_decisions: pd.DataFrame,
    *,
    aok_task_uid: str,
    gate_uid: str,
    gate_review_path: str,
    agent_recommendation: str,
    human_decision: str,
    next_step: str = "",
    next_task_action: str = "",
    created_successor_task_uid: str = "",
    note: str = "",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """记录一次闸门决策。

    Args:
        gate_decisions: 闸门决策表。
        aok_task_uid: 任务 UID。
        gate_uid: 闸门 UID。
        gate_review_path: 审计报告路径。
        agent_recommendation: 审计建议。
        human_decision: 人类最终决策。
        next_step: 下一执行步骤。
        next_task_action: 下一任务动作。
        created_successor_task_uid: 新建后继任务 UID。
        note: 备注。

    Returns:
        `(更新后的表, 新增记录)`。
    """

    row = {
        "aok_task_uid": aok_task_uid,
        "gate_uid": gate_uid,
        "gate_review_path": gate_review_path,
        "agent_recommendation": agent_recommendation,
        "human_decision": human_decision,
        "next_step": next_step,
        "next_task_action": next_task_action,
        "created_successor_task_uid": created_successor_task_uid,
        "note": note,
        "created_at": _utc_now_iso(),
    }
    return _append_row(gate_decisions, row, list(DEFAULT_AOK_TASK_GATE_DECISION_COLUMNS)), row


def task_handoff_record(
    handoffs: pd.DataFrame,
    *,
    aok_task_uid: str,
    handoff_role: str,
    receiver: str,
    manifest_path: str,
    status: str = "pending",
    note: str = "",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """记录一次任务交接。

    Args:
        handoffs: 交接表。
        aok_task_uid: 任务 UID。
        handoff_role: 交接角色。
        receiver: 接收方。
        manifest_path: 交接清单路径。
        status: 交接状态。
        note: 备注。

    Returns:
        `(更新后的表, 新增记录)`。
    """

    row = {
        "aok_task_uid": aok_task_uid,
        "handoff_role": handoff_role,
        "receiver": receiver,
        "manifest_path": manifest_path,
        "status": status,
        "note": note,
        "created_at": _utc_now_iso(),
    }
    return _append_row(handoffs, row, list(DEFAULT_AOK_TASK_HANDOFF_COLUMNS)), row


def task_relation_upsert(
    relations: pd.DataFrame,
    *,
    aok_task_uid: str,
    related_task_uid: str,
    relation_type: str,
    note: str = "",
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    """插入或更新任务关系。

    Args:
        relations: 任务关系表。
        aok_task_uid: 主任务 UID。
        related_task_uid: 关联任务 UID。
        relation_type: 关系类型。
        note: 备注。

    Returns:
        `(更新后的表, 关系记录, 动作)`。
    """

    working = _ensure_columns(relations, list(DEFAULT_AOK_TASK_RELATION_COLUMNS))
    mask = (
        (working["aok_task_uid"].astype(str) == _stringify(aok_task_uid))
        & (working["related_task_uid"].astype(str) == _stringify(related_task_uid))
        & (working["relation_type"].astype(str) == _stringify(relation_type))
    )
    matches = working.index[mask].tolist()
    row = {
        "aok_task_uid": aok_task_uid,
        "related_task_uid": related_task_uid,
        "relation_type": relation_type,
        "note": note,
        "created_at": _utc_now_iso(),
    }
    if matches:
        for column, value in row.items():
            working.at[matches[0], column] = value
        return working, row, "updated"
    return _append_row(working, row, list(DEFAULT_AOK_TASK_RELATION_COLUMNS)), row, "inserted"


def task_round_snapshot_register(
    round_views: pd.DataFrame,
    *,
    aok_task_uid: str,
    source_round: str,
    view_name: str,
    artifact_path: str,
    source_affair: str,
    status: str = "active",
    note: str = "",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """登记轮次视图快照。

    Args:
        round_views: 轮次视图表。
        aok_task_uid: 任务 UID。
        source_round: 轮次编号。
        view_name: 视图名称。
        artifact_path: 视图文件路径。
        source_affair: 来源事务。
        status: 状态。
        note: 备注。

    Returns:
        `(更新后的表, 新增记录)`。
    """

    row = {
        "aok_task_uid": aok_task_uid,
        "source_round": source_round,
        "view_name": view_name,
        "artifact_path": artifact_path,
        "source_affair": source_affair,
        "status": status,
        "note": note,
        "created_at": _utc_now_iso(),
    }
    return _append_row(round_views, row, list(DEFAULT_AOK_TASK_ROUND_VIEW_COLUMNS)), row


def task_release_register(
    releases: pd.DataFrame,
    *,
    aok_task_uid: str,
    artifact_name: str,
    artifact_path: str,
    release_level: str,
    promoted_to: str,
    note: str = "",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """登记一次任务产物提升或发布。

    Args:
        releases: 发布记录表。
        aok_task_uid: 任务 UID。
        artifact_name: 产物名称。
        artifact_path: 产物路径。
        release_level: 发布级别。
        promoted_to: 提升目标路径或目标域。
        note: 备注。

    Returns:
        `(更新后的表, 新增记录)`。
    """

    row = {
        "aok_task_uid": aok_task_uid,
        "artifact_name": artifact_name,
        "artifact_path": artifact_path,
        "release_level": release_level,
        "promoted_to": promoted_to,
        "note": note,
        "created_at": _utc_now_iso(),
    }
    return _append_row(releases, row, list(DEFAULT_AOK_TASK_RELEASE_COLUMNS)), row


def task_release_promote(
    tasks: pd.DataFrame,
    artifacts: pd.DataFrame,
    releases: pd.DataFrame,
    *,
    aok_task_uid: str,
    artifact_name: str,
    artifact_path: str,
    promoted_to: str,
    release_level: str = "promote",
    note: str = "",
    ensure_file_exists: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """把任务产物登记为发布记录。

    Args:
        tasks: 任务主表。
        artifacts: 任务产物表。
        releases: 发布记录表。
        aok_task_uid: 任务 UID。
        artifact_name: 产物名称。
        artifact_path: 产物路径。
        promoted_to: 提升目标。
        release_level: 发布级别。
        note: 备注。
        ensure_file_exists: 是否检查文件存在。

    Returns:
        `(更新后的任务表, 更新后的产物表, 更新后的发布表, 发布记录)`。
    """

    updated_tasks, updated_artifacts, _ = task_artifact_register(
        tasks,
        artifacts,
        aok_task_uid=aok_task_uid,
        artifact_name=artifact_name,
        artifact_type="release",
        artifact_path=artifact_path,
        note=note,
        ensure_file_exists=ensure_file_exists,
    )
    updated_releases, release_row = task_release_register(
        releases,
        aok_task_uid=aok_task_uid,
        artifact_name=artifact_name,
        artifact_path=artifact_path,
        release_level=release_level,
        promoted_to=promoted_to,
        note=note,
    )
    return updated_tasks, updated_artifacts, updated_releases, release_row


def task_literature_binding_register(
    bindings: pd.DataFrame,
    *,
    aok_task_uid: str,
    uid_literature: str,
    binding_role: str,
    source_affair: str = "",
    source_gate_uid: str = "",
    release_level: str = "working",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """登记任务与文献的显式绑定记录。"""

    row = {
        "aok_task_uid": aok_task_uid,
        "uid_literature": uid_literature,
        "binding_role": binding_role,
        "source_affair": source_affair,
        "source_gate_uid": source_gate_uid,
        "release_level": release_level,
        "created_at": _utc_now_iso(),
    }
    return _append_row(bindings, row, list(DEFAULT_AOK_TASK_LITERATURE_BINDING_COLUMNS)), row


def task_knowledge_binding_register(
    bindings: pd.DataFrame,
    *,
    aok_task_uid: str,
    uid_knowledge: str,
    binding_role: str,
    source_affair: str = "",
    source_gate_uid: str = "",
    release_level: str = "working",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """登记任务与知识的显式绑定记录。"""

    row = {
        "aok_task_uid": aok_task_uid,
        "uid_knowledge": uid_knowledge,
        "binding_role": binding_role,
        "source_affair": source_affair,
        "source_gate_uid": source_gate_uid,
        "release_level": release_level,
        "created_at": _utc_now_iso(),
    }
    return _append_row(bindings, row, list(DEFAULT_AOK_TASK_KNOWLEDGE_BINDING_COLUMNS)), row


def task_artifact_register(
    tasks: pd.DataFrame,
    artifacts: pd.DataFrame,
    *,
    aok_task_uid: str,
    artifact_name: str,
    artifact_type: str,
    artifact_path: str,
    note: str = "",
    ensure_file_exists: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """登记任务产物。

    Args:
        tasks: 任务主表。
        artifacts: 任务产物表。
        aok_task_uid: 任务 UID。
        artifact_name: 产物名称。
        artifact_type: 产物类型。
        artifact_path: 产物绝对路径。
        note: 备注。
        ensure_file_exists: 是否强制检查文件存在。

    Returns:
        `(更新后的任务表, 更新后的产物表, 新增产物记录)`。

    Raises:
        KeyError: 任务不存在时抛出异常。
        FileNotFoundError: 要求检查存在但文件不存在时抛出异常。
    """

    task_uid = _stringify(aok_task_uid)
    task_table = _ensure_columns(tasks, list(DEFAULT_AOK_TASK_COLUMNS))
    artifact_table = _ensure_columns(artifacts, list(DEFAULT_AOK_TASK_ARTIFACT_COLUMNS))

    matches = task_table.index[task_table["aok_task_uid"].astype(str) == task_uid].tolist()
    if not matches:
        raise KeyError(f"任务不存在: {task_uid}")

    path_obj = Path(_stringify(artifact_path)).resolve()
    if ensure_file_exists and not path_obj.exists():
        raise FileNotFoundError(f"产物文件不存在: {path_obj}")

    row = {
        "aok_task_uid": task_uid,
        "artifact_name": _stringify(artifact_name) or path_obj.name,
        "artifact_type": _stringify(artifact_type) or "other",
        "artifact_path": str(path_obj),
        "note": _stringify(note),
        "created_at": _utc_now_iso(),
    }
    artifact_table = pd.concat([artifact_table, pd.DataFrame([row])], ignore_index=True)

    idx = matches[0]
    task_table.loc[idx, "updated_at"] = _utc_now_iso()
    return task_table, artifact_table, row


def task_bundle_export(
    artifacts: pd.DataFrame,
    *,
    aok_task_uid: str,
    output_dir: str | Path,
) -> Dict[str, Any]:
    """导出指定任务的产物集合。

    Args:
        artifacts: 任务产物表。
        aok_task_uid: 任务 UID。
        output_dir: 导出目录。

    Returns:
        导出结果摘要，包含复制文件列表。
    """

    artifact_table = _ensure_columns(artifacts, list(DEFAULT_AOK_TASK_ARTIFACT_COLUMNS))
    task_uid = _stringify(aok_task_uid)
    filtered = artifact_table[artifact_table["aok_task_uid"].astype(str) == task_uid]

    target_root = (Path(output_dir).resolve() / task_uid).resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    exported_files: List[str] = []
    missing_files: List[str] = []
    for _, item in filtered.iterrows():
        source_path = Path(_stringify(item.get("artifact_path"))).resolve()
        if not source_path.exists():
            missing_files.append(str(source_path))
            continue
        target_path = target_root / source_path.name
        if target_path.exists() and target_path.resolve() != source_path.resolve():
            target_path = target_root / f"{source_path.stem}_{sha1(str(source_path).encode('utf-8')).hexdigest()[:6]}{source_path.suffix}"
        shutil.copy2(source_path, target_path)
        exported_files.append(str(target_path))

    return {
        "status": "PASS" if not missing_files else "WARN",
        "aok_task_uid": task_uid,
        "export_root": str(target_root),
        "exported_files": exported_files,
        "missing_files": missing_files,
        "export_count": len(exported_files),
    }


def task_get(
    tasks: pd.DataFrame,
    artifacts: pd.DataFrame,
    *,
    aok_task_uid: str,
) -> Dict[str, Any]:
    """读取任务详情与产物列表。

    Args:
        tasks: 任务主表。
        artifacts: 任务产物表。
        aok_task_uid: 任务 UID。

    Returns:
        任务详情字典，附带产物列表。

    Raises:
        KeyError: 任务不存在时抛出异常。
    """

    task_table = _ensure_columns(tasks, list(DEFAULT_AOK_TASK_COLUMNS))
    artifact_table = _ensure_columns(artifacts, list(DEFAULT_AOK_TASK_ARTIFACT_COLUMNS))
    task_uid = _stringify(aok_task_uid)

    matches = task_table.index[task_table["aok_task_uid"].astype(str) == task_uid].tolist()
    if not matches:
        raise KeyError(f"任务不存在: {task_uid}")

    idx = matches[0]
    record = dict(task_table.loc[idx])
    related = artifact_table[artifact_table["aok_task_uid"].astype(str) == task_uid]
    artifacts_list = [dict(item) for _, item in related.iterrows()]

    return {
        **record,
        "literature_uids_list": _normalize_uid_list(_stringify(record.get("literature_uids"))),
        "knowledge_uids_list": _normalize_uid_list(_stringify(record.get("knowledge_uids"))),
        "artifacts": artifacts_list,
        "artifact_count": len(artifacts_list),
    }


def bootstrap_aok_taskdb(
    project_root: str | Path = ".",
    *,
    tasks_db_root: str | Path | None = None,
    tasks_workspace_root: str | Path | None = None,
) -> Dict[str, Any]:
    """初始化 AOK 003 任务数据库骨架。

    Args:
        project_root: 项目根目录。
        tasks_db_root: 自定义任务数据库目录，默认使用 `project_root/database/tasks`。
        tasks_workspace_root: 自定义任务工作区目录，默认使用 `project_root/tasks`。

    Returns:
        初始化结果摘要。
    """

    root, resolved_tasks_db_root, resolved_tasks_workspace_root = _resolve_aok_roots(
        project_root=project_root,
        tasks_db_root=tasks_db_root,
        tasks_workspace_root=tasks_workspace_root,
    )
    resolved_tasks_db_root.mkdir(parents=True, exist_ok=True)
    resolved_tasks_workspace_root.mkdir(parents=True, exist_ok=True)

    files = {
        "tasks.csv": ",".join(DEFAULT_AOK_TASK_COLUMNS) + "\n",
        "task_artifacts.csv": ",".join(DEFAULT_AOK_TASK_ARTIFACT_COLUMNS) + "\n",
        "task_status_log.csv": ",".join(DEFAULT_AOK_TASK_STATUS_LOG_COLUMNS) + "\n",
        "task_gate_decisions.csv": ",".join(DEFAULT_AOK_TASK_GATE_DECISION_COLUMNS) + "\n",
        "task_handoffs.csv": ",".join(DEFAULT_AOK_TASK_HANDOFF_COLUMNS) + "\n",
        "task_relations.csv": ",".join(DEFAULT_AOK_TASK_RELATION_COLUMNS) + "\n",
        "task_round_views.csv": ",".join(DEFAULT_AOK_TASK_ROUND_VIEW_COLUMNS) + "\n",
        "task_releases.csv": ",".join(DEFAULT_AOK_TASK_RELEASE_COLUMNS) + "\n",
        "task_literature_bindings.csv": ",".join(DEFAULT_AOK_TASK_LITERATURE_BINDING_COLUMNS) + "\n",
        "task_knowledge_bindings.csv": ",".join(DEFAULT_AOK_TASK_KNOWLEDGE_BINDING_COLUMNS) + "\n",
    }

    created_paths: List[str] = []
    for file_name, header in files.items():
        target = resolved_tasks_db_root / file_name
        if not target.exists():
            target.write_text(header, encoding="utf-8")
        created_paths.append(str(target))

    return {
        "status": "PASS",
        "mode": "aok-taskdb-bootstrap",
        "project_root": str(root),
        "artifacts": {
            "tasks_db_root": str(resolved_tasks_db_root),
            "tasks_workspace_root": str(resolved_tasks_workspace_root),
        },
        "created_paths": created_paths,
    }


def _validate_task_uid_exists(uid_set: set[str], uid_text: str) -> bool:
    """检查 UID 是否在给定集合中。

    Args:
        uid_set: UID 集合。
        uid_text: UID 文本。

    Returns:
        若存在返回 True，否则返回 False。
    """

    return _stringify(uid_text) in uid_set


def validate_aok_taskdb(
    project_root: str | Path = ".",
    *,
    tasks_db_root: str | Path | None = None,
    tasks_workspace_root: str | Path | None = None,
    references_db: str | Path | None = None,
    knowledge_db: str | Path | None = None,
) -> Dict[str, Any]:
    """校验 AOK 003 任务数据库一致性。

    Args:
        project_root: 项目根目录。
        tasks_db_root: 自定义任务数据库目录，默认使用 `project_root/database/tasks`。
        tasks_workspace_root: 自定义任务工作区目录，默认使用 `project_root/tasks`。
        references_db: 自定义文献主表路径。
        knowledge_db: 自定义知识索引表路径。

    Returns:
        校验结果摘要，包含错误和警告。
    """

    root, resolved_tasks_db_root, resolved_tasks_workspace_root = _resolve_aok_roots(
        project_root=project_root,
        tasks_db_root=tasks_db_root,
        tasks_workspace_root=tasks_workspace_root,
    )
    resolved_references_db = (
        resolve_content_db_path(Path(references_db).resolve())
        if references_db is not None
        else root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME
    )
    resolved_knowledge_db = (
        resolve_content_db_path(Path(knowledge_db).resolve())
        if knowledge_db is not None
        else root / "database" / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME
    )

    required_files = [
        resolved_tasks_db_root / "tasks.csv",
        resolved_tasks_db_root / "task_artifacts.csv",
        resolved_tasks_db_root / "task_status_log.csv",
        resolved_tasks_db_root / "task_gate_decisions.csv",
        resolved_tasks_db_root / "task_handoffs.csv",
        resolved_tasks_db_root / "task_relations.csv",
        resolved_tasks_db_root / "task_round_views.csv",
        resolved_tasks_db_root / "task_releases.csv",
        resolved_tasks_db_root / "task_literature_bindings.csv",
        resolved_tasks_db_root / "task_knowledge_bindings.csv",
    ]

    errors: List[str] = []
    warnings: List[str] = []

    for path in required_files:
        if not path.exists():
            errors.append(f"缺少文件: {path}")

    if not resolved_tasks_workspace_root.exists():
        errors.append(f"缺少任务目录: {resolved_tasks_workspace_root}")

    if errors:
        return {
            "status": "BLOCKED",
            "mode": "aok-taskdb-validate",
            "project_root": str(root),
            "error_count": len(errors),
            "warning_count": 0,
            "errors": errors,
            "warnings": warnings,
        }

    tasks = pd.read_csv(resolved_tasks_db_root / "tasks.csv", dtype=str, keep_default_na=False)
    tasks = _ensure_columns(tasks, list(DEFAULT_AOK_TASK_COLUMNS))
    artifacts = pd.read_csv(resolved_tasks_db_root / "task_artifacts.csv", dtype=str, keep_default_na=False)
    artifacts = _ensure_columns(artifacts, list(DEFAULT_AOK_TASK_ARTIFACT_COLUMNS))
    gate_decisions = _ensure_columns(
        pd.read_csv(resolved_tasks_db_root / "task_gate_decisions.csv", dtype=str, keep_default_na=False),
        list(DEFAULT_AOK_TASK_GATE_DECISION_COLUMNS),
    )
    handoffs = _ensure_columns(
        pd.read_csv(resolved_tasks_db_root / "task_handoffs.csv", dtype=str, keep_default_na=False),
        list(DEFAULT_AOK_TASK_HANDOFF_COLUMNS),
    )
    relations = _ensure_columns(
        pd.read_csv(resolved_tasks_db_root / "task_relations.csv", dtype=str, keep_default_na=False),
        list(DEFAULT_AOK_TASK_RELATION_COLUMNS),
    )
    round_views = _ensure_columns(
        pd.read_csv(resolved_tasks_db_root / "task_round_views.csv", dtype=str, keep_default_na=False),
        list(DEFAULT_AOK_TASK_ROUND_VIEW_COLUMNS),
    )
    releases = _ensure_columns(
        pd.read_csv(resolved_tasks_db_root / "task_releases.csv", dtype=str, keep_default_na=False),
        list(DEFAULT_AOK_TASK_RELEASE_COLUMNS),
    )

    task_uid_set = set(tasks["aok_task_uid"].astype(str).tolist())

    literature_uid_set: set[str] = set()
    if resolved_references_db.exists():
        if resolved_references_db.suffix.lower() == ".db":
            with sqlite3.connect(str(resolved_references_db)) as conn:
                literature_table = pd.read_sql_query("SELECT uid_literature FROM literatures", conn)
        else:
            literature_table = pd.read_csv(resolved_references_db, dtype=str, keep_default_na=False)
        if "uid_literature" in literature_table.columns:
            literature_uid_set = set(literature_table["uid_literature"].astype(str).tolist())
    else:
        warnings.append(f"未找到文献主表，跳过文献 UID 校验: {resolved_references_db}")

    knowledge_uid_set: set[str] = set()
    if resolved_knowledge_db.exists():
        if resolved_knowledge_db.suffix.lower() == ".db":
            with sqlite3.connect(str(resolved_knowledge_db)) as conn:
                knowledge_table = pd.read_sql_query("SELECT uid_knowledge FROM knowledge_index", conn)
        else:
            knowledge_table = pd.read_csv(resolved_knowledge_db, dtype=str, keep_default_na=False)
        if "uid_knowledge" in knowledge_table.columns:
            knowledge_uid_set = set(knowledge_table["uid_knowledge"].astype(str).tolist())
    else:
        warnings.append(f"未找到知识索引表，跳过知识 UID 校验: {resolved_knowledge_db}")

    for _, row in tasks.iterrows():
        task_uid = _stringify(row.get("aok_task_uid"))
        workspace_dir = _stringify(row.get("workspace_dir"))
        if not workspace_dir:
            errors.append(f"任务缺少 workspace_dir: {task_uid}")
        elif not Path(workspace_dir).exists():
            errors.append(f"任务工作目录不存在: {task_uid} -> {workspace_dir}")

        if literature_uid_set:
            for uid in _normalize_uid_list(_stringify(row.get("literature_uids"))):
                if not _validate_task_uid_exists(literature_uid_set, uid):
                    errors.append(f"任务绑定的文献 UID 不存在: {task_uid} -> {uid}")

        if knowledge_uid_set:
            for uid in _normalize_uid_list(_stringify(row.get("knowledge_uids"))):
                if not _validate_task_uid_exists(knowledge_uid_set, uid):
                    errors.append(f"任务绑定的知识 UID 不存在: {task_uid} -> {uid}")

    for _, row in artifacts.iterrows():
        task_uid = _stringify(row.get("aok_task_uid"))
        if not _validate_task_uid_exists(task_uid_set, task_uid):
            errors.append(f"产物引用了不存在任务: {task_uid}")
        artifact_path = _stringify(row.get("artifact_path"))
        if not artifact_path:
            errors.append(f"产物记录缺少 artifact_path: {task_uid}")
            continue
        if not Path(artifact_path).exists():
            errors.append(f"产物路径不存在: {task_uid} -> {artifact_path}")

    for _, row in gate_decisions.iterrows():
        task_uid = _stringify(row.get("aok_task_uid"))
        gate_review_path = _stringify(row.get("gate_review_path"))
        if task_uid and not _validate_task_uid_exists(task_uid_set, task_uid):
            errors.append(f"闸门记录引用了不存在任务: {task_uid}")
        if gate_review_path and not Path(gate_review_path).exists():
            errors.append(f"闸门审计报告不存在: {task_uid} -> {gate_review_path}")

    for _, row in handoffs.iterrows():
        task_uid = _stringify(row.get("aok_task_uid"))
        manifest_path = _stringify(row.get("manifest_path"))
        if task_uid and not _validate_task_uid_exists(task_uid_set, task_uid):
            errors.append(f"交接记录引用了不存在任务: {task_uid}")
        if manifest_path and not Path(manifest_path).exists():
            errors.append(f"交接清单不存在: {task_uid} -> {manifest_path}")

    for _, row in relations.iterrows():
        task_uid = _stringify(row.get("aok_task_uid"))
        related_task_uid = _stringify(row.get("related_task_uid"))
        if task_uid and not _validate_task_uid_exists(task_uid_set, task_uid):
            errors.append(f"任务关系引用了不存在任务: {task_uid}")
        if related_task_uid and not _validate_task_uid_exists(task_uid_set, related_task_uid):
            errors.append(f"任务关系引用了不存在关联任务: {task_uid} -> {related_task_uid}")

    for _, row in round_views.iterrows():
        task_uid = _stringify(row.get("aok_task_uid"))
        artifact_path = _stringify(row.get("artifact_path"))
        if task_uid and not _validate_task_uid_exists(task_uid_set, task_uid):
            errors.append(f"轮次视图引用了不存在任务: {task_uid}")
        if artifact_path and not Path(artifact_path).exists():
            errors.append(f"轮次视图文件不存在: {task_uid} -> {artifact_path}")

    for _, row in releases.iterrows():
        task_uid = _stringify(row.get("aok_task_uid"))
        artifact_path = _stringify(row.get("artifact_path"))
        if task_uid and not _validate_task_uid_exists(task_uid_set, task_uid):
            errors.append(f"发布记录引用了不存在任务: {task_uid}")
        if artifact_path and not Path(artifact_path).exists():
            errors.append(f"发布产物不存在: {task_uid} -> {artifact_path}")

    return {
        "status": "PASS" if not errors else "BLOCKED",
        "mode": "aok-taskdb-validate",
        "project_root": str(root),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }
