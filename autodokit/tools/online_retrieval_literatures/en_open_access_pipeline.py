"""英文开放源整体验证流水线。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


def _discover_repo_root(start_path: Path) -> Path:
    for candidate in [start_path, *start_path.parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "autodokit").is_dir():
            return candidate
    raise RuntimeError("未找到 autodo-kit 仓库根目录。")


REPO_ROOT = _discover_repo_root(Path(__file__).resolve().parent)


def _load_core_module() -> Any:
    module_path = REPO_ROOT / "autodokit" / "tools" / "open_access_literature_retrieval.py"
    spec = importlib.util.spec_from_file_location("autodokit.tools.open_access_literature_retrieval", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块源码：{module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CORE = _load_core_module()
search_openalex = _CORE.search_openalex
search_crossref = _CORE.search_crossref
search_europe_pmc = _CORE.search_europe_pmc
search_arxiv = _CORE.search_arxiv
merge_records = _CORE.merge_records
download_record = _CORE.download_record
write_metadata_outputs = _CORE.write_metadata_outputs
write_download_outputs = _CORE.write_download_outputs


DEFAULT_SOURCES = ["openalex", "crossref", "europe_pmc", "arxiv"]


def _search_source(source: str, query: str, *, max_pages: int, per_page: int) -> dict[str, Any]:
    if source == "openalex":
        return search_openalex(query, max_pages=max_pages, per_page=per_page)
    if source == "crossref":
        return search_crossref(query, max_pages=max_pages, per_page=per_page)
    if source == "europe_pmc":
        return search_europe_pmc(query, max_pages=max_pages, per_page=per_page)
    if source == "arxiv":
        return search_arxiv(query, max_pages=max_pages, per_page=per_page)
    raise ValueError(f"不支持的英文来源: {source}")


def run_pipeline(config: dict[str, Any]) -> dict[str, Any]:
    query = str(config.get("query") or "").strip()
    max_pages = max(int(config.get("max_pages") or 1), 1)
    per_page = max(int(config.get("per_page") or 20), 1)
    sources = [str(item).strip() for item in list(config.get("sources") or DEFAULT_SOURCES) if str(item).strip()]
    download_policy = str(config.get("download_policy") or "download").strip().lower()
    max_downloads = int(config.get("max_downloads") or 0)
    output_dir = Path(str(config.get("output_dir") or REPO_ROOT / "sandbox" / "online_retrieval_debug" / "outputs" / "en_open_access")).expanduser().resolve()
    bailian_api_key_file = str(config.get("bailian_api_key_file") or "")

    source_runs: list[dict[str, Any]] = []
    for source in sources:
        try:
            source_result = _search_source(source, query, max_pages=max_pages, per_page=per_page)
            source_result["status"] = "PASS"
        except Exception as exc:  # noqa: BLE001
            source_result = {
                "source": source,
                "status": "BLOCKED",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
                "page_count": 0,
                "total_count": 0,
                "records": [],
            }
        source_runs.append(source_result)

    records = merge_records(source_runs)
    metadata_paths = write_metadata_outputs(records, output_dir)

    manifest: list[dict[str, Any]] = []
    download_paths: dict[str, str] = {}
    download_count = 0
    blocked_count = 0
    if download_policy != "metadata-only" and records:
        download_dir = output_dir / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)
        limit = max_downloads if max_downloads > 0 else len(records)
        for index, record in enumerate(records[:limit], start=1):
            result = download_record(
                record,
                download_dir,
                bailian_api_key_file=bailian_api_key_file,
                request_timeout=int(config.get("download_request_timeout") or 12),
                max_attempts=int(config.get("per_record_max_attempts") or 6),
                enable_barrier_analysis=bool(config.get("enable_barrier_analysis", False)),
            )
            manifest.append(
                {
                    "index": index,
                    "status": str(result.get("status") or "BLOCKED"),
                    "title": record.title,
                    "source": record.source,
                    "saved_path": str(result.get("saved_path") or ""),
                    "final_url": str(result.get("final_url") or ""),
                    "barrier_type": str(result.get("barrier_type") or ""),
                }
            )
            if str(result.get("status") or "") == "PASS":
                download_count += 1
            elif str(result.get("status") or "") == "BLOCKED":
                blocked_count += 1
        download_paths = write_download_outputs(manifest, output_dir)

    return {
        "status": "PASS" if records or download_count else "BLOCKED",
        "query": query,
        "source_runs": source_runs,
        "record_count": len(records),
        "download_count": download_count,
        "blocked_count": blocked_count,
        "metadata_paths": metadata_paths,
        "download_paths": download_paths,
        "manifest": manifest,
        "output_dir": str(output_dir),
    }