"""事务：PDF 文件转 Markdown 文件。

本事务用于批量将一个文件夹（不含子文件夹）内的所有 `.pdf` 文件转换为同名 `.md` 文件。

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
from autodokit.tools.pdf_to_markdown_converter_use_markitdown import convert_pdf_to_markdown_file as _convert_with_markitdown


@dataclass
class PdfDirToMdConfig:
    """PDF 批量转 Markdown 的事务配置。

    Attributes:
        input_pdf_dir: 输入 PDF 文件夹（仅扫描本层，不递归）。
        output_md_dir: 输出 Markdown 文件夹。
        converter: 转换器类型。当前支持 "markitdown"；"babeldoc" 仅保留占位。
        babeldoc_placeholder: BabelDOC 占位参数（暂不使用）。
        overwrite: 是否覆盖已存在的 md 文件。
        output_log: 可选，过程日志输出路径（若提供则边打印边写文件）。
    """

    input_pdf_dir: str  # 输入 PDF 文件夹（绝对路径）
    output_md_dir: str  # 输出 md 文件夹（绝对路径）
    converter: str = "markitdown"  # 转换器类型
    babeldoc_placeholder: Dict[str, Any] | None = None  # BabelDOC 占位参数
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


def _convert_with_babeldoc(
    pdf_path: Path,
    output_md_path: Path,
    *,
    babeldoc: Dict[str, Any] | None = None,
) -> Path:
    """BabelDOC 转 Markdown 占位实现。

    Args:
        pdf_path: 输入 PDF 绝对路径。
        output_md_path: 输出 Markdown 绝对路径。
        babeldoc: BabelDOC 预留配置。

    Returns:
        Path: 输出 Markdown 路径。

    Raises:
        NotImplementedError: 当前仓库尚未提供 BabelDOC 到 Markdown 的实际转换实现。
    """

    raise NotImplementedError(
        "converter='babeldoc' 暂未实现 PDF -> Markdown 转换，请改用 markitdown，"
        f"或后续在工具层补齐实现。pdf={pdf_path} output={output_md_path} babeldoc={babeldoc!r}"
    )


def execute(config_path: Path) -> List[Path]:
    """事务入口：批量把 PDF 转为 Markdown。

    Args:
        config_path: 调度器写入的合并后临时配置文件路径（.json 或 .py）。

    Returns:
        List[Path]: 写出的 Markdown 文件路径列表。

    Raises:
        ValueError: 配置缺失/不合法，或路径不是绝对路径。
        RuntimeError: 转换过程发生不可恢复错误。
    """

    raw_cfg = load_json_or_py(config_path)
    affair_cfg: Dict[str, Any] = dict(raw_cfg)

    cfg = PdfDirToMdConfig(
        input_pdf_dir=str(affair_cfg.get("input_pdf_dir") or ""),
        output_md_dir=str(affair_cfg.get("output_md_dir") or ""),
        converter=str(affair_cfg.get("converter") or "markitdown"),
        babeldoc_placeholder=affair_cfg.get("babeldoc") if isinstance(affair_cfg.get("babeldoc"), dict) else None,
        overwrite=bool(affair_cfg.get("overwrite", False)),
        output_log=str(affair_cfg.get("output_log") or "").strip() or None,
    )

    input_dir = _require_absolute_dir(cfg.input_pdf_dir, field_name="input_pdf_dir")

    if not isinstance(cfg.output_md_dir, str) or not cfg.output_md_dir.strip():
        raise ValueError("output_md_dir 为空")
    output_dir = Path(cfg.output_md_dir)
    if not output_dir.is_absolute():
        raise ValueError(
            "output_md_dir 必须是绝对路径（应由调度层预处理为绝对路径）。"
            f"当前值={cfg.output_md_dir!r}"
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
        """同时输出到终端与可选日志文件。

        Args:
            line: 单行日志。
        """

        print(line)
        if output_log_path is not None:
            # 关键逻辑说明：
            # - 采用追加写入，确保长任务过程中日志实时落盘，异常中断也能保留已处理进度。
            with output_log_path.open("a", encoding="utf-8") as f:
                f.write(line.rstrip("\n") + "\n")

    converter = str(cfg.converter or "markitdown").strip().lower()

    pdf_files = sorted([p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"])

    # 关键逻辑说明：
    # - 按文件名排序可保证批处理输出稳定，便于回溯与复现。
    # - 不递归子目录，避免无意处理大量文件。
    written: List[Path] = []
    failures: List[Dict[str, Any]] = []

    total = len(pdf_files)
    if total == 0:
        _log(f"未在目录中找到 PDF：{input_dir}")

    # 记录一次运行的配置回显，避免用户拿到 log 却不知道对应的输入输出。
    if output_log_path is not None:
        _log("[CONFIG]")
        _log(f"input_pdf_dir={input_dir}")
        _log(f"output_md_dir={output_dir}")
        _log(f"converter={converter}")
        _log(f"overwrite={cfg.overwrite}")

    for i, pdf_path in enumerate(pdf_files, start=1):
        # 实时进度：长任务时用户可以在终端看到当前处理到哪个文件。
        _log(f"({i}/{total}) 正在处理：{pdf_path.name}")

        out_md = (output_dir / (pdf_path.stem + ".md")).resolve()

        if out_md.exists() and not cfg.overwrite:
            _log(f"  - 已存在，跳过：{out_md.name}")
            continue

        try:
            if converter in {"markitdown", "microsoft_markitdown", "ms_markitdown"}:
                written.append(
                    _convert_with_markitdown(
                        pdf_path.resolve(),
                        out_md,
                        converter=converter,
                    )
                )
            elif converter == "babeldoc":
                written.append(
                    _convert_with_babeldoc(
                        pdf_path.resolve(),
                        out_md,
                        babeldoc=cfg.babeldoc_placeholder,
                    )
                )
            else:
                raise ValueError(
                    f"不支持的 converter：{cfg.converter!r}（支持：markitdown / babeldoc）"
                )

            _log(f"  - 已生成：{out_md.name}")
        except NotImplementedError:
            # converter=babeldoc 时会走到这里：作为流程中止信号更清晰
            raise
        except Exception as exc:
            _log(f"  - 转换失败：{pdf_path.name}：{exc}")
            failures.append(
                {
                    "pdf_path": str(pdf_path),
                    "output_md_path": str(out_md),
                    "error": str(exc),
                }
            )

    # 写出失败清单与清单回显，方便用户快速定位。
    manifest = {
        "input_pdf_dir": str(input_dir),
        "output_md_dir": str(output_dir),
        "converter": converter,
        "overwrite": bool(cfg.overwrite),
        "pdf_count": int(len(pdf_files)),
        "written_md_count": int(len(written)),
        "failed_count": int(len(failures)),
        "failures": failures,
    }

    manifest_path = (output_dir / "pdf_to_md_manifest.json").resolve()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    outputs: List[Path] = [*written, manifest_path]
    if output_log_path is not None:
        outputs.append(output_log_path)

    # 保持与仓库内其它事务一致：返回“真实产物路径列表”。
    return outputs


def main() -> None:
    """命令行入口（用于调试）。"""

    import sys

    if len(sys.argv) < 2:
        raise SystemExit("用法：python PDF文件转md文件.py <config_path>")

    for p in execute(Path(sys.argv[1])):
        print(p)


if __name__ == "__main__":
    main()


