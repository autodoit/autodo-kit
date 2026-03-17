"""
CAJ 文件转 PDF 事务（占位实现 — 需要人工操作）

本文件提供一个事务占位实现以便在工作流中声明 "CAJ文件转PDF" 的步骤。
该事务不实现自动化的 CAJ -> PDF 转换逻辑；相反，工作流与文档会说明如何使用第三方工具或在线服务（例如 https://caj2pdf.cn/batch ）进行批量转换，用户在外部完成转换并手动把导出的 PDF 放入指定的 `output_dir`。

本占位实现的目的：
- 在调度器/工作流层面占位该事务，使工作流完整；
- 在运行时给出清晰的日志/返回值，提醒使用者需手动完成转换并把产物放到指定位置；
- 简单地返回 `output_dir` 中已经存在的 PDF 列表（如果有的话）。

注意：本文件遵循仓库的事务约定——不做任何路径绝对化或路径修复；调度器应该在传入的合并后配置中保证路径已为绝对路径。

Args:
    config_path: 合并后的事务配置文件路径（由调度器写入的临时 JSON 文件），类型为 `Path` 或可被 `Path()` 接受的字符串。

Returns:
    List[Path]: 如果 `output_dir` 中已有 PDF 文件，则返回这些 PDF 的路径列表；否则返回空列表（表示需要人工将转换产物放入该目录）。

Raises:
    ValueError: 当 `config_path` 不存在或无法解析为 JSON 时抛出。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def execute(config_path: "Path | str") -> List[Path]:
    """
    占位事务入口：提示并等待用户在外部完成 CAJ -> PDF 的转换，并把导出的 PDF 放到配置的 `output_dir`。

    Args:
        config_path: 调度器写入的合并后临时配置文件路径（JSON）。

    Returns:
        List[Path]: `output_dir` 中已存在的 PDF 文件路径列表（可能为空）。

    Raises:
        ValueError: 如果 `config_path` 不存在或 JSON 无法解析。
    """
    p = Path(config_path)
    if not p.exists():
        raise ValueError(f"配置文件不存在: {config_path}")

    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"无法读取或解析配置 JSON: {e}")

    output_dir = cfg.get("output_dir")
    if output_dir is None:
        logger.info("配置中未指定 output_dir；事务作为占位不做任何文件写入。")
        return []

    outp = Path(output_dir)
    # 不对路径做任何强行转换；按照仓库约定，路径应当由调度层预先绝对化
    logger.info(
        "CAJ 转 PDF 事务为占位实现；请参照工作流文档在外部完成 CAJ -> PDF 的批量转换，并把导出的 PDF 放到：%s",
        str(outp),
    )

    if outp.exists() and outp.is_dir():
        pdfs = sorted(outp.glob("*.pdf"))
        logger.info("在 output_dir 中发现 %d 个 PDF 文件。", len(pdfs))
        return pdfs

    logger.info("output_dir 不存在或为空：%s", str(outp))
    return []


if __name__ == "__main__":
    # 允许以脚本方式快速演示（仅输出提示）
    import sys

    if len(sys.argv) > 1:
        cfg_path = sys.argv[1]
    else:
        cfg_path = "config.json"
    try:
        results = execute(cfg_path)
        print(f"占位事务完成，发现 PDF: {[str(p) for p in results]}")
    except Exception as e:
        print(f"占位事务运行出错：{e}")
        raise

