"""合并去重文献元数据脚本。

该脚本以“文献元数据主表 CSV”为输入（通常由 `导入和预处理文献元数据` 事务生成），
将其读入为 pandas DataFrame，并按指定的去重策略生成“去重后的 CSV”。

当前版本仅做去重输出，不做跨行字段级合并（字段合并在后续版本再实现）。

主要功能：
- 提供 programmatic API `dedup_metadata_csv` 以便被调度器或其他脚本调用。
- 提供 CLI 接口用于命令行运行。

去重策略（默认）：
- 优先按 DOI 去重（归一化 DOI）。
- 对缺失 DOI 的记录，再用 title + authors + year 的归一化键去重。

注意：
- 本脚本不修改 `合并去重bibtex.py`，其事务仍可按原方式处理 .bib 文件。
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from autodokit.tools import load_json_or_py
from autodokit.tools.metadata_dedup import dedup_metadata_df


@dataclass
class DedupConfig:
    """去重配置。

    Args:
        input_table_csv: 输入文献元数据主表 CSV（应为绝对路径，建议由调度层统一解析）。
        output_table_csv: 输出去重后的 CSV（应为绝对路径）。
        dry_run: 若为 True，仅输出统计信息，不写文件。
        backup: 若输出文件已存在，是否备份旧文件。
    """

    input_table_csv: str
    output_table_csv: str
    dry_run: bool = False
    backup: bool = True


def dedup_metadata_csv(
    *,
    input_table_csv: str | Path,
    output_table_csv: str | Path,
    dry_run: bool = False,
    backup: bool = True,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """读取文献元数据 CSV，去重后写出 CSV。

    Args:
        input_table_csv: 输入 CSV 路径（通常是“文献数据表.csv”）。
        output_table_csv: 输出 CSV 路径。
        dry_run: 若为 True，仅返回统计信息不写出。
        backup: 若输出文件存在，是否备份。
        logger: 可选 logger。

    Returns:
        统计信息字典。

    Raises:
        ValueError: 路径为空或不是绝对路径时抛出。
        FileNotFoundError: 输入文件不存在时抛出。
    """

    if logger is None:
        logger = logging.getLogger(__name__)

    in_path = Path(input_table_csv)
    out_path = Path(output_table_csv)

    # 兼容两种模式：
    # - 调度器模式：上游已统一把路径解析为绝对路径；
    # - 脚本直跑：用户可能给相对路径，此时相对当前工作目录解析。
    if not in_path.is_absolute():
        in_path = in_path.resolve()
    if not out_path.is_absolute():
        out_path = out_path.resolve()

    if not in_path.exists():
        raise FileNotFoundError(f"找不到输入文献表：{in_path}")

    df = pd.read_csv(in_path, encoding="utf-8-sig")
    # 兼容导入事务的写法：uid 既可能是 index，也可能是明确列。
    if "uid" in df.columns:
        try:
            df = df.set_index("uid", drop=False)
        except Exception:
            pass

    out_df = dedup_metadata_df(df)

    result = {
        "total_input_count": int(len(df)),
        "deduped_count": int(len(out_df)),
        "removed_count": int(len(df) - len(out_df)),
        "input_table_csv": str(in_path),
        "output_table_csv": str(out_path),
    }

    if dry_run:
        logger.info("dry_run=True，不写出文件：%s", json.dumps(result, ensure_ascii=False))
        return result

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and backup:
        bak = out_path.with_suffix(out_path.suffix + f".{datetime.now().strftime('%Y%m%d%H%M%S')}.bak")
        shutil.copy(str(out_path), str(bak))
        logger.info("已备份旧输出文件到 %s", bak)

    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info("已写出去重后的文献表：%s", out_path)

    return result


def _build_cli_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="对文献元数据 CSV 做去重并输出新的 CSV")
    p.add_argument("--input-table-csv", required=True, help="输入文献表 CSV（绝对路径）")
    p.add_argument("--output-table-csv", required=True, help="输出去重文献表 CSV（绝对路径）")
    p.add_argument("--dry-run", action="store_true", help="仅统计不写文件")
    p.add_argument("--no-backup", dest="backup", action="store_false", help="如果输出文件存在，不备份")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def execute(config_path: Path, workspace_root: Path | None = None, **_: Any) -> List[Path]:
    """调度器事务入口：按配置执行文献元数据去重。

    Args:
        config_path: 调度器写入的临时 JSON 配置文件路径。
        workspace_root: 工作区根目录（调度器透传，当前事务不强依赖）。
        **_: 预留参数位，避免调度器透传额外参数导致报错。

    Returns:
        写出的文件路径列表（dry_run=True 时返回空列表）。

    Raises:
        ValueError: 配置缺失或路径不合法。
        FileNotFoundError: 输入文件不存在。
    """

    _ = workspace_root

    cfg = load_json_or_py(config_path)

    input_table_csv = str(cfg.get("input_table_csv") or "").strip()
    output_table_csv = str(cfg.get("output_table_csv") or "").strip()
    if not input_table_csv:
        raise ValueError("配置缺少 input_table_csv")
    if not output_table_csv:
        raise ValueError("配置缺少 output_table_csv")

    dry_run = bool(cfg.get("dry_run", False))
    backup = bool(cfg.get("backup", True))

    dedup_metadata_csv(
        input_table_csv=input_table_csv,
        output_table_csv=output_table_csv,
        dry_run=dry_run,
        backup=backup,
    )

    if dry_run:
        return []
    return [Path(output_table_csv)]


def main(argv: Optional[list] = None) -> int:
    """脚本入口。返回 0 表示成功，非 0 表示失败。"""

    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))
    logger = logging.getLogger("合并去重文献元数据")

    try:
        res = dedup_metadata_csv(
            input_table_csv=args.input_table_csv,
            output_table_csv=args.output_table_csv,
            dry_run=bool(args.dry_run),
            backup=bool(args.backup),
            logger=logger,
        )
        logger.info(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        logger.exception("处理失败: %s", e)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


