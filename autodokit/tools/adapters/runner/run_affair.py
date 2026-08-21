"""AOK 统一事务 Runner。

为 Copilot Skill 提供统一的 AOK affair 调用入口。Skill-local wrapper 只需解析参数
并调用本 runner，无需重复实现事务查找、导入、执行逻辑。

用法：
    python -m autodokit.tools.adapters.runner.run_affair \\
        --affair "生成关键词集合" \\
        --params params.json \\
        --repo-root /path/to/autodo-kit \\
        --dry-run

    # 或通过 Python API：
    from autodokit.tools.adapters.runner.run_affair import run_affair
    result = run_affair("生成关键词集合", Path("params.json"), repo_root=Path("..."))

设计原则：
1. 不承载业务逻辑 —— 只负责事务查找、参数加载、调用 execute()。
2. 与 run_capability.py 互补 —— 后者按 tool_name 调用工具函数，本脚本按 affair 名称调用事务。
3. 输出结构化 JSON 结果，便于 Skill wrapper 解析。
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class AffairResult:
    """事务执行结果。"""
    affair_name: str
    status: str = "FAIL"          # "PASS" | "FAIL" | "DRY_RUN"
    code: int = 1
    output_files: list[str] = None  # type: ignore[assignment]
    error: str = ""
    metadata: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.output_files is None:
            self.output_files = []
        if self.metadata is None:
            self.metadata = {}


# ---------------------------------------------------------------------------
# 核心逻辑
# ---------------------------------------------------------------------------

def find_affair_dir(affair_name: str, repo_root: Path) -> Path | None:
    """在 autodo-kit 仓库中按名称查找事务目录。
    
    Args:
        affair_name: 事务目录名，如 "生成关键词集合"、"CNKI基础检索"。
        repo_root: autodo-kit 仓库根目录。
    
    Returns:
        匹配的 affair 目录路径，未找到则返回 None。
    """
    affairs_root = repo_root / "autodokit" / "affairs"
    if not affairs_root.is_dir():
        return None
    
    # 1. 精确匹配
    exact = affairs_root / affair_name
    if exact.is_dir() and (exact / "affair.py").is_file():
        return exact
    
    # 2. 大小写不敏感匹配
    affair_lower = affair_name.lower()
    for child in sorted(affairs_root.iterdir()):
        if child.is_dir() and child.name.lower() == affair_lower:
            if (child / "affair.py").is_file():
                return child
    
    # 3. 包含匹配
    for child in sorted(affairs_root.iterdir()):
        if child.is_dir() and affair_lower in child.name.lower():
            if (child / "affair.py").is_file():
                return child
    
    return None


def _import_affair_module(affair_dir: Path) -> Any:
    """动态导入 affair 模块。
    
    由于 affair 目录名可能包含中文，不能直接 import。
    使用 importlib 按文件路径导入。
    """
    affair_py = affair_dir / "affair.py"
    if not affair_py.is_file():
        raise FileNotFoundError(f"事务入口文件不存在: {affair_py}")
    
    # 构造唯一模块名
    module_name = f"_aok_affair_runner_{affair_dir.name.encode('utf-8').hex()}"
    
    spec = importlib.util.spec_from_file_location(module_name, str(affair_py))
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载事务模块: {affair_py}")
    
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_affair(
    affair_name: str,
    params_path: Path,
    repo_root: Path | None = None,
    dry_run: bool = False,
) -> AffairResult:
    """执行指定名称的 AOK 事务。
    
    Args:
        affair_name: 事务目录名。
        params_path: 参数 JSON 文件路径。
        repo_root: autodo-kit 仓库根目录。默认自动查找。
        dry_run: 仅验证不执行。
    
    Returns:
        AffairResult: 结构化执行结果。
    """
    # 自动查找 repo_root
    if repo_root is None:
        # 尝试从当前文件路径推断
        current = Path(__file__).resolve().parent
        for ancestor in [current, *current.parents]:
            if (ancestor / "pyproject.toml").is_file() and (ancestor / "autodokit").is_dir():
                repo_root = ancestor
                break
    if repo_root is None:
        return AffairResult(
            affair_name=affair_name,
            status="FAIL",
            error="无法自动定位 autodo-kit 仓库根目录，请通过 --repo-root 指定",
        )
    
    # 查找事务目录
    affair_dir = find_affair_dir(affair_name, repo_root)
    if affair_dir is None:
        return AffairResult(
            affair_name=affair_name,
            status="FAIL",
            error=f"未找到事务目录: {affair_name}（已搜索 {repo_root / 'autodokit' / 'affairs'}）",
        )
    
    # 验证参数文件
    if not params_path.is_file():
        return AffairResult(
            affair_name=affair_name,
            status="FAIL",
            error=f"参数文件不存在: {params_path}",
        )
    
    if dry_run:
        return AffairResult(
            affair_name=affair_name,
            status="DRY_RUN",
            code=0,
            metadata={
                "affair_dir": str(affair_dir),
                "params_path": str(params_path),
                "repo_root": str(repo_root),
                "message": "dry-run 模式，未实际执行事务",
            },
        )
    
    # 导入并执行
    try:
        module = _import_affair_module(affair_dir)
    except Exception as exc:
        return AffairResult(
            affair_name=affair_name,
            status="FAIL",
            error=f"导入事务模块失败: {exc}",
        )
    
    if not hasattr(module, "execute"):
        return AffairResult(
            affair_name=affair_name,
            status="FAIL",
            error=f"事务模块缺少 execute 函数: {affair_dir / 'affair.py'}",
        )
    
    try:
        output_files = module.execute(params_path.resolve())
    except Exception as exc:
        return AffairResult(
            affair_name=affair_name,
            status="FAIL",
            error=f"事务执行异常: {type(exc).__name__}: {exc}",
        )
    
    # 规范化输出
    output_paths: list[str] = []
    if isinstance(output_files, list):
        output_paths = [str(p) for p in output_files]
    elif isinstance(output_files, (str, Path)):
        output_paths = [str(output_files)]
    
    return AffairResult(
        affair_name=affair_name,
        status="PASS",
        code=0,
        output_files=output_paths,
        metadata={
            "affair_dir": str(affair_dir),
            "params_path": str(params_path),
            "repo_root": str(repo_root),
        },
    )


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="AOK 统一事务 Runner — 按事务名称执行 affair.execute()",
    )
    parser.add_argument(
        "--affair",
        required=True,
        help="事务目录名，如 '生成关键词集合'、'CNKI基础检索'",
    )
    parser.add_argument(
        "--params",
        required=True,
        help="参数 JSON 文件路径",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="autodo-kit 仓库根目录（默认自动查找）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅验证参数与路径，不实际执行事务",
    )
    args = parser.parse_args()
    
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    params_path = Path(args.params).expanduser().resolve()
    
    result = run_affair(
        affair_name=args.affair,
        params_path=params_path,
        repo_root=repo_root,
        dry_run=args.dry_run,
    )
    
    # 输出结构化 JSON
    output = asdict(result)
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    
    return result.code


if __name__ == "__main__":
    raise SystemExit(main())
