"""Unlimited-OCR (mlx-vlm) 核心引擎：模型加载、单页推理与检测解析。

Unlimited-OCR 是百度开源的端到端文档 OCR 模型（model_type: unlimited-ocr），
mlx-vlm >= 0.6 内置对应架构，可在 Apple Silicon 上原生推理（普通页面
3-6 秒/页，``temp=0.0`` 贪心采样零退化）。

关键事实（实测验证）：
- 检测输出格式为 ``<|det|>type [x1,y1,x2,y2]<|/det|>content``，type 含
  title/text/equation/table/footer/page_number/aside_text 等；表格直出 HTML。
- 检测坐标为**归一化×1000 坐标系**（与渲染图像素无关）：与源文档坐标对齐
  时需各自归一化（源坐标除以页高，检测坐标除以 1000）；x 轴常有偏移，
  定位匹配优先只用归一化 y。
- ``load()`` 不能传 ``trust_repo``（会报 TypeError）；prompt 必须含
  ``<image>`` 占位符。

本模块不在导入期依赖 mlx_vlm / fitz，仅在函数内延迟导入，保证无 MLX
环境的机器也能导入本包做路径解析。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "resolve_unlimited_ocr_model_path",
    "load_unlimited_ocr_model",
    "ocr_image",
    "parse_detections",
    "normalize_source_y",
    "normalize_det_y",
    "match_by_normalized_y",
]

#: 默认模型目录相对名（位于宿主工程 ``pypackage/model_weight/`` 下）
DEFAULT_MODEL_DIRNAME = "Unlimited-OCR-4bit"

#: 标准提示词（官方布局保留模式）
DEFAULT_PROMPT = "<image> OCR with layout preservation."

_DET_RE = re.compile(r"<\|det\|>(\w+)\s*\[([\d,\s]+)\]<\|/det\|>", re.S)


def resolve_unlimited_ocr_model_path(
    workspace_root: str | Path | None = None,
    model_path: str | Path | None = None,
) -> Path:
    """解析 Unlimited-OCR 模型权重目录。

    解析顺序：
    1. 显式传入的 ``model_path``（存在即返回）；
    2. ``{workspace_root}/pypackage/model_weight/Unlimited-OCR-4bit``；
    3. ``pypackage/model_weight/Unlimited-OCR-4bit``（当前工作目录相对）。

    Args:
        workspace_root: 宿主工程根目录（含 ``pypackage/``）。
        model_path: 可选的显式模型目录。

    Returns:
        模型权重目录的绝对路径。

    Raises:
        FileNotFoundError: 所有候选位置均未找到模型目录。

    Examples:
        >>> p = resolve_unlimited_ocr_model_path("/path/to/AcademicResearch-auto-workflow")
        >>> p.name
        'Unlimited-OCR-4bit'
    """
    candidates: List[Path] = []
    if model_path:
        candidates.append(Path(model_path).expanduser().resolve())
    if workspace_root:
        candidates.append(
            (Path(workspace_root).expanduser().resolve()
             / "pypackage" / "model_weight" / DEFAULT_MODEL_DIRNAME)
        )
    candidates.append(Path.cwd() / "pypackage" / "model_weight" / DEFAULT_MODEL_DIRNAME)

    for cand in candidates:
        if cand.is_dir() and (cand / "config.json").exists():
            return cand
    searched = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        f"未找到 Unlimited-OCR 模型目录（候选: {searched}）。"
        "请先下载：huggingface-cli download mlx-community/Unlimited-OCR-4bit "
        "--local-dir pypackage/model_weight/Unlimited-OCR-4bit"
    )


def load_unlimited_ocr_model(
    workspace_root: str | Path | None = None,
    model_path: str | Path | None = None,
) -> Tuple[Any, Any]:
    """加载 Unlimited-OCR 模型与 processor（延迟导入 mlx_vlm）。

    Args:
        workspace_root: 宿主工程根目录。
        model_path: 可选的显式模型目录。

    Returns:
        ``(model, processor)`` 元组。

    Raises:
        ImportError: 未安装 mlx-vlm。
        FileNotFoundError: 模型目录不存在。
    """
    try:
        from mlx_vlm import load  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "需要安装 mlx-vlm（pip install mlx-vlm）才能加载 Unlimited-OCR"
        ) from exc

    path = resolve_unlimited_ocr_model_path(workspace_root, model_path)
    logger.info("loading Unlimited-OCR from %s", path)
    # 注意：不能传 trust_repo（mlx-vlm 会透传给 processor 导致 TypeError）
    return load(str(path))


def ocr_image(
    model: Any,
    processor: Any,
    image_path: str | Path,
    *,
    generate: Any = None,
    prompt: str = DEFAULT_PROMPT,
    max_tokens: int = 8192,
    temp: float = 0.0,
) -> str:
    """对单张图片执行 Unlimited-OCR 推理，返回原始文本输出。

    Args:
        model: ``load_unlimited_ocr_model`` 返回的模型。
        processor: ``load_unlimited_ocr_model`` 返回的 processor。
        image_path: 图片路径（建议渲染宽度 1024 左右）。
        generate: 可选，注入 ``mlx_vlm.generate``（便于测试）。
        prompt: 提示词，必须含 ``<image>`` 占位符。
        max_tokens: 输出 token 上限。
        temp: 采样温度；0.0 贪心采样，普通内容零退化。

    Returns:
        模型原始输出文本（含 ``<|det|>`` 检测标记）。

    Raises:
        ValueError: prompt 缺少 ``<image>`` 占位符。
    """
    if "<image>" not in prompt:
        raise ValueError("prompt 必须包含 <image> 占位符")
    if generate is None:
        from mlx_vlm import generate as _generate  # type: ignore[import-untyped]
        generate = _generate

    result = generate(
        model, processor, prompt,
        image=str(image_path), max_tokens=max_tokens, temp=temp,
    )
    return result.text if hasattr(result, "text") else str(result)


def parse_detections(raw: str) -> List[Dict[str, Any]]:
    """解析 Unlimited-OCR 输出为检测块列表。

    Args:
        raw: 模型原始输出。

    Returns:
        ``[{type, box, content}, ...]``；``box`` 为归一化×1000 坐标系
        的 ``[x1, y1, x2, y2]``，``content`` 为该检测块的内容文本。

    Examples:
        >>> dets = parse_detections("<|det|>equation [100, 200, 300, 250]<|/det|>E=mc^2")
        >>> dets[0]["type"], dets[0]["content"]
        ('equation', 'E=mc^2')
    """
    items: List[Dict[str, Any]] = []
    matches = list(_DET_RE.finditer(raw))
    for i, m in enumerate(matches):
        box = [float(v) for v in m.group(2).split(",")]
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        items.append({
            "type": m.group(1),
            "box": box,
            "content": raw[m.end():end].strip(),
        })
    return items


def normalize_source_y(bbox: List[float] | Tuple[float, ...], page_height: float) -> float:
    """把源文档（PDF 点坐标）的 bbox 归一化为中心 y（0-1）。

    Args:
        bbox: ``[x0, y0, x1, y1]`` PDF 点坐标。
        page_height: PDF 页面高度（点）。

    Returns:
        归一化 y 中心。
    """
    return (bbox[1] + bbox[3]) / 2.0 / page_height


def normalize_det_y(box: List[float]) -> float:
    """把 Unlimited-OCR 检测框归一化为中心 y（0-1）。

    检测坐标为归一化×1000 坐标系，除以 1000 即与源文档归一化坐标可比。

    Args:
        box: 检测框 ``[x1, y1, x2, y2]``（0-1000）。

    Returns:
        归一化 y 中心。
    """
    return (box[1] + box[3]) / 2.0 / 1000.0


def match_by_normalized_y(
    source_bboxes: List[List[float]],
    det_boxes: List[List[float]],
    page_height: float,
    threshold: float = 0.05,
) -> Dict[int, int]:
    """按归一化 y 中心最近邻配对源框与检测框。

    x 轴检测坐标常有偏移，匹配只依赖归一化 y；每个检测框至多被使用一次。

    Args:
        source_bboxes: 源文档 bbox 列表（PDF 点坐标）。
        det_boxes: 检测框列表（归一化×1000）。
        page_height: PDF 页面高度（点）。
        threshold: 归一化 y 距离阈值（默认 0.05，约页高 5%）。

    Returns:
        ``{source_idx: det_idx}`` 映射。

    Examples:
        >>> match_by_normalized_y([[0, 100, 50, 120]], [[500, 110, 600, 130]], 200.0)
        {0: 0}
    """
    if not source_bboxes or not det_boxes:
        return {}
    src_ys = sorted(
        (normalize_source_y(b, page_height), i) for i, b in enumerate(source_bboxes)
    )
    det_ys = [(normalize_det_y(b), j) for j, b in enumerate(det_boxes)]
    mapping: Dict[int, int] = {}
    used: set = set()
    for sy, src_idx in src_ys:
        best_j: Optional[int] = None
        best_dist = threshold
        for dy, det_idx in det_ys:
            if det_idx in used:
                continue
            dist = abs(sy - dy)
            if dist < best_dist:
                best_j, best_dist = det_idx, dist
        if best_j is not None:
            mapping[src_idx] = best_j
            used.add(best_j)
    return mapping
