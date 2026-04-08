"""英文开放源单篇原文下载工具。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from .retrieval_policy import evaluate_policy


def _discover_repo_root(start_path: Path) -> Path:
    for candidate in [start_path, *start_path.parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "autodokit").is_dir():
            return candidate
    raise RuntimeError("未找到 autodo-kit 仓库根目录。")


REPO_ROOT = _discover_repo_root(Path(__file__).resolve().parent)


def _load_core_module() -> Any:
    module_path = REPO_ROOT / "autodokit" / "tools" / "online_retrieval_literatures" / "open_access_literature_retrieval.py"
    spec = importlib.util.spec_from_file_location("autodokit.tools.open_access_literature_retrieval", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块源码：{module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


_CORE = _load_core_module()
RetrievalRecord = _CORE.RetrievalRecord
download_record = _CORE.download_record


def _resolve_repo_path(raw_path: str | Path | None, default_relative: str) -> Path:
    raw_text = str(raw_path or "").strip()
    if not raw_text:
        return (REPO_ROOT / default_relative).resolve()
    candidate = Path(raw_text).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (REPO_ROOT / candidate).resolve()


def _to_record(record_dict: dict[str, Any]) -> RetrievalRecord:
    return RetrievalRecord(
        source=str(record_dict.get("source") or "custom"),
        source_id=str(record_dict.get("source_id") or ""),
        title=str(record_dict.get("title") or "untitled"),
        year=str(record_dict.get("year") or ""),
        doi=str(record_dict.get("doi") or ""),
        journal=str(record_dict.get("journal") or ""),
        authors=[str(item) for item in list(record_dict.get("authors") or [])],
        abstract=str(record_dict.get("abstract") or ""),
        landing_url=str(record_dict.get("landing_url") or ""),
        pdf_url=str(record_dict.get("pdf_url") or ""),
        bibtex_key=str(record_dict.get("bibtex_key") or ""),
        raw=dict(record_dict.get("raw") or {}),
    )


def _load_record(args: argparse.Namespace) -> RetrievalRecord:
    if args.record_json:
        payload = json.loads(args.record_json)
        if not isinstance(payload, dict):
            raise ValueError("record-json 必须是 JSON 对象。")
        return _to_record(payload)

    if args.record_path:
        path = Path(args.record_path).expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            if not payload:
                raise ValueError("record-path 指向的数组为空。")
            payload = payload[0]
        if not isinstance(payload, dict):
            raise ValueError("record-path 必须是对象或对象数组。")
        return _to_record(payload)

    if args.pdf_url or args.landing_url or args.doi:
        return _to_record(
            {
                "source": args.source,
                "source_id": args.source_id,
                "title": args.title,
                "year": args.year,
                "doi": args.doi,
                "journal": args.journal,
                "authors": [item.strip() for item in str(args.authors or "").split(",") if item.strip()],
                "abstract": args.abstract,
                "landing_url": args.landing_url,
                "pdf_url": args.pdf_url,
                "bibtex_key": args.bibtex_key,
                "raw": {
                    "download_candidates": [item.strip() for item in str(args.download_candidates or "").split(",") if item.strip()]
                },
            }
        )

    raise ValueError("缺少单篇记录输入，请提供 --record-json / --record-path / (pdf_url|landing_url|doi)。")


def download_single(config: dict[str, Any], record: RetrievalRecord) -> dict[str, Any]:
    rules = dict(config.get("retrieval_rules") or {})
    decision = evaluate_policy(record.to_dict(), rules, channel="download", source="en_open_access")
    if decision.skip:
        return {
            "status": "SKIPPED",
            "record": record.to_dict(),
            "result": {
                "status": "SKIPPED",
                "reason": decision.reason,
                "matched_tokens": decision.matched_tokens,
            },
            "output_path": "",
        }

    output_dir = _resolve_repo_path(config.get("output_dir"), "sandbox/online_retrieval_debug/outputs/en_open_access/single")
    download_dir = output_dir / "downloads"
    output_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)

    result = download_record(
        record,
        download_dir,
        bailian_api_key_file=str(config.get("bailian_api_key_file") or ""),
        request_timeout=int(config.get("download_request_timeout") or 12),
        max_attempts=int(config.get("per_record_max_attempts") or 6),
        enable_barrier_analysis=bool(config.get("enable_barrier_analysis", False)),
        min_request_delay_seconds=float(config.get("min_request_delay_seconds") or 0.35),
        max_request_delay_seconds=float(config.get("max_request_delay_seconds") or 1.6),
    )

    payload = {
        "status": str(result.get("status") or "BLOCKED"),
        "record": record.to_dict(),
        "result": result,
    }
    output_path = output_dir / "single_download_result.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["output_path"] = str(output_path)
    return payload


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="英文开放源单篇原文下载")
    parser.add_argument("--record-json", default="", help="单条记录 JSON 字符串")
    parser.add_argument("--record-path", default="", help="单条记录 JSON 文件路径")

    parser.add_argument("--source", default="custom", help="来源")
    parser.add_argument("--source-id", default="", help="来源内 ID")
    parser.add_argument("--title", default="", help="标题")
    parser.add_argument("--year", default="", help="年份")
    parser.add_argument("--doi", default="", help="DOI")
    parser.add_argument("--journal", default="", help="期刊")
    parser.add_argument("--authors", default="", help="作者列表，逗号分隔")
    parser.add_argument("--abstract", default="", help="摘要")
    parser.add_argument("--landing-url", default="", help="落地页 URL")
    parser.add_argument("--pdf-url", default="", help="直接 PDF URL")
    parser.add_argument("--bibtex-key", default="", help="BibTeX key")
    parser.add_argument("--download-candidates", default="", help="附加下载候选 URL，逗号分隔")

    parser.add_argument("--output-dir", default="", help="输出目录")
    parser.add_argument("--bailian-api-key-file", default="", help="百炼 API key 文件路径")
    parser.add_argument("--download-request-timeout", type=int, default=12, help="下载超时秒数")
    parser.add_argument("--per-record-max-attempts", type=int, default=6, help="单条最大尝试次数")
    parser.add_argument("--min-request-delay-seconds", type=float, default=0.35, help="单条内部请求最小随机等待秒数")
    parser.add_argument("--max-request-delay-seconds", type=float, default=1.6, help="单条内部请求最大随机等待秒数")
    parser.add_argument("--enable-barrier-analysis", action="store_true", help="启用阻断页分析")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    record = _load_record(args)
    config = {
        "output_dir": args.output_dir,
        "bailian_api_key_file": args.bailian_api_key_file,
        "download_request_timeout": args.download_request_timeout,
        "per_record_max_attempts": args.per_record_max_attempts,
        "min_request_delay_seconds": args.min_request_delay_seconds,
        "max_request_delay_seconds": args.max_request_delay_seconds,
        "enable_barrier_analysis": args.enable_barrier_analysis,
    }
    result = download_single(config, record)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
