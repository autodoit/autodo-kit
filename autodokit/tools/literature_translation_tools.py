"""英文文献翻译工具集。

该模块提供三类翻译能力：
1. 文献元数据翻译（title/abstract/keywords）；
2. 标准文献笔记译读版生成；
3. 解析资产正文译文生成。

说明：
- 默认目标语言为中文（zh-CN）。
- 默认优先使用阿里百炼小模型；可回退到本地开源引擎。
- 所有翻译结果都通过 translation assets 索引登记，便于重跑和审计。
"""

from __future__ import annotations

import importlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

import pandas as pd

from autodokit.tools.bibliodb_sqlite import load_literatures_df, load_parse_assets_df
from autodokit.tools.contentdb_sqlite import (
    connect_sqlite,
    infer_workspace_root_from_content_db,
    resolve_content_db_path,
    upsert_knowledge_literature_link,
    upsert_translation_asset_rows,
)
from autodokit.tools.llm_clients import ModelRoutingIntent, invoke_aliyun_llm
from autodokit.tools.storage_backend import load_knowledge_tables, persist_knowledge_tables


DEFAULT_TRANSLATION_POLICY: Dict[str, Any] = {
    "enabled": True,
    "target_lang": "zh-CN",
    "engine_preference": ["aliyun_dashscope", "open_source_local", "manual"],
    "metadata": {
        "auto_translate": True,
        "provider": "aliyun_dashscope",
        "model": "qwen3.5-flash",
        "overwrite_existing": False,
        "max_items": 0,
    },
    "standard_note": {
        "auto_translate": True,
        "provider": "aliyun_dashscope",
        "model": "qwen3.5-plus",
        "overwrite_existing": False,
    },
    "parse_text": {
        "auto_translate": False,
        "provider": "aliyun_dashscope",
        "model": "qwen3.5-plus",
        "overwrite_existing": False,
        "max_chars_per_chunk": 4000,
    },
}


def _now_iso() -> str:
    """返回当前时间字符串。"""

    return datetime.now().isoformat(timespec="seconds")


def _safe_file_stem(text: str) -> str:
    """把任意字符串转为可用文件名片段。"""

    raw = str(text or "").strip()
    if not raw:
        return "untitled"
    return "".join(character if character not in "\\/:*?\"<>|" else "_" for character in raw)


def _has_cjk(text: str) -> bool:
    """检测文本是否含 CJK 字符。"""

    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _looks_like_english(text: str) -> bool:
    """粗粒度判断文本是否为英文。"""

    candidate = str(text or "")
    letters = re.findall(r"[A-Za-z]", candidate)
    if len(letters) < 8:
        return False
    if _has_cjk(candidate):
        return False
    non_space = re.sub(r"\s+", "", candidate)
    if not non_space:
        return False
    return (len(letters) / max(1, len(non_space))) >= 0.35


def _merge_policy(policy: Dict[str, Any] | None) -> Dict[str, Any]:
    """合并用户策略与默认翻译策略。"""

    merged = json.loads(json.dumps(DEFAULT_TRANSLATION_POLICY))
    incoming = policy or {}
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def _resolve_workspace_root(content_db: Path, workspace_root: str | Path | None) -> Path:
    """解析工作区根路径。"""

    if workspace_root:
        return Path(workspace_root).resolve()
    return infer_workspace_root_from_content_db(content_db)


def _split_text(text: str, max_chars: int) -> List[str]:
    """按段落切分长文本。"""

    source = str(text or "")
    if not source:
        return []
    if len(source) <= max_chars:
        return [source]

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for block in source.split("\n\n"):
        block_text = block.strip()
        if not block_text:
            continue
        extra = len(block_text) + (2 if current else 0)
        if current and current_len + extra > max_chars:
            chunks.append("\n\n".join(current))
            current = [block_text]
            current_len = len(block_text)
            continue
        current.append(block_text)
        current_len += extra

    if current:
        chunks.append("\n\n".join(current))

    if not chunks:
        chunks = [source[index : index + max_chars] for index in range(0, len(source), max_chars)]
    return chunks


def _translate_with_open_source_local(text: str, source_lang: str, target_lang: str) -> Dict[str, Any]:
    """尝试使用本地开源引擎翻译。"""

    try:
        import argostranslate.translate as argos_translate  # type: ignore
    except Exception as exc:
        return {"status": "FAIL", "error": f"open_source_local 未安装: {exc}", "text": "", "provider": "open_source_local", "model": ""}

    source_code = source_lang.split("-")[0]
    target_code = target_lang.split("-")[0]
    try:
        installed = argos_translate.get_installed_languages()
        from_lang = next((item for item in installed if item.code == source_code), None)
        to_lang = next((item for item in installed if item.code == target_code), None)
        if from_lang is None or to_lang is None:
            return {
                "status": "FAIL",
                "error": f"open_source_local 缺少语言包: {source_code}->{target_code}",
                "text": "",
                "provider": "open_source_local",
                "model": "argos_translate",
            }
        translation = from_lang.get_translation(to_lang)
        output = translation.translate(text)
        return {"status": "PASS", "error": "", "text": str(output or "").strip(), "provider": "open_source_local", "model": "argos_translate"}
    except Exception as exc:
        return {"status": "FAIL", "error": str(exc), "text": "", "provider": "open_source_local", "model": "argos_translate"}


def _translate_with_aliyun(
    *,
    text: str,
    source_lang: str,
    target_lang: str,
    model: str,
    quality_tier: str,
    budget_tier: str,
    affair_name: str,
    config_path: str | Path | None,
) -> Dict[str, Any]:
    """通过阿里百炼路由器执行翻译。"""

    prompt = (
        "你是学术翻译助手。\n"
        f"请把以下{source_lang}文本翻译为{target_lang}。\n"
        "要求：\n"
        "1) 保持学术术语准确；\n"
        "2) 不补充原文不存在的结论；\n"
        "3) 只输出译文正文，不要解释。\n\n"
        "待翻译文本：\n"
        f"{text}"
    )
    intent = ModelRoutingIntent(
        task_type="long_text" if len(text) > 1500 else "general",
        quality_tier=quality_tier if quality_tier in {"standard", "high", "max"} else "high",
        budget_tier=budget_tier if budget_tier in {"cheap", "balanced", "premium"} else "balanced",
        affair_name=affair_name,
        input_chars=len(text),
    )
    result = invoke_aliyun_llm(
        prompt=prompt,
        system="你是严谨的学术文本中译助手。",
        intent=intent,
        config_path=config_path,
        affair_name=affair_name,
        route_hints={"task_type": intent.task_type, "budget_tier": intent.budget_tier, "input_chars": intent.input_chars},
        temperature=0.1,
        max_tokens=4096,
    )
    if str(result.get("status") or "").upper() != "PASS":
        return {
            "status": "FAIL",
            "error": str(result.get("error") or "aliyun_llm_failed"),
            "text": "",
            "provider": "aliyun_dashscope",
            "model": model,
        }
    response = result.get("response") or {}
    text_out = str(response.get("text") or "").strip()
    return {
        "status": "PASS" if text_out else "FAIL",
        "error": "" if text_out else "empty_translation",
        "text": text_out,
        "provider": "aliyun_dashscope",
        "model": str(response.get("llm_model") or model or ""),
    }


def _translate_text(
    *,
    text: str,
    source_lang: str,
    target_lang: str,
    engine_preference: Sequence[str],
    model: str,
    quality_tier: str,
    budget_tier: str,
    affair_name: str,
    config_path: str | Path | None,
) -> Dict[str, Any]:
    """按引擎优先级翻译文本。"""

    cleaned = str(text or "").strip()
    if not cleaned:
        return {"status": "SKIP", "error": "empty_input", "text": "", "provider": "", "model": ""}

    errors: List[str] = []
    for engine in engine_preference:
        name = str(engine or "").strip().lower()
        if name in {"", "manual"}:
            errors.append("manual_required")
            continue
        if name == "open_source_local":
            attempt = _translate_with_open_source_local(cleaned, source_lang, target_lang)
        else:
            attempt = _translate_with_aliyun(
                text=cleaned,
                source_lang=source_lang,
                target_lang=target_lang,
                model=model,
                quality_tier=quality_tier,
                budget_tier=budget_tier,
                affair_name=affair_name,
                config_path=config_path,
            )
        if attempt.get("status") == "PASS":
            return attempt
        errors.append(str(attempt.get("error") or "unknown_error"))

    return {
        "status": "FAIL",
        "error": " | ".join([item for item in errors if item]) or "all_engines_failed",
        "text": "",
        "provider": "",
        "model": "",
    }


def _get_knowledge_note_tools() -> Dict[str, Any]:
    """延迟加载知识笔记工具，避免循环导入。"""

    tools_module = importlib.import_module("autodokit.tools")
    return {
        "knowledge_note_register": getattr(tools_module, "knowledge_note_register"),
        "knowledge_index_sync_from_note": getattr(tools_module, "knowledge_index_sync_from_note"),
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> Path:
    """写 JSON 文件并返回路径。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _resolve_config_path(workspace_root: Path, config_path: str | Path | None) -> Path:
    """解析 config.json 路径。"""

    if config_path:
        return Path(config_path).resolve()
    return workspace_root / "config" / "config.json"


def _update_literature_translation_fields(
    *,
    content_db: Path,
    uid_literature: str,
    source_lang: str,
    title_zh: str,
    abstract_zh: str,
    keywords_zh: str,
    status: str,
    provider: str,
    model: str,
) -> None:
    """写回 literatures 的元数据译文字段。"""

    now = _now_iso()
    with connect_sqlite(content_db) as conn:
        conn.execute(
            """
            UPDATE literatures
            SET source_lang = ?,
                title_zh = ?,
                abstract_zh = ?,
                keywords_zh = ?,
                metadata_translation_status = ?,
                metadata_translation_provider = ?,
                metadata_translation_model = ?,
                metadata_translation_updated_at = ?,
                updated_at = ?
            WHERE uid_literature = ?
            """,
            (
                source_lang,
                title_zh,
                abstract_zh,
                keywords_zh,
                status,
                provider,
                model,
                now,
                now,
                uid_literature,
            ),
        )
        conn.commit()


def translate_literature_metadata(
    *,
    content_db: str | Path,
    translation_policy: Dict[str, Any] | None = None,
    workspace_root: str | Path | None = None,
    max_items: int = 0,
    affair_name: str = "A020",
    config_path: str | Path | None = None,
) -> Dict[str, Any]:
    """翻译英文文献元数据。"""

    policy = _merge_policy(translation_policy)
    metadata_cfg = policy.get("metadata") or {}
    if not bool(policy.get("enabled", True)) or not bool(metadata_cfg.get("auto_translate", True)):
        return {"status": "SKIP", "translated_count": 0, "failed_count": 0, "audit_path": "", "reason": "metadata_auto_translate_disabled"}

    resolved_content_db = resolve_content_db_path(content_db)
    resolved_workspace_root = _resolve_workspace_root(resolved_content_db, workspace_root)
    resolved_config_path = _resolve_config_path(resolved_workspace_root, config_path)

    table = load_literatures_df(resolved_content_db).fillna("")
    if table.empty:
        return {"status": "SKIP", "translated_count": 0, "failed_count": 0, "audit_path": "", "reason": "empty_literatures"}

    expected_cols = ["source_lang", "title_zh", "abstract_zh", "keywords_zh"]
    for column in expected_cols:
        if column not in table.columns:
            table[column] = ""

    translated = 0
    failed = 0
    details: List[Dict[str, Any]] = []

    limit = int(max_items or metadata_cfg.get("max_items") or 0)
    engine_preference = policy.get("engine_preference") or [metadata_cfg.get("provider") or "aliyun_dashscope"]
    model_name = str(metadata_cfg.get("model") or "qwen3.5-flash")
    overwrite_existing = bool(metadata_cfg.get("overwrite_existing", False))

    for _, row in table.iterrows():
        uid_literature = str(row.get("uid_literature") or "").strip()
        if not uid_literature:
            continue

        title = str(row.get("title") or "").strip()
        abstract = str(row.get("abstract") or "").strip()
        keywords = str(row.get("keywords") or "").strip()

        source_lang = str(row.get("source_lang") or "").strip().lower()
        if source_lang not in {"en", "zh", "zh-cn"}:
            probe_text = "\n".join([title, abstract, keywords])
            source_lang = "en" if _looks_like_english(probe_text) else ("zh" if _has_cjk(probe_text) else "unknown")

        if source_lang != "en":
            continue

        current_title_zh = str(row.get("title_zh") or "").strip()
        current_abstract_zh = str(row.get("abstract_zh") or "").strip()
        current_keywords_zh = str(row.get("keywords_zh") or "").strip()

        need_title = bool(title) and (overwrite_existing or not current_title_zh)
        need_abstract = bool(abstract) and (overwrite_existing or not current_abstract_zh)
        need_keywords = bool(keywords) and (overwrite_existing or not current_keywords_zh)
        if not (need_title or need_abstract or need_keywords):
            continue

        if limit > 0 and translated + failed >= limit:
            break

        provider_used = ""
        model_used = ""
        local_failures: List[str] = []
        title_zh = current_title_zh
        abstract_zh = current_abstract_zh
        keywords_zh = current_keywords_zh

        if need_title:
            title_result = _translate_text(
                text=title,
                source_lang="en",
                target_lang=str(policy.get("target_lang") or "zh-CN"),
                engine_preference=engine_preference,
                model=model_name,
                quality_tier="high",
                budget_tier="cheap",
                affair_name=affair_name,
                config_path=resolved_config_path,
            )
            if title_result.get("status") == "PASS":
                title_zh = str(title_result.get("text") or "").strip()
                provider_used = provider_used or str(title_result.get("provider") or "")
                model_used = model_used or str(title_result.get("model") or "")
            else:
                local_failures.append(f"title: {title_result.get('error')}")

        if need_abstract:
            abstract_result = _translate_text(
                text=abstract,
                source_lang="en",
                target_lang=str(policy.get("target_lang") or "zh-CN"),
                engine_preference=engine_preference,
                model=model_name,
                quality_tier="high",
                budget_tier="balanced",
                affair_name=affair_name,
                config_path=resolved_config_path,
            )
            if abstract_result.get("status") == "PASS":
                abstract_zh = str(abstract_result.get("text") or "").strip()
                provider_used = provider_used or str(abstract_result.get("provider") or "")
                model_used = model_used or str(abstract_result.get("model") or "")
            else:
                local_failures.append(f"abstract: {abstract_result.get('error')}")

        if need_keywords:
            keywords_result = _translate_text(
                text=keywords,
                source_lang="en",
                target_lang=str(policy.get("target_lang") or "zh-CN"),
                engine_preference=engine_preference,
                model=model_name,
                quality_tier="standard",
                budget_tier="cheap",
                affair_name=affair_name,
                config_path=resolved_config_path,
            )
            if keywords_result.get("status") == "PASS":
                keywords_zh = str(keywords_result.get("text") or "").strip()
                provider_used = provider_used or str(keywords_result.get("provider") or "")
                model_used = model_used or str(keywords_result.get("model") or "")
            else:
                local_failures.append(f"keywords: {keywords_result.get('error')}")

        if local_failures and not (title_zh or abstract_zh or keywords_zh):
            failed += 1
            status = "failed"
        elif local_failures:
            translated += 1
            status = "partial_failed"
        else:
            translated += 1
            status = "ready"

        _update_literature_translation_fields(
            content_db=resolved_content_db,
            uid_literature=uid_literature,
            source_lang="en",
            title_zh=title_zh,
            abstract_zh=abstract_zh,
            keywords_zh=keywords_zh,
            status=status,
            provider=provider_used,
            model=model_used,
        )

        details.append(
            {
                "uid_literature": uid_literature,
                "cite_key": str(row.get("cite_key") or "").strip(),
                "status": status,
                "provider": provider_used,
                "model": model_used,
                "errors": local_failures,
            }
        )

    audit_dir = resolved_workspace_root / "logs" / "translations"
    audit_path = audit_dir / f"metadata_translation_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
    audit_payload = {
        "scope": "metadata",
        "translated_count": translated,
        "failed_count": failed,
        "details": details,
        "created_at": _now_iso(),
    }
    _write_json(audit_path, audit_payload)

    if details:
        translation_rows = [
            {
                "translation_uid": f"tr-meta-{item['uid_literature']}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "uid_literature": item["uid_literature"],
                "cite_key": item["cite_key"],
                "source_asset_uid": "",
                "source_kind": "metadata",
                "target_lang": str(policy.get("target_lang") or "zh-CN"),
                "translation_scope": "metadata",
                "provider": item.get("provider") or "",
                "model_name": item.get("model") or "",
                "asset_dir": "",
                "translated_markdown_path": "",
                "translated_structured_path": "",
                "translation_audit_path": str(audit_path),
                "status": item.get("status") or "ready",
                "is_current": 1,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            for item in details
        ]
        upsert_translation_asset_rows(resolved_content_db, translation_rows)

    return {
        "status": "PASS",
        "translated_count": translated,
        "failed_count": failed,
        "audit_path": str(audit_path),
    }


def translate_standard_note(
    *,
    content_db: str | Path,
    uid_literature: str,
    cite_key: str,
    source_note_path: str | Path,
    translation_policy: Dict[str, Any] | None = None,
    workspace_root: str | Path | None = None,
    affair_name: str = "A105",
    config_path: str | Path | None = None,
) -> Dict[str, Any]:
    """生成标准文献笔记译读版。"""

    policy = _merge_policy(translation_policy)
    standard_cfg = policy.get("standard_note") or {}
    if not bool(policy.get("enabled", True)) or not bool(standard_cfg.get("auto_translate", True)):
        return {"status": "SKIP", "reason": "standard_note_auto_translate_disabled", "translated_note_path": ""}

    resolved_content_db = resolve_content_db_path(content_db)
    resolved_workspace_root = _resolve_workspace_root(resolved_content_db, workspace_root)
    resolved_config_path = _resolve_config_path(resolved_workspace_root, config_path)
    source_path = Path(source_note_path).resolve()
    if not source_path.exists():
        return {"status": "FAIL", "reason": f"source_note_not_found: {source_path}", "translated_note_path": ""}

    source_text = source_path.read_text(encoding="utf-8-sig")
    if not _looks_like_english(source_text):
        return {"status": "SKIP", "reason": "source_note_not_english", "translated_note_path": ""}

    engine_preference = policy.get("engine_preference") or [standard_cfg.get("provider") or "aliyun_dashscope"]
    model_name = str(standard_cfg.get("model") or "qwen3.5-plus")
    translation_result = _translate_text(
        text=source_text,
        source_lang="en",
        target_lang=str(policy.get("target_lang") or "zh-CN"),
        engine_preference=engine_preference,
        model=model_name,
        quality_tier="high",
        budget_tier="balanced",
        affair_name=affair_name,
        config_path=resolved_config_path,
    )
    if translation_result.get("status") != "PASS":
        return {"status": "FAIL", "reason": str(translation_result.get("error") or "translate_failed"), "translated_note_path": ""}

    translated_dir = resolved_workspace_root / "knowledge" / "translations" / "standard_notes" / str(policy.get("target_lang") or "zh-CN")
    translated_dir.mkdir(parents=True, exist_ok=True)
    translated_note_path = translated_dir / f"{_safe_file_stem(cite_key)}.md"

    translated_body = str(translation_result.get("text") or "").strip()
    translated_note_path.write_text(translated_body, encoding="utf-8")

    tools = _get_knowledge_note_tools()
    knowledge_note_register = tools["knowledge_note_register"]
    knowledge_index_sync_from_note = tools["knowledge_index_sync_from_note"]

    knowledge_index_df, knowledge_attachments_df, _ = load_knowledge_tables(db_path=resolved_content_db)
    note_info = knowledge_note_register(
        note_path=translated_note_path,
        title=f"{cite_key}（中文译读）",
        note_type="literature_standard_note_translation",
        status="draft",
        tags=["aok/translation", "aok/standard_note_translation"],
        aliases=[cite_key],
        evidence_uids=[uid_literature],
        uid_literature=uid_literature,
        cite_key=cite_key,
        body=translated_body,
    )
    knowledge_index_df, _ = knowledge_index_sync_from_note(knowledge_index_df, translated_note_path, workspace_root=resolved_workspace_root)
    persist_knowledge_tables(index_df=knowledge_index_df, attachments_df=knowledge_attachments_df, db_path=resolved_content_db)
    upsert_knowledge_literature_link(
        resolved_content_db,
        uid_knowledge=str(note_info.get("uid_knowledge") or "").strip(),
        uid_literature=uid_literature,
        relation_type="standard_note_translation",
        is_primary=0,
        cite_key=cite_key,
        source_field="literature_translation_tools.standard_note",
    )

    audit_dir = resolved_workspace_root / "logs" / "translations"
    audit_path = audit_dir / f"standard_note_translation_{_safe_file_stem(cite_key)}_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
    _write_json(
        audit_path,
        {
            "scope": "standard_note",
            "uid_literature": uid_literature,
            "cite_key": cite_key,
            "source_note_path": str(source_path),
            "translated_note_path": str(translated_note_path),
            "provider": str(translation_result.get("provider") or ""),
            "model": str(translation_result.get("model") or ""),
            "status": "ready",
            "created_at": _now_iso(),
        },
    )

    upsert_translation_asset_rows(
        resolved_content_db,
        [
            {
                "translation_uid": f"tr-note-{uid_literature}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "source_asset_uid": "",
                "source_kind": "standard_note",
                "target_lang": str(policy.get("target_lang") or "zh-CN"),
                "translation_scope": "standard_note_full",
                "provider": str(translation_result.get("provider") or ""),
                "model_name": str(translation_result.get("model") or ""),
                "asset_dir": str(translated_dir),
                "translated_markdown_path": str(translated_note_path),
                "translated_structured_path": "",
                "translation_audit_path": str(audit_path),
                "status": "ready",
                "is_current": 1,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        ],
    )

    return {
        "status": "PASS",
        "translated_note_path": str(translated_note_path),
        "audit_path": str(audit_path),
        "provider": str(translation_result.get("provider") or ""),
        "model": str(translation_result.get("model") or ""),
    }


def translate_parse_asset_text(
    *,
    content_db: str | Path,
    uid_literature: str,
    cite_key: str,
    parse_level: str = "non_review_deep",
    translation_policy: Dict[str, Any] | None = None,
    workspace_root: str | Path | None = None,
    affair_name: str = "A100",
    config_path: str | Path | None = None,
) -> Dict[str, Any]:
    """生成解析正文译文资产。"""

    policy = _merge_policy(translation_policy)
    parse_cfg = policy.get("parse_text") or {}
    if not bool(policy.get("enabled", True)) or not bool(parse_cfg.get("auto_translate", False)):
        return {
            "status": "SKIP",
            "reason": "parse_text_auto_translate_disabled",
            "translated_markdown_path": "",
            "translated_structured_path": "",
        }

    resolved_content_db = resolve_content_db_path(content_db)
    resolved_workspace_root = _resolve_workspace_root(resolved_content_db, workspace_root)
    resolved_config_path = _resolve_config_path(resolved_workspace_root, config_path)

    parse_assets = load_parse_assets_df(resolved_content_db, parse_level=parse_level, only_current=True).fillna("")
    if parse_assets.empty:
        return {"status": "FAIL", "reason": "parse_asset_not_found", "translated_markdown_path": "", "translated_structured_path": ""}

    selected = parse_assets[
        (parse_assets.get("uid_literature", pd.Series(dtype=str)).astype(str) == str(uid_literature))
        | (parse_assets.get("cite_key", pd.Series(dtype=str)).astype(str) == str(cite_key))
    ]
    if selected.empty:
        return {"status": "FAIL", "reason": "parse_asset_not_found_for_literature", "translated_markdown_path": "", "translated_structured_path": ""}

    row = selected.iloc[0]
    source_asset_uid = str(row.get("asset_uid") or "").strip()
    asset_dir = Path(str(row.get("asset_dir") or "").strip())
    reconstructed_path = Path(str(row.get("reconstructed_markdown_path") or "").strip())
    normalized_path = Path(str(row.get("normalized_structured_path") or "").strip())

    source_text = ""
    if reconstructed_path.exists() and reconstructed_path.is_file():
        source_text = reconstructed_path.read_text(encoding="utf-8-sig")
    elif normalized_path.exists() and normalized_path.is_file():
        payload = json.loads(normalized_path.read_text(encoding="utf-8-sig"))
        source_text = str(((payload.get("text") or {}).get("full_text") or "")).strip()

    if not source_text.strip():
        return {"status": "FAIL", "reason": "empty_parse_text", "translated_markdown_path": "", "translated_structured_path": ""}

    if not _looks_like_english(source_text[:4000]):
        return {"status": "SKIP", "reason": "parse_text_not_english", "translated_markdown_path": "", "translated_structured_path": ""}

    target_lang = str(policy.get("target_lang") or "zh-CN")
    max_chars = int(parse_cfg.get("max_chars_per_chunk") or 4000)
    chunks = _split_text(source_text, max_chars=max_chars)

    engine_preference = policy.get("engine_preference") or [parse_cfg.get("provider") or "aliyun_dashscope"]
    model_name = str(parse_cfg.get("model") or "qwen3.5-plus")

    translated_chunks: List[str] = []
    errors: List[str] = []
    provider_used = ""
    model_used = ""
    for chunk in chunks:
        chunk_result = _translate_text(
            text=chunk,
            source_lang="en",
            target_lang=target_lang,
            engine_preference=engine_preference,
            model=model_name,
            quality_tier="high",
            budget_tier="balanced",
            affair_name=affair_name,
            config_path=resolved_config_path,
        )
        if chunk_result.get("status") != "PASS":
            errors.append(str(chunk_result.get("error") or "chunk_translate_failed"))
            continue
        translated_chunks.append(str(chunk_result.get("text") or ""))
        provider_used = provider_used or str(chunk_result.get("provider") or "")
        model_used = model_used or str(chunk_result.get("model") or "")

    if not translated_chunks:
        return {
            "status": "FAIL",
            "reason": " | ".join([item for item in errors if item]) or "all_chunks_failed",
            "translated_markdown_path": "",
            "translated_structured_path": "",
        }

    translated_text = "\n\n".join(translated_chunks).strip()
    translation_dir = (asset_dir / "translations" / target_lang).resolve()
    translation_dir.mkdir(parents=True, exist_ok=True)

    translated_markdown_path = translation_dir / "translated_markdown.md"
    translated_markdown_path.write_text(translated_text, encoding="utf-8")

    translated_structured_path = Path()
    if normalized_path.exists() and normalized_path.is_file():
        payload = json.loads(normalized_path.read_text(encoding="utf-8-sig"))
        text_block = payload.get("text") or {}
        if isinstance(text_block, dict):
            text_block["full_text"] = translated_text
            payload["text"] = text_block
        metadata = payload.get("metadata") or {}
        if isinstance(metadata, dict):
            metadata["translation"] = {
                "target_lang": target_lang,
                "source_lang": "en",
                "provider": provider_used,
                "model": model_used,
                "created_at": _now_iso(),
            }
            payload["metadata"] = metadata
        translated_structured_path = translation_dir / "translated_structured.json"
        translated_structured_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    audit_path = translation_dir / "translation_audit.json"
    _write_json(
        audit_path,
        {
            "scope": "parse_text",
            "uid_literature": uid_literature,
            "cite_key": cite_key,
            "source_asset_uid": source_asset_uid,
            "source_markdown_path": str(reconstructed_path),
            "source_structured_path": str(normalized_path),
            "translated_markdown_path": str(translated_markdown_path),
            "translated_structured_path": str(translated_structured_path) if translated_structured_path else "",
            "provider": provider_used,
            "model": model_used,
            "chunk_count": len(chunks),
            "translated_chunk_count": len(translated_chunks),
            "errors": errors,
            "created_at": _now_iso(),
        },
    )

    upsert_translation_asset_rows(
        resolved_content_db,
        [
            {
                "translation_uid": f"tr-parse-{uid_literature}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "uid_literature": uid_literature,
                "cite_key": cite_key,
                "source_asset_uid": source_asset_uid,
                "source_kind": "parse_text",
                "target_lang": target_lang,
                "translation_scope": "parse_markdown_full",
                "provider": provider_used,
                "model_name": model_used,
                "asset_dir": str(translation_dir),
                "translated_markdown_path": str(translated_markdown_path),
                "translated_structured_path": str(translated_structured_path) if translated_structured_path else "",
                "translation_audit_path": str(audit_path),
                "status": "ready" if not errors else "partial_failed",
                "is_current": 1,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        ],
    )

    return {
        "status": "PASS" if not errors else "PARTIAL",
        "translated_markdown_path": str(translated_markdown_path),
        "translated_structured_path": str(translated_structured_path) if translated_structured_path else "",
        "audit_path": str(audit_path),
        "provider": provider_used,
        "model": model_used,
        "error": " | ".join([item for item in errors if item]),
    }


def run_literature_translation(
    *,
    content_db: str | Path,
    translation_scope: str,
    translation_policy: Dict[str, Any] | None = None,
    workspace_root: str | Path | None = None,
    uid_literature: str = "",
    cite_key: str = "",
    source_note_path: str | Path | None = None,
    parse_level: str = "non_review_deep",
    max_items: int = 0,
    affair_name: str = "manual_translation",
    config_path: str | Path | None = None,
) -> Dict[str, Any]:
    """统一翻译调度入口。"""

    normalized_scope = str(translation_scope or "").strip().lower()
    if normalized_scope == "metadata":
        return translate_literature_metadata(
            content_db=content_db,
            translation_policy=translation_policy,
            workspace_root=workspace_root,
            max_items=max_items,
            affair_name=affair_name,
            config_path=config_path,
        )

    if normalized_scope == "standard_note":
        if not (uid_literature or cite_key):
            return {"status": "FAIL", "reason": "uid_literature_or_cite_key_required", "translated_note_path": ""}
        resolved_content_db = resolve_content_db_path(content_db)
        table = load_literatures_df(resolved_content_db).fillna("")
        matched = table[
            (table.get("uid_literature", pd.Series(dtype=str)).astype(str) == str(uid_literature))
            | (table.get("cite_key", pd.Series(dtype=str)).astype(str) == str(cite_key))
        ]
        if matched.empty:
            return {"status": "FAIL", "reason": "literature_not_found", "translated_note_path": ""}
        row = matched.iloc[0]
        resolved_uid = str(row.get("uid_literature") or uid_literature or "").strip()
        resolved_cite = str(row.get("cite_key") or cite_key or resolved_uid).strip()

        note_path = Path(source_note_path).resolve() if source_note_path else Path(str((workspace_root or _resolve_workspace_root(resolved_content_db, None)))).resolve() / "knowledge" / "standard_notes" / f"{_safe_file_stem(resolved_cite)}.md"
        return translate_standard_note(
            content_db=resolved_content_db,
            uid_literature=resolved_uid,
            cite_key=resolved_cite,
            source_note_path=note_path,
            translation_policy=translation_policy,
            workspace_root=workspace_root,
            affair_name=affair_name,
            config_path=config_path,
        )

    if normalized_scope == "parse_text":
        if not (uid_literature or cite_key):
            return {"status": "FAIL", "reason": "uid_literature_or_cite_key_required", "translated_markdown_path": ""}
        return translate_parse_asset_text(
            content_db=content_db,
            uid_literature=uid_literature,
            cite_key=cite_key,
            parse_level=parse_level,
            translation_policy=translation_policy,
            workspace_root=workspace_root,
            affair_name=affair_name,
            config_path=config_path,
        )

    return {"status": "FAIL", "reason": f"unsupported_translation_scope: {translation_scope}"}


__all__ = [
    "DEFAULT_TRANSLATION_POLICY",
    "translate_literature_metadata",
    "translate_standard_note",
    "translate_parse_asset_text",
    "run_literature_translation",
]
