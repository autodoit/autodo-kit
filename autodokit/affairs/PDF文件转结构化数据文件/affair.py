"""事务：PDF 文件转结构化数据文件。

本事务用于批量将一个文件夹（不含子文件夹）内的所有 `.pdf` 文件转换为“适合大模型读取与解析”的结构化文档数据。

设计目标：
- 面向复杂论文 PDF：尽量保留表格/公式/图注等信息的可追溯结构。
- 输出以 JSON 为主，必要时允许包含多模态占位（例如图片引用路径、页码、bbox）。

约定（务必遵守）：
- 事务只消费绝对路径；任何相对路径都视为调度层/配置层缺陷，本事务将直接报错。
- 路径绝对化由调度器在写入 `.tmp/*.json` 前完成。

"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from autodokit.tools import load_json_or_py
from autodokit.tools.pdf_to_structured_data_converter_local_pipeline_v2 import (
    convert_pdf_to_structured_data_file as convert_pdf_to_structured_data_file_local_v2,
)
from autodokit.tools.pdf_to_structure_data_converter_use_babeldoc import (
    convert_pdf_to_structured_data_file as convert_pdf_to_structured_data_file_babeldoc,
)


@dataclass
class PdfDirToStructuredDataConfig:
    """PDF 批量转结构化数据的事务配置。

    Attributes:
        input_pdf_dir: 输入 PDF 文件夹（仅扫描本层，不递归）。
        output_structured_dir: 输出结构化数据文件夹。
        converter: 转换器类型。当前仅支持 "babeldoc"。
        babeldoc: BabelDOC 的配置字典（透传给工具层）。
        extractors: 抽取器开关（本地流水线）
        overwrite: 是否覆盖已存在的结构化文件。
        output_log: 可选，过程日志输出路径（若提供则边打印边写文件）。
    """

    input_pdf_dir: str  # 输入 PDF 文件夹（绝对路径）
    output_structured_dir: str  # 输出结构化数据文件夹（绝对路径）
    converter: str = "local_pipeline_v2"  # 转换器类型
    babeldoc: Dict[str, Any] | None = None  # BabelDOC 配置（历史兼容）
    extractors: Dict[str, Any] | None = None  # 抽取器开关（本地流水线）
    overwrite: bool = False  # 是否覆盖已存在文件
    output_log: str | None = None  # 过程日志输出文件（绝对路径）


def _require_absolute_dir(path_str: str, *, field_name: str) -> Path:
    """校验目录字段为绝对路径并存在。

    Args:
        path_str: 配置中的路径字符串。
        field_name: 字段名，用于错误信息。

    Returns:
        Path: 绝对路径对象。

    Raises:
        ValueError: 路径为空、不是绝对路径或目录不存在。
    """

    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError(f"{field_name} 为空")

    p = Path(path_str)
    if not p.is_absolute():
        raise ValueError(
            f"{field_name} 必须是绝对路径（应由调度层预处理为绝对路径）。当前值={path_str!r}"
        )
    if not p.exists() or not p.is_dir():
        raise ValueError(f"{field_name} 必须是存在的目录：{p}")
    return p


def execute(config_path: Path) -> List[Path]:
    """事务入口：批量把 PDF 转为结构化数据文件。

    Args:
        config_path: 调度器写入的合并后临时配置文件路径（.json 或 .py）。

    Returns:
        List[Path]: 写出的结构化数据文件路径列表。

    Raises:
        ValueError: 配置缺失/不合法，或路径不是绝对路径。
        RuntimeError: 转换过程发生不可恢复错误。
    """

    raw_cfg = load_json_or_py(config_path)
    affair_cfg: Dict[str, Any] = dict(raw_cfg)

    cfg = PdfDirToStructuredDataConfig(
        input_pdf_dir=str(affair_cfg.get("input_pdf_dir") or ""),
        output_structured_dir=str(affair_cfg.get("output_structured_dir") or ""),
        converter=str(affair_cfg.get("converter") or "local_pipeline_v2"),
        babeldoc=affair_cfg.get("babeldoc") if isinstance(affair_cfg.get("babeldoc"), dict) else None,
        extractors=affair_cfg.get("extractors") if isinstance(affair_cfg.get("extractors"), dict) else None,
        overwrite=bool(affair_cfg.get("overwrite", False)),
        output_log=str(affair_cfg.get("output_log") or "").strip() or None,
    )

    input_dir = _require_absolute_dir(cfg.input_pdf_dir, field_name="input_pdf_dir")

    if not isinstance(cfg.output_structured_dir, str) or not cfg.output_structured_dir.strip():
        raise ValueError("output_structured_dir 为空")
    output_dir = Path(cfg.output_structured_dir)
    if not output_dir.is_absolute():
        raise ValueError(
            "output_structured_dir 必须是绝对路径（应由调度层预处理为绝对路径）。"
            f"当前值={cfg.output_structured_dir!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    output_log_path: Path | None = None
    if cfg.output_log:
        output_log_path = Path(cfg.output_log)
        if not output_log_path.is_absolute():
            raise ValueError(
                "output_log 必须是绝对路径（应由调度层预处理为绝对路径）。"
                f"当前值={cfg.output_log!r}"
            )
        output_log_path.parent.mkdir(parents=True, exist_ok=True)

    def _log(line: str) -> None:
        """同时输出到终端与可选日志文件。"""

        print(line)
        if output_log_path is not None:
            # 关键逻辑说明：追加写入保证长任务实时落盘，异常中断也能保留已处理进度。
            with output_log_path.open("a", encoding="utf-8") as f:
                f.write(line.rstrip("\n") + "\n")

    converter = str(cfg.converter or "local_pipeline_v2").strip().lower()
    if converter not in {"local_pipeline_v2", "babeldoc"}:
        raise ValueError(
            f"不支持的 converter：{cfg.converter!r}（当前支持 'local_pipeline_v2' 与历史兼容 'babeldoc'）"
        )

    pdf_files = sorted([p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"])

    written: List[Path] = []
    failures: List[Dict[str, Any]] = []

    total = len(pdf_files)
    if total == 0:
        _log(f"未在目录中找到 PDF：{input_dir}")

    if output_log_path is not None:
        _log("[CONFIG]")
        _log(f"input_pdf_dir={input_dir}")
        _log(f"output_structured_dir={output_dir}")
        _log(f"converter={converter}")
        _log(f"overwrite={cfg.overwrite}")

    for i, pdf_path in enumerate(pdf_files, start=1):
        _log(f"({i}/{total}) 正在处理：{pdf_path.name}")

        out_json = (output_dir / (pdf_path.stem + ".structured.json")).resolve()

        if out_json.exists() and not cfg.overwrite:
            _log(f"  - 已存在，跳过：{out_json.name}")
            continue

        try:
            if converter == "local_pipeline_v2":
                written.append(
                    convert_pdf_to_structured_data_file_local_v2(
                        pdf_path.resolve(),
                        out_json,
                        extractors=cfg.extractors,
                    )
                )
            else:
                written.append(
                    convert_pdf_to_structured_data_file_babeldoc(
                        pdf_path.resolve(),
                        out_json,
                        babeldoc=cfg.babeldoc,
                    )
                )

            _log(f"  - 已生成：{out_json.name}")
        except Exception as exc:
            _log(f"  - 转换失败：{pdf_path.name}：{exc}")
            failures.append(
                {
                    "pdf_path": str(pdf_path),
                    "output_structured_path": str(out_json),
                    "error": str(exc),
                }
            )

    manifest = {
        "input_pdf_dir": str(input_dir),
        "output_structured_dir": str(output_dir),
        "converter": converter,
        "overwrite": bool(cfg.overwrite),
        "pdf_count": int(len(pdf_files)),
        "written_structured_count": int(len(written)),
        "failed_count": int(len(failures)),
        "failures": failures,
    }

    manifest_path = (output_dir / "pdf_to_structured_manifest.json").resolve()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    outputs: List[Path] = [*written, manifest_path]
    if output_log_path is not None:
        outputs.append(output_log_path)

    return outputs


def main() -> None:
    """命令行入口（用于调试）。"""

    import sys

    if len(sys.argv) < 2:
        raise SystemExit("用法：python PDF文件转结构化数据文件.py <config_path>")

    for p in execute(Path(sys.argv[1])):
        print(p)


if __name__ == "__main__":
    main()


