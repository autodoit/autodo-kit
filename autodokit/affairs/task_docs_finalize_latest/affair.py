"""事务：latest→UID 固化（重命名 + 同步 frontmatter）。

把 `任务名-需求/设计/过程-latest.md` 固化为 `任务名-需求/设计/过程-<UID>.md`。

UID 来源：
- 默认从 frontmatter 的 tags 中读取 `#时间戳/<UID>`。
- 可选：当缺失时生成 UID 并回写（generate_if_missing=true）。

输入（config，核心字段）：
- root_dir: 扫描根目录（必填）
- task_name: 任务名称（必填）
- doc_types: 类型列表（可选，默认 ["需求","设计","过程"]）
- generate_if_missing: UID 缺失时是否生成并回写（可选，默认 false）
- uid_mode / uid_random_length: 生成 UID 时使用（可选）
- dry_run: 是否干运行（可选，默认 false）

输出：
- 固化后的文件路径列表。

Args:
    config_path: 调度器传入的配置文件路径（.json 或 .py）。

Returns:
    写出的文件 Path 列表。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from autodokit.tools import load_json_or_py
from autodokit.tools.task_docs import UidSpec, finalize_latest_file


@dataclass
class FinalizeLatestConfig:
    """固化 latest 的事务配置。

    Attributes:
        root_dir: 扫描根目录。
        task_name: 任务名。
        doc_types: 需要固化的文档类型列表。
        generate_if_missing: UID 缺失时是否生成并回写。
        uid_mode: UID 生成模式。
        uid_random_length: UID 随机后缀长度。
        dry_run: 是否干运行。
    """

    root_dir: str
    task_name: str
    doc_types: List[str]
    generate_if_missing: bool = False
    uid_mode: str = "timestamp-us-rand"
    uid_random_length: int = 2
    dry_run: bool = False


def _parse_config(data: Dict[str, Any]) -> FinalizeLatestConfig:
    """解析并校验事务配置。

    Args:
        data: 配置字典。

    Returns:
        FinalizeLatestConfig: 结构化配置。

    Raises:
        ValueError: 配置缺失或类型不正确。
    """

    root_dir = str(data.get("root_dir") or "").strip()
    if not root_dir:
        raise ValueError("root_dir 不能为空")

    task_name = str(data.get("task_name") or "").strip()
    if not task_name:
        raise ValueError("task_name 不能为空")

    doc_types_raw = data.get("doc_types")
    if doc_types_raw is None:
        doc_types = ["需求", "设计", "过程"]
    else:
        if not isinstance(doc_types_raw, list) or not doc_types_raw:
            raise ValueError("doc_types 必须是非空列表（或不提供以使用默认值）")
        doc_types = [str(x).strip() for x in doc_types_raw if str(x).strip()]
        if not doc_types:
            raise ValueError("doc_types 不能为空")

    generate_if_missing = bool(data.get("generate_if_missing") or False)
    uid_mode = str(data.get("uid_mode") or "timestamp-us-rand").strip() or "timestamp-us-rand"
    uid_random_length = int(data.get("uid_random_length") or 2)
    dry_run = bool(data.get("dry_run") or False)

    return FinalizeLatestConfig(
        root_dir=root_dir,
        task_name=task_name,
        doc_types=doc_types,
        generate_if_missing=generate_if_missing,
        uid_mode=uid_mode,
        uid_random_length=uid_random_length,
        dry_run=dry_run,
    )


def execute(config_path: Path, workspace_root: Path | None = None) -> List[Path]:
    """AOK 事务入口：固化 latest 文档。

    Args:
        config_path: 调度器传入的临时配置文件路径。
        workspace_root: 工作区根目录（由调度器传入；本事务不强依赖）。

    Returns:
        固化后的文件 Path 列表。
    """

    data = load_json_or_py(Path(config_path))
    cfg = _parse_config(data)

    root_dir = Path(cfg.root_dir)
    uid_spec = UidSpec(mode=cfg.uid_mode, random_length=cfg.uid_random_length)

    out_paths: List[Path] = []
    for doc_type in cfg.doc_types:
        latest_name = f"{cfg.task_name}-{doc_type}-latest.md"
        candidate = (root_dir / latest_name).resolve()
        if not candidate.exists():
            # 兼容：如果用户传入的 root_dir 更大，允许递归查找同名文件
            found = list(root_dir.rglob(latest_name))
            if not found:
                raise FileNotFoundError(f"找不到 latest 文件：{latest_name}（root_dir={root_dir}）")
            candidate = found[0].resolve()

        out_paths.append(
            finalize_latest_file(
                path=candidate,
                generate_if_missing=cfg.generate_if_missing,
                uid_spec=uid_spec,
                dry_run=cfg.dry_run,
            )
        )

    return out_paths

