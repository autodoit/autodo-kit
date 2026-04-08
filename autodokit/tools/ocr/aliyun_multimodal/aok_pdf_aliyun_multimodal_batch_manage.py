"""阿里百炼多模态 PDF 批量管理工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from autodokit.tools.ocr.aliyun_multimodal.aok_pdf_aliyun_multimodal_parse import parse_pdf_with_aliyun_multimodal
from autodokit.tools.time_utils import now_iso


def _utc_now_iso() -> str:
    return now_iso()


def _resolve_path(path: str | Path, *, field_name: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if field_name == "api_key_file" and (not resolved.exists() or not resolved.is_file()):
        raise ValueError(f"{field_name} 必须是存在的文件：{resolved}")
    return resolved


def _load_jobs(jobs: Iterable[Dict[str, Any]] | None, jobs_file: str | Path | None) -> List[Dict[str, Any]]:
    if jobs is not None:
        return [dict(item) for item in jobs]
    if jobs_file is None:
        raise ValueError("jobs 与 jobs_file 不能同时为空")
    payload = json.loads(_resolve_path(jobs_file, field_name="jobs_file").read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError("jobs_file 必须是 JSON 数组")
    return [dict(item) for item in payload]


def _render_batch_report(summary: Dict[str, Any]) -> str:
    lines = ["# AOK 阿里百炼多模态 PDF 批量运行报告", ""]
    lines.append(f"- 创建时间：{summary['created_at']}")
    lines.append(f"- 任务总数：{summary['job_count']}")
    lines.append(f"- 成功数：{summary['success_count']}")
    lines.append(f"- 失败数：{summary['failure_count']}")
    lines.append("")
    if summary["results"]:
        lines.append("## 成功任务")
        lines.append("")
        for item in summary["results"]:
            lines.append(
                f"- {item['job_label']}：{item['page_count']} 页，{item['element_count']} elements，{item['chunk_count']} chunks，输出目录 {item['output_dir']}"
            )
        lines.append("")
    if summary["failures"]:
        lines.append("## 失败任务")
        lines.append("")
        for item in summary["failures"]:
            lines.append(f"- {item['job_label']}：{item['error']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def batch_manage_pdf_with_aliyun_multimodal(
    *,
    output_root: str | Path,
    api_key_file: str | Path,
    jobs: Iterable[Dict[str, Any]] | None = None,
    jobs_file: str | Path | None = None,
    output_name_key: str = "output_name",
    model: str = "auto",
    generate_report: bool = True,
    fail_fast: bool = False,
    overwrite_output: bool = False,
    **default_parse_kwargs: Any,
) -> Dict[str, Any]:
    """批量管理单篇阿里百炼多模态解析。

    Args:
        output_root: 批量输出根目录。
        api_key_file: 阿里百炼 API Key 文件路径。
        jobs: 任务数组。
        jobs_file: 任务文件路径，内容为 JSON 数组。
        output_name_key: 从每个 job 中读取输出目录名的字段名。
        model: 默认模型名。
        generate_report: 是否生成 Markdown 报告。
        fail_fast: 遇到失败是否立即停止。
        overwrite_output: 是否允许覆盖已有输出目录。
        **default_parse_kwargs: 透传给单篇解析函数的默认参数。

    Returns:
        Dict[str, Any]: 批处理摘要。
    """

    batch_root = _resolve_path(output_root, field_name="output_root")
    batch_root.mkdir(parents=True, exist_ok=True)
    resolved_api_key_file = _resolve_path(api_key_file, field_name="api_key_file")
    resolved_jobs = _load_jobs(jobs, jobs_file)

    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    for index, raw_job in enumerate(resolved_jobs, start=1):
        job = dict(raw_job)
        pdf_path = job.pop("pdf_path", None)
        if not pdf_path:
            error = {"job_index": index, "job_label": f"job_{index:03d}", "error": "job.pdf_path 不能为空"}
            failures.append(error)
            if fail_fast:
                break
            continue

        job_output_name = None
        if output_name_key:
            candidate = str(job.pop(output_name_key, "") or "").strip()
            job_output_name = candidate or None

        job_model = str(job.pop("model", "") or model).strip() or model
        job_api_key_file = Path(str(job.pop("api_key_file", resolved_api_key_file))).expanduser().resolve()
        job_label = str(job.get("document_id") or Path(str(pdf_path)).stem or f"job_{index:03d}")

        parse_kwargs = dict(default_parse_kwargs)
        parse_kwargs.update(job)
        parse_kwargs["overwrite_output"] = bool(parse_kwargs.get("overwrite_output", overwrite_output))

        try:
            result = parse_pdf_with_aliyun_multimodal(
                pdf_path=pdf_path,
                output_root=batch_root,
                output_name=job_output_name,
                api_key_file=job_api_key_file,
                model=job_model,
                **parse_kwargs,
            )
            results.append(
                {
                    "job_index": index,
                    "job_label": job_label,
                    "pdf_path": str(Path(str(pdf_path)).expanduser().resolve()),
                    "output_name": str(result.get("output_name") or ""),
                    "output_dir": str(result.get("output_dir") or ""),
                    "page_count": int(result.get("page_count") or 0),
                    "element_count": int(result.get("element_count") or 0),
                    "chunk_count": int(result.get("chunk_count") or 0),
                    "result_path": str(Path(str(result.get("output_dir") or "")).resolve() / "result.json"),
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "job_index": index,
                    "job_label": job_label,
                    "pdf_path": str(Path(str(pdf_path)).expanduser().resolve()),
                    "output_name": str(job_output_name or ""),
                    "error": str(exc),
                }
            )
            if fail_fast:
                break

    summary = {
        "tool": "aok_pdf_aliyun_multimodal_batch_manage",
        "created_at": _utc_now_iso(),
        "output_root": str(batch_root),
        "job_count": len(resolved_jobs),
        "success_count": len(results),
        "failure_count": len(failures),
        "results": results,
        "failures": failures,
    }

    run_summary_path = (batch_root / "run_summary.json").resolve()
    run_summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report_path = ""
    if generate_report:
        report_file = (batch_root / "report.md").resolve()
        report_file.write_text(_render_batch_report(summary), encoding="utf-8")
        report_path = str(report_file)

    summary["run_summary_path"] = str(run_summary_path)
    summary["report_path"] = report_path
    run_summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


__all__ = ["batch_manage_pdf_with_aliyun_multimodal"]
