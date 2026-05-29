"""主链事务入口注册表工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autodokit.path_compat import resolve_portable_path
from autodokit.tools.config_contract_utils import export_to_chinese_contract, normalize_to_legacy_contract
from autodokit.tools.obsidian_note_timezone_tools import get_current_time_iso


MAINLINE_AFFAIR_ENTRY_MAP: dict[str, dict[str, Any]] = {
    "A010": {"node_name": "项目初始化", "affair_uid": "ar_A010_项目初始化", "module": "autodokit.tools.a010_skill_bootstrap_runner", "callable": "execute", "implemented": True, "notes": "A010 当前只走技能脚本冷启动，不再默认走 autodokit.affairs.项目初始化.affair。"},
    "A020": {"node_name": "文献导入与预处理", "affair_uid": "ar_A020_导入和预处理文献元数据", "module": "autodokit.affairs.导入和预处理文献元数据.affair", "callable": "execute", "implemented": True},
    "A030": {"node_name": "研究问题与关键词生成", "affair_uid": "ar_A030_生成关键词集合", "module": "autodokit.affairs.生成关键词集合.affair", "callable": "execute", "implemented": True},
    "A040": {"node_name": "文献检索与入库", "affair_uid": "ar_A040_检索治理", "module": "autodokit.affairs.检索治理.affair", "callable": "execute", "implemented": True},
    "A045": {"node_name": "文献下载与主附件入库", "affair_uid": "ar_A045_文献下载与主附件入库", "module": "autodokit.affairs.文献下载与主附件入库.affair", "callable": "execute", "implemented": True},
    "A050": {
        "node_name": "预处理优先级生成",
        "affair_uid": "ar_A050_统一文献预处理解析",
        "module": "autodokit.affairs.统一文献预处理解析.affair",
        "callable": "execute",
        "implemented": True,
        "notes": "A050 对 content.db 文献主表全库生成 A050_REVIEW/A050_NON_REVIEW 当前优先级，并回写主文献表既有预处理摘要列（execution_mode=priority_only）。",
    },
    "A055": {
        "node_name": "统一文献预处理执行",
        "affair_uid": "ar_A055_统一文献预处理执行",
        "module": "autodokit.affairs.统一文献预处理解析.affair",
        "callable": "execute",
        "implemented": True,
        "notes": "A055 按主文献表当前预处理摘要列派生的 queued 队列持续消费，并以 priority ASC 执行具体预处理（execution_mode=full_preprocess）。",
    },
    "A060": {
        "node_name": "综述文献候选视图构建",
        "affair_uid": "ar_A060_综述文献候选视图构建",
        "module": "autodokit.affairs.候选文献视图构建.affair",
        "callable": "execute",
        "implemented": True,
        "notes": "A060 重新作为综述链候选视图构建入口，仅负责生成综述候选池、阅读池、批次与 A070 当前态输入。",
    },
    "A070": {
        "node_name": "综述文献研读",
        "affair_uid": "ar_A070_综述文献研读",
        "module": "autodokit.affairs.候选文献视图构建.affair",
        "callable": "execute",
        "implemented": True,
        "notes": "A070 承接 A060 输出，当前外部节点内串行执行 A065 参考文献预处理与 A070 综述综合研读。",
    },
    "A075": {
        "node_name": "普通文献候选视图构建",
        "affair_uid": "ar_A075_普通文献候选视图构建",
        "module": "autodokit.affairs.非综述候选种子生成.affair",
        "callable": "execute",
        "implemented": True,
        "notes": "A075 重新作为普通链候选视图构建入口，负责消费 A070 导出件与人工种子并正式写入 A080 队列。",
    },
    "A080": {
        "node_name": "普通文献泛读",
        "affair_uid": "ar_A080_普通文献泛读",
        "module": "autodokit.affairs.非综述候选视图构建.affair",
        "callable": "execute",
        "implemented": True,
        "notes": "A080 当前负责普通文献预处理与解析落盘，并把可继续阅读的条目正式推进到 A095。",
    },
    "A095": {
        "node_name": "普通文献研读候选视图构建",
        "affair_uid": "ar_A095_普通文献研读候选视图构建",
        "module": "autodokit.affairs.普通文献研读候选视图构建.affair",
        "callable": "execute",
        "implemented": True,
        "notes": "A095 承接 A080 输出，执行普通文献粗读、轻量分析与批次汇总，并把可深读条目推进到 A100。",
    },
    "A100": {
        "node_name": "文献批判性研读",
        "affair_uid": "ar_A100_文献批判性研读",
        "module": "autodokit.affairs.文献研读与正式知识回写.affair",
        "callable": "execute",
        "implemented": True,
        "notes": "A100 物理吸收 A105，当前主链显示名统一为文献批判性研读。",
    },
    "A110": {
        "node_name": "研究脉络梳理",
        "affair_uid": "ar_A110_研究脉络梳理",
        "module": "autodokit.affairs.文献矩阵.affair",
        "callable": "execute",
        "implemented": True,
        "notes": "A110 物理吸收 A120/A130，当前主链显示名统一为研究脉络梳理。",
    },
    "A140": {
        "node_name": "创新点凝练",
        "affair_uid": "ar_A140_创新点凝练",
        "module": "autodokit.affairs.创新点池构建.affair",
        "callable": "execute",
        "implemented": True,
        "notes": "A140 物理吸收 A150/A160，当前主链显示名统一为创新点凝练。",
    },
}


def build_mainline_affair_entry_registry(
    *,
    workspace_root: str | Path,
    node_inputs: dict[str, Any] | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> dict[str, Any]:
    """构建主链事务入口注册表。"""

    resolved_root = resolve_portable_path(workspace_root, base=Path.cwd())
    records: list[dict[str, Any]] = []
    for node_code, base in MAINLINE_AFFAIR_ENTRY_MAP.items():
        record = dict(base)
        if node_inputs and node_code in node_inputs:
            config_path = str(resolve_portable_path(str(node_inputs[node_code]), base=resolved_root))
        else:
            config_path = str(resolved_root / "config" / "affairs_config" / f"{node_code}.json")
        record.update({"node_code": node_code, "config_path": config_path})
        records.append(record)

    payload = {
        "schema_version": "2026-04-05-mainline-entry-v1",
        "generated_at": get_current_time_iso(timezone_name),
        "workspace_root": str(resolved_root),
        "timezone": timezone_name,
        "records": records,
    }
    return export_to_chinese_contract(payload)


def write_mainline_affair_entry_registry(
    output_path: str | Path,
    *,
    workspace_root: str | Path,
    node_inputs: dict[str, Any] | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> Path:
    """写出主链事务入口注册表 JSON。"""

    target = resolve_portable_path(output_path, base=Path.cwd())
    payload = build_mainline_affair_entry_registry(
        workspace_root=workspace_root,
        node_inputs=node_inputs,
        timezone_name=timezone_name,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def resolve_mainline_affair_entry(node_code: str, registry: dict[str, Any] | str | Path) -> dict[str, Any]:
    """从主链事务入口注册表中解析单个节点。"""

    if isinstance(registry, (str, Path)):
        registry_path = resolve_portable_path(registry, base=Path.cwd())
        payload = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    else:
        payload = dict(registry)
    payload = normalize_to_legacy_contract(payload)
    for record in payload.get("records", []):
        if str(record.get("node_code") or "").strip() == str(node_code or "").strip():
            return record
    raise KeyError(f"未找到主链节点入口：{node_code}")


__all__ = [
    "MAINLINE_AFFAIR_ENTRY_MAP",
    "build_mainline_affair_entry_registry",
    "write_mainline_affair_entry_registry",
    "resolve_mainline_affair_entry",
]