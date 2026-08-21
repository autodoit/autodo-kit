"""作者姓名预处理工具（阿里百炼）。

本模块提供两类能力：
1. 批量预处理姓名（中英文），返回结构化标准结果；
2. 对 content.db 的文献作者串执行预处理并回填，供 A020 或事后补救使用。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from autodokit.tools.contentdb_sqlite import (
    LITERATURE_TABLE_NAME,
    resolve_content_physical_column,
    sync_author_entities_from_literature_rows,
)
from autodokit.tools.atomic.llm import ModelRoutingIntent, invoke_aliyun_llm
from autodokit.tools.atomic.llm import parse_json_object_from_text


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _split_author_values(value: object) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    normalized = (
        text.replace(" and ", "|")
        .replace("；", "|")
        .replace(";", "|")
        .replace("、", "|")
    )
    if "|" in normalized:
        return [segment.strip() for segment in normalized.split("|") if segment.strip()]

    comma_segments = [segment.strip() for segment in text.replace("，", ",").split(",") if segment.strip()]
    if len(comma_segments) == 2:
        return [text]
    if len(comma_segments) > 2 and len(comma_segments) % 2 == 0:
        paired = [", ".join(comma_segments[index:index + 2]).strip() for index in range(0, len(comma_segments), 2)]
        if all(paired):
            return paired
    return comma_segments or [text]


def _fallback_normalize_name(raw_name: str) -> Dict[str, str]:
    """在 LLM 不可用时的兜底处理。"""

    text = " ".join(str(raw_name or "").replace("\u3000", " ").strip().split())
    text = text.replace("本报记者", "").replace("记者", "").replace("通讯员", "").strip()
    if not text:
        return {
            "normalized_display_name": "",
            "canonical_name": "",
            "surname": "",
            "given_names": "",
            "author_type": "其他",
            "confidence": "0.20",
            "source": "fallback",
        }

    surname = text
    given_names = ""
    if "," in text:
        surname, given_names = [segment.strip() for segment in text.split(",", 1)]
    elif " " in text:
        parts = [segment for segment in text.split(" ") if segment]
        surname = parts[-1]
        given_names = " ".join(parts[:-1])

    return {
        "normalized_display_name": text,
        "canonical_name": text,
        "surname": surname,
        "given_names": given_names,
        "author_type": "个人作者",
        "confidence": "0.20",
        "source": "fallback",
    }


def _build_llm_prompt(names: Iterable[str]) -> str:
    payload = {"names": [str(name) for name in names]}
    schema_hint = {
        "items": [
            {
                "original": "原始姓名",
                "normalized_display_name": "用于展示的标准姓名",
                "canonical_name": "标准作者名，机构可为空",
                "surname": "姓（中文姓/英文 last name）",
                "given_names": "名（中文名/英文 given names）",
                "author_type": "个人作者|机构署名|编辑部署名|其他",
                "confidence": "0-1 的小数"
            }
        ]
    }
    return (
        "你是学术文献作者姓名规范化专家。\n"
        "请把输入姓名列表规范化，要求：\n"
        "1) 去除报道角色前缀（如 本报记者、记者、通讯员）。\n"
        "2) 区分个人作者与机构署名。\n"
        "3) 中文姓名正确拆分姓和名；英文姓名拆分 last name 与 given names。\n"
        "4) 保留原语种，不做机器翻译。\n"
        "5) 仅输出 JSON 对象，不要输出额外解释。\n\n"
        f"输出 JSON Schema 示例：{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
        f"输入：{json.dumps(payload, ensure_ascii=False)}"
    )


def _resolve_api_key_file(payload: Dict[str, Any]) -> str | None:
    explicit = str(payload.get("api_key_file") or "").strip()
    if explicit:
        return explicit

    config_path = str(payload.get("config_path") or "").strip()
    if not config_path:
        return None

    try:
        config_data = json.loads(Path(config_path).expanduser().resolve().read_text(encoding="utf-8-sig"))
    except Exception:
        return None

    if not isinstance(config_data, dict):
        return None

    llm_cfg = config_data.get("llm") if isinstance(config_data.get("llm"), dict) else {}
    for candidate in (
        llm_cfg.get("aliyun_api_key_file"),
        llm_cfg.get("api_key_file"),
        config_data.get("aliyun_api_key_file"),
        config_data.get("api_key_file"),
    ):
        value = str(candidate or "").strip()
        if value:
            return value

    return None


def preprocess_author_names_with_aliyun(payload: Dict[str, Any]) -> Dict[str, Any]:
    """批量预处理中英文姓名。

    Args:
        payload: 输入参数。
            - names: 姓名列表。
            - api_key_file: 可选，百炼 API key 文件。
            - config_path: 可选，全局配置路径。
            - model: 可选，模型名。
            - batch_size: 可选，默认 50。
            - allow_fallback_cleaning: 可选，是否允许降级清洗，默认 False。

    Returns:
        预处理结果字典。
    """

    raw_names = payload.get("names")
    if not isinstance(raw_names, list):
        raise ValueError("names 必须是列表")

    names = [str(item or "").strip() for item in raw_names if str(item or "").strip()]
    unique_names = list(dict.fromkeys(names))

    batch_size = max(1, int(payload.get("batch_size") or 50))
    model = str(payload.get("model") or "auto").strip() or "auto"
    config_path = str(payload.get("config_path") or "").strip() or None
    api_key_file = _resolve_api_key_file(payload)
    allow_fallback_cleaning = bool(payload.get("allow_fallback_cleaning", False))

    resolved: Dict[str, Dict[str, str]] = {}
    llm_success_batches = 0
    llm_failed_batches = 0
    failed_batches: List[Dict[str, Any]] = []

    for start in range(0, len(unique_names), batch_size):
        batch = unique_names[start:start + batch_size]
        if not batch:
            continue

        llm_result = invoke_aliyun_llm(
            prompt=_build_llm_prompt(batch),
            system="你必须只输出一个 JSON 对象。",
            intent=ModelRoutingIntent(task_type="general", quality_tier="high", budget_tier="balanced", risk_level="strict", affair_name="作者姓名预处理"),
            max_tokens=4096,
            temperature=0.0,
            api_key_file=api_key_file,
            config_path=config_path,
            affair_name="作者姓名预处理",
            route_hints={"task_type": "general", "budget_tier": "balanced", "model": model},
        )

        batch_mapped = False
        if str(llm_result.get("status") or "").upper() == "PASS":
            text = str(((llm_result.get("response") or {}).get("text") or "")).strip()
            try:
                parsed, _debug = parse_json_object_from_text(text)
                items = parsed.get("items") if isinstance(parsed, dict) else None
                if isinstance(items, list):
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        original = str(item.get("original") or "").strip()
                        if not original:
                            continue
                        resolved[original] = {
                            "normalized_display_name": str(item.get("normalized_display_name") or original).strip() or original,
                            "canonical_name": str(item.get("canonical_name") or "").strip(),
                            "surname": str(item.get("surname") or "").strip(),
                            "given_names": str(item.get("given_names") or "").strip(),
                            "author_type": str(item.get("author_type") or "个人作者").strip() or "个人作者",
                            "confidence": str(item.get("confidence") or "0.70").strip() or "0.70",
                            "source": "aliyun_llm",
                        }
                    batch_mapped = True
            except Exception:
                batch_mapped = False

        if batch_mapped:
            llm_success_batches += 1
            continue

        llm_failed_batches += 1
        attempts = llm_result.get("attempts") if isinstance(llm_result, dict) else None
        failed_batches.append(
            {
                "batch_start": start,
                "batch_size": len(batch),
                "batch_examples": batch[:5],
                "attempts": attempts if isinstance(attempts, list) else [],
                "error": str(llm_result.get("error") or "") if isinstance(llm_result, dict) else "",
            }
        )

        if allow_fallback_cleaning:
            for raw_name in batch:
                resolved[raw_name] = _fallback_normalize_name(raw_name)

    if failed_batches and not allow_fallback_cleaning:
        return {
            "status": "FAIL",
            "reason": "LLM 调用失败，且已禁用降级清洗。",
            "input_count": len(names),
            "unique_input_count": len(unique_names),
            "llm_success_batches": llm_success_batches,
            "llm_failed_batches": llm_failed_batches,
            "failed_batches": failed_batches,
            "allow_fallback_cleaning": False,
            "items": [],
        }

    normalized_items = []
    for raw_name in names:
        normalized = resolved.get(raw_name) or _fallback_normalize_name(raw_name)
        normalized_items.append({"original": raw_name, **normalized})

    return {
        "status": "PASS",
        "input_count": len(names),
        "unique_input_count": len(unique_names),
        "llm_success_batches": llm_success_batches,
        "llm_failed_batches": llm_failed_batches,
        "failed_batches": failed_batches,
        "allow_fallback_cleaning": allow_fallback_cleaning,
        "items": normalized_items,
    }


def normalize_content_db_author_names_with_aliyun(payload: Dict[str, Any]) -> Dict[str, Any]:
    """对 content.db 的文献作者串执行 LLM 预处理并回填。

    Args:
        payload: 输入参数。
            - content_db: content.db 路径（必填）。
            - api_key_file/config_path/model/batch_size: 透传到 LLM 预处理函数。
            - allow_fallback_cleaning: 是否允许降级清洗，默认 False。
            - sample_limit: 返回样本上限，默认 20。

    Returns:
        处理摘要。
    """

    db_raw = str(payload.get("content_db") or "").strip()
    if not db_raw:
        raise ValueError("content_db 不能为空")
    db_path = Path(db_raw).expanduser().resolve()
    sample_limit = max(1, int(payload.get("sample_limit") or 20))

    uid_column = resolve_content_physical_column(LITERATURE_TABLE_NAME, "uid_literature")
    authors_column = resolve_content_physical_column(LITERATURE_TABLE_NAME, "authors")
    first_author_column = resolve_content_physical_column(LITERATURE_TABLE_NAME, "first_author")
    updated_column = resolve_content_physical_column(LITERATURE_TABLE_NAME, "updated_at")

    with sqlite3.connect(str(db_path), timeout=60) as conn:
        rows = conn.execute(
            f"SELECT {_quote_identifier(uid_column)} AS uid_literature, {_quote_identifier(authors_column)} AS authors FROM {_quote_identifier(LITERATURE_TABLE_NAME)}"
        ).fetchall()

        unique_names: List[str] = []
        seen_names: set[str] = set()
        for _, authors in rows:
            for name in _split_author_values(authors):
                if name not in seen_names:
                    seen_names.add(name)
                    unique_names.append(name)

        preprocess_payload = {
            "names": unique_names,
            "api_key_file": payload.get("api_key_file"),
            "config_path": payload.get("config_path"),
            "model": payload.get("model"),
            "batch_size": payload.get("batch_size"),
            "allow_fallback_cleaning": payload.get("allow_fallback_cleaning", False),
        }
        preprocess_result = preprocess_author_names_with_aliyun(preprocess_payload)
        if str(preprocess_result.get("status") or "").upper() != "PASS":
            raise RuntimeError(
                "作者姓名 LLM 预处理失败："
                + str(preprocess_result.get("reason") or preprocess_result.get("error") or "未知错误")
            )

        name_map: Dict[str, Dict[str, str]] = {
            str(item.get("original") or "").strip(): item
            for item in preprocess_result.get("items", [])
            if isinstance(item, dict) and str(item.get("original") or "").strip()
        }

        update_rows: List[tuple[str, str, str, str]] = []
        changed_rows: List[Dict[str, str]] = []
        normalized_rows: List[Dict[str, str]] = []
        for uid_literature, authors in rows:
            raw_authors = _split_author_values(authors)
            normalized_names: List[str] = []
            for raw_name in raw_authors:
                resolved = name_map.get(raw_name)
                if not isinstance(resolved, dict):
                    if bool(payload.get("allow_fallback_cleaning", False)):
                        resolved = _fallback_normalize_name(raw_name)
                    else:
                        raise RuntimeError(f"作者姓名未返回 LLM 结果：{raw_name}")
                normalized_display_name = str(resolved.get("normalized_display_name") or raw_name).strip() or raw_name
                normalized_names.append(normalized_display_name)

            normalized_authors = " and ".join(normalized_names)
            normalized_first_author = normalized_names[0] if normalized_names else ""
            raw_authors_text = str(authors or "")
            if normalized_authors != raw_authors_text:
                changed_rows.append(
                    {
                        "uid_literature": str(uid_literature),
                        "before_authors": raw_authors_text,
                        "after_authors": normalized_authors,
                        "before_first_author": "",
                        "after_first_author": normalized_first_author,
                    }
                )
            normalized_rows.append(
                {
                    "uid_literature": str(uid_literature),
                    "authors": normalized_authors,
                    "first_author": normalized_first_author,
                }
            )
            update_rows.append((normalized_authors, normalized_first_author, str(uid_literature),))

        conn.executemany(
            f"UPDATE {_quote_identifier(LITERATURE_TABLE_NAME)} SET {_quote_identifier(authors_column)} = ?, {_quote_identifier(first_author_column)} = ?, {_quote_identifier(updated_column)} = CURRENT_TIMESTAMP WHERE {_quote_identifier(uid_column)} = ?",
            update_rows,
        )
        conn.commit()

    sync_author_entities_from_literature_rows(
        db_path,
        pd.DataFrame(normalized_rows),
        replace_link_scope=[row["uid_literature"] for row in normalized_rows],
    )

    return {
        "status": "PASS",
        "content_db": str(db_path),
        "literature_total": len(rows),
        "changed_literature_count": len(changed_rows),
        "llm_success_batches": int(preprocess_result.get("llm_success_batches") or 0),
        "llm_failed_batches": int(preprocess_result.get("llm_failed_batches") or 0),
        "sample_changes": changed_rows[:sample_limit],
        "preprocess_summary": {
            "input_count": int(preprocess_result.get("input_count") or 0),
            "unique_input_count": int(preprocess_result.get("unique_input_count") or 0),
        },
    }
