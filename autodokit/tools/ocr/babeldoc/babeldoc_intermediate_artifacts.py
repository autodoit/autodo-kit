"""BabelDOC 中间产物导出与解析（纯标准库）。

本模块用于：
1) 把 BabelDOC 的 working_dir/output_dir 中的中间产物复制到指定 artifacts 目录；
2) 尝试从中间产物中解析出版面元素的空间信息（页码、bbox、元素类型等）。

重要说明：
- BabelDOC 的产物结构随版本变化较大。本模块采取“探测 + 多策略解析 + 降级”的方式：
  - 优先解析 JSON/XML 等更可能包含 bbox 的文件；
  - 若未发现可解析的空间信息，则只输出文件清单与 parse_error，保证可追溯。
- 本模块严格只使用 Python 标准库，避免引入额外依赖。

"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class LayoutParseResult:
    """BabelDOC 中间产物版面解析结果。

    Attributes:
        layout: 解析出的版面信息（可能为空）。
        intermediate_files: 被复制/索引的中间产物文件清单。
        parse_error: 解析失败原因（若有）。
    """

    layout: Dict[str, Any]  # 版面信息
    intermediate_files: List[Dict[str, Any]]  # 中间产物清单
    parse_error: Optional[str]  # 解析错误


def _sha256_of_file(path: Path, *, max_bytes: int = 8 * 1024 * 1024) -> str:
    """计算文件 sha256（最多读取 max_bytes，用于快速指纹）。"""

    h = hashlib.sha256()
    read_bytes = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            read_bytes += len(chunk)
            if read_bytes >= max_bytes:
                break
    return h.hexdigest()


def _iter_candidate_files(
    *,
    working_dir: Path,
    output_dir: Path,
    allowed_suffixes: Tuple[str, ...] = (".json", ".xml", ".html", ".htm", ".txt"),
) -> Iterable[Path]:
    """遍历可能包含结构信息的候选文件。"""

    for root in [output_dir, working_dir]:
        if not root.exists() or not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() in allowed_suffixes:
                yield p


def export_babeldoc_intermediate_artifacts(
    *,
    working_dir: Path,
    output_dir: Path,
    artifacts_dir: Path,
    copy_mode: str = "copy",
    max_total_mb: int = 512,
) -> List[Dict[str, Any]]:
    """导出 BabelDOC 中间产物到 artifacts 目录。

    Args:
        working_dir: BabelDOC working_dir。
        output_dir: BabelDOC output_dir。
        artifacts_dir: 目标 artifacts 目录（会创建）。
        copy_mode: "copy"（复制文件）或 "index"（不复制，只输出清单）。
        max_total_mb: 复制文件的大小上限（MB）。超过后停止复制，但仍记录清单。

    Returns:
        list[dict]: 导出的文件清单。
    """

    artifacts_dir.mkdir(parents=True, exist_ok=True)

    total_limit = int(max_total_mb) * 1024 * 1024
    copied_bytes = 0

    exported: List[Dict[str, Any]] = []

    # 关键逻辑说明：
    # - BabelDOC 可能在 working_dir/output_dir 都产生诊断与中间文件。
    # - 我们按文件后缀过滤，避免复制大体积 PDF/图片造成磁盘膨胀。
    for p in _iter_candidate_files(working_dir=working_dir, output_dir=output_dir):
        try:
            stat = p.stat()
        except Exception:
            continue

        rec: Dict[str, Any] = {
            "abs_path": str(p),
            "name": p.name,
            "suffix": p.suffix.lower(),
            "size_bytes": int(stat.st_size),
            "sha256_head": None,
            "exported_path": None,
            "source_root": "working_dir" if str(p).startswith(str(working_dir)) else "output_dir",
        }

        if rec["size_bytes"] > 0:
            try:
                rec["sha256_head"] = _sha256_of_file(p)
            except Exception:
                rec["sha256_head"] = None

        if copy_mode == "copy":
            if copied_bytes + rec["size_bytes"] <= total_limit:
                dest = artifacts_dir / rec["source_root"] / p.relative_to(working_dir if rec["source_root"] == "working_dir" else output_dir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(p, dest)
                    rec["exported_path"] = str(dest)
                    copied_bytes += rec["size_bytes"]
                except Exception:
                    rec["exported_path"] = None
            else:
                # 超过上限就不再复制，但仍记录
                rec["exported_path"] = None

        exported.append(rec)

    return exported


def _coerce_bbox(value: Any) -> Optional[Dict[str, float]]:
    """把 bbox 值转换为统一格式。"""

    if value is None:
        return None

    # 常见格式： [x0, y0, x1, y1]
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            x0, y0, x1, y1 = [float(v) for v in value]
            return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
        except Exception:
            return None

    # 常见格式： {x0,y0,x1,y1} 或 {left,top,right,bottom}
    if isinstance(value, dict):
        keys = set(value.keys())
        if {"x0", "y0", "x1", "y1"}.issubset(keys):
            try:
                return {
                    "x0": float(value["x0"]),
                    "y0": float(value["y0"]),
                    "x1": float(value["x1"]),
                    "y1": float(value["y1"]),
                }
            except Exception:
                return None

        if {"left", "top", "right", "bottom"}.issubset(keys):
            try:
                return {
                    "x0": float(value["left"]),
                    "y0": float(value["top"]),
                    "x1": float(value["right"]),
                    "y1": float(value["bottom"]),
                }
            except Exception:
                return None

    return None


def parse_layout_elements_from_babeldoc_intermediate(
    *,
    working_dir: Path,
    output_dir: Path,
    max_files: int = 200,
) -> LayoutParseResult:
    """解析 BabelDOC 中间产物，尽量抽取版面元素与空间信息。

    Args:
        working_dir: BabelDOC working_dir。
        output_dir: BabelDOC output_dir。
        max_files: 最多解析的文件数（避免超大目录拖慢）。

    Returns:
        LayoutParseResult: 解析结果。
    """

    elements: List[Dict[str, Any]] = []
    scanned_files: List[Dict[str, Any]] = []

    parse_error: Optional[str] = None

    # 关键逻辑说明：
    # - 我们优先解析 JSON，因为最可能包含 bbox/page/type。
    # - 若 BabelDOC 未导出相关 JSON，则结果为空，但仍返回 scanned_files 便于排查。
    try:
        json_files = []
        for p in _iter_candidate_files(working_dir=working_dir, output_dir=output_dir, allowed_suffixes=(".json",)):
            json_files.append(p)
            if len(json_files) >= max_files:
                break

        for p in json_files:
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue

            scanned_files.append({"abs_path": str(p), "suffix": ".json"})

            # 宽松递归：寻找同时包含 page + bbox 的对象
            def walk(x: Any) -> None:
                if isinstance(x, dict):
                    page = x.get("page")
                    if page is None:
                        page = x.get("page_index")
                    if page is None:
                        page = x.get("pageIndex")
                    if page is None:
                        page = x.get("page_num")

                    bbox = _coerce_bbox(x.get("bbox") or x.get("box") or x.get("rect"))
                    if page is not None and bbox is not None:
                        etype = (
                            x.get("type")
                            or x.get("element_type")
                            or x.get("category")
                            or x.get("label")
                            or "unknown"
                        )
                        text = x.get("text") or x.get("content")
                        elements.append(
                            {
                                "page_index": int(page),
                                "type": str(etype),
                                "bbox": bbox,
                                "text": str(text)[:2000] if isinstance(text, str) else None,
                                "source_artifact": str(p),
                            }
                        )

                    for v in x.values():
                        walk(v)
                elif isinstance(x, list):
                    for it in x:
                        walk(it)

            walk(obj)

    except Exception as exc:
        parse_error = str(exc)

    layout: Dict[str, Any] = {
        "coord_system": "unknown",
        "pages": [],
        "elements": elements,
        "sources": scanned_files,
    }

    return LayoutParseResult(layout=layout, intermediate_files=scanned_files, parse_error=parse_error)

