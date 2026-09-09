"""MinerU CLI 运行封装。

本模块封装 MinerU 命令行工具的探测、单篇 PDF 解析调用与输出文件发现。

设计说明：
- MinerU 属于可选依赖。未安装时调用 ``run_mineru_single_pdf`` 会抛出带安装
  提示的 ``RuntimeError``。
- 所有路径要求为绝对路径（由调度层统一预处理）。
- 本模块只负责“运行 MinerU 并发现产物”，不承担输出解析；输出解析由
  ``pdf_to_structure_data_converter_use_mineru`` 完成。

MinerU 后端选择（CLI 参数 ``--backend``）：
- ``pipeline``：传统版面+OCR 流水线，支持纯 CPU 与 Apple Silicon/MPS，
  中文场景推荐；精度 OmniDocBench v1.6 ≈ 86.47。
- ``hybrid-engine``（默认）：VLM + 小模型混合后端，需 GPU 或 Apple Silicon，
  最低 8GB 显存；精度 ≈ 95.26（medium）/ 95.39（high）。
- ``vlm-engine``：纯 VLM 后端，需 GPU 或 Apple Silicon。
- ``vlm-http-client`` / ``hybrid-http-client``：对接 OpenAI 兼容服务。

M5 Max（128GB 统一内存）建议：
- 追求最高精度：``backend="hybrid-engine", effort="high"``。
- 批量/中文文献兼顾速度：``backend="hybrid-engine", effort="medium"``。
- 纯 CPU 或极低资源：``backend="pipeline", method="ocr", lang="ch"``。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 默认值 ──────────────────────────────────────────
DEFAULT_MINERU_BACKEND = "hybrid-engine"
DEFAULT_MINERU_EFFORT = "medium"
SUPPORTED_BACKENDS = (
    "pipeline",
    "vlm-engine",
    "hybrid-engine",
    "vlm-http-client",
    "hybrid-http-client",
)
SUPPORTED_EFFORTS = ("medium", "high")
SUPPORTED_METHODS = ("auto", "txt", "ocr")
# pipeline 后端支持的语言（OCR 精度提示，仅 pipeline 生效）
PIPELINE_LANGS = ("ch", "ch_server", "korean", "ta", "te", "ka", "th", "el", "arabic", "east_slavic", "cyrillic", "devanagari")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def resolve_mineru_cli(explicit_path: str | Path | None = None) -> str:
    """解析 MinerU CLI 可执行文件路径。

    Args:
        explicit_path: 显式指定的 mineru 可执行文件路径（可选）。

    Returns:
        mineru CLI 绝对路径字符串。

    Raises:
        RuntimeError: 未找到 mineru 可执行文件时抛出。

    Examples:
        >>> resolve_mineru_cli()  # 依赖 PATH 或环境变量
        '/path/to/mineru'
    """

    candidates: list[str] = []
    if explicit_path and _stringify(explicit_path):
        candidates.append(str(Path(_stringify(explicit_path)).expanduser()))
    for env_name in ("MINERU_CLI_PATH", "AUTODOKIT_MINERU_CLI"):
        env_value = _stringify(os.environ.get(env_name))
        if env_value:
            candidates.append(str(Path(env_value).expanduser()))

    for candidate in candidates:
        path = Path(candidate)
        if path.is_absolute() and path.exists() and path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())

    located = shutil.which("mineru")
    if located:
        return located

    raise RuntimeError(
        "未找到 MinerU CLI。请先安装：uv pip install -U 'mineru[all]'\n"
        "或在环境变量 MINERU_CLI_PATH / AUTODOKIT_MINERU_CLI 中指定 mineru 可执行文件绝对路径。"
    )


def _normalize_backend(value: str) -> str:
    backend = _stringify(value).strip().lower() or DEFAULT_MINERU_BACKEND
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"不支持的 MinerU backend：{backend!r}，可选：{', '.join(SUPPORTED_BACKENDS)}"
        )
    return backend


def _normalize_effort(value: str) -> str:
    effort = _stringify(value).strip().lower() or DEFAULT_MINERU_EFFORT
    if effort not in SUPPORTED_EFFORTS:
        raise ValueError(f"不支持的 MinerU effort：{effort!r}，可选：{', '.join(SUPPORTED_EFFORTS)}")
    return effort


def _normalize_method(value: str) -> str:
    method = _stringify(value).strip().lower() or "auto"
    if method not in SUPPORTED_METHODS:
        raise ValueError(f"不支持的 MinerU method：{method!r}，可选：{', '.join(SUPPORTED_METHODS)}")
    return method


def _build_mineru_command(
    *,
    cli_path: str,
    pdf_path: Path,
    output_dir: Path,
    backend: str,
    effort: str,
    method: str,
    lang: str,
    formula: bool,
    table: bool,
    image_analysis: bool,
    start_page: int | None,
    end_page: int | None,
    client_side_output: bool,
) -> list[str]:
    """构造 mineru 命令行。"""

    command = [
        cli_path,
        "-p",
        str(pdf_path),
        "-o",
        str(output_dir),
        "-b",
        backend,
    ]
    if backend != "pipeline":
        command.extend(["--effort", effort])
    if backend in {"pipeline", "hybrid-engine", "hybrid-http-client"}:
        command.extend(["-m", method])
    if backend == "pipeline" and lang:
        command.extend(["-l", lang])
    command.extend(["--formula", str(bool(formula)).lower()])
    command.extend(["--table", str(bool(table)).lower()])
    if backend in {"vlm-engine", "hybrid-engine", "vlm-http-client", "hybrid-http-client"}:
        command.extend(["--image-analysis", str(bool(image_analysis)).lower()])
    if start_page is not None and start_page >= 0:
        command.extend(["-s", str(int(start_page))])
    if end_page is not None and end_page >= 0:
        command.extend(["-e", str(int(end_page))])
    if client_side_output:
        command.append("--client-side-output-generation")
    return command


@dataclass(frozen=True)
class MineruRunResult:
    """MinerU 单篇运行结果。

    Attributes:
        command: 实际执行的命令行。
        returncode: 进程退出码。
        output_dir: MinerU 输出目录（绝对路径）。
        stdout_tail: 标准输出末尾片段（诊断用）。
        stderr_tail: 标准错误末尾片段（诊断用）。
    """

    command: list[str]
    returncode: int
    output_dir: Path
    stdout_tail: str = ""
    stderr_tail: str = ""


def run_mineru_single_pdf(
    pdf_path: str | Path,
    output_dir: str | Path,
    *,
    backend: str = DEFAULT_MINERU_BACKEND,
    effort: str = DEFAULT_MINERU_EFFORT,
    method: str = "auto",
    lang: str = "ch",
    formula: bool = True,
    table: bool = True,
    image_analysis: bool = True,
    start_page: int | None = None,
    end_page: int | None = None,
    client_side_output: bool = True,
    cli_path: str | Path | None = None,
    timeout_seconds: int = 7200,
    env: Dict[str, str] | None = None,
) -> MineruRunResult:
    """对单个 PDF 运行 MinerU 解析。

    Args:
        pdf_path: PDF 文件绝对路径。
        output_dir: MinerU 输出目录（绝对路径；不存在时自动创建）。
        backend: MinerU 后端，可选 pipeline / vlm-engine / hybrid-engine /
            vlm-http-client / hybrid-http-client，默认 hybrid-engine。
        effort: hybrid 解析强度，可选 medium / high，默认 medium。
        method: 解析方法，可选 auto / txt / ocr（pipeline 与 hybrid 后端生效）。
        lang: pipeline 后端语言提示，默认 ch。
        formula: 是否启用公式解析，默认 True。
        table: 是否启用表格解析，默认 True。
        image_analysis: 是否启用图像/图表分析（VLM 与 hybrid 后端），默认 True。
        start_page: 起始页（0 基），None 表示从首页开始。
        end_page: 结束页（0 基，含），None 表示到末页。
        client_side_output: 是否由客户端本地生成 Markdown 与 content list，
            默认 True。
        cli_path: 显式指定 mineru CLI 路径（可选）。
        timeout_seconds: 单篇解析超时秒数，默认 7200。
        env: 额外环境变量（可选，合并到当前环境）。

    Returns:
        MineruRunResult: 运行结果与输出目录。

    Raises:
        ValueError: 路径非绝对路径或参数非法时抛出。
        RuntimeError: MinerU 未安装或解析失败时抛出。
    """

    pdf = Path(pdf_path)
    out = Path(output_dir)
    if not pdf.is_absolute():
        raise ValueError(f"pdf_path 必须是绝对路径：{pdf}")
    if not out.is_absolute():
        raise ValueError(f"output_dir 必须是绝对路径：{out}")
    if not pdf.exists() or not pdf.is_file():
        raise ValueError(f"PDF 文件不存在：{pdf}")

    out.mkdir(parents=True, exist_ok=True)

    normalized_backend = _normalize_backend(backend)
    normalized_effort = _normalize_effort(effort)
    normalized_method = _normalize_method(method)
    normalized_lang = _stringify(lang)
    if normalized_backend == "pipeline" and normalized_lang and normalized_lang not in PIPELINE_LANGS:
        raise ValueError(
            f"pipeline 后端不支持语言 {normalized_lang!r}，可选：{', '.join(PIPELINE_LANGS)}"
        )

    cli = resolve_mineru_cli(cli_path)
    command = _build_mineru_command(
        cli_path=cli,
        pdf_path=pdf,
        output_dir=out,
        backend=normalized_backend,
        effort=normalized_effort,
        method=normalized_method,
        lang=normalized_lang,
        formula=formula,
        table=table,
        image_analysis=image_analysis,
        start_page=start_page,
        end_page=end_page,
        client_side_output=client_side_output,
    )

    run_env = dict(os.environ)
    if env:
        run_env.update({key: _stringify(value) for key, value in env.items()})

    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=run_env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"MinerU CLI 不可执行：{cli}\n请检查安装与环境变量。") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"MinerU 解析超时（>{timeout_seconds}s）：{pdf.name}"
        ) from exc

    stdout_tail = (proc.stdout or "")[-2000:]
    stderr_tail = (proc.stderr or "")[-4000:]

    if proc.returncode != 0:
        raise RuntimeError(
            f"MinerU 解析失败（exit={proc.returncode}）：{pdf.name}\n"
            f"命令：{' '.join(command)}\n"
            f"stderr 末尾：{stderr_tail}"
        )

    return MineruRunResult(
        command=command,
        returncode=int(proc.returncode),
        output_dir=out.resolve(),
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
    )


def discover_mineru_output_files(output_dir: str | Path) -> List[Dict[str, Any]]:
    """发现 MinerU 在输出目录中生成的产物文件。

    Args:
        output_dir: MinerU 输出目录（绝对路径）。

    Returns:
        文件信息字典列表，按名称排序。

    Examples:
        >>> files = discover_mineru_output_files("/tmp/mineru_out")
        >>> any(f["name"].endswith("_content_list.json") for f in files)
        True
    """

    root = Path(output_dir)
    if not root.is_absolute():
        raise ValueError(f"output_dir 必须是绝对路径：{root}")
    if not root.exists() or not root.is_dir():
        return []

    results: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        results.append(
            {
                "path": str(path),
                "name": path.name,
                "suffix": path.suffix.lower(),
                "size_bytes": int(stat.st_size),
                "mtime": float(stat.st_mtime),
            }
        )
    return results
