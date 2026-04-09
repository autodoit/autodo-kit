"""主链事务入口注册表工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autodokit.tools.obsidian_note_timezone_tools import get_current_time_iso


MAINLINE_AFFAIR_ENTRY_MAP: dict[str, dict[str, Any]] = {
    "A010": {"node_name": "项目初始化", "affair_uid": "项目初始化", "module": "autodokit.affairs.项目初始化.affair", "callable": "execute", "implemented": True},
    "A020": {"node_name": "文献导入与预处理", "affair_uid": "导入和预处理文献元数据", "module": "autodokit.affairs.导入和预处理文献元数据.affair", "callable": "execute", "implemented": True},
    "A030": {"node_name": "研究问题与关键词生成", "affair_uid": "生成关键词集合", "module": "autodokit.affairs.生成关键词集合.affair", "callable": "execute", "implemented": True},
    "A040": {"node_name": "文献检索与入库", "affair_uid": "检索治理", "module": "autodokit.affairs.检索治理.affair", "callable": "execute", "implemented": True},
    "A050": {"node_name": "综述候选文献视图构建", "affair_uid": "候选文献视图构建", "module": "autodokit.affairs.候选文献视图构建.affair", "callable": "execute", "implemented": True},
    "A060": {"node_name": "综述预处理", "affair_uid": "综述预处理", "module": "autodokit.affairs.综述预处理.affair", "callable": "execute", "implemented": True},
    "A065": {"node_name": "综述参考文献预处理与笔记骨架", "affair_uid": "综述参考文献预处理与笔记骨架", "module": "autodokit.affairs.综述参考文献预处理与笔记骨架.affair", "callable": "execute", "implemented": True},
    "A070": {"node_name": "综述研读与研究脉络", "affair_uid": "综述研读与研究地图生成", "module": "autodokit.affairs.综述研读与研究地图生成.affair", "callable": "execute", "implemented": True},
    "A080": {"node_name": "非综述候选与预处理编排", "affair_uid": "非综述候选视图构建", "module": "autodokit.affairs.非综述候选视图构建.affair", "callable": "execute", "implemented": True},
    "A090": {"node_name": "文献泛读与轻量分析", "affair_uid": "文献泛读与粗读", "module": "autodokit.affairs.文献泛读与粗读.affair", "callable": "execute", "implemented": True},
    "A095": {"node_name": "泛读批次分析汇总", "affair_uid": "泛读批次分析汇总", "module": "autodokit.affairs.泛读批次分析汇总.affair", "callable": "execute", "implemented": True},
    "A100": {"node_name": "文献研读与正式知识回写", "affair_uid": "文献研读与正式知识回写", "module": "autodokit.affairs.文献研读与正式知识回写.affair", "callable": "execute", "implemented": True},
    "A105": {"node_name": "文献批判性研读与标准笔记", "affair_uid": "文献批判性研读与标准笔记", "module": "autodokit.affairs.文献批判性研读与标准笔记.affair", "callable": "execute", "implemented": True},
    "A110": {"node_name": "文献矩阵与研究缺口", "affair_uid": "文献矩阵", "module": "autodokit.affairs.文献矩阵.affair", "callable": "execute", "implemented": True},
    "A120": {"node_name": "研究脉络梳理", "affair_uid": "研究脉络梳理", "module": "autodokit.affairs.研究脉络梳理.affair", "callable": "execute", "implemented": True},
    "A130": {"node_name": "领域知识框架", "affair_uid": "领域知识框架构建", "module": "", "callable": "execute", "implemented": False, "notes": "当前仓库未发现同名官方 affair.py，保留为设计占位。"},
    "A140": {"node_name": "创新点池构建", "affair_uid": "创新点池构建", "module": "autodokit.affairs.创新点池构建.affair", "callable": "execute", "implemented": True},
    "A150": {"node_name": "创新点可行性验证", "affair_uid": "创新点可行性验证", "module": "autodokit.affairs.创新点可行性验证.affair", "callable": "execute", "implemented": True},
    "A160": {"node_name": "报告收敛与交付", "affair_uid": "成果归档发布", "module": "autodokit.affairs.成果归档发布.affair", "callable": "execute", "implemented": True, "notes": "如需完整交付链，可在 PA 中追加 task_docs_* 事务。"},
}


def build_mainline_affair_entry_registry(
    *,
    workspace_root: str | Path,
    node_inputs: dict[str, Any] | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> dict[str, Any]:
    """构建主链事务入口注册表。"""

    resolved_root = Path(workspace_root).expanduser().resolve()
    records: list[dict[str, Any]] = []
    for node_code, base in MAINLINE_AFFAIR_ENTRY_MAP.items():
        record = dict(base)
        if node_inputs and node_code in node_inputs:
            config_path = str(Path(str(node_inputs[node_code])).expanduser().resolve())
        else:
            config_path = str((resolved_root / "config" / "affairs_config" / f"{node_code}.json").resolve())
        record.update({"node_code": node_code, "config_path": config_path})
        records.append(record)

    return {
        "schema_version": "2026-04-05-mainline-entry-v1",
        "generated_at": get_current_time_iso(timezone_name),
        "workspace_root": str(resolved_root),
        "timezone": timezone_name,
        "records": records,
    }


def write_mainline_affair_entry_registry(
    output_path: str | Path,
    *,
    workspace_root: str | Path,
    node_inputs: dict[str, Any] | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> Path:
    """写出主链事务入口注册表 JSON。"""

    target = Path(output_path).expanduser().resolve()
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
        payload = json.loads(Path(registry).expanduser().resolve().read_text(encoding="utf-8-sig"))
    else:
        payload = dict(registry)
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