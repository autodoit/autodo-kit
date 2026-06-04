"""统一内容主库 SQLite 适配层。

该模块为 AOK 内容层提供统一物理主库能力：
1. 将旧的 `references.db` / `knowledge.db` 路径统一解析到 `content.db`。
2. 初始化文献域、知识域和跨域关系表。
3. 提供关系表回填与兼容字段同步能力。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import sqlite3
from typing import Mapping, Sequence

import pandas as pd

from autodokit.path_compat import resolve_portable_path
from autodokit.tools.time_utils import now_iso


DEFAULT_CONTENT_DB_NAME = "content.db"
CONTENT_DB_DIRECTORY_NAME = "content"
LITERATURE_TABLE_NAME = "文献主表"
ATTACHMENT_TABLE_NAME = "附件表"
ATTACHMENT_LINK_TABLE_NAME = "文献附件关联"
TAG_TABLE_NAME = "标签表"
LITERATURE_TAG_TABLE_NAME = "文献标签关联"
AUTHOR_TABLE_NAME = "作者表"
AUTHOR_LINK_TABLE_NAME = "文献作者关联"
PARSE_ASSET_TABLE_NAME = "文献解析资产"
TRANSLATION_ASSET_TABLE_NAME = "文献翻译资产"
TRANSLATION_ASSET_STORAGE_TABLE_NAME = "content_translation_assets_storage"
CHUNK_SET_TABLE_NAME = "文献分块集"
CHUNK_TABLE_NAME = "文献分块"
KNOWLEDGE_INDEX_TABLE_NAME = "知识索引"
KNOWLEDGE_ATTACHMENT_TABLE_NAME = "知识附件"
KNOWLEDGE_LINK_TABLE_NAME = "知识文献关联"
KNOWLEDGE_EVIDENCE_TABLE_NAME = "知识证据关联"
KNOWLEDGE_NOTES_TABLE_NAME = "知识笔记"
READING_STATE_TABLE_NAME = "文献阅读状态"
WORKSPACE_NODE_STATE_TABLE_NAME = "工作区节点状态"
REVIEW_STATE_TABLE_NAME = "综述文献阅读状态"
FLOW_STATE_TABLE_NAME = "文献流程状态"
READING_QUEUE_TABLE_NAME = "文献预处理"
FLOW_STATE_OVERVIEW_VIEW_NAME = "文献流程状态总视图"
WORKSPACE_NODE_OVERVIEW_VIEW_NAME = "工作区节点状态总视图"
WORKSPACE_NODE_FILTER_VIEWS: tuple[tuple[str, str], ...] = (
    ("待执行节点清单", "IFNULL(待执行, 0) = 1"),
    ("执行中节点清单", "IFNULL(执行中, 0) = 1"),
    ("已完成节点清单", "IFNULL(已完成, 0) = 1"),
    ("闸门待处理节点清单", "IFNULL(闸门状态, '') IN ('retry_current', 'fallback_current', 'pause_current', 'stop_workflow')"),
    ("失败待重试节点清单", "IFNULL(失败原因, '') <> ''"),
)
FLOW_STATE_FILTER_VIEWS: tuple[tuple[str, str], ...] = (
    ("待处理文献流程清单", "IFNULL(当前状态, '') = '待处理'"),
    ("处理中文献流程清单", "IFNULL(当前状态, '') = '处理中'"),
    ("失败文献流程清单", "IFNULL(当前状态, '') = '失败'"),
    ("阻塞文献流程清单", "IFNULL(当前状态, '') = '阻塞'"),
)
FLOW_STAGE_LIST_VIEWS: tuple[tuple[str, str], ...] = (
    ("待预处理文献清单", "IFNULL(当前阶段, '') = '普通文献预处理' AND IFNULL(当前状态, '') IN ('待处理', '阻塞')"),
    ("补件待办文献清单", "IFNULL(当前阶段, '') = '普通文献预处理' AND IFNULL(当前状态, '') = '阻塞'"),
    ("待泛读文献清单", "IFNULL(当前阶段, '') = '普通文献泛读' AND IFNULL(当前状态, '') = '待处理'"),
    ("待研读候选构建文献清单", "IFNULL(当前阶段, '') = '普通文献研读候选视图构建' AND IFNULL(当前状态, '') = '待处理'"),
    ("待批判性研读文献清单", "IFNULL(当前阶段, '') = '批判性研读' AND IFNULL(当前状态, '') = '待处理'"),
)
TRANSACTION_RELATION_OVERVIEW_VIEW_NAME = "事务关联总视图"
TRANSACTION_RELATION_NODE_LABELS: tuple[tuple[str, str], ...] = (
    ("A110", "综述文献候选视图构建"),
    ("A130", "综述文献研读"),
    ("A140", "普通文献候选视图构建"),
    ("A150", "普通文献泛读"),
    ("A160", "普通文献研读候选视图构建"),
    ("A170", "文献批判性研读"),
    ("A180", "研究脉络梳理"),
    ("A190", "创新点凝练"),
)
TRANSACTION_RELATION_FILTER_VIEWS: tuple[tuple[str, str], ...] = tuple(
    (f"{node_code}事务关联视图", node_code)
    for node_code, _ in TRANSACTION_RELATION_NODE_LABELS
)
LEGACY_TRANSACTION_RELATION_VIEW_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            "事务编号关联总视图",
            "A040事务关联视图",
            "A050事务关联视图",
            "A055事务关联视图",
            "A040事务编号关联视图",
            "A050事务编号关联视图",
            "A055事务编号关联视图",
            "A065事务编号关联视图",
            "A065事务关联视图",
            "A090事务编号关联视图",
            "A090事务关联视图",
            "A105事务编号关联视图",
            "A105事务关联视图",
            "A120事务编号关联视图",
            "A120事务关联视图",
            "A130事务编号关联视图",
            "A130事务关联视图",
            "A150事务编号关联视图",
            "A150事务关联视图",
            "A160事务编号关联视图",
            "A160事务关联视图",
            *[f"{node_code}事务编号关联视图" for node_code, _ in TRANSACTION_RELATION_NODE_LABELS],
        ]
    )
)
LITERATURE_PARSE_STATE_PENDING = "未完成"
LITERATURE_PARSE_STATE_RUNNING = "在运行"
LITERATURE_PARSE_STATE_COMPLETED = "已完成"


def normalize_literature_parse_state(value: object, *, fallback: str = LITERATURE_PARSE_STATE_PENDING) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    if text == LITERATURE_PARSE_STATE_COMPLETED or normalized in {"ready", "success", "succeeded", "successful", "completed", "done", "ok", "已处理", "完成", "成功"}:
        return LITERATURE_PARSE_STATE_COMPLETED
    if text == LITERATURE_PARSE_STATE_RUNNING or normalized in {"running", "in_progress", "processing", "处理中", "执行中", "进行中", "dispatching", "queued_remote"}:
        return LITERATURE_PARSE_STATE_RUNNING
    if text == LITERATURE_PARSE_STATE_PENDING or normalized in {"", "pending", "queued", "failed", "error", "blocked", "missing_attachment", "未处理", "处理失败", "失败", "阻塞", "需补件"}:
        return LITERATURE_PARSE_STATE_PENDING
    return fallback


def derive_literature_parse_state(
    *,
    parse_state: object = "",
    current_parse_status: object = "",
    structured_status: object = "",
    preprocess_state: object = "",
    has_parse_result: bool = False,
) -> str:
    explicit_state = normalize_literature_parse_state(parse_state, fallback="")
    if explicit_state:
        return explicit_state

    for candidate in (current_parse_status, structured_status, preprocess_state):
        if normalize_literature_parse_state(candidate, fallback="") == LITERATURE_PARSE_STATE_COMPLETED:
            return LITERATURE_PARSE_STATE_COMPLETED

    for candidate in (current_parse_status, structured_status, preprocess_state):
        if normalize_literature_parse_state(candidate, fallback="") == LITERATURE_PARSE_STATE_RUNNING:
            return LITERATURE_PARSE_STATE_RUNNING

    if has_parse_result:
        return LITERATURE_PARSE_STATE_COMPLETED
    return LITERATURE_PARSE_STATE_PENDING


CONTENTDB_CHINESE_CONTRACT_VIEWS: dict[str, tuple[str, dict[str, str]]] = {
    "文献主表": (
        LITERATURE_TABLE_NAME,
        {
            "id": "id",
            "uid_literature": "uid_literature",
            "cite_key": "cite_key",
            "title": "标题",
            "clean_title": "标题清洗",
            "title_norm": "标题标准化",
            "authors": "作者串",
            "first_author": "第一作者",
            "year": "年份",
            "entry_type": "entry_type",
            "abstract": "摘要",
            "keywords": "关键词",
            "pdf_path": "PDF路径",
            "is_placeholder": "是否占位",
            "placeholder_reason": "占位原因",
            "placeholder_status": "占位状态",
            "placeholder_run_uid": "placeholder_run_uid",
            "has_fulltext": "是否有全文",
            "primary_attachment_name": "主附件名称",
            "primary_attachment_source_path": "主附件源路径",
            "standard_note_uid": "standard_note_uid",
            "source_type": "来源类型",
            "origin_path": "来源路径",
            "created_at": "创建时间",
            "updated_at": "更新时间",
            "structured_status": "结构化状态",
            "structured_abs_path": "结构化正文路径",
            "structured_backend": "结构化后端",
            "structured_task_type": "结构化任务类型",
            "structured_updated_at": "结构化更新时间",
            "structured_schema_version": "结构化Schema版本",
            "structured_text_length": "结构化文本长度",
            "structured_reference_count": "结构化参考文献数",
            "文献语种": "文献语种",
            "title_zh": "标题译文",
            "abstract_zh": "摘要译文",
            "keywords_zh": "关键词译文",
            "metadata_translation_status": "元数据翻译状态",
            "metadata_translation_provider": "元数据翻译提供方",
            "metadata_translation_model": "元数据翻译模型",
            "metadata_translation_updated_at": "元数据翻译更新时间",
            "note": "备注",
            "parse_state": "解析状态",
            "literature_type": "文献类型",
            "pdf_rel_path": "PDF相对路径",
        },
    ),
    "附件表": (
        ATTACHMENT_TABLE_NAME,
        {
            "id": "id",
            "uid_attachment": "uid_attachment",
            "attachment_name": "附件名称",
            "attachment_type": "附件类型",
            "file_ext": "文件扩展名",
            "storage_path": "存储路径",
            "source_path": "来源路径",
            "附件来源类型": "附件来源类型",
            "来源事务": "来源事务",
            "checksum": "校验和",
            "status": "状态",
            "created_at": "创建时间",
            "updated_at": "更新时间",
            "path_rel": "相对路径",
        },
    ),
    "文献附件关联": (
        ATTACHMENT_LINK_TABLE_NAME,
        {
            "id": "id",
            "uid_attachment_link": "uid_attachment_link",
            "uid_literature": "uid_literature",
            "uid_attachment": "uid_attachment",
            "link_role": "关联角色",
            "is_primary": "是否主附件",
            "source_type": "来源类型",
            "legacy_uid_attachment": "legacy_uid_attachment",
            "created_at": "创建时间",
            "updated_at": "更新时间",
        },
    ),
    "作者表": (
        AUTHOR_TABLE_NAME,
        {
            "id": "id",
            "uid_author": "uid_author",
            "display_name": "显示姓名",
            "normalized_name": "规范姓名",
            "surname": "姓",
            "given_names": "名",
            "orcid": "研究者标识",
            "source_type": "来源类型",
            "created_at": "创建时间",
            "updated_at": "更新时间",
            "标准作者名": "标准作者名",
            "作者类型": "作者类型",
            "作者质量标记": "作者质量标记",
        },
    ),
    "文献作者关联": (
        AUTHOR_LINK_TABLE_NAME,
        {
            "id": "id",
            "uid_literature_author": "uid_literature_author",
            "uid_literature": "uid_literature",
            "uid_author": "uid_author",
            "author_order": "作者顺序",
            "is_first_author": "是否第一作者",
            "is_corresponding": "是否通讯作者",
            "display_name": "显示姓名",
            "source_type": "来源类型",
            "created_at": "创建时间",
            "updated_at": "更新时间",
        },
    ),
    "标签表": (
        TAG_TABLE_NAME,
        {
            "id": "id",
            "uid_tag": "uid_tag",
            "tag": "标签",
            "tag_norm": "标签规范名",
            "tag_display": "标签显示名",
            "tag_group": "标签分组",
            "created_at": "创建时间",
            "updated_at": "更新时间",
        },
    ),
    "文献标签关联": (
        LITERATURE_TAG_TABLE_NAME,
        {
            "id": "id",
            "uid_literature": "uid_literature",
            "cite_key": "cite_key",
            "tag": "标签",
            "tag_norm": "标签规范名",
            "source_type": "来源类型",
            "created_at": "创建时间",
            "updated_at": "更新时间",
        },
    ),
    "文献解析资产": (
        PARSE_ASSET_TABLE_NAME,
        {
            "id": "id",
            "asset_uid": "asset_uid",
            "uid_literature": "uid_literature",
            "cite_key": "cite_key",
            "uid_attachment": "uid_attachment",
            "parse_level": "解析层级",
            "backend": "解析后端",
            "model_name": "模型名称",
            "asset_dir": "资产目录",
            "normalized_structured_path": "结构化正文路径",
            "reconstructed_markdown_path": "重构Markdown路径",
            "linear_index_path": "线性索引路径",
            "elements_path": "元素路径",
            "chunks_jsonl_path": "分块JSONL路径",
            "parse_record_path": "解析记录路径",
            "quality_report_path": "质量报告路径",
            "parse_status": "解析状态",
            "last_run_uid": "last_run_uid",
            "is_current": "是否当前有效",
            "created_at": "创建时间",
            "updated_at": "更新时间",
        },
    ),
    "文献翻译资产": (
        TRANSLATION_ASSET_STORAGE_TABLE_NAME,
        {
            "id": "id",
            "translation_uid": "translation_uid",
            "uid_literature": "uid_literature",
            "cite_key": "cite_key",
            "source_asset_uid": "source_asset_uid",
            "source_kind": "来源类型",
            "target_lang": "目标语种",
            "translation_scope": "翻译范围",
            "provider": "提供方",
            "model_name": "模型名称",
            "asset_dir": "资产目录",
            "translated_markdown_path": "译文Markdown路径",
            "translated_structured_path": "译文结构化路径",
            "translation_audit_path": "翻译审计路径",
            "status": "状态",
            "is_current": "是否当前有效",
            "created_at": "创建时间",
            "updated_at": "更新时间",
        },
    ),
    "文献分块集": (
        CHUNK_SET_TABLE_NAME,
        {
            "id": "id",
            "chunks_uid": "chunks_uid",
            "source_scope": "来源范围",
            "chunks_abs_path": "分块绝对路径",
            "source_backend": "来源后端",
            "chunk_count": "分块数量",
            "source_doc_count": "来源文献数",
            "created_at": "创建时间",
            "status": "状态",
        },
    ),
    "文献分块": (
        CHUNK_TABLE_NAME,
        {
            "id": "id",
            "chunk_id": "chunk_id",
            "chunks_uid": "chunks_uid",
            "uid_literature": "uid_literature",
            "cite_key": "cite_key",
            "shard_abs_path": "分片路径",
            "chunk_index": "分块序号",
            "chunk_type": "分块类型",
            "char_start": "起始字符位",
            "char_end": "结束字符位",
            "text_length": "文本长度",
            "created_at": "创建时间",
        },
    ),
    "工作区节点状态": (
        WORKSPACE_NODE_STATE_TABLE_NAME,
        {
            "node_code": "节点编码",
            "node_name": "节点名称",
            "pending_run": "待执行",
            "in_progress": "执行中",
            "completed": "已完成",
            "gate_status": "闸门状态",
            "last_task_uid": "last_task_uid",
            "current_task_uid": "current_task_uid",
            "last_run_at": "最近执行时间",
            "completed_at": "完成时间",
            "summary": "摘要",
            "next_node_code": "下一节点编码",
            "failure_reason": "失败原因",
            "retry_count": "重试次数",
            "updated_at": "更新时间",
        },
    ),
    "知识笔记": (
        KNOWLEDGE_NOTES_TABLE_NAME,
        {
            "id": "id",
            "uid_note": "uid_note",
            "uid_literature": "uid_literature",
            "cite_key": "cite_key",
            "note_type": "笔记类型",
            "note_path": "笔记路径",
            "title": "标题",
            "status": "状态",
            "source_stage": "来源阶段",
            "source_run_uid": "source_run_uid",
            "content_hash": "内容哈希",
            "created_at": "创建时间",
            "updated_at": "更新时间",
        },
    ),
    "知识文献关联": (
        KNOWLEDGE_LINK_TABLE_NAME,
        {
            "id": "id",
            "uid_knowledge": "uid_knowledge",
            "uid_literature": "uid_literature",
            "relation_type": "关联类型",
            "is_primary": "是否主项",
            "cite_key": "cite_key",
            "source_field": "来源字段",
            "created_at": "创建时间",
            "updated_at": "更新时间",
        },
    ),
    "知识证据关联": (
        KNOWLEDGE_EVIDENCE_TABLE_NAME,
        {
            "id": "id",
            "uid_knowledge": "uid_knowledge",
            "evidence_type": "证据类型",
            "target_uid": "target_uid",
            "evidence_role": "证据角色",
            "source_field": "来源字段",
            "created_at": "创建时间",
        },
    ),
}
READING_QUEUE_REQUIRED_COLUMNS: dict[str, str] = {
    "queue_uid": "TEXT",
    "stage": "TEXT",
    "queue_status": "TEXT",
    "priority": "REAL",
    "theme_bucket": "TEXT",
    "recommended_reason": "TEXT",
    "source_stage": "TEXT",
    "source_run_uid": "TEXT",
    "task_batch_id": "TEXT",
    "decision": "TEXT",
    "decision_reason": "TEXT",
    "is_current": "INTEGER",
    "entered_at": "TEXT",
    "completed_at": "TEXT",
}
READING_STATE_REQUIRED_COLUMNS: dict[str, str] = {
    "cite_key": "TEXT",
    "source_stage": "TEXT",
    "source_uid_literature": "TEXT",
    "source_cite_key": "TEXT",
    "recommended_reason": "TEXT",
    "theme_relation": "TEXT",
    "source_origin": "TEXT",
    "reading_objective": "TEXT",
    "manual_guidance": "TEXT",
    "pending_preprocess": "INTEGER",
    "preprocessed": "INTEGER",
    "allow_unparsed_read": "INTEGER",
    "unparsed_read_in_effect": "INTEGER",
    "preprocess_status": "TEXT",
    "preprocess_note_path": "TEXT",
    "standard_note_path": "TEXT",
    "pending_rough_read": "INTEGER",
    "in_rough_read": "INTEGER",
    "rough_read_done": "INTEGER",
    "rough_read_note_path": "TEXT",
    "rough_read_decision": "TEXT",
    "rough_read_reason": "TEXT",
    "analysis_light_synced": "INTEGER",
    "analysis_batch_synced": "INTEGER",
    "pending_deep_read": "INTEGER",
    "in_deep_read": "INTEGER",
    "deep_read_done": "INTEGER",
    "deep_read_count": "INTEGER",
    "deep_read_note_path": "TEXT",
    "deep_read_decision": "TEXT",
    "deep_read_reason": "TEXT",
    "rough_read_without_parse_done": "INTEGER",
    "deep_read_without_parse_done": "INTEGER",
    "require_reread_after_parse": "INTEGER",
    "analysis_formal_synced": "INTEGER",
    "innovation_synced": "INTEGER",
    "last_batch_id": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}
WORKSPACE_NODE_STATE_REQUIRED_COLUMNS: dict[str, str] = {
    "node_name": "TEXT",
    "pending_run": "INTEGER",
    "in_progress": "INTEGER",
    "completed": "INTEGER",
    "gate_status": "TEXT",
    "last_task_uid": "TEXT",
    "current_task_uid": "TEXT",
    "last_run_at": "TEXT",
    "completed_at": "TEXT",
    "summary": "TEXT",
    "next_node_code": "TEXT",
    "failure_reason": "TEXT",
    "retry_count": "INTEGER",
    "updated_at": "TEXT",
}
REVIEW_STATE_REQUIRED_COLUMNS: dict[str, str] = {
    "cite_key": "TEXT",
    "pending_review_candidate": "INTEGER",
    "review_candidate_ready": "INTEGER",
    "pending_review_parse": "INTEGER",
    "review_parse_ready": "INTEGER",
    "pending_reference_preprocess": "INTEGER",
    "reference_preprocessed": "INTEGER",
    "pending_review_read": "INTEGER",
    "in_review_read": "INTEGER",
    "review_read_done": "INTEGER",
    "review_read_count": "INTEGER",
    "source_stage": "TEXT",
    "source_origin": "TEXT",
    "recommended_reason": "TEXT",
    "reading_objective": "TEXT",
    "manual_guidance": "TEXT",
    "parse_asset_uid": "TEXT",
    "structured_abs_path": "TEXT",
    "note_uid": "TEXT",
    "updated_at": "TEXT",
}
FLOW_STATE_REQUIRED_COLUMNS: dict[str, str] = {
    "cite_key": "TEXT",
    "parse_asset_uid": "TEXT",
    "note_uid": "TEXT",
    "source_uid_literature": "TEXT",
    "parent_uid_literature": "TEXT",
    "stage_code": "TEXT",
    "node_code": "TEXT",
    "文献角色": "TEXT",
    "流程轨道": "TEXT",
    "当前阶段": "TEXT",
    "当前阶段组": "TEXT",
    "当前状态": "TEXT",
    "下一阶段": "TEXT",
    "来源阶段": "TEXT",
    "来源类型": "TEXT",
    "推荐原因": "TEXT",
    "主题关系": "TEXT",
    "阅读目标": "TEXT",
    "人工提示": "TEXT",
    "失败原因": "TEXT",
    "阻塞原因": "TEXT",
    "是否当前有效": "INTEGER",
    "是否可执行": "INTEGER",
    "uid_最近任务": "TEXT",
    "uid_最近批次": "TEXT",
    "创建时间": "TEXT",
    "更新时间": "TEXT",
}
PDF_STRUCTURED_VARIANT_SPECS: tuple[dict[str, str], ...] = (
    {
        "converter": "local_pipeline_v2",
        "task_type": "reference_context",
        "column": "structured_path_local_pipeline_v2_reference_context",
        "folder": "structured_local_pipeline_v2_reference_context",
    },
    {
        "converter": "local_pipeline_v2",
        "task_type": "full_fine_grained",
        "column": "structured_path_local_pipeline_v2_full_fine_grained",
        "folder": "structured_local_pipeline_v2_full_fine_grained",
    },
    {
        "converter": "babeldoc",
        "task_type": "reference_context",
        "column": "structured_path_babeldoc_reference_context",
        "folder": "structured_babeldoc_reference_context",
    },
    {
        "converter": "babeldoc",
        "task_type": "full_fine_grained",
        "column": "structured_path_babeldoc_full_fine_grained",
        "folder": "structured_babeldoc_full_fine_grained",
    },
)
PDF_STRUCTURED_VARIANT_PATH_COLUMNS: dict[str, str] = {
    spec["column"]: "TEXT"
    for spec in PDF_STRUCTURED_VARIANT_SPECS
}
LITERATURE_REQUIRED_COLUMNS: dict[str, str] = {
    "文献语种": "TEXT",
    "title_clean": "TEXT",
    "title_normalized": "TEXT",
    "authors": "TEXT",
    "primary_attachment_source_path": "TEXT",
    "placeholder_reason": "TEXT",
    "placeholder_status": "TEXT",
    "placeholder_run_uid": "TEXT",
    "source_type": "TEXT",
    "source_path": "TEXT",
    "structured_status": "TEXT",
    "structured_text_path": "TEXT",
    "structured_backend": "TEXT",
    "structured_task_type": "TEXT",
    "structured_updated_at": "TEXT",
    "structured_schema_version": "TEXT",
    "structured_text_length": "INTEGER",
    "structured_reference_count": "INTEGER",
    "pdf_rel_path": "TEXT",
    "title_zh": "TEXT",
    "abstract_zh": "TEXT",
    "keywords_zh": "TEXT",
    "metadata_translation_status": "TEXT",
    "metadata_translation_provider": "TEXT",
    "metadata_translation_model": "TEXT",
    "parse_state": "TEXT",
    "metadata_translation_updated_at": "TEXT",
}
ATTACHMENT_REQUIRED_COLUMNS: dict[str, str] = {
    "path_rel": "TEXT",
}
TRANSLATION_ASSET_REQUIRED_COLUMNS: dict[str, str] = {
    "translation_uid": "TEXT",
    "uid_literature": "TEXT",
    "cite_key": "TEXT",
    "source_asset_uid": "TEXT",
    "source_kind": "TEXT",
    "target_lang": "TEXT",
    "translation_scope": "TEXT",
    "provider": "TEXT",
    "model_name": "TEXT",
    "asset_dir": "TEXT",
    "translated_markdown_path": "TEXT",
    "translated_structured_path": "TEXT",
    "translation_audit_path": "TEXT",
    "status": "TEXT",
    "is_current": "INTEGER",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}
FLOW_STATE_TO_LITERATURE_COLUMN_MAP: dict[str, str] = {
    "parse_asset_uid": "流程解析资产UID",
    "note_uid": "流程笔记UID",
    "source_uid_literature": "流程来源文献UID",
    "parent_uid_literature": "流程父文献UID",
    "stage_code": "流程阶段编码",
    "node_code": "流程节点编码",
    "文献角色": "流程文献角色",
    "流程轨道": "流程轨道",
    "当前阶段": "流程当前阶段",
    "当前阶段组": "流程当前阶段组",
    "当前状态": "流程当前状态",
    "下一阶段": "流程下一阶段",
    "来源阶段": "流程来源阶段",
    "来源类型": "流程来源类型",
    "推荐原因": "流程推荐原因",
    "主题关系": "流程主题关系",
    "阅读目标": "流程阅读目标",
    "人工提示": "流程人工提示",
    "失败原因": "流程失败原因",
    "阻塞原因": "流程阻塞原因",
    "是否当前有效": "流程是否当前有效",
    "是否可执行": "流程是否可执行",
    "uid_最近任务": "流程最近任务UID",
    "uid_最近批次": "流程最近批次UID",
    "创建时间": "流程创建时间",
    "更新时间": "流程更新时间",
}
READING_STATE_TO_LITERATURE_COLUMN_MAP: dict[str, str] = {
    "source_stage": "阅读来源阶段",
    "source_uid_literature": "阅读来源文献UID",
    "source_cite_key": "阅读来源题录键",
    "recommended_reason": "阅读推荐原因",
    "theme_relation": "阅读主题关系",
    "source_origin": "阅读来源口径",
    "reading_objective": "阅读目标",
    "manual_guidance": "阅读人工提示",
    "pending_preprocess": "阅读待预处理",
    "preprocessed": "阅读已预处理",
    "preprocess_status": "阅读预处理状态",
    "preprocess_note_path": "阅读预处理笔记路径",
    "standard_note_path": "阅读标准笔记路径",
    "pending_rough_read": "阅读待泛读",
    "in_rough_read": "阅读泛读中",
    "rough_read_done": "阅读已泛读",
    "rough_read_note_path": "阅读泛读笔记路径",
    "rough_read_decision": "阅读泛读决策",
    "rough_read_reason": "阅读泛读原因",
    "analysis_light_synced": "阅读轻量分析已同步",
    "analysis_batch_synced": "阅读批次分析已同步",
    "pending_deep_read": "阅读待研读",
    "in_deep_read": "阅读研读中",
    "deep_read_done": "阅读已研读",
    "deep_read_count": "阅读研读次数",
    "deep_read_note_path": "阅读研读笔记路径",
    "deep_read_decision": "阅读研读决策",
    "deep_read_reason": "阅读研读原因",
    "analysis_formal_synced": "阅读正式分析已同步",
    "innovation_synced": "阅读创新点已同步",
    "last_batch_id": "阅读最近批次UID",
    "created_at": "阅读创建时间",
    "updated_at": "阅读更新时间",
}
READING_QUEUE_TO_LITERATURE_COLUMN_MAP: dict[str, str] = {
    "queue_uid": "预处理队列UID",
    "stage": "预处理阶段",
    "source_affair": "预处理来源事务",
    "queue_status": "预处理队列状态",
    "decision": "预处理决策",
    "priority": "预处理优先级",
    "bucket": "预处理主题桶",
    "preferred_next_stage": "预处理推荐下一阶段",
    "recommended_reason": "预处理推荐原因",
    "theme_relation": "预处理主题关系",
    "evidence_note_path": "预处理证据笔记路径",
    "preprocess_state": "预处理执行状态",
    "preprocess_result_path": "预处理结果路径",
    "preprocess_started_at": "预处理开始时间",
    "preprocess_finished_at": "预处理完成时间",
    "preprocess_failure_reason": "预处理失败原因",
    "source_round": "预处理来源轮次",
    "run_uid": "预处理运行UID",
    "scope_key": "预处理范围键",
    "is_current": "预处理是否当前有效",
    "created_at": "预处理创建时间",
    "updated_at": "预处理更新时间",
}
PARSE_ASSET_TO_LITERATURE_COLUMN_MAP: dict[str, str] = {
    "asset_uid": "current_parse_asset_uid",
    "uid_attachment": "current_parse_uid_attachment",
    "parse_level": "current_parse_level",
    "backend": "current_parse_backend",
    "normalized_structured_path": "current_parse_path",
    "reconstructed_markdown_path": "current_parse_markdown_path",
    "parse_status": "current_parse_status",
    "parse_state": "parse_state",
    "updated_at": "current_parse_updated_at",
}
PARSE_ASSET_TO_ATTACHMENT_COLUMN_MAP: dict[str, str] = {
    "asset_uid": "current_parse_asset_uid",
    "parse_level": "current_parse_level",
    "backend": "current_parse_backend",
    "normalized_structured_path": "current_parse_path",
    "reconstructed_markdown_path": "current_parse_markdown_path",
    "parse_status": "current_parse_status",
    "updated_at": "current_parse_updated_at",
}
LITERATURE_RUNTIME_SUMMARY_COLUMNS: dict[str, str] = {
    **{column_name: "TEXT" for column_name in FLOW_STATE_TO_LITERATURE_COLUMN_MAP.values()},
    **{column_name: "TEXT" for column_name in READING_STATE_TO_LITERATURE_COLUMN_MAP.values()},
    **{column_name: "TEXT" for column_name in READING_QUEUE_TO_LITERATURE_COLUMN_MAP.values()},
    **{column_name: "TEXT" for column_name in PARSE_ASSET_TO_LITERATURE_COLUMN_MAP.values()},
}
ATTACHMENT_RUNTIME_SUMMARY_COLUMNS: dict[str, str] = {
    **{column_name: "TEXT" for column_name in PARSE_ASSET_TO_ATTACHMENT_COLUMN_MAP.values()},
}

TAG_REQUIRED_COLUMNS: dict[str, str] = {
    "uid_tag": "TEXT",
    "tag": "TEXT",
    "tag_norm": "TEXT",
    "tag_display": "TEXT",
    "tag_group": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}

AUTHOR_REQUIRED_COLUMNS: dict[str, str] = {
    "uid_author": "TEXT",
    "display_name": "TEXT",
    "normalized_name": "TEXT",
    "surname": "TEXT",
    "given_names": "TEXT",
    "标准作者名": "TEXT",
    "作者类型": "TEXT",
    "作者质量标记": "TEXT",
    "orcid": "TEXT",
    "source_type": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}

AUTHOR_LINK_REQUIRED_COLUMNS: dict[str, str] = {
    "uid_literature_author": "TEXT",
    "uid_literature": "TEXT",
    "uid_author": "TEXT",
    "author_order": "INTEGER",
    "is_first_author": "INTEGER",
    "is_corresponding": "INTEGER",
    "display_name": "TEXT",
    "source_type": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}

_COMMON_CHINESE_SURNAME_PREFIXES: tuple[str, ...] = (
    "欧阳",
    "司马",
    "上官",
    "诸葛",
    "尉迟",
    "夏侯",
    "东方",
    "皇甫",
    "公孙",
    "令狐",
)


def _utc_now_iso() -> str:
    return now_iso()


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _split_pipe_values(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    normalized = text.replace(",", "|").replace("；", "|").replace(";", "|")
    items = [segment.strip() for segment in normalized.split("|")]
    return [segment for segment in items if segment]


def _split_author_values(value: object) -> list[str]:
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
        parts = [segment.strip() for segment in normalized.split("|")]
        return [segment for segment in parts if segment]

    comma_segments = [segment.strip() for segment in text.replace("，", ",").split(",") if segment.strip()]
    if len(comma_segments) == 2:
        return [text]
    if len(comma_segments) > 2 and len(comma_segments) % 2 == 0:
        paired = [", ".join(comma_segments[index:index + 2]).strip() for index in range(0, len(comma_segments), 2)]
        if all(paired):
            return paired
    return comma_segments or [text]


def _split_author_name_components(author_name: object) -> tuple[str, str]:
    # 把作者名拆分为 (姓, 名) 元组。

    cleaned_text, _ = _clean_author_display_name(author_name)
    if not cleaned_text:
        return "", ""

    if re.search(r"[\u4e00-\u9fff]", cleaned_text):
        compact = re.sub(r"\s+", "", cleaned_text)
        if not compact:
            return "", ""
        for prefix in sorted(_COMMON_CHINESE_SURNAME_PREFIXES, key=len, reverse=True):
            if compact.startswith(prefix):
                return prefix, compact[len(prefix):]
        return compact[:1], compact[1:]

    if "," in cleaned_text:
        surname, given_names = [segment.strip() for segment in cleaned_text.split(",", 1)]
        return surname, given_names

    parts = [segment for segment in cleaned_text.split() if segment]
    if len(parts) <= 1:
        return cleaned_text, ""
    return parts[-1], " ".join(parts[:-1])


def _normalize_person_name(value: object) -> str:
    cleaned_text, _ = _clean_author_display_name(value)
    return " ".join(cleaned_text.lower().split())


def _strip_outer_braces(text: str) -> str:
    current = str(text or "").strip()
    while len(current) >= 2 and current.startswith("{") and current.endswith("}"):
        inner = current[1:-1].strip()
        if not inner:
            break
        current = inner
    return current


def _clean_author_display_name(author_name: object) -> tuple[str, list[str]]:
    text = " ".join(str(author_name or "").replace("\u3000", " ").strip().split())
    if not text:
        return "", []

    flags: list[str] = []
    stripped = _strip_outer_braces(text)
    if stripped != text:
        flags.append("含BibTeX保护花括号")
        text = stripped

    text = re.sub(r"\s*·\s*", "·", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text, flags


def _looks_like_latin_initial_name(text: str) -> bool:
    return re.fullmatch(r"[A-Za-z](?:\.)?", text.strip()) is not None


def _looks_like_transliterated_name(text: str) -> bool:
    return "·" in text and re.search(r"[\u4e00-\u9fff]", text) is not None


def _looks_like_institution_author(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "编委会",
            "课题组",
            "项目组",
            "研究院",
            "研究所",
            "实验室",
            "中心",
            "办公室",
            "委员会",
            "学院",
            "大学",
            "银行",
            "支行",
            "公司",
            "政府",
            "出版社",
            "电视台",
            "报社",
        )
    )


def _classify_author_display_name(author_name: object) -> dict[str, str]:
    text, flags = _clean_author_display_name(author_name)
    if not text:
        return {
            "标准作者名": "",
            "作者类型": "缺失作者",
            "作者质量标记": "原始作者缺失",
        }

    normalized_person_name = text
    author_type = "个人作者"

    if text.startswith("本报记者"):
        author_type = "记者复合署名"
        flags.append("含角色前缀")
        normalized_person_name = re.sub(r"^本报记者\s*", "", text).strip()
        if normalized_person_name and " " in normalized_person_name:
            flags.append("疑似多人署名")
    elif text.endswith("编辑部") or text in {"本刊编辑部", "编辑部"}:
        author_type = "编辑部署名"
        flags.append("机构型署名")
        normalized_person_name = ""
    elif _looks_like_institution_author(text):
        author_type = "机构署名"
        flags.append("疑似机构署名")
        normalized_person_name = ""
    elif _looks_like_latin_initial_name(text):
        flags.append("疑似缩写名")
    elif _looks_like_transliterated_name(text):
        flags.append("疑似译名")

    return {
        "标准作者名": normalized_person_name,
        "作者类型": author_type,
        "作者质量标记": ";".join(flags),
    }


def _stable_tag_uid(tag_norm: str) -> str:
    normalized = str(tag_norm or "").strip().lower()
    return f"tag-{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"


def _stable_author_uid(normalized_name: str) -> str:
    normalized = str(normalized_name or "").strip().lower()
    return f"author-{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"


def _stable_author_link_uid(uid_literature: str, uid_author: str, author_order: int) -> str:
    normalized = f"{uid_literature}|{uid_author}|{author_order}".lower()
    return f"litauth-{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"


def resolve_content_db_path(db_path: str | Path) -> Path:
    """把旧内容库路径标准化到统一 `content.db`。"""

    path = Path(db_path).resolve()
    file_name = path.name.lower()
    parent_name = path.parent.name.lower()

    if file_name == DEFAULT_CONTENT_DB_NAME:
        return path

    if file_name in {"references.db", "knowledge.db"}:
        if parent_name == "database":
            return path.parent / CONTENT_DB_DIRECTORY_NAME / DEFAULT_CONTENT_DB_NAME
        return path

    return path


def resolve_content_db_config(
    raw_cfg: Mapping[str, object],
    *,
    content_key: str = "content_db",
    legacy_keys: Sequence[str] = ("references_db", "knowledge_db"),
    default_path: str | Path | None = None,
    required: bool = False,
) -> tuple[Path | None, str]:
    """从配置字典解析统一内容主库路径。

    优先读取 `content_db`，历史双库字段仅作为兼容别名。
    """

    for key in (content_key, *legacy_keys):
        raw_value = raw_cfg.get(key)
        value = str(raw_value or "").strip()
        if not value:
            continue
        path = resolve_portable_path(value, base=Path.cwd())
        return resolve_content_db_path(path), key

    if default_path is not None:
        path = resolve_portable_path(default_path, base=Path.cwd())
        return resolve_content_db_path(path), "default"

    if required:
        accepted = ", ".join([content_key, *legacy_keys])
        raise ValueError(f"必须提供统一内容主库路径，支持字段：{accepted}")

    return None, ""


def infer_workspace_root_from_content_db(db_path: str | Path) -> Path:
    """根据统一内容主库路径推导工作区根目录。"""

    resolved = resolve_content_db_path(db_path)
    if resolved.name != DEFAULT_CONTENT_DB_NAME:
        raise ValueError(f"不是受支持的内容主库文件名：{resolved}")
    if resolved.parent.name != CONTENT_DB_DIRECTORY_NAME:
        raise ValueError(f"内容主库目录结构不符合约定：{resolved}")
    if resolved.parent.parent.name != "database":
        raise ValueError(f"内容主库上级目录不符合约定：{resolved}")
    return resolved.parent.parent.parent


def normalize_db_relative_path(path_text: str | Path) -> str:
    """规范化数据库中的相对路径文本。"""

    text = str(path_text or "").strip()
    if not text:
        return ""
    return text.replace("\\", "/").lstrip("/")


def build_relative_path_from_workspace(path_text: str | Path, *, workspace_root: str | Path) -> str:
    """把路径转为相对 `workspace_root` 的路径文本。

    若无法计算相对路径，返回空字符串。
    """

    text = str(path_text or "").strip()
    if not text:
        return ""
    root = resolve_portable_path(workspace_root, base=Path.cwd())
    try:
        resolved = resolve_portable_path(text, base=root)
    except Exception:
        return ""
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return ""
    return normalize_db_relative_path(relative.as_posix())


def resolve_content_path(
    path_text: str | Path,
    *,
    workspace_root: str | Path,
) -> Path:
    """统一解析 content.db 中的路径字段到当前运行时绝对路径。"""

    root = resolve_portable_path(workspace_root, base=Path.cwd())
    return resolve_portable_path(path_text, base=root)


def resolve_content_path_candidates(
    *,
    workspace_root: str | Path,
    relative_path: str | Path | None = None,
    absolute_or_legacy_path: str | Path | None = None,
) -> list[Path]:
    """解析候选路径并去重，优先返回可用候选顺序。"""

    root = resolve_portable_path(workspace_root, base=Path.cwd())
    results: list[Path] = []
    seen: set[str] = set()
    for candidate in (relative_path, absolute_or_legacy_path):
        raw = str(candidate or "").strip()
        if not raw:
            continue
        try:
            resolved = resolve_portable_path(raw, base=root).resolve()
        except Exception:
            continue
        marker = str(resolved).lower()
        if marker in seen:
            continue
        seen.add(marker)
        results.append(resolved)
    return results


def get_pdf_structured_variant_spec(converter: str, task_type: str) -> dict[str, str] | None:
    """按解析工具链与任务类型获取四组合规格。"""

    normalized_converter = str(converter or "").strip().lower()
    normalized_task_type = str(task_type or "").strip().lower()
    for spec in PDF_STRUCTURED_VARIANT_SPECS:
        if spec["converter"] == normalized_converter and spec["task_type"] == normalized_task_type:
            return dict(spec)
    return None


def get_pdf_structured_variant_column(converter: str, task_type: str) -> str | None:
    """返回四组合对应的文献主表路径字段名。"""

    spec = get_pdf_structured_variant_spec(converter, task_type)
    return None if spec is None else spec["column"]


def build_pdf_structured_variant_dir_map(references_root: str | Path) -> dict[str, Path]:
    """构造 `workspace/references` 下的四组合目录映射。"""

    root = Path(references_root)
    return {spec["folder"]: root / spec["folder"] for spec in PDF_STRUCTURED_VARIANT_SPECS}


def resolve_pdf_structured_variant_output_dir(
    workspace_root: str | Path,
    *,
    converter: str,
    task_type: str,
) -> Path:
    """根据四组合契约返回固定 structured 输出目录。"""

    spec = get_pdf_structured_variant_spec(converter, task_type)
    if spec is None:
        raise ValueError(
            f"不支持的 PDF 解析组合：converter={converter!r}, task_type={task_type!r}"
        )
    return Path(workspace_root) / "references" / spec["folder"]


def connect_sqlite(db_path: str | Path) -> sqlite3.Connection:
    """创建统一内容主库连接，并开启基础 pragma。"""

    original = Path(db_path).resolve()
    resolved = resolve_content_db_path(original)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(resolved))
    _ensure_legacy_db_alias(original, resolved)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        pass
    return connection


def _ensure_legacy_db_alias(original: Path, resolved: Path) -> None:
    if original == resolved:
        return
    original.parent.mkdir(parents=True, exist_ok=True)
    if original.exists():
        try:
            if original.samefile(resolved):
                return
        except OSError:
            return
    try:
        os.link(resolved, original)
    except OSError:
        return


CONTENTDB_PHYSICAL_COLUMN_ALIASES: dict[str, dict[str, str]] = {
    LITERATURE_TABLE_NAME: {
        "id": "内部编号",
        "uid_literature": "uid_文献",
        "cite_key": "cite_key",
        "doi": "bib_doi",
        "isbn": "bib_isbn",
        "issn": "bib_issn",
        "entry_type": "bib_entry_type",
        "orig_entry_type": "bib_orig_entry_type",
        "journal": "bib_journal",
        "booktitle": "bib_booktitle",
        "pages": "bib_pages",
        "volume": "bib_volume",
        "number": "bib_number",
        "month": "bib_month",
        "publisher": "bib_publisher",
        "editor": "bib_editor",
        "school": "bib_school",
        "author": "bib_author",
        "file": "bib_file",
        "url": "bib_url",
        "urldate": "bib_urldate",
        "langid": "bib_langid",
        "howpublished": "bib_howpublished",
        "note": "bib_note",
        "title": "标题",
        "clean_title": "标题清洗",
        "title_clean": "标题清洗",
        "title_norm": "标题标准化",
        "title_normalized": "标题标准化",
        "authors": "作者串",
        "first_author": "第一作者",
        "year": "年份",
        "abstract": "摘要",
        "keywords": "关键词",
        "pdf_path": "PDF路径",
        "is_placeholder": "是否占位",
        "placeholder_reason": "占位原因",
        "placeholder_status": "占位状态",
        "placeholder_run_uid": "uid_占位运行",
        "has_fulltext": "是否有全文",
        "primary_attachment_name": "主附件名称",
        "primary_attachment_source_path": "主附件源路径",
        "standard_note_uid": "uid_标准笔记",
        "source_type": "来源类型",
        "origin_path": "来源路径",
        "source_path": "来源路径",
        "source": "导入来源",
        "created_at": "创建时间",
        "updated_at": "更新时间",
        "imported_at": "导入时间",
        "structured_status": "结构化状态",
        "structured_abs_path": "结构化正文路径",
        "structured_text_path": "结构化正文路径",
        "structured_backend": "结构化后端",
        "structured_task_type": "结构化任务类型",
        "structured_updated_at": "结构化更新时间",
        "structured_schema_version": "结构化Schema版本",
        "structured_text_length": "结构化文本长度",
        "structured_reference_count": "结构化参考文献数",
        "source_lang": "文献语种",
        "language": "文献语种",
        "title_zh": "标题译文",
        "abstract_zh": "摘要译文",
        "keywords_zh": "关键词译文",
        "metadata_translation_status": "元数据翻译状态",
        "metadata_translation_provider": "元数据翻译提供方",
        "metadata_translation_model": "元数据翻译模型",
        "metadata_translation_updated_at": "元数据翻译更新时间",
        "notes": "备注",
        "literature_type": "文献类型",
        "pdf_path": "PDF路径",
        "pdf_rel_path": "PDF相对路径",
        "current_parse_asset_uid": "uid_当前解析资产",
        "current_parse_uid_attachment": "uid_当前解析附件",
        "current_parse_level": "当前解析层级",
        "current_parse_backend": "当前解析后端",
        "current_parse_path": "当前解析路径",
        "current_parse_markdown_path": "当前解析Markdown路径",
        "current_parse_status": "当前解析状态",
        "current_parse_updated_at": "当前解析更新时间",
        "parse_state": "解析状态",
    },
    ATTACHMENT_TABLE_NAME: {
        "id": "内部编号",
        "uid_attachment": "uid_附件",
        "attachment_name": "附件名称",
        "attachment_type": "附件类型",
        "file_ext": "文件扩展名",
        "storage_path": "存储路径",
        "source_path": "来源路径",
        "source_kind": "附件来源类型",
        "source_affair": "来源事务",
        "checksum": "校验和",
        "status": "状态",
        "created_at": "创建时间",
        "updated_at": "更新时间",
        "path_rel": "相对路径",
        "current_parse_asset_uid": "uid_当前解析资产",
        "current_parse_level": "当前解析层级",
        "current_parse_backend": "当前解析后端",
        "current_parse_path": "当前解析路径",
        "current_parse_markdown_path": "当前解析Markdown路径",
        "current_parse_status": "当前解析状态",
        "current_parse_updated_at": "当前解析更新时间",
    },
    ATTACHMENT_LINK_TABLE_NAME: {
        "id": "内部编号",
        "uid_attachment_link": "uid_文献附件关联",
        "uid_literature": "uid_文献",
        "uid_attachment": "uid_附件",
        "link_role": "关联角色",
        "is_primary": "是否主附件",
        "source_type": "来源类型",
        "legacy_uid_attachment": "uid_旧附件",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    AUTHOR_TABLE_NAME: {
        "id": "内部编号",
        "uid_author": "uid_作者",
        "display_name": "显示姓名",
        "normalized_name": "规范姓名",
        "surname": "姓",
        "given_names": "名",
        "orcid": "研究者标识",
        "source_type": "来源类型",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    AUTHOR_LINK_TABLE_NAME: {
        "id": "内部编号",
        "uid_literature_author": "uid_文献作者关联",
        "uid_literature": "uid_文献",
        "uid_author": "uid_作者",
        "author_order": "作者顺序",
        "is_first_author": "是否第一作者",
        "is_corresponding": "是否通讯作者",
        "display_name": "显示姓名",
        "source_type": "来源类型",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    TAG_TABLE_NAME: {
        "id": "内部编号",
        "uid_tag": "uid_标签",
        "tag": "标签",
        "tag_norm": "标签规范名",
        "tag_display": "标签显示名",
        "tag_group": "标签分组",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    LITERATURE_TAG_TABLE_NAME: {
        "id": "内部编号",
        "uid_literature": "uid_文献",
        "cite_key": "cite_key",
        "tag": "标签",
        "tag_norm": "标签规范名",
        "source_type": "来源类型",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    PARSE_ASSET_TABLE_NAME: {
        "id": "内部编号",
        "asset_uid": "uid_资产",
        "uid_literature": "uid_文献",
        "cite_key": "cite_key",
        "uid_attachment": "uid_附件",
        "parse_level": "解析层级",
        "backend": "解析后端",
        "model_name": "模型名称",
        "asset_dir": "资产目录",
        "normalized_structured_path": "结构化正文路径",
        "structured_text_path": "结构化正文路径",
        "reconstructed_markdown_path": "重构文稿路径",
        "markdown_path": "重构文稿路径",
        "linear_index_path": "线性索引路径",
        "elements_path": "元素路径",
        "chunks_jsonl_path": "分块记录路径",
        "parse_record_path": "解析记录路径",
        "parse_log_path": "解析记录路径",
        "quality_report_path": "质量报告路径",
        "parse_status": "解析状态",
        "status": "解析状态",
        "last_run_uid": "uid_最近运行",
        "is_current": "是否当前有效",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    TRANSLATION_ASSET_TABLE_NAME: {
        "id": "内部编号",
        "translation_uid": "uid_翻译资产",
        "uid_literature": "uid_文献",
        "cite_key": "cite_key",
        "source_asset_uid": "uid_来源资产",
        "source_kind": "来源类型",
        "target_lang": "目标语种",
        "translation_scope": "翻译范围",
        "provider": "提供方",
        "model_name": "模型名称",
        "asset_dir": "资产目录",
        "translated_markdown_path": "译文文稿路径",
        "translated_structured_path": "译文结构化路径",
        "translation_audit_path": "翻译审计路径",
        "status": "状态",
        "is_current": "是否当前有效",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    CHUNK_SET_TABLE_NAME: {
        "id": "内部编号",
        "chunks_uid": "uid_分块集",
        "source_scope": "来源范围",
        "chunks_path": "分块绝对路径",
        "source_backend": "来源后端",
        "chunk_count": "分块数量",
        "literature_count": "来源文献数",
        "created_at": "创建时间",
        "status": "状态",
    },
    CHUNK_TABLE_NAME: {
        "id": "内部编号",
        "chunks_uid": "uid_分块集",
        "uid_literature": "uid_文献",
        "chunk_id": "分块编号",
        "fragment_path": "分片路径",
        "chunk_order": "分块序号",
        "chunk_type": "分块类型",
        "start_char": "起始字符位",
        "end_char": "结束字符位",
        "text_length": "文本长度",
        "created_at": "创建时间",
    },
    KNOWLEDGE_NOTES_TABLE_NAME: {
        "id": "内部编号",
        "uid_note": "uid_笔记",
        "uid_literature": "uid_文献",
        "note_type": "笔记类型",
        "note_path": "笔记路径",
        "title": "标题",
        "status": "状态",
        "source_stage": "来源阶段",
        "source_run_uid": "uid_来源运行",
        "content_hash": "内容哈希",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    KNOWLEDGE_LINK_TABLE_NAME: {
        "id": "内部编号",
        "uid_knowledge": "uid_知识",
        "uid_literature": "uid_文献",
        "relation_type": "关联类型",
        "is_primary": "是否主项",
        "source_field": "来源字段",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    KNOWLEDGE_EVIDENCE_TABLE_NAME: {
        "id": "内部编号",
        "uid_knowledge": "uid_知识",
        "target_uid": "uid_目标对象",
        "evidence_type": "证据类型",
        "evidence_role": "证据角色",
        "source_field": "来源字段",
        "created_at": "创建时间",
    },
    WORKSPACE_NODE_STATE_TABLE_NAME: {
        "node_code": "节点编码",
        "node_name": "节点名称",
        "pending_run": "待执行",
        "in_progress": "执行中",
        "completed": "已完成",
        "gate_status": "闸门状态",
        "last_task_uid": "uid_最近任务",
        "current_task_uid": "uid_当前任务",
        "last_run_at": "最近执行时间",
        "completed_at": "完成时间",
        "summary": "摘要",
        "next_node_code": "下一节点编码",
        "failure_reason": "失败原因",
        "retry_count": "重试次数",
        "updated_at": "更新时间",
    },
    FLOW_STATE_TABLE_NAME: {
        "uid_literature": "uid_文献",
        "cite_key": "cite_key",
        "parse_asset_uid": "uid_解析资产",
        "note_uid": "uid_笔记",
        "source_uid_literature": "uid_来源文献",
        "parent_uid_literature": "uid_父文献",
        "stage_code": "阶段编码",
        "node_code": "节点编码",
        "literature_role": "文献角色",
        "flow_track": "流程轨道",
        "current_stage": "当前阶段",
        "current_stage_group": "当前阶段组",
        "current_status": "当前状态",
        "next_stage": "下一阶段",
        "source_stage": "来源阶段",
        "source_type": "来源类型",
        "recommend_reason": "推荐原因",
        "topic_relation": "主题关系",
        "reading_goal": "阅读目标",
        "human_hint": "人工提示",
        "failure_reason": "失败原因",
        "blocked_reason": "阻塞原因",
        "is_current": "是否当前有效",
        "is_executable": "是否可执行",
        "last_task_uid": "uid_最近任务",
        "last_batch_id": "uid_最近批次",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    READING_STATE_TABLE_NAME: {
        "uid_literature": "uid_文献",
        "cite_key": "cite_key",
        "source_stage": "来源阶段",
        "source_uid_literature": "uid_来源文献",
        "source_cite_key": "source_cite_key",
        "recommended_reason": "推荐原因",
        "theme_relation": "主题关系",
        "source_origin": "来源口径",
        "reading_objective": "阅读目标",
        "manual_guidance": "人工提示",
        "pending_preprocess": "待预处理",
        "preprocessed": "已预处理",
        "allow_unparsed_read": "允许未解析阅读",
        "unparsed_read_in_effect": "未解析阅读生效",
        "preprocess_status": "预处理状态",
        "preprocess_note_path": "预处理笔记路径",
        "standard_note_path": "标准笔记路径",
        "pending_rough_read": "待泛读",
        "in_rough_read": "泛读中",
        "rough_read_done": "已泛读",
        "rough_read_note_path": "泛读笔记路径",
        "rough_read_decision": "泛读决策",
        "rough_read_reason": "泛读原因",
        "analysis_light_synced": "轻量分析已同步",
        "analysis_batch_synced": "批次分析已同步",
        "pending_deep_read": "待研读",
        "in_deep_read": "研读中",
        "deep_read_done": "已研读",
        "deep_read_count": "研读次数",
        "deep_read_note_path": "研读笔记路径",
        "deep_read_decision": "研读决策",
        "deep_read_reason": "研读原因",
        "rough_read_without_parse_done": "未解析已泛读",
        "deep_read_without_parse_done": "未解析已研读",
        "require_reread_after_parse": "解析后需重读",
        "analysis_formal_synced": "正式分析已同步",
        "innovation_synced": "创新点已同步",
        "last_batch_id": "uid_最近批次",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    REVIEW_STATE_TABLE_NAME: {
        "uid_literature": "uid_文献",
        "pending_review_candidate": "待综述候选",
        "review_candidate_ready": "综述候选就绪",
        "pending_review_parse": "待综述解析",
        "review_parse_ready": "综述解析就绪",
        "pending_reference_preprocess": "待参考预处理",
        "reference_preprocessed": "参考预处理完成",
        "pending_review_read": "待综述阅读",
        "in_review_read": "综述阅读中",
        "review_read_done": "综述已读",
        "review_read_count": "综述阅读次数",
        "source_stage": "来源阶段",
        "source_origin": "来源口径",
        "recommended_reason": "推荐原因",
        "reading_objective": "阅读目标",
        "manual_guidance": "人工提示",
        "parse_asset_uid": "uid_解析资产",
        "structured_abs_path": "结构化正文路径",
        "note_uid": "uid_笔记",
        "updated_at": "更新时间",
    },
    READING_QUEUE_TABLE_NAME: {
        "id": "内部编号",
        "uid_literature": "uid_文献",
        "cite_key": "cite_key",
        "queue_uid": "预处理队列UID",
        "stage": "阶段",
        "source_affair": "来源事务",
        "queue_status": "队列状态",
        "decision": "决策",
        "priority": "优先级",
        "bucket": "主题桶",
        "preferred_next_stage": "推荐下一阶段",
        "recommended_reason": "推荐原因",
        "theme_relation": "主题关系",
        "evidence_note_path": "证据笔记路径",
        "preprocess_state": "预处理状态",
        "preprocess_result_path": "预处理结果路径",
        "preprocess_started_at": "预处理开始时间",
        "preprocess_finished_at": "预处理完成时间",
        "preprocess_failure_reason": "预处理失败原因",
        "source_round": "来源轮次",
        "run_uid": "uid_运行",
        "scope_key": "范围键",
        "is_current": "是否当前有效",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
}

for _column_name in LITERATURE_RUNTIME_SUMMARY_COLUMNS:
    CONTENTDB_PHYSICAL_COLUMN_ALIASES.setdefault(LITERATURE_TABLE_NAME, {}).setdefault(_column_name, _column_name)

for _column_name in ATTACHMENT_RUNTIME_SUMMARY_COLUMNS:
    CONTENTDB_PHYSICAL_COLUMN_ALIASES.setdefault(ATTACHMENT_TABLE_NAME, {}).setdefault(_column_name, _column_name)

CONTENTDB_PHYSICAL_COLUMN_ALIASES.setdefault(
    TRANSLATION_ASSET_STORAGE_TABLE_NAME,
    dict(CONTENTDB_PHYSICAL_COLUMN_ALIASES.get(TRANSLATION_ASSET_TABLE_NAME, {})),
)

# 命名治理英文例外：历史库若曾把这些列名中文化，初始化时应回迁到英文列名。
CONTENTDB_LEGACY_EXCEPTION_COLUMN_RENAMES: dict[str, dict[str, str]] = {
    LITERATURE_TABLE_NAME: {
        "题录键": "cite_key",
    },
    LITERATURE_TAG_TABLE_NAME: {
        "题录键": "cite_key",
    },
    PARSE_ASSET_TABLE_NAME: {
        "题录键": "cite_key",
    },
    TRANSLATION_ASSET_TABLE_NAME: {
        "题录键": "cite_key",
    },
    TRANSLATION_ASSET_STORAGE_TABLE_NAME: {
        "题录键": "cite_key",
    },
    FLOW_STATE_TABLE_NAME: {
        "题录键": "cite_key",
    },
    READING_STATE_TABLE_NAME: {
        "题录键": "cite_key",
        "来源题录键": "source_cite_key",
        "阅读来源题录键": "source_cite_key",
    },
    READING_QUEUE_TABLE_NAME: {
        "题录键": "cite_key",
    },
    KNOWLEDGE_NOTES_TABLE_NAME: {
        "题录键": "cite_key",
    },
}


def resolve_content_physical_column(table_name: str, column_name: str) -> str:
    aliases = CONTENTDB_PHYSICAL_COLUMN_ALIASES.get(table_name, {})
    return aliases.get(column_name, column_name)


def _resolve_physical_column(table_name: str, column_name: str) -> str:
    return resolve_content_physical_column(table_name, column_name)


def _migrate_legacy_exception_columns(conn: sqlite3.Connection, table_name: str) -> None:
    if _sqlite_object_type(conn, table_name) != "table":
        return
    existing_columns = _physical_table_columns(conn, table_name)
    rename_mapping = CONTENTDB_LEGACY_EXCEPTION_COLUMN_RENAMES.get(table_name, {})
    for legacy_column, target_column in rename_mapping.items():
        if legacy_column not in existing_columns or target_column in existing_columns:
            continue
        conn.execute(
            f"ALTER TABLE {_quote_identifier(table_name)} RENAME COLUMN {_quote_identifier(legacy_column)} TO {_quote_identifier(target_column)}"
        )
        existing_columns.remove(legacy_column)
        existing_columns.add(target_column)


def _rename_table_columns_to_physical_aliases(conn: sqlite3.Connection, table_name: str) -> None:
    if _sqlite_object_type(conn, table_name) != "table":
        return
    _migrate_legacy_exception_columns(conn, table_name)
    existing_columns = _physical_table_columns(conn, table_name)
    aliases = CONTENTDB_PHYSICAL_COLUMN_ALIASES.get(table_name, {})
    for logical_name, physical_name in aliases.items():
        if logical_name == physical_name:
            continue
        if logical_name not in existing_columns or physical_name in existing_columns:
            continue
        conn.execute(
            f"ALTER TABLE {_quote_identifier(table_name)} RENAME COLUMN {_quote_identifier(logical_name)} TO {_quote_identifier(physical_name)}"
        )
        existing_columns.remove(logical_name)
        existing_columns.add(physical_name)


def _qualified_physical_column(table_name: str, logical_name: str, table_alias: str | None = None) -> str:
    physical_name = _quote_identifier(_resolve_physical_column(table_name, logical_name))
    if not table_alias:
        return physical_name
    return f"{table_alias}.{physical_name}"


def _build_transaction_name_case(column_name: str = "事务编号") -> str:
    cases = [f"WHEN {column_name} = '{node_code}' THEN '{node_label}'" for node_code, node_label in TRANSACTION_RELATION_NODE_LABELS]
    if not cases:
        return "''"
    return "CASE\n            " + "\n            ".join(cases) + "\n            ELSE ''\n        END"


def _physical_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        str(row[1]).strip()
        for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table_name)})")
        if str(row[1]).strip()
    }


def _adapt_frame_to_physical_schema(
    conn: sqlite3.Connection,
    table_name: str,
    frame: pd.DataFrame,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return frame
    physical_columns = _physical_table_columns(conn, table_name)
    renamed = frame.rename(columns={column: _resolve_physical_column(table_name, str(column)) for column in frame.columns})
    duplicate_columns = [column for column in renamed.columns if column in physical_columns]
    if not duplicate_columns:
        return renamed.iloc[:, 0:0]
    return renamed.loc[:, ~renamed.columns.duplicated()].loc[:, duplicate_columns]


def adapt_frame_to_content_physical_schema(
    conn: sqlite3.Connection,
    table_name: str,
    frame: pd.DataFrame,
) -> pd.DataFrame:
    return _adapt_frame_to_physical_schema(conn, table_name, frame)


def _replace_table_rows(conn: sqlite3.Connection, table_name: str, frame: pd.DataFrame) -> None:
    if _sqlite_object_type(conn, table_name) != "table":
        return
    conn.execute(f"DELETE FROM {_quote_identifier(table_name)}")
    if frame is None or frame.empty:
        return
    physical_frame = _adapt_frame_to_physical_schema(conn, table_name, frame)
    working = physical_frame.where(pd.notnull(physical_frame), None)
    if working.empty or not list(working.columns):
        return
    working.to_sql(table_name, conn, if_exists="append", index=False)


def _sqlite_object_type(conn: sqlite3.Connection, object_name: str) -> str:
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = ? LIMIT 1",
        (object_name,),
    ).fetchone()
    return str(row[0]).strip().lower() if row and row[0] else ""


def _create_index_if_table(conn: sqlite3.Connection, table_name: str, index_sql: str) -> None:
    if _sqlite_object_type(conn, table_name) == "table":
        try:
            conn.execute(index_sql)
        except sqlite3.OperationalError:
            return


def _ensure_table_columns(conn: sqlite3.Connection, table_name: str, column_types: Mapping[str, str]) -> None:
    if _sqlite_object_type(conn, table_name) != "table":
        return
    existing_columns = _physical_table_columns(conn, table_name)
    existing_column_lowers = {column.lower() for column in existing_columns}
    aliases = CONTENTDB_PHYSICAL_COLUMN_ALIASES.get(table_name, {})
    uses_chinese_schema = any(any("\u4e00" <= char <= "\u9fff" for char in column) for column in existing_columns)
    for column_name, column_type in column_types.items():
        logical_name = str(column_name).strip()
        if uses_chinese_schema and logical_name not in existing_columns and logical_name not in aliases:
            continue
        if uses_chinese_schema:
            normalized_name = _resolve_physical_column(table_name, logical_name)
            if (
                normalized_name
                and normalized_name != logical_name
                and logical_name in existing_columns
                and normalized_name not in existing_columns
            ):
                # 旧逻辑列已存在时，后续 rename 会统一收口；这里不要先补一个物理别名列。
                continue
        else:
            normalized_name = logical_name
        if not normalized_name or normalized_name in existing_columns or normalized_name.lower() in existing_column_lowers:
            continue
        normalized_type = str(column_type or "TEXT").strip() or "TEXT"
        conn.execute(
            f"ALTER TABLE {_quote_identifier(table_name)} ADD COLUMN {_quote_identifier(normalized_name)} {normalized_type}"
        )
        existing_columns.add(normalized_name)
        existing_column_lowers.add(normalized_name.lower())


def _create_or_replace_view(conn: sqlite3.Connection, view_name: str, select_sql: str) -> None:
    object_type = _sqlite_object_type(conn, view_name)
    if object_type == "table":
        raise sqlite3.OperationalError(f"对象 {view_name} 已存在且为表，无法覆盖为视图")
    # 无论探测结果如何，统一先删除同名视图，避免编码/缓存差异下误判导致重复创建失败。
    quoted_name = _quote_identifier(view_name)
    conn.execute(f"DROP VIEW IF EXISTS temp.{quoted_name}")
    conn.execute(f"DROP VIEW IF EXISTS main.{quoted_name}")
    conn.execute(f"DROP VIEW IF EXISTS {quoted_name}")
    try:
        conn.execute(f"CREATE VIEW {_quote_identifier(view_name)} AS\n{select_sql.strip()}")
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "already exists" in msg:
            # 防御性兜底：某些边界条件下 DROP 未生效（如连接隔离、schema 缓存或编码差异），
            # 直接遍历 sqlite_master 强制删除所有同名视图/表对象后再重试一次。
            stale_objects = conn.execute(
                "SELECT name, type FROM sqlite_master WHERE name = ?", (view_name,)
            ).fetchall()
            for obj_name, obj_type in stale_objects:
                qn = _quote_identifier(obj_name)
                if obj_type == "view":
                    conn.execute(f"DROP VIEW IF EXISTS {qn}")
                elif obj_type == "table":
                    raise sqlite3.OperationalError(
                        f"对象 {view_name} 已存在且为表，无法覆盖为视图"
                    )
            conn.execute(f"CREATE VIEW {_quote_identifier(view_name)} AS\n{select_sql.strip()}")
        else:
            raise


CONTENTDB_CONTRACT_VIEW_ALIAS_OVERRIDES: dict[str, str] = {
    "id": "内部编号",
    "entry_type": "题录类型",
    "orig_entry_type": "原始题录类型",
}


def _resolve_contract_view_alias(source_table_name: str, logical_name: str, proposed_alias: str) -> str:
    alias = str(proposed_alias or "").strip() or str(logical_name or "").strip()
    if alias and not alias.isascii():
        return alias

    physical_alias = CONTENTDB_PHYSICAL_COLUMN_ALIASES.get(source_table_name, {}).get(str(logical_name or "").strip())
    if physical_alias:
        normalized_physical_alias = str(physical_alias).strip()
        if normalized_physical_alias and not normalized_physical_alias.isascii():
            return normalized_physical_alias

    override = CONTENTDB_CONTRACT_VIEW_ALIAS_OVERRIDES.get(str(logical_name or "").strip())
    if override:
        return override
    return alias


def _drop_all_views(conn: sqlite3.Connection) -> None:
    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall():
        view_name = str(row[0]).strip()
        if view_name:
            conn.execute(f"DROP VIEW IF EXISTS {_quote_identifier(view_name)}")


def _logicalize_runtime_frame(table_name: str, frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return frame
    alias_map = CONTENTDB_PHYSICAL_COLUMN_ALIASES.get(table_name, {})
    reverse_map: dict[str, str] = {}
    for logical_name, physical_name in alias_map.items():
        reverse_map.setdefault(str(physical_name), str(logical_name))
    if not reverse_map:
        return frame
    logicalized = frame.rename(
        columns={column: reverse_map.get(str(column), str(column)) for column in frame.columns}
    )
    if logicalized.columns.duplicated().any():
        logicalized = logicalized.loc[:, ~logicalized.columns.duplicated(keep="last")]
    return logicalized


def _update_runtime_summary_rows(
    conn: sqlite3.Connection,
    *,
    target_table: str,
    key_column: str,
    frame: pd.DataFrame,
    column_map: Mapping[str, str],
) -> None:
    if frame is None or frame.empty or _sqlite_object_type(conn, target_table) != "table":
        return
    target_key_physical = _resolve_physical_column(target_table, key_column)
    existing_columns = _physical_table_columns(conn, target_table)
    if target_key_physical not in existing_columns:
        return

    writable_pairs: list[tuple[str, str]] = []
    for logical_name, target_summary_name in column_map.items():
        if logical_name not in frame.columns:
            continue
        target_physical = _resolve_physical_column(target_table, target_summary_name)
        if target_physical not in existing_columns:
            continue
        writable_pairs.append((logical_name, target_physical))
    if not writable_pairs:
        return

    set_clause = ", ".join(
        f"{_quote_identifier(target_physical)} = ?"
        for _, target_physical in writable_pairs
    )
    target_sql = _quote_identifier(target_table)
    key_sql = _quote_identifier(target_key_physical)
    for _, row in frame.iterrows():
        key_value = row.get(key_column)
        if pd.isna(key_value) or key_value in (None, ""):
            continue
        params = [None if pd.isna(row.get(source_name)) else row.get(source_name) for source_name, _ in writable_pairs]
        params.append(key_value)
        conn.execute(
            f"UPDATE {target_sql} SET {set_clause} WHERE {key_sql} = ?",
            tuple(params),
        )


def _migrate_public_translation_asset_table(conn: sqlite3.Connection) -> None:
    public_type = _sqlite_object_type(conn, TRANSLATION_ASSET_TABLE_NAME)
    if public_type != "table":
        return

    storage_type = _sqlite_object_type(conn, TRANSLATION_ASSET_STORAGE_TABLE_NAME)
    if storage_type != "table":
        conn.execute(
            f"ALTER TABLE {_quote_identifier(TRANSLATION_ASSET_TABLE_NAME)} RENAME TO {_quote_identifier(TRANSLATION_ASSET_STORAGE_TABLE_NAME)}"
        )
        return

    frame = pd.read_sql_query(
        f"SELECT * FROM {_quote_identifier(TRANSLATION_ASSET_TABLE_NAME)}",
        conn,
    )
    frame = _logicalize_runtime_frame(TRANSLATION_ASSET_TABLE_NAME, frame)
    adapted = _adapt_frame_to_physical_schema(conn, TRANSLATION_ASSET_STORAGE_TABLE_NAME, frame)
    if adapted is not None and not adapted.empty:
        records = adapted.where(pd.notnull(adapted), None).to_dict(orient="records")
        writable_columns = list(adapted.columns)
        for row in records:
            translation_uid = row.get("translation_uid")
            if translation_uid in (None, ""):
                continue
            update_columns = [column for column in writable_columns if column != "translation_uid"]
            if update_columns:
                update_sql = ", ".join(
                    f"{_quote_identifier(column)} = ?" for column in update_columns
                )
                updated = conn.execute(
                    f"UPDATE {_quote_identifier(TRANSLATION_ASSET_STORAGE_TABLE_NAME)} SET {update_sql} WHERE {_quote_identifier('translation_uid')} = ?",
                    tuple(row.get(column) for column in update_columns) + (translation_uid,),
                )
                if updated.rowcount and updated.rowcount > 0:
                    continue
            placeholders = ", ".join(["?"] * len(writable_columns))
            conn.execute(
                f"INSERT INTO {_quote_identifier(TRANSLATION_ASSET_STORAGE_TABLE_NAME)} ({', '.join(_quote_identifier(column) for column in writable_columns)}) VALUES ({placeholders})",
                tuple(row.get(column) for column in writable_columns),
            )

    conn.execute(f"DROP TABLE IF EXISTS {_quote_identifier(TRANSLATION_ASSET_TABLE_NAME)}")


def _migrate_public_parse_asset_table(conn: sqlite3.Connection) -> None:
    if _sqlite_object_type(conn, PARSE_ASSET_TABLE_NAME) != "table":
        return
    frame = pd.read_sql_query(f"SELECT * FROM {_quote_identifier(PARSE_ASSET_TABLE_NAME)}", conn)
    frame = _logicalize_runtime_frame(PARSE_ASSET_TABLE_NAME, frame)
    attachment_uid_column = _resolve_physical_column(ATTACHMENT_TABLE_NAME, "uid_attachment")
    attachment_uids = {
        str(row[0]).strip()
        for row in conn.execute(
            f"SELECT {_quote_identifier(attachment_uid_column)} FROM {_quote_identifier(ATTACHMENT_TABLE_NAME)}"
        ).fetchall()
        if row and str(row[0]).strip()
    }
    if not frame.empty:
        for _, row in frame.iterrows():
            uid_attachment = str(row.get("uid_attachment") or "").strip()
            uid_literature = str(row.get("uid_literature") or "").strip()
            target_table = ATTACHMENT_TABLE_NAME if uid_attachment and uid_attachment in attachment_uids else LITERATURE_TABLE_NAME
            key_column = "uid_attachment" if target_table == ATTACHMENT_TABLE_NAME else "uid_literature"
            key_value = uid_attachment if target_table == ATTACHMENT_TABLE_NAME else uid_literature
            if not key_value:
                continue
            single = pd.DataFrame([row.to_dict()])
            _update_runtime_summary_rows(
                conn,
                target_table=target_table,
                key_column=key_column,
                frame=single,
                column_map=(
                    PARSE_ASSET_TO_ATTACHMENT_COLUMN_MAP
                    if target_table == ATTACHMENT_TABLE_NAME
                    else PARSE_ASSET_TO_LITERATURE_COLUMN_MAP
                ),
            )
            if target_table != LITERATURE_TABLE_NAME:
                continue
            assignments = []
            params: list[object] = []
            structured_pairs = (
                ("parse_status", "structured_status"),
                ("normalized_structured_path", "structured_abs_path"),
                ("backend", "structured_backend"),
                ("parse_level", "structured_task_type"),
                ("updated_at", "structured_updated_at"),
            )
            for source_name, target_name in structured_pairs:
                target_physical = _resolve_physical_column(LITERATURE_TABLE_NAME, target_name)
                if target_physical not in _physical_table_columns(conn, LITERATURE_TABLE_NAME):
                    continue
                assignments.append(f"{_quote_identifier(target_physical)} = ?")
                value = row.get(source_name)
                params.append(None if pd.isna(value) else value)
            if assignments:
                params.append(uid_literature)
                conn.execute(
                    f"UPDATE {_quote_identifier(LITERATURE_TABLE_NAME)} SET {', '.join(assignments)} WHERE {_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'uid_literature'))} = ?",
                    tuple(params),
                )
    conn.execute(f"DROP TABLE IF EXISTS {_quote_identifier(PARSE_ASSET_TABLE_NAME)}")


def _migrate_public_runtime_projection_tables(conn: sqlite3.Connection) -> None:
    for object_name, column_map in (
        (READING_STATE_TABLE_NAME, READING_STATE_TO_LITERATURE_COLUMN_MAP),
        (READING_QUEUE_TABLE_NAME, READING_QUEUE_TO_LITERATURE_COLUMN_MAP),
        (FLOW_STATE_TABLE_NAME, FLOW_STATE_TO_LITERATURE_COLUMN_MAP),
    ):
        if _sqlite_object_type(conn, object_name) != "table":
            continue
        frame = pd.read_sql_query(f"SELECT * FROM {_quote_identifier(object_name)}", conn)
        frame = _logicalize_runtime_frame(object_name, frame)
        _update_runtime_summary_rows(
            conn,
            target_table=LITERATURE_TABLE_NAME,
            key_column="uid_literature",
            frame=frame,
            column_map=column_map,
        )
        conn.execute(f"DROP TABLE IF EXISTS {_quote_identifier(object_name)}")

    _migrate_public_parse_asset_table(conn)


def _runtime_projection_alias(table_name: str, logical_name: str) -> str:
    return _quote_identifier(_resolve_physical_column(table_name, logical_name))


def _refresh_runtime_projection_views(conn: sqlite3.Connection) -> None:
    for view_name in LEGACY_TRANSACTION_RELATION_VIEW_NAMES:
        conn.execute(f"DROP VIEW IF EXISTS {_quote_identifier(view_name)}")

    literature_uid = _qualified_physical_column(LITERATURE_TABLE_NAME, "uid_literature", "lit")
    literature_cite = _qualified_physical_column(LITERATURE_TABLE_NAME, "cite_key", "lit")
    literature_columns = _physical_table_columns(conn, LITERATURE_TABLE_NAME)
    attachment_columns = _physical_table_columns(conn, ATTACHMENT_TABLE_NAME)

    def _literature_projection(summary_name: str, default_sql: str = "''") -> str:
        physical_name = _resolve_physical_column(LITERATURE_TABLE_NAME, summary_name)
        if physical_name in literature_columns:
            return _qualified_physical_column(LITERATURE_TABLE_NAME, summary_name, "lit")
        return default_sql

    def _attachment_projection(summary_name: str, default_sql: str = "''") -> str:
        physical_name = _resolve_physical_column(ATTACHMENT_TABLE_NAME, summary_name)
        if physical_name in attachment_columns:
            return _qualified_physical_column(ATTACHMENT_TABLE_NAME, summary_name, "att")
        return default_sql

    reading_exprs: dict[str, str] = {
        "uid_literature": literature_uid,
        "cite_key": literature_cite,
    }
    for logical_name, summary_name in READING_STATE_TO_LITERATURE_COLUMN_MAP.items():
        reading_exprs[logical_name] = _literature_projection(summary_name)
    reading_select = ",\n            ".join(
        f"{expr} AS {_runtime_projection_alias(READING_STATE_TABLE_NAME, logical_name)}"
        for logical_name, expr in reading_exprs.items()
    )
    reading_filter = " OR ".join(
        [
            f"COALESCE({_literature_projection('阅读更新时间')}, '') <> ''",
            f"COALESCE({_literature_projection('阅读待预处理')}, '') <> ''",
            f"COALESCE({_literature_projection('阅读待泛读')}, '') <> ''",
            f"COALESCE({_literature_projection('阅读待研读')}, '') <> ''",
            f"COALESCE({_literature_projection('阅读已预处理')}, '') <> ''",
            f"COALESCE({_literature_projection('阅读已泛读')}, '') <> ''",
            f"COALESCE({_literature_projection('阅读已研读')}, '') <> ''",
        ]
    )
    _create_or_replace_view(
        conn,
        READING_STATE_TABLE_NAME,
        f"""
        SELECT
            {reading_select}
        FROM {_quote_identifier(LITERATURE_TABLE_NAME)} AS lit
        WHERE {reading_filter}
        """,
    )

    queue_exprs: dict[str, str] = {
        "uid_literature": literature_uid,
        "cite_key": literature_cite,
    }
    for logical_name, summary_name in READING_QUEUE_TO_LITERATURE_COLUMN_MAP.items():
        queue_exprs[logical_name] = _literature_projection(summary_name)
    queue_select = ",\n            ".join(
        f"{expr} AS {_runtime_projection_alias(READING_QUEUE_TABLE_NAME, logical_name)}"
        for logical_name, expr in queue_exprs.items()
    )
    queue_filter = " OR ".join(
        [
            f"COALESCE({_literature_projection('预处理更新时间')}, '') <> ''",
            f"COALESCE({_literature_projection('预处理阶段')}, '') <> ''",
            f"COALESCE({_literature_projection('预处理队列状态')}, '') <> ''",
            f"COALESCE({_literature_projection('预处理队列UID')}, '') <> ''",
        ]
    )
    _create_or_replace_view(
        conn,
        READING_QUEUE_TABLE_NAME,
        f"""
        SELECT
            {queue_select}
        FROM {_quote_identifier(LITERATURE_TABLE_NAME)} AS lit
        WHERE {queue_filter}
        """,
    )

    flow_exprs: dict[str, str] = {
        "uid_literature": literature_uid,
        "cite_key": literature_cite,
    }
    for logical_name, summary_name in FLOW_STATE_TO_LITERATURE_COLUMN_MAP.items():
        flow_exprs[logical_name] = _literature_projection(summary_name)
    flow_select = ",\n            ".join(
        f"{expr} AS {_runtime_projection_alias(FLOW_STATE_TABLE_NAME, logical_name)}"
        for logical_name, expr in flow_exprs.items()
    )
    flow_filter = " OR ".join(
        [
            f"COALESCE({_literature_projection('流程更新时间')}, '') <> ''",
            f"COALESCE({_literature_projection('流程节点编码')}, '') <> ''",
            f"COALESCE({_literature_projection('流程当前阶段')}, '') <> ''",
            f"COALESCE({_literature_projection('流程当前状态')}, '') <> ''",
        ]
    )
    _create_or_replace_view(
        conn,
        FLOW_STATE_TABLE_NAME,
        f"""
        SELECT
            {flow_select}
        FROM {_quote_identifier(LITERATURE_TABLE_NAME)} AS lit
        WHERE {flow_filter}
        """,
    )

    attachment_uid = _qualified_physical_column(ATTACHMENT_TABLE_NAME, "uid_attachment", "att")
    parse_select_literature = ",\n            ".join(
        [
            f"{_literature_projection('current_parse_asset_uid')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'asset_uid')}",
            f"{literature_uid} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'uid_literature')}",
            f"{literature_cite} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'cite_key')}",
            f"{_literature_projection('current_parse_uid_attachment')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'uid_attachment')}",
            f"{_literature_projection('current_parse_level')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'parse_level')}",
            f"{_literature_projection('current_parse_backend')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'backend')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'model_name')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'asset_dir')}",
            f"{_literature_projection('current_parse_path')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'normalized_structured_path')}",
            f"{_literature_projection('current_parse_markdown_path')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'reconstructed_markdown_path')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'linear_index_path')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'elements_path')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'chunks_jsonl_path')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'parse_record_path')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'quality_report_path')}",
            f"{_literature_projection('current_parse_status')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'parse_status')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'last_run_uid')}",
            f"1 AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'is_current')}",
            f"{_literature_projection('current_parse_updated_at')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'created_at')}",
            f"{_literature_projection('current_parse_updated_at')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'updated_at')}",
        ]
    )
    parse_select_attachment = ",\n            ".join(
        [
            f"{_attachment_projection('current_parse_asset_uid')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'asset_uid')}",
            f"{_qualified_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_literature', 'lnk')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'uid_literature')}",
            f"COALESCE({literature_cite}, '') AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'cite_key')}",
            f"{attachment_uid} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'uid_attachment')}",
            f"{_attachment_projection('current_parse_level')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'parse_level')}",
            f"{_attachment_projection('current_parse_backend')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'backend')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'model_name')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'asset_dir')}",
            f"{_attachment_projection('current_parse_path')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'normalized_structured_path')}",
            f"{_attachment_projection('current_parse_markdown_path')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'reconstructed_markdown_path')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'linear_index_path')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'elements_path')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'chunks_jsonl_path')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'parse_record_path')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'quality_report_path')}",
            f"{_attachment_projection('current_parse_status')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'parse_status')}",
            f"'' AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'last_run_uid')}",
            f"1 AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'is_current')}",
            f"{_attachment_projection('current_parse_updated_at')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'created_at')}",
            f"{_attachment_projection('current_parse_updated_at')} AS {_runtime_projection_alias(PARSE_ASSET_TABLE_NAME, 'updated_at')}",
        ]
    )
    parse_literature_filter = " OR ".join(
        [
            f"COALESCE({_literature_projection('current_parse_asset_uid')}, '') <> ''",
            f"COALESCE({_literature_projection('current_parse_status')}, '') <> ''",
            f"COALESCE({_literature_projection('current_parse_path')}, '') <> ''",
        ]
    )
    parse_attachment_filter = " OR ".join(
        [
            f"COALESCE({_attachment_projection('current_parse_asset_uid')}, '') <> ''",
            f"COALESCE({_attachment_projection('current_parse_status')}, '') <> ''",
            f"COALESCE({_attachment_projection('current_parse_path')}, '') <> ''",
        ]
    )
    _create_or_replace_view(
        conn,
        PARSE_ASSET_TABLE_NAME,
        f"""
        SELECT
            {parse_select_literature}
        FROM {_quote_identifier(LITERATURE_TABLE_NAME)} AS lit
        WHERE {parse_literature_filter}
        UNION ALL
        SELECT
            {parse_select_attachment}
        FROM {_quote_identifier(ATTACHMENT_TABLE_NAME)} AS att
        LEFT JOIN {_quote_identifier(ATTACHMENT_LINK_TABLE_NAME)} AS lnk
            ON lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_attachment'))} = {attachment_uid}
        LEFT JOIN {_quote_identifier(LITERATURE_TABLE_NAME)} AS lit
            ON lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'uid_literature'))} = lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_literature'))}
        WHERE ({parse_attachment_filter})
          AND COALESCE(lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_literature'))}, '') <> ''
        """,
    )


def _refresh_chinese_contract_views(conn: sqlite3.Connection) -> None:
    for view_name, (source_table_name, column_map) in CONTENTDB_CHINESE_CONTRACT_VIEWS.items():
        if _sqlite_object_type(conn, source_table_name) != "table":
            continue
        if _sqlite_object_type(conn, view_name) == "table":
            continue
        existing_columns = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({_quote_identifier(source_table_name)})")
        }
        selected_columns = []
        for old_name, new_name in column_map.items():
            source_column = _resolve_physical_column(source_table_name, old_name)
            if source_column not in existing_columns:
                continue
            display_name = _resolve_contract_view_alias(source_table_name, old_name, new_name)
            selected_columns.append(f"{_quote_identifier(source_column)} AS {_quote_identifier(display_name)}")
        if not selected_columns:
            continue
        select_sql = "SELECT\n            " + ",\n            ".join(selected_columns)
        select_sql += f"\n        FROM {_quote_identifier(source_table_name)}"
        _create_or_replace_view(conn, view_name, select_sql)


def _refresh_reading_state_views(conn: sqlite3.Connection) -> None:
    node_code_col = _qualified_physical_column(WORKSPACE_NODE_STATE_TABLE_NAME, "node_code")
    node_name_col = _qualified_physical_column(WORKSPACE_NODE_STATE_TABLE_NAME, "node_name")
    pending_col = _qualified_physical_column(WORKSPACE_NODE_STATE_TABLE_NAME, "pending_run")
    running_col = _qualified_physical_column(WORKSPACE_NODE_STATE_TABLE_NAME, "in_progress")
    completed_col = _qualified_physical_column(WORKSPACE_NODE_STATE_TABLE_NAME, "completed")
    gate_col = _qualified_physical_column(WORKSPACE_NODE_STATE_TABLE_NAME, "gate_status")
    last_task_col = _qualified_physical_column(WORKSPACE_NODE_STATE_TABLE_NAME, "last_task_uid")
    current_task_col = _qualified_physical_column(WORKSPACE_NODE_STATE_TABLE_NAME, "current_task_uid")
    next_node_col = _qualified_physical_column(WORKSPACE_NODE_STATE_TABLE_NAME, "next_node_code")
    failure_col = _qualified_physical_column(WORKSPACE_NODE_STATE_TABLE_NAME, "failure_reason")
    workspace_updated_col = _qualified_physical_column(WORKSPACE_NODE_STATE_TABLE_NAME, "updated_at")

    workspace_overview_sql = f"""
    SELECT
        {node_code_col} AS 节点编码,
        COALESCE({node_name_col}, '') AS 节点名称,
        COALESCE({pending_col}, 0) AS 待执行,
        COALESCE({running_col}, 0) AS 执行中,
        COALESCE({completed_col}, 0) AS 已完成,
        COALESCE({gate_col}, '') AS 闸门状态,
        COALESCE({last_task_col}, '') AS 最近任务,
        COALESCE({current_task_col}, '') AS 当前任务,
        COALESCE({next_node_col}, '') AS 下一节点,
        COALESCE({failure_col}, '') AS 失败原因,
        COALESCE({workspace_updated_col}, '') AS 更新时间
    FROM {WORKSPACE_NODE_STATE_TABLE_NAME}
    ORDER BY 更新时间 DESC, 节点编码
    """
    _create_or_replace_view(conn, WORKSPACE_NODE_OVERVIEW_VIEW_NAME, workspace_overview_sql)
    quoted_workspace_name = _quote_identifier(WORKSPACE_NODE_OVERVIEW_VIEW_NAME)
    for view_name, where_clause in WORKSPACE_NODE_FILTER_VIEWS:
        view_sql = f"""
        SELECT *
        FROM {quoted_workspace_name}
        WHERE {where_clause}
        ORDER BY 更新时间 DESC, 节点编码
        """
        _create_or_replace_view(conn, view_name, view_sql)

    flow_overview_sql = f"""
    WITH parse_summary AS (
        SELECT
            {_qualified_physical_column(PARSE_ASSET_TABLE_NAME, 'uid_literature')} AS uid_literature,
            MAX(CASE WHEN COALESCE({_qualified_physical_column(PARSE_ASSET_TABLE_NAME, 'is_current')}, 0) = 1 THEN {_qualified_physical_column(PARSE_ASSET_TABLE_NAME, 'parse_level')} ELSE '' END) AS current_parse_level,
            MAX(CASE WHEN COALESCE({_qualified_physical_column(PARSE_ASSET_TABLE_NAME, 'is_current')}, 0) = 1 THEN {_qualified_physical_column(PARSE_ASSET_TABLE_NAME, 'parse_status')} ELSE '' END) AS current_parse_status,
            MAX(CASE WHEN COALESCE({_qualified_physical_column(PARSE_ASSET_TABLE_NAME, 'is_current')}, 0) = 1 THEN {_qualified_physical_column(PARSE_ASSET_TABLE_NAME, 'structured_text_path')} ELSE '' END) AS current_structured_path
        FROM {_quote_identifier(PARSE_ASSET_TABLE_NAME)}
        GROUP BY uid_literature
    )
    SELECT
        fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'uid_literature'))} AS 文献标识,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'cite_key'))}, lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'cite_key'))}, '') AS 引文键,
        COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'title'))}, '') AS 标题,
        COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'first_author'))}, '') AS 第一作者,
        COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'year'))}, '') AS 年份,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'literature_role'))}, '') AS 文献角色,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'flow_track'))}, '') AS 流程轨道,
        COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'primary_attachment_name'))}, '') AS 主附件名称,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_stage_group'))}, '') AS 当前阶段组,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_stage'))}, '') AS 当前阶段,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_status'))}, '') AS 当前状态,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'next_stage'))}, '') AS 下一阶段,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'recommend_reason'))}, '') AS 推荐原因,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'failure_reason'))}, '') AS 失败原因,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'blocked_reason'))}, '') AS 阻塞原因,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'node_code'))}, '') AS 节点编码,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'parse_asset_uid'))}, '') AS 解析资产标识,
        COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'parse_state'))}, '') AS 解析状态,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'note_uid'))}, '') AS 标准笔记标识,
        COALESCE(parse.current_parse_status, '') AS 当前解析状态,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'is_current'))}, 1) AS 是否当前有效,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'is_executable'))}, 1) AS 是否可执行,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'last_task_uid'))}, '') AS 最近任务标识,
        COALESCE(fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'updated_at'))}, '') AS 更新时间
    FROM {_quote_identifier(FLOW_STATE_TABLE_NAME)} AS fs
    LEFT JOIN {_quote_identifier(LITERATURE_TABLE_NAME)} AS lit
        ON lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'uid_literature'))} = fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'uid_literature'))}
    LEFT JOIN parse_summary AS parse
        ON parse.uid_literature = fs.{_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'uid_literature'))}
    ORDER BY 更新时间 DESC, 年份 DESC, 引文键, 文献标识
    """
    _create_or_replace_view(conn, FLOW_STATE_OVERVIEW_VIEW_NAME, flow_overview_sql)
    quoted_flow_name = _quote_identifier(FLOW_STATE_OVERVIEW_VIEW_NAME)
    for view_name, where_clause in FLOW_STATE_FILTER_VIEWS:
        view_sql = f"""
        SELECT *
        FROM {quoted_flow_name}
        WHERE {where_clause}
        ORDER BY 更新时间 DESC, 年份 DESC, 引文键, 文献标识
        """
        _create_or_replace_view(conn, view_name, view_sql)
    for view_name, where_clause in FLOW_STAGE_LIST_VIEWS:
        view_sql = f"""
        SELECT *
        FROM {quoted_flow_name}
        WHERE {where_clause}
        ORDER BY 更新时间 DESC, 年份 DESC, 引文键, 文献标识
        """
        _create_or_replace_view(conn, view_name, view_sql)

    flow_transaction_name_case = _build_transaction_name_case("节点编码")
    queue_transaction_name_case = _build_transaction_name_case("qb.事务编号")
    queue_transaction_code_case = "CASE\n"
    for node_code, _node_label in TRANSACTION_RELATION_NODE_LABELS:
        queue_transaction_code_case += (
            f"            WHEN COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'source_affair'))}, '') = '{node_code}' THEN '{node_code}'\n"
        )
    for node_code, _node_label in TRANSACTION_RELATION_NODE_LABELS:
        queue_transaction_code_case += (
            f"            WHEN COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'stage'))}, '') = '{node_code}' THEN '{node_code}'\n"
        )
    queue_transaction_code_case += "            ELSE ''\n        END"
    queue_status_case = f"""
        CASE
            WHEN COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'queue_status'))}, '') IN ('queued', 'pending', 'ready') THEN '待处理'
            WHEN COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'queue_status'))}, '') IN ('running', 'processing', 'in_progress') THEN '处理中'
            WHEN COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'queue_status'))}, '') IN ('blocked', 'missing_attachment') THEN '阻塞'
            WHEN COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'queue_status'))}, '') IN ('failed', 'error') THEN '失败'
            WHEN COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'queue_status'))}, '') IN ('done', 'completed', 'succeeded', 'success') THEN '已完成'
            ELSE COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'queue_status'))}, '')
        END
    """
    transaction_overview_sql = f"""
    WITH flow_base AS (
        SELECT
            节点编码 AS 事务编号,
            {flow_transaction_name_case} AS 事务名称,
            文献标识,
            引文键,
            标题,
            第一作者,
            年份,
            文献角色,
            流程轨道,
            主附件名称,
            当前阶段组,
            当前阶段,
            当前状态,
            下一阶段,
            推荐原因,
            失败原因,
            阻塞原因,
            解析资产标识,
            标准笔记标识,
            解析状态,
            当前解析状态,
            是否当前有效,
            是否可执行,
            最近任务标识,
            更新时间
        FROM {quoted_flow_name}
        WHERE IFNULL(节点编码, '') <> ''
    ),
    queue_base AS (
        SELECT
            {queue_transaction_code_case} AS 事务编号,
            COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'uid_literature'))}, q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'uid_literature'))}) AS 文献标识,
            COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'cite_key'))}, lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'cite_key'))}, '') AS 引文键,
            COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'title'))}, '') AS 标题,
            COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'first_author'))}, '') AS 第一作者,
            COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'year'))}, '') AS 年份,
            '' AS 文献角色,
            CASE
                WHEN COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'stage'))}, '') IN ('A060', 'A070', 'A110', 'A120', 'A130') THEN '综述主链'
                WHEN COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'stage'))}, '') IN ('A140', 'A150', 'A160', 'A170', 'A105') THEN '普通主链'
                ELSE ''
            END AS 流程轨道,
            COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'primary_attachment_name'))}, '') AS 主附件名称,
            '队列表' AS 当前阶段组,
            COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'stage'))}, '') AS 当前阶段,
            {queue_status_case} AS 当前状态,
            COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'preferred_next_stage'))}, '') AS 下一阶段,
            COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'recommended_reason'))}, '') AS 推荐原因,
            COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'preprocess_failure_reason'))}, '') AS 失败原因,
            CASE
                WHEN COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'queue_status'))}, '') IN ('blocked', 'missing_attachment')
                THEN COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'preprocess_failure_reason'))}, '')
                ELSE ''
            END AS 阻塞原因,
            COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'current_parse_asset_uid'))}, '') AS 解析资产标识,
            COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'standard_note_uid'))}, '') AS 标准笔记标识,
            COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'parse_state'))}, '') AS 解析状态,
            COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'current_parse_status'))}, '') AS 当前解析状态,
            COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'is_current'))}, 1) AS 是否当前有效,
            CASE
                WHEN COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'queue_status'))}, '') IN ('blocked', 'missing_attachment', 'failed', 'error') THEN 0
                ELSE 1
            END AS 是否可执行,
            COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'run_uid'))}, '') AS 最近任务标识,
            COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'updated_at'))}, '') AS 更新时间
        FROM {_quote_identifier(READING_QUEUE_TABLE_NAME)} AS q
        LEFT JOIN {_quote_identifier(LITERATURE_TABLE_NAME)} AS lit
            ON lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'uid_literature'))} = q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'uid_literature'))}
        WHERE CAST(COALESCE(q.{_quote_identifier(_resolve_physical_column(READING_QUEUE_TABLE_NAME, 'is_current'))}, '1') AS INTEGER) = 1
    )
    SELECT *
    FROM flow_base
    UNION ALL
    SELECT
        qb.事务编号,
        {queue_transaction_name_case} AS 事务名称,
        qb.文献标识,
        qb.引文键,
        qb.标题,
        qb.第一作者,
        qb.年份,
        qb.文献角色,
        qb.流程轨道,
        qb.主附件名称,
        qb.当前阶段组,
        qb.当前阶段,
        qb.当前状态,
        qb.下一阶段,
        qb.推荐原因,
        qb.失败原因,
        qb.阻塞原因,
        qb.解析资产标识,
        qb.标准笔记标识,
        qb.解析状态,
        qb.当前解析状态,
        qb.是否当前有效,
        qb.是否可执行,
        qb.最近任务标识,
        qb.更新时间
    FROM queue_base AS qb
    WHERE IFNULL(qb.事务编号, '') <> ''
      AND NOT EXISTS (
          SELECT 1
          FROM flow_base AS fb
          WHERE fb.事务编号 = qb.事务编号
            AND COALESCE(fb.文献标识, '') = COALESCE(qb.文献标识, '')
            AND COALESCE(fb.引文键, '') = COALESCE(qb.引文键, '')
      )
    ORDER BY 事务编号, 更新时间 DESC, 年份 DESC, 引文键, 文献标识
    """
    legacy_stage_name_case = """
    CASE 当前阶段
        WHEN 'A040' THEN '文献检索与入库事务'
        WHEN 'A060' THEN '预处理优先级生成事务'
        WHEN 'A070' THEN '统一文献预处理执行事务'
        WHEN 'A110' THEN '综述文献候选视图构建事务'
        WHEN 'A120' THEN '综述参考文献预处理与笔记骨架事务'
        WHEN 'A130' THEN '综述文献研读事务'
        WHEN 'A140' THEN '普通文献候选视图构建事务'
        WHEN 'A150' THEN '普通文献泛读事务'
        WHEN 'A160' THEN '普通文献研读候选视图构建事务'
        WHEN 'A170' THEN '文献批判性研读事务'
        WHEN 'A180' THEN '研究脉络梳理事务'
        WHEN 'A190' THEN '创新点凝练事务'
        WHEN 'A105' THEN '文献批判性研读与标准笔记事务'
        ELSE 当前阶段
    END
    """
    _create_or_replace_view(
        conn,
        TRANSACTION_RELATION_OVERVIEW_VIEW_NAME,
        f"""
        SELECT
            事务编号 AS 事务编码,
            事务编号,
            事务名称,
            文献标识,
            引文键,
            标题,
            第一作者,
            年份,
            文献角色,
            流程轨道,
            主附件名称,
            当前阶段组,
            {legacy_stage_name_case} AS 当前阶段,
            当前状态,
            下一阶段,
            推荐原因,
            失败原因,
            阻塞原因,
            解析资产标识,
            标准笔记标识,
            解析状态,
            当前解析状态,
            是否当前有效,
            是否可执行,
            最近任务标识,
            更新时间
        FROM (
            {transaction_overview_sql}
        ) AS tx
        """,
    )
    quoted_transaction_name = _quote_identifier(TRANSACTION_RELATION_OVERVIEW_VIEW_NAME)
    for view_name, node_code in TRANSACTION_RELATION_FILTER_VIEWS:
        view_sql = f"""
        SELECT *
        FROM {quoted_transaction_name}
        WHERE 事务编号 = '{node_code}'
        ORDER BY 更新时间 DESC, 年份 DESC, 引文键, 文献标识
        """
        _create_or_replace_view(conn, view_name, view_sql)

    workflow_overview_sql = f"""
    SELECT *
    FROM (
        SELECT '节点推进' AS 类别, COUNT(1) AS 数量, '执行中' AS 状态
                FROM {WORKSPACE_NODE_STATE_TABLE_NAME}
                WHERE IFNULL({_quote_identifier(_resolve_physical_column(WORKSPACE_NODE_STATE_TABLE_NAME, 'in_progress'))}, 0) = 1
        UNION ALL
        SELECT
                        CASE WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'flow_track'))}, '') = '综述主链' THEN '综述链' ELSE '普通阅读链' END AS 类别,
            COUNT(1) AS 数量,
            CASE
                                WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_stage'))}, '') = '综述候选构建' THEN '待筛选'
                                WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_stage'))}, '') = '综述正文解析' THEN '待解析'
                                WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_stage'))}, '') = '综述参考扩展' THEN '待参考扩展'
                                WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_stage'))}, '') = '综述综合研读' THEN CASE WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_status'))}, '') = '处理中' THEN '阅读中' ELSE '待阅读' END
                                WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_stage'))}, '') = '普通文献预处理' THEN CASE WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_status'))}, '') = '阻塞' THEN '补件待办' ELSE '待预处理' END
                                WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_stage'))}, '') = '普通文献泛读' THEN CASE WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_status'))}, '') = '处理中' THEN '泛读中' ELSE '待泛读' END
                                WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_stage'))}, '') = '普通文献研读候选视图构建' THEN '待研读候选构建'
                                WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_stage'))}, '') = '批判性研读' THEN '待研读'
                                WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_stage'))}, '') = '批判性研读' THEN CASE WHEN COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_status'))}, '') = '处理中' THEN '研读中' ELSE '待批判性研读' END
                                ELSE COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_status'))}, '未归类')
            END AS 状态
        FROM {_quote_identifier(FLOW_STATE_TABLE_NAME)}
                WHERE COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'is_current'))}, 1) = 1
                    AND COALESCE({_quote_identifier(_resolve_physical_column(FLOW_STATE_TABLE_NAME, 'current_status'))}, '') IN ('待处理', '处理中', '阻塞')
        GROUP BY 类别, 状态
    )
    WHERE 数量 > 0
    """
    _create_or_replace_view(conn, "工作流总览视图", workflow_overview_sql)

    attachment_overview_sql = f"""
    SELECT
        lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_attachment_link'))} AS 附件关联标识,
        lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_literature'))} AS 文献标识,
        COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'cite_key'))}, '') AS 引文键,
        COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'title'))}, '') AS 文献标题,
        lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_attachment'))} AS 附件标识,
        COALESCE(att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'attachment_name'))}, '') AS 附件名称,
        COALESCE(att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'storage_path'))}, '') AS 当前存储路径,
        COALESCE(att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'source_path'))}, '') AS 原始来源路径,
        COALESCE(att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'status'))}, '') AS 附件状态,
        COALESCE(lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'link_role'))}, '') AS 关联角色,
        COALESCE(lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'is_primary'))}, 0) AS 是否主附件,
        COALESCE(lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'updated_at'))}, att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'updated_at'))}, '') AS 更新时间
    FROM {ATTACHMENT_LINK_TABLE_NAME} AS lnk
    LEFT JOIN {ATTACHMENT_TABLE_NAME} AS att
        ON att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'uid_attachment'))} = lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_attachment'))}
    LEFT JOIN {_quote_identifier(LITERATURE_TABLE_NAME)} AS lit
        ON lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'uid_literature'))} = lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_literature'))}
    ORDER BY 更新时间 DESC, 引文键, 附件名称
    """
    _create_or_replace_view(conn, "文献附件总视图", attachment_overview_sql)

    primary_attachment_view_sql = """
    SELECT *
    FROM "文献附件总视图"
    WHERE IFNULL(是否主附件, 0) = 1
    ORDER BY 更新时间 DESC, 引文键
    """
    _create_or_replace_view(conn, "文献主附件视图", primary_attachment_view_sql)

    tag_overview_sql = f"""
    SELECT
        t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'uid_tag'))} AS 标签标识,
        COALESCE(t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag_display'))}, t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag'))}, '') AS 标签显示名,
        COALESCE(t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag_norm'))}, '') AS 标签规范名,
        COALESCE(t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag_group'))}, '') AS 标签分组,
        COUNT(DISTINCT lnk.{_quote_identifier(_resolve_physical_column(LITERATURE_TAG_TABLE_NAME, 'uid_literature'))}) AS 关联文献数,
        COALESCE(MAX(lnk.{_quote_identifier(_resolve_physical_column(LITERATURE_TAG_TABLE_NAME, 'updated_at'))}), MAX(t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'updated_at'))}), '') AS 更新时间
    FROM {TAG_TABLE_NAME} AS t
    LEFT JOIN {_quote_identifier(LITERATURE_TAG_TABLE_NAME)} AS lnk
        ON lnk.{_quote_identifier(_resolve_physical_column(LITERATURE_TAG_TABLE_NAME, 'tag_norm'))} = t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag_norm'))}
    GROUP BY t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'uid_tag'))}, t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag_display'))}, t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag'))}, t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag_norm'))}, t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag_group'))}
    ORDER BY 关联文献数 DESC, 标签显示名
    """
    _create_or_replace_view(conn, "标签总表", tag_overview_sql)

    literature_tag_overview_sql = f"""
    SELECT
        lnk.{_quote_identifier(_resolve_physical_column(LITERATURE_TAG_TABLE_NAME, 'uid_literature'))} AS 文献标识,
        COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'cite_key'))}, '') AS 引文键,
        COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'title'))}, '') AS 文献标题,
        t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'uid_tag'))} AS 标签标识,
        COALESCE(t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag_display'))}, t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag'))}, lnk.{_quote_identifier(_resolve_physical_column(LITERATURE_TAG_TABLE_NAME, 'tag'))}) AS 标签显示名,
        COALESCE(t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag_group'))}, '') AS 标签分组,
        COALESCE(lnk.{_quote_identifier(_resolve_physical_column(LITERATURE_TAG_TABLE_NAME, 'source_type'))}, '') AS 来源类型,
        COALESCE(lnk.{_quote_identifier(_resolve_physical_column(LITERATURE_TAG_TABLE_NAME, 'updated_at'))}, '') AS 更新时间
    FROM {_quote_identifier(LITERATURE_TAG_TABLE_NAME)} AS lnk
    LEFT JOIN {TAG_TABLE_NAME} AS t
        ON t.{_quote_identifier(_resolve_physical_column(TAG_TABLE_NAME, 'tag_norm'))} = lnk.{_quote_identifier(_resolve_physical_column(LITERATURE_TAG_TABLE_NAME, 'tag_norm'))}
    LEFT JOIN {_quote_identifier(LITERATURE_TABLE_NAME)} AS lit
        ON lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'uid_literature'))} = lnk.{_quote_identifier(_resolve_physical_column(LITERATURE_TAG_TABLE_NAME, 'uid_literature'))}
    ORDER BY 更新时间 DESC, 引文键, 标签显示名
    """
    _create_or_replace_view(conn, "文献标签关联总视图", literature_tag_overview_sql)

    author_overview_sql = f"""
    SELECT
        a.{_quote_identifier(_resolve_physical_column(AUTHOR_TABLE_NAME, 'uid_author'))} AS 作者标识,
        COALESCE(a.{_quote_identifier(_resolve_physical_column(AUTHOR_TABLE_NAME, 'display_name'))}, '') AS 作者姓名,
        COALESCE(a.{_quote_identifier(_resolve_physical_column(AUTHOR_TABLE_NAME, 'normalized_name'))}, '') AS 作者规范名,
        COUNT(DISTINCT la.{_quote_identifier(_resolve_physical_column(AUTHOR_LINK_TABLE_NAME, 'uid_literature'))}) AS 关联文献数,
        COALESCE(MAX(la.{_quote_identifier(_resolve_physical_column(AUTHOR_LINK_TABLE_NAME, 'updated_at'))}), MAX(a.{_quote_identifier(_resolve_physical_column(AUTHOR_TABLE_NAME, 'updated_at'))}), '') AS 更新时间
    FROM {AUTHOR_TABLE_NAME} AS a
    LEFT JOIN {AUTHOR_LINK_TABLE_NAME} AS la
        ON la.{_quote_identifier(_resolve_physical_column(AUTHOR_LINK_TABLE_NAME, 'uid_author'))} = a.{_quote_identifier(_resolve_physical_column(AUTHOR_TABLE_NAME, 'uid_author'))}
    GROUP BY a.{_quote_identifier(_resolve_physical_column(AUTHOR_TABLE_NAME, 'uid_author'))}, a.{_quote_identifier(_resolve_physical_column(AUTHOR_TABLE_NAME, 'display_name'))}, a.{_quote_identifier(_resolve_physical_column(AUTHOR_TABLE_NAME, 'normalized_name'))}
    ORDER BY 关联文献数 DESC, 作者姓名
    """
    _create_or_replace_view(conn, "作者总表", author_overview_sql)

    literature_author_overview_sql = f"""
    SELECT
        la.{_quote_identifier(_resolve_physical_column(AUTHOR_LINK_TABLE_NAME, 'uid_literature'))} AS 文献标识,
        COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'cite_key'))}, '') AS 引文键,
        COALESCE(lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'title'))}, '') AS 文献标题,
        la.{_quote_identifier(_resolve_physical_column(AUTHOR_LINK_TABLE_NAME, 'uid_author'))} AS 作者标识,
        COALESCE(la.{_quote_identifier(_resolve_physical_column(AUTHOR_LINK_TABLE_NAME, 'display_name'))}, a.{_quote_identifier(_resolve_physical_column(AUTHOR_TABLE_NAME, 'display_name'))}, '') AS 作者姓名,
        COALESCE(la.{_quote_identifier(_resolve_physical_column(AUTHOR_LINK_TABLE_NAME, 'author_order'))}, 0) AS 作者顺序,
        COALESCE(la.{_quote_identifier(_resolve_physical_column(AUTHOR_LINK_TABLE_NAME, 'is_first_author'))}, 0) AS 是否第一作者,
        COALESCE(la.{_quote_identifier(_resolve_physical_column(AUTHOR_LINK_TABLE_NAME, 'updated_at'))}, '') AS 更新时间
    FROM {AUTHOR_LINK_TABLE_NAME} AS la
    LEFT JOIN {AUTHOR_TABLE_NAME} AS a
        ON a.{_quote_identifier(_resolve_physical_column(AUTHOR_TABLE_NAME, 'uid_author'))} = la.{_quote_identifier(_resolve_physical_column(AUTHOR_LINK_TABLE_NAME, 'uid_author'))}
    LEFT JOIN {_quote_identifier(LITERATURE_TABLE_NAME)} AS lit
        ON lit.{_quote_identifier(_resolve_physical_column(LITERATURE_TABLE_NAME, 'uid_literature'))} = la.{_quote_identifier(_resolve_physical_column(AUTHOR_LINK_TABLE_NAME, 'uid_literature'))}
    ORDER BY 更新时间 DESC, 引文键, 作者顺序
    """
    _create_or_replace_view(conn, "文献作者关联总视图", literature_author_overview_sql)

def _refresh_legacy_attachment_projections(conn: sqlite3.Connection) -> None:
    return


def _attachment_entity_uid(
    *,
    checksum: str,
    storage_path: str,
    source_path: str,
    attachment_name: str,
) -> str:
    token = checksum or storage_path or source_path or attachment_name
    normalized = str(token or "").strip().lower()
    return f"att-{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"


def _attachment_link_uid(uid_literature: str, uid_attachment: str, legacy_uid_attachment: str) -> str:
    token = legacy_uid_attachment or f"{uid_literature}|{uid_attachment}"
    normalized = str(token or "").strip().lower()
    return f"attlnk-{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"


def _build_attachment_normalized_frames(legacy_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    attachment_columns = [
        "uid_attachment",
        "attachment_name",
        "attachment_type",
        "file_ext",
        "storage_path",
        "source_path",
        "checksum",
        "status",
        "created_at",
        "updated_at",
    ]
    link_columns = [
        "uid_attachment_link",
        "uid_literature",
        "uid_attachment",
        "link_role",
        "is_primary",
        "source_type",
        "legacy_uid_attachment",
        "created_at",
        "updated_at",
    ]
    if legacy_df is None or legacy_df.empty:
        return pd.DataFrame(columns=attachment_columns), pd.DataFrame(columns=link_columns)

    attachment_rows_by_uid: dict[str, dict[str, object]] = {}
    link_rows: list[dict[str, object]] = []
    now = _utc_now_iso()

    for _, row in legacy_df.fillna("").iterrows():
        uid_literature = str(row.get("uid_literature") or "").strip()
        if not uid_literature:
            continue
        checksum = str(row.get("checksum") or "").strip()
        storage_path = str(row.get("storage_path") or "").strip()
        source_path = str(row.get("source_path") or "").strip()
        attachment_name = str(row.get("attachment_name") or "").strip()
        if not any([checksum, storage_path, source_path, attachment_name]):
            continue

        uid_attachment = _attachment_entity_uid(
            checksum=checksum,
            storage_path=storage_path,
            source_path=source_path,
            attachment_name=attachment_name,
        )
        existing_attachment_row = attachment_rows_by_uid.get(uid_attachment, {})
        attachment_rows_by_uid[uid_attachment] = {
            "uid_attachment": uid_attachment,
            "attachment_name": attachment_name or str(existing_attachment_row.get("attachment_name") or ""),
            "attachment_type": str(row.get("attachment_type") or existing_attachment_row.get("attachment_type") or "").strip(),
            "file_ext": str(row.get("file_ext") or existing_attachment_row.get("file_ext") or "").strip(),
            "storage_path": storage_path or str(existing_attachment_row.get("storage_path") or ""),
            "source_path": source_path or str(existing_attachment_row.get("source_path") or ""),
            "checksum": checksum or str(existing_attachment_row.get("checksum") or ""),
            "status": str(row.get("status") or existing_attachment_row.get("status") or "available").strip() or "available",
            "created_at": str(existing_attachment_row.get("created_at") or row.get("created_at") or now).strip() or now,
            "updated_at": str(row.get("updated_at") or existing_attachment_row.get("updated_at") or now).strip() or now,
        }

        legacy_uid_attachment = str(row.get("uid_attachment") or "").strip()
        link_rows.append(
            {
                "uid_attachment_link": _attachment_link_uid(uid_literature, uid_attachment, legacy_uid_attachment),
                "uid_literature": uid_literature,
                "uid_attachment": uid_attachment,
                "link_role": str(row.get("attachment_type") or "attached").strip() or "attached",
                "is_primary": int(pd.to_numeric(row.get("is_primary"), errors="coerce") or 0),
                "source_type": "legacy_literature_attachments",
                "legacy_uid_attachment": legacy_uid_attachment,
                "created_at": str(row.get("created_at") or now).strip() or now,
                "updated_at": str(row.get("updated_at") or now).strip() or now,
            }
        )

    attachments_df = pd.DataFrame(list(attachment_rows_by_uid.values()), columns=attachment_columns)
    links_df = pd.DataFrame(link_rows, columns=link_columns)
    if not links_df.empty:
        links_df = links_df.sort_values(
            by=["uid_literature", "uid_attachment", "is_primary", "updated_at"],
            ascending=[True, True, False, False],
            na_position="last",
        )
        links_df = links_df.drop_duplicates(subset=["uid_literature", "uid_attachment"], keep="first").reset_index(drop=True)
    return attachments_df, links_df


def _build_legacy_attachment_projection(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        f"""
        SELECT
            COALESCE(lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'legacy_uid_attachment'))}, lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_attachment_link'))}, att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'uid_attachment'))}) AS uid_attachment,
            lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_literature'))} AS uid_literature,
            att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'attachment_name'))} AS attachment_name,
            COALESCE(NULLIF(lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'link_role'))}, ''), att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'attachment_type'))}) AS attachment_type,
            att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'file_ext'))} AS file_ext,
            att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'storage_path'))} AS storage_path,
            att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'source_path'))} AS source_path,
            att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'checksum'))} AS checksum,
            COALESCE(lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'is_primary'))}, 0) AS is_primary,
            att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'status'))} AS status,
            COALESCE(lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'created_at'))}, att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'created_at'))}) AS created_at,
            COALESCE(lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'updated_at'))}, att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'updated_at'))}) AS updated_at
        FROM {ATTACHMENT_LINK_TABLE_NAME} AS lnk
        LEFT JOIN {ATTACHMENT_TABLE_NAME} AS att
            ON att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'uid_attachment'))} = lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_attachment'))}
        ORDER BY lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'uid_literature'))}, COALESCE(lnk.{_quote_identifier(_resolve_physical_column(ATTACHMENT_LINK_TABLE_NAME, 'is_primary'))}, 0) DESC, att.{_quote_identifier(_resolve_physical_column(ATTACHMENT_TABLE_NAME, 'attachment_name'))}
        """,
        conn,
    )


def _migrate_and_drop_legacy_attachment_table(conn: sqlite3.Connection) -> None:
    if _sqlite_object_type(conn, "literature_attachments") != "table":
        return

    attachment_count = conn.execute(f"SELECT COUNT(1) FROM {ATTACHMENT_TABLE_NAME}").fetchone()
    link_count = conn.execute(f"SELECT COUNT(1) FROM {ATTACHMENT_LINK_TABLE_NAME}").fetchone()
    attachment_total = int((attachment_count or [0])[0] or 0)
    link_total = int((link_count or [0])[0] or 0)

    if attachment_total == 0 and link_total == 0:
        legacy_df = pd.read_sql_query("SELECT * FROM literature_attachments", conn)
        if not legacy_df.empty:
            attachments_df, links_df = _build_attachment_normalized_frames(legacy_df)
            _replace_table_rows(conn, ATTACHMENT_TABLE_NAME, attachments_df)
            _replace_table_rows(conn, ATTACHMENT_LINK_TABLE_NAME, links_df)

    conn.execute('DROP TABLE IF EXISTS "literature_attachments"')


def _sync_tag_entities(conn: sqlite3.Connection) -> None:
    if _sqlite_object_type(conn, LITERATURE_TAG_TABLE_NAME) != "table":
        return

    tag_links_df = pd.read_sql_query(f"SELECT * FROM {_quote_identifier(LITERATURE_TAG_TABLE_NAME)}", conn)
    if tag_links_df.empty:
        _replace_table_rows(conn, TAG_TABLE_NAME, pd.DataFrame(columns=list(TAG_REQUIRED_COLUMNS.keys())))
        return

    now = _utc_now_iso()
    rows_by_uid: dict[str, dict[str, object]] = {}
    for _, row in tag_links_df.fillna("").iterrows():
        tag = str(row.get("tag") or "").strip()
        tag_norm = str(row.get("tag_norm") or tag).strip().lower()
        if not tag_norm:
            continue
        uid_tag = _stable_tag_uid(tag_norm)
        rows_by_uid[uid_tag] = {
            "uid_tag": uid_tag,
            "tag": tag or tag_norm,
            "tag_norm": tag_norm,
            "tag_display": tag or tag_norm,
            "tag_group": tag.split("/", 1)[0] if "/" in tag else "",
            "created_at": str(row.get("created_at") or now).strip() or now,
            "updated_at": str(row.get("updated_at") or now).strip() or now,
        }

    tags_df = pd.DataFrame(list(rows_by_uid.values()), columns=list(TAG_REQUIRED_COLUMNS.keys()))
    _replace_table_rows(conn, TAG_TABLE_NAME, tags_df)


def _sync_author_entities(conn: sqlite3.Connection) -> None:
    if _sqlite_object_type(conn, LITERATURE_TABLE_NAME) != "table":
        return

    literature_columns = _physical_table_columns(conn, LITERATURE_TABLE_NAME)
    authors_column = "作者串" if "作者串" in literature_columns else "authors"
    created_column = "创建时间" if "创建时间" in literature_columns else "created_at"
    updated_column = "更新时间" if "更新时间" in literature_columns else "updated_at"
    if authors_column not in literature_columns:
        return
    uid_literature_column = resolve_content_physical_column(LITERATURE_TABLE_NAME, "uid_literature")
    literature_df = pd.read_sql_query(
        f"SELECT {_quote_identifier(uid_literature_column)} AS uid_literature, {_quote_identifier(authors_column)} AS authors, {_quote_identifier(created_column)} AS created_at, {_quote_identifier(updated_column)} AS updated_at FROM {_quote_identifier(LITERATURE_TABLE_NAME)}",
        conn,
    )
    if literature_df.empty:
        _replace_table_rows(conn, AUTHOR_TABLE_NAME, pd.DataFrame(columns=list(AUTHOR_REQUIRED_COLUMNS.keys())))
        _replace_table_rows(conn, AUTHOR_LINK_TABLE_NAME, pd.DataFrame(columns=list(AUTHOR_LINK_REQUIRED_COLUMNS.keys())))
        return

    now = _utc_now_iso()
    author_rows_by_uid: dict[str, dict[str, object]] = {}
    author_link_rows: list[dict[str, object]] = []
    for _, row in literature_df.fillna("").iterrows():
        uid_literature = str(row.get("uid_literature") or "").strip()
        if not uid_literature:
            continue
        for index, author_name in enumerate(_split_author_values(row.get("authors")), start=1):
            cleaned_author_name, _ = _clean_author_display_name(author_name)
            normalized_name = _normalize_person_name(cleaned_author_name)
            if not normalized_name:
                continue
            author_meta = _classify_author_display_name(cleaned_author_name or author_name)
            canonical_name = str(author_meta.get("标准作者名") or cleaned_author_name or author_name).strip()
            display_name = cleaned_author_name or str(author_name or "").strip()
            uid_author = _stable_author_uid(normalized_name)
            surname, given_names = _split_author_name_components(canonical_name or display_name)
            author_rows_by_uid[uid_author] = {
                "uid_author": uid_author,
                "display_name": display_name,
                "normalized_name": normalized_name,
                "surname": surname,
                "given_names": given_names,
                "标准作者名": str(author_meta.get("标准作者名") or ""),
                "作者类型": str(author_meta.get("作者类型") or "个人作者"),
                "作者质量标记": str(author_meta.get("作者质量标记") or ""),
                "orcid": "",
                "source_type": "文献主表.authors",
                "created_at": str(row.get("created_at") or now).strip() or now,
                "updated_at": str(row.get("updated_at") or now).strip() or now,
            }
            author_link_rows.append(
                {
                    "uid_literature_author": _stable_author_link_uid(uid_literature, uid_author, index),
                    "uid_literature": uid_literature,
                    "uid_author": uid_author,
                    "author_order": index,
                    "is_first_author": 1 if index == 1 else 0,
                    "is_corresponding": 0,
                    "display_name": display_name,
                    "source_type": "文献主表.authors",
                    "created_at": str(row.get("created_at") or now).strip() or now,
                    "updated_at": str(row.get("updated_at") or now).strip() or now,
                }
            )

    authors_df = pd.DataFrame(list(author_rows_by_uid.values()), columns=list(AUTHOR_REQUIRED_COLUMNS.keys()))
    links_df = pd.DataFrame(author_link_rows, columns=list(AUTHOR_LINK_REQUIRED_COLUMNS.keys()))
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        _replace_table_rows(conn, AUTHOR_TABLE_NAME, authors_df)
        try:
            _replace_table_rows(conn, AUTHOR_LINK_TABLE_NAME, pd.DataFrame(columns=list(AUTHOR_LINK_REQUIRED_COLUMNS.keys())))
            _replace_table_rows(conn, AUTHOR_LINK_TABLE_NAME, links_df)
        except Exception:
            # 兼容历史库：若外键契约不一致，则保留作者主表并跳过关联表重建。
            pass
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _known_contentdb_table_has_rows(conn: sqlite3.Connection, table_name: str) -> bool:
    if _sqlite_object_type(conn, table_name) != "table":
        return False
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table_name)}").fetchone()
    except sqlite3.Error:
        return True
    return bool(row and int(row[0] or 0) > 0)


def _enforce_empty_chinese_physical_schema(conn: sqlite3.Connection) -> None:
    """在空库初始化时重建中文物理字段 schema。"""

    tracked_tables = (
        LITERATURE_TABLE_NAME,
        ATTACHMENT_TABLE_NAME,
        ATTACHMENT_LINK_TABLE_NAME,
        AUTHOR_TABLE_NAME,
        AUTHOR_LINK_TABLE_NAME,
        TAG_TABLE_NAME,
        LITERATURE_TAG_TABLE_NAME,
        PARSE_ASSET_TABLE_NAME,
        TRANSLATION_ASSET_TABLE_NAME,
        CHUNK_SET_TABLE_NAME,
        CHUNK_TABLE_NAME,
        KNOWLEDGE_NOTES_TABLE_NAME,
        KNOWLEDGE_LINK_TABLE_NAME,
        KNOWLEDGE_EVIDENCE_TABLE_NAME,
        WORKSPACE_NODE_STATE_TABLE_NAME,
        FLOW_STATE_TABLE_NAME,
        READING_STATE_TABLE_NAME,
        REVIEW_STATE_TABLE_NAME,
        "literature_reading_queue",
        KNOWLEDGE_INDEX_TABLE_NAME,
        KNOWLEDGE_ATTACHMENT_TABLE_NAME,
    )
    if any(_known_contentdb_table_has_rows(conn, table_name) for table_name in tracked_tables):
        return

    all_views = [
        str(row[0]).strip()
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
        if row and str(row[0]).strip()
    ]
    for view_name in all_views:
        conn.execute(f"DROP VIEW IF EXISTS {_quote_identifier(view_name)}")

    conn.execute("PRAGMA foreign_keys=OFF")
    for table_name in tracked_tables:
        if _sqlite_object_type(conn, table_name) == "table":
            conn.execute(f"DROP TABLE IF EXISTS {_quote_identifier(table_name)}")

    conn.executescript(
        '''
        CREATE TABLE IF NOT EXISTS "文献主表" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            "uid_文献" TEXT UNIQUE,
            "题录键" TEXT,
            bib_doi TEXT,
            bib_isbn TEXT,
            bib_issn TEXT,
            bib_entry_type TEXT,
            bib_orig_entry_type TEXT,
            bib_journal TEXT,
            bib_booktitle TEXT,
            bib_pages TEXT,
            bib_volume TEXT,
            bib_number TEXT,
            bib_month TEXT,
            bib_publisher TEXT,
            bib_editor TEXT,
            bib_school TEXT,
            bib_author TEXT,
            bib_file TEXT,
            bib_url TEXT,
            bib_urldate TEXT,
            bib_langid TEXT,
            bib_note TEXT,
            bib_howpublished TEXT,
            "标题" TEXT,
            "标题清洗" TEXT,
            "标题标准化" TEXT,
            "作者串" TEXT,
            "第一作者" TEXT,
            "年份" TEXT,
            "摘要" TEXT,
            "关键词" TEXT,
            "PDF路径" TEXT,
            "是否占位" INTEGER,
            "占位原因" TEXT,
            "占位状态" TEXT,
            "uid_占位运行" TEXT,
            "是否有全文" INTEGER,
            "主附件名称" TEXT,
            "主附件源路径" TEXT,
            "uid_标准笔记" TEXT,
            "来源类型" TEXT,
            "来源路径" TEXT,
            "导入来源" TEXT,
            "创建时间" TEXT,
            "更新时间" TEXT,
            "导入时间" TEXT,
            "结构化状态" TEXT,
            "结构化正文路径" TEXT,
            "结构化后端" TEXT,
            "结构化任务类型" TEXT,
            "结构化更新时间" TEXT,
            "结构化Schema版本" TEXT,
            "结构化文本长度" INTEGER,
            "结构化参考文献数" INTEGER,
            "文献语种" TEXT,
            "标题译文" TEXT,
            "摘要译文" TEXT,
            "关键词译文" TEXT,
            "元数据翻译状态" TEXT,
            "元数据翻译提供方" TEXT,
            "元数据翻译模型" TEXT,
            "元数据翻译更新时间" TEXT,
            "备注" TEXT,
            "文献类型" TEXT,
            "PDF相对路径" TEXT,
            "uid_当前解析资产" TEXT,
            "uid_当前解析附件" TEXT,
            "当前解析层级" TEXT,
            "当前解析后端" TEXT,
            "当前解析路径" TEXT,
            "当前解析Markdown路径" TEXT,
            "当前解析状态" TEXT,
            "当前解析更新时间" TEXT
        );

        CREATE TABLE IF NOT EXISTS "附件表" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            uid_attachment TEXT UNIQUE,
            "附件名称" TEXT,
            "附件类型" TEXT,
            "文件扩展名" TEXT,
            "存储路径" TEXT,
            "来源路径" TEXT,
            "附件来源类型" TEXT,
            "来源事务" TEXT,
            "校验和" TEXT,
            "状态" TEXT,
            "创建时间" TEXT,
            "更新时间" TEXT,
            "相对路径" TEXT
        );

        CREATE TABLE IF NOT EXISTS "文献附件关联" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            uid_attachment_link TEXT UNIQUE,
            uid_literature TEXT,
            uid_attachment TEXT,
            "关联角色" TEXT,
            "是否主附件" INTEGER,
            "来源类型" TEXT,
            legacy_uid_attachment TEXT,
            "创建时间" TEXT,
            "更新时间" TEXT,
            UNIQUE(uid_literature, uid_attachment)
        );

        CREATE TABLE IF NOT EXISTS "作者表" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            uid_author TEXT UNIQUE,
            "显示姓名" TEXT,
            "规范姓名" TEXT,
            "姓" TEXT,
            "名" TEXT,
            "研究者标识" TEXT,
            "来源类型" TEXT,
            "创建时间" TEXT,
            "更新时间" TEXT,
            "标准作者名" TEXT,
            "作者类型" TEXT,
            "作者质量标记" TEXT
        );

        CREATE TABLE IF NOT EXISTS "文献作者关联" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            uid_literature_author TEXT UNIQUE,
            uid_literature TEXT,
            uid_author TEXT,
            "作者顺序" INTEGER,
            "是否第一作者" INTEGER,
            "是否通讯作者" INTEGER,
            "显示姓名" TEXT,
            "来源类型" TEXT,
            "创建时间" TEXT,
            "更新时间" TEXT,
            UNIQUE(uid_literature, uid_author, "作者顺序")
        );

        CREATE TABLE IF NOT EXISTS "标签表" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            uid_tag TEXT UNIQUE,
            "标签" TEXT,
            "标签规范名" TEXT,
            "标签显示名" TEXT,
            "标签分组" TEXT,
            "创建时间" TEXT,
            "更新时间" TEXT
        );

        CREATE TABLE IF NOT EXISTS "文献标签关联" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            uid_literature TEXT,
            cite_key TEXT,
            "标签" TEXT,
            "标签规范名" TEXT,
            "来源类型" TEXT,
            "创建时间" TEXT,
            "更新时间" TEXT,
            UNIQUE(uid_literature, "标签")
        );

        CREATE TABLE IF NOT EXISTS "文献解析资产" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_uid TEXT UNIQUE,
            uid_literature TEXT,
            cite_key TEXT,
            uid_attachment TEXT,
            "解析层级" TEXT,
            "解析后端" TEXT,
            "模型名称" TEXT,
            "资产目录" TEXT,
            "结构化正文路径" TEXT,
            "重构Markdown路径" TEXT,
            "线性索引路径" TEXT,
            "元素路径" TEXT,
            "分块JSONL路径" TEXT,
            "解析记录路径" TEXT,
            "质量报告路径" TEXT,
            "解析状态" TEXT,
            last_run_uid TEXT,
            "是否当前有效" INTEGER,
            "创建时间" TEXT,
            "更新时间" TEXT
        );

        CREATE TABLE IF NOT EXISTS "文献翻译资产" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            translation_uid TEXT UNIQUE,
            uid_literature TEXT,
            cite_key TEXT,
            source_asset_uid TEXT,
            "来源类型" TEXT,
            "目标语种" TEXT,
            "翻译范围" TEXT,
            "提供方" TEXT,
            "模型名称" TEXT,
            "资产目录" TEXT,
            "译文Markdown路径" TEXT,
            "译文结构化路径" TEXT,
            "翻译审计路径" TEXT,
            "状态" TEXT,
            "是否当前有效" INTEGER,
            "创建时间" TEXT,
            "更新时间" TEXT
        );

        CREATE TABLE IF NOT EXISTS "文献分块集" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            chunks_uid TEXT UNIQUE,
            "来源范围" TEXT,
            "分块绝对路径" TEXT,
            "来源后端" TEXT,
            "分块数量" INTEGER,
            "来源文献数" INTEGER,
            "创建时间" TEXT,
            "状态" TEXT
        );

        CREATE TABLE IF NOT EXISTS "文献分块" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            "分块编号" TEXT UNIQUE,
            chunks_uid TEXT,
            uid_literature TEXT,
            cite_key TEXT,
            "分片路径" TEXT,
            "分块序号" INTEGER,
            "分块类型" TEXT,
            "起始字符位" INTEGER,
            "结束字符位" INTEGER,
            "文本长度" INTEGER,
            "创建时间" TEXT
        );

        CREATE TABLE IF NOT EXISTS "知识笔记" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            uid_note TEXT UNIQUE,
            uid_literature TEXT,
            cite_key TEXT,
            "笔记类型" TEXT,
            "笔记路径" TEXT,
            "标题" TEXT,
            "状态" TEXT,
            "来源阶段" TEXT,
            source_run_uid TEXT,
            "内容哈希" TEXT,
            "创建时间" TEXT,
            "更新时间" TEXT
        );

        CREATE TABLE IF NOT EXISTS "知识文献关联" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            uid_knowledge TEXT,
            uid_literature TEXT,
            "关联类型" TEXT,
            "是否主项" INTEGER,
            cite_key TEXT,
            "来源字段" TEXT,
            "创建时间" TEXT,
            "更新时间" TEXT,
            UNIQUE(uid_knowledge, uid_literature, "关联类型")
        );

        CREATE TABLE IF NOT EXISTS "知识证据关联" (
            "内部编号" INTEGER PRIMARY KEY AUTOINCREMENT,
            uid_knowledge TEXT,
            "证据类型" TEXT,
            target_uid TEXT,
            "证据角色" TEXT,
            "来源字段" TEXT,
            "创建时间" TEXT,
            UNIQUE(uid_knowledge, "证据类型", target_uid, "证据角色")
        );

        CREATE TABLE IF NOT EXISTS "工作区节点状态" (
            "节点编码" TEXT PRIMARY KEY,
            "节点名称" TEXT,
            "待执行" INTEGER,
            "执行中" INTEGER,
            "已完成" INTEGER,
            "闸门状态" TEXT,
            "uid_最近任务" TEXT,
            "当前任务UID" TEXT,
            "最近执行时间" TEXT,
            "完成时间" TEXT,
            "摘要" TEXT,
            "下一节点编码" TEXT,
            "失败原因" TEXT,
            "重试次数" INTEGER,
            "更新时间" TEXT
        );

        CREATE TABLE IF NOT EXISTS "文献流程状态" (
            uid_literature TEXT PRIMARY KEY,
            cite_key TEXT,
            "解析资产UID" TEXT,
            "笔记UID" TEXT,
            "来源文献UID" TEXT,
            "父文献UID" TEXT,
            "阶段编码" TEXT,
            "节点编码" TEXT,
            "文献角色" TEXT,
            "流程轨道" TEXT,
            "当前阶段" TEXT,
            "当前阶段组" TEXT,
            "当前状态" TEXT,
            "下一阶段" TEXT,
            "来源阶段" TEXT,
            "来源类型" TEXT,
            "推荐原因" TEXT,
            "主题关系" TEXT,
            "阅读目标" TEXT,
            "人工提示" TEXT,
            "失败原因" TEXT,
            "阻塞原因" TEXT,
            "是否当前有效" INTEGER,
            "是否可执行" INTEGER,
            "uid_最近任务" TEXT,
            "uid_最近批次" TEXT,
            "创建时间" TEXT,
            "更新时间" TEXT
        );
        '''
    )
    conn.executescript(
        '''
        CREATE INDEX IF NOT EXISTS idx_lit_uid ON "文献主表"("uid_文献");
        CREATE INDEX IF NOT EXISTS idx_lit_cite ON "文献主表"("题录键");
        CREATE INDEX IF NOT EXISTS idx_lit_author_year ON "文献主表"("第一作者", "年份");
        CREATE INDEX IF NOT EXISTS idx_attachment_path ON "附件表"("存储路径");
        CREATE INDEX IF NOT EXISTS idx_attachment_checksum ON "附件表"("校验和");
        CREATE INDEX IF NOT EXISTS idx_attachment_link_lit ON "文献附件关联"(uid_literature);
        CREATE INDEX IF NOT EXISTS idx_attachment_link_attachment ON "文献附件关联"(uid_attachment);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tag_uid ON "标签表"(uid_tag);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tag_norm_unique ON "标签表"("标签规范名");
        CREATE INDEX IF NOT EXISTS idx_tag_lit ON "文献标签关联"(uid_literature);
        CREATE INDEX IF NOT EXISTS idx_tag_name ON "文献标签关联"("标签");
        CREATE UNIQUE INDEX IF NOT EXISTS idx_author_uid ON "作者表"(uid_author);
        CREATE INDEX IF NOT EXISTS idx_author_name ON "作者表"("规范姓名");
        CREATE INDEX IF NOT EXISTS idx_author_link_lit ON "文献作者关联"(uid_literature);
        CREATE INDEX IF NOT EXISTS idx_author_link_author ON "文献作者关联"(uid_author);
        CREATE INDEX IF NOT EXISTS idx_parse_asset_lit_level ON "文献解析资产"(uid_literature, "解析层级");
        CREATE INDEX IF NOT EXISTS idx_parse_asset_current ON "文献解析资产"("解析层级", "是否当前有效");
        CREATE INDEX IF NOT EXISTS idx_translation_asset_lit_scope ON "文献翻译资产"(uid_literature, "来源类型", "目标语种", "翻译范围");
        CREATE INDEX IF NOT EXISTS idx_translation_asset_current ON "文献翻译资产"("来源类型", "目标语种", "是否当前有效");
        CREATE INDEX IF NOT EXISTS idx_flow_state_stage ON "文献流程状态"("当前阶段", "当前状态");
        CREATE INDEX IF NOT EXISTS idx_flow_state_track ON "文献流程状态"("流程轨道", "文献角色");
        CREATE INDEX IF NOT EXISTS idx_flow_state_cite ON "文献流程状态"(cite_key);
        CREATE INDEX IF NOT EXISTS idx_workspace_node_gate ON "工作区节点状态"("闸门状态", "执行中", "待执行");
        CREATE VIEW IF NOT EXISTS "工作区节点状态总视图" AS SELECT * FROM "工作区节点状态";
        CREATE VIEW IF NOT EXISTS "文献流程状态总视图" AS SELECT * FROM "文献流程状态";
        CREATE VIEW IF NOT EXISTS "文献附件总视图" AS
            SELECT l.uid_literature, l.cite_key, l."标题", a.uid_attachment, a."附件名称", a."存储路径", la."关联角色", la."是否主附件"
            FROM "文献附件关联" la
            LEFT JOIN "文献主表" l ON l.uid_literature = la.uid_literature
            LEFT JOIN "附件表" a ON a.uid_attachment = la.uid_attachment;
        CREATE VIEW IF NOT EXISTS "文献主附件视图" AS SELECT * FROM "文献附件总视图" WHERE IFNULL("是否主附件", 0) = 1;
        CREATE VIEW IF NOT EXISTS "标签总表" AS SELECT * FROM "标签表";
        CREATE VIEW IF NOT EXISTS "文献标签关联总视图" AS SELECT * FROM "文献标签关联";
        CREATE VIEW IF NOT EXISTS "作者总表" AS SELECT * FROM "作者表";
        CREATE VIEW IF NOT EXISTS "文献作者关联总视图" AS SELECT * FROM "文献作者关联";
        CREATE VIEW IF NOT EXISTS "工作流总览视图" AS
            SELECT '工作区节点' AS 对象类型, "当前状态" AS 状态, COUNT(*) AS 数量
            FROM (SELECT CASE WHEN IFNULL("执行中", 0) = 1 THEN '执行中' WHEN IFNULL("已完成", 0) = 1 THEN '已完成' WHEN IFNULL("待执行", 0) = 1 THEN '待执行' ELSE '未开始' END AS "当前状态" FROM "工作区节点状态")
            GROUP BY "当前状态"
            UNION ALL
            SELECT '文献流程' AS 对象类型, IFNULL("当前状态", '') AS 状态, COUNT(*) AS 数量
            FROM "文献流程状态"
            GROUP BY IFNULL("当前状态", '');
        '''
    )
    for view_name, condition in WORKSPACE_NODE_FILTER_VIEWS:
        conn.execute(
            f'''CREATE VIEW IF NOT EXISTS {_quote_identifier(view_name)} AS
                SELECT * FROM "工作区节点状态" WHERE {condition}'''
        )
    for view_name, condition in FLOW_STATE_FILTER_VIEWS:
        conn.execute(
            f'''CREATE VIEW IF NOT EXISTS {_quote_identifier(view_name)} AS
                SELECT * FROM "文献流程状态" WHERE {condition}'''
        )
    conn.execute("PRAGMA foreign_keys=ON")


def init_content_db(db_path: str | Path) -> Path:
    """初始化统一内容主库。"""

    resolved = resolve_content_db_path(db_path)
    with connect_sqlite(resolved) as conn:
        cur = conn.cursor()
        _migrate_public_translation_asset_table(conn)
        _enforce_empty_chinese_physical_schema(conn)
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_quote_identifier(LITERATURE_TABLE_NAME)} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_literature TEXT UNIQUE
            )
            """
        )
        _ensure_table_columns(conn, LITERATURE_TABLE_NAME, LITERATURE_REQUIRED_COLUMNS)
        _create_index_if_table(conn, LITERATURE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_lit_uid ON {_quote_identifier(LITERATURE_TABLE_NAME)}(uid_literature)")
        _create_index_if_table(conn, LITERATURE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_lit_cite ON {_quote_identifier(LITERATURE_TABLE_NAME)}(cite_key)")
        _create_index_if_table(conn, LITERATURE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_lit_author_year ON {_quote_identifier(LITERATURE_TABLE_NAME)}(first_author, year)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ATTACHMENT_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_attachment TEXT UNIQUE,
                attachment_name TEXT,
                attachment_type TEXT,
                file_ext TEXT,
                storage_path TEXT,
                source_path TEXT,
                附件来源类型 TEXT,
                来源事务 TEXT,
                checksum TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        _ensure_table_columns(conn, ATTACHMENT_TABLE_NAME, ATTACHMENT_REQUIRED_COLUMNS)
        _create_index_if_table(conn, ATTACHMENT_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_attachment_path ON {ATTACHMENT_TABLE_NAME}(storage_path)")
        _create_index_if_table(conn, ATTACHMENT_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_attachment_checksum ON {ATTACHMENT_TABLE_NAME}(checksum)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ATTACHMENT_LINK_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_attachment_link TEXT UNIQUE,
                uid_literature TEXT,
                uid_attachment TEXT,
                link_role TEXT,
                is_primary INTEGER,
                source_type TEXT,
                legacy_uid_attachment TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(uid_literature, uid_attachment),
                FOREIGN KEY(uid_literature) REFERENCES "文献主表"(uid_literature),
                FOREIGN KEY(uid_attachment) REFERENCES {ATTACHMENT_TABLE_NAME}(uid_attachment)
            )
            """
        )
        _create_index_if_table(conn, ATTACHMENT_LINK_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_attachment_link_lit ON {ATTACHMENT_LINK_TABLE_NAME}(uid_literature)")
        _create_index_if_table(conn, ATTACHMENT_LINK_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_attachment_link_attachment ON {ATTACHMENT_LINK_TABLE_NAME}(uid_attachment)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TAG_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_tag TEXT UNIQUE,
                tag TEXT,
                tag_norm TEXT,
                tag_display TEXT,
                tag_group TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        _ensure_table_columns(conn, TAG_TABLE_NAME, TAG_REQUIRED_COLUMNS)
        _create_index_if_table(conn, TAG_TABLE_NAME, f"CREATE UNIQUE INDEX IF NOT EXISTS idx_tag_uid ON {TAG_TABLE_NAME}(uid_tag)")
        _create_index_if_table(conn, TAG_TABLE_NAME, f"CREATE UNIQUE INDEX IF NOT EXISTS idx_tag_norm_unique ON {TAG_TABLE_NAME}(tag_norm)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_quote_identifier(LITERATURE_TAG_TABLE_NAME)} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_literature TEXT,
                cite_key TEXT,
                tag TEXT,
                tag_norm TEXT,
                source_type TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(uid_literature, tag),
                FOREIGN KEY(uid_literature) REFERENCES "文献主表"(uid_literature)
            )
            """
        )
        _create_index_if_table(conn, LITERATURE_TAG_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_tag_lit ON {_quote_identifier(LITERATURE_TAG_TABLE_NAME)}(uid_literature)")
        _create_index_if_table(conn, LITERATURE_TAG_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_tag_name ON {_quote_identifier(LITERATURE_TAG_TABLE_NAME)}(tag)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {AUTHOR_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_author TEXT UNIQUE,
                display_name TEXT,
                normalized_name TEXT,
                surname TEXT,
                given_names TEXT,
                "研究者标识" TEXT,
                source_type TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        _ensure_table_columns(conn, AUTHOR_TABLE_NAME, AUTHOR_REQUIRED_COLUMNS)
        _create_index_if_table(conn, AUTHOR_TABLE_NAME, f"CREATE UNIQUE INDEX IF NOT EXISTS idx_author_uid ON {AUTHOR_TABLE_NAME}(uid_author)")
        _create_index_if_table(conn, AUTHOR_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_author_name ON {AUTHOR_TABLE_NAME}(normalized_name)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {AUTHOR_LINK_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_literature_author TEXT UNIQUE,
                uid_literature TEXT,
                uid_author TEXT,
                author_order INTEGER,
                is_first_author INTEGER,
                is_corresponding INTEGER,
                display_name TEXT,
                source_type TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(uid_literature, uid_author, author_order),
                FOREIGN KEY(uid_literature) REFERENCES "文献主表"(uid_literature),
                FOREIGN KEY(uid_author) REFERENCES {AUTHOR_TABLE_NAME}(uid_author)
            )
            """
        )
        _ensure_table_columns(conn, AUTHOR_LINK_TABLE_NAME, AUTHOR_LINK_REQUIRED_COLUMNS)
        _create_index_if_table(conn, AUTHOR_LINK_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_author_link_lit ON {AUTHOR_LINK_TABLE_NAME}(uid_literature)")
        _create_index_if_table(conn, AUTHOR_LINK_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_author_link_author ON {AUTHOR_LINK_TABLE_NAME}(uid_author)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TRANSLATION_ASSET_STORAGE_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                translation_uid TEXT UNIQUE,
                uid_literature TEXT,
                cite_key TEXT,
                source_asset_uid TEXT,
                source_kind TEXT,
                target_lang TEXT,
                translation_scope TEXT,
                provider TEXT,
                model_name TEXT,
                asset_dir TEXT,
                translated_markdown_path TEXT,
                translated_structured_path TEXT,
                translation_audit_path TEXT,
                status TEXT,
                is_current INTEGER,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(uid_literature) REFERENCES "文献主表"("uid_文献")
            )
            """
        )
        _ensure_table_columns(conn, TRANSLATION_ASSET_STORAGE_TABLE_NAME, TRANSLATION_ASSET_REQUIRED_COLUMNS)
        _create_index_if_table(
            conn,
            TRANSLATION_ASSET_STORAGE_TABLE_NAME,
            f"CREATE INDEX IF NOT EXISTS idx_translation_asset_lit_scope ON {TRANSLATION_ASSET_STORAGE_TABLE_NAME}(uid_literature, source_kind, target_lang, translation_scope)",
        )
        _create_index_if_table(
            conn,
            TRANSLATION_ASSET_STORAGE_TABLE_NAME,
            f"CREATE INDEX IF NOT EXISTS idx_translation_asset_current ON {TRANSLATION_ASSET_STORAGE_TABLE_NAME}(source_kind, target_lang, is_current)",
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {WORKSPACE_NODE_STATE_TABLE_NAME} (
                node_code TEXT PRIMARY KEY,
                node_name TEXT,
                pending_run INTEGER,
                in_progress INTEGER,
                completed INTEGER,
                gate_status TEXT,
                last_task_uid TEXT,
                current_task_uid TEXT,
                last_run_at TEXT,
                completed_at TEXT,
                summary TEXT,
                next_node_code TEXT,
                failure_reason TEXT,
                retry_count INTEGER,
                updated_at TEXT
            )
            """
        )
        _ensure_table_columns(conn, WORKSPACE_NODE_STATE_TABLE_NAME, WORKSPACE_NODE_STATE_REQUIRED_COLUMNS)
        _create_index_if_table(conn, WORKSPACE_NODE_STATE_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_workspace_node_gate ON {WORKSPACE_NODE_STATE_TABLE_NAME}(gate_status, in_progress, pending_run)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS "文献分块集" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunks_uid TEXT UNIQUE,
                source_scope TEXT,
                chunks_abs_path TEXT,
                source_backend TEXT,
                chunk_count INTEGER,
                source_doc_count INTEGER,
                created_at TEXT,
                status TEXT
            )
            """
        )
        _create_index_if_table(conn, CHUNK_SET_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_chunk_set_uid ON {_quote_identifier(CHUNK_SET_TABLE_NAME)}(chunks_uid)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS "文献分块" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT UNIQUE,
                chunks_uid TEXT,
                uid_literature TEXT,
                cite_key TEXT,
                shard_abs_path TEXT,
                chunk_index INTEGER,
                chunk_type TEXT,
                char_start INTEGER,
                char_end INTEGER,
                text_length INTEGER,
                created_at TEXT,
                FOREIGN KEY(chunks_uid) REFERENCES "文献分块集"(chunks_uid),
                FOREIGN KEY(uid_literature) REFERENCES "文献主表"(uid_literature)
            )
            """
        )
        _create_index_if_table(conn, CHUNK_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_chunk_uid ON {_quote_identifier(CHUNK_TABLE_NAME)}(chunk_id)")
        _create_index_if_table(conn, CHUNK_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_chunk_set_ref ON {_quote_identifier(CHUNK_TABLE_NAME)}(chunks_uid)")
        _create_index_if_table(conn, CHUNK_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_chunk_lit_uid ON {_quote_identifier(CHUNK_TABLE_NAME)}(uid_literature)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS "知识索引" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_knowledge TEXT UNIQUE,
                note_name TEXT,
                note_path TEXT,
                note_type TEXT,
                title TEXT,
                status TEXT,
                tags TEXT,
                aliases TEXT,
                source_type TEXT,
                evidence_uids TEXT,
                uid_literature TEXT,
                cite_key TEXT,
                attachment_uids TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        _create_index_if_table(conn, KNOWLEDGE_INDEX_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_know_uid ON {_quote_identifier(KNOWLEDGE_INDEX_TABLE_NAME)}(uid_knowledge)")
        _create_index_if_table(conn, KNOWLEDGE_INDEX_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_know_type_status ON {_quote_identifier(KNOWLEDGE_INDEX_TABLE_NAME)}(note_type, status)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS "知识附件" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_attachment TEXT UNIQUE,
                uid_knowledge TEXT,
                attachment_name TEXT,
                attachment_type TEXT,
                file_ext TEXT,
                storage_path TEXT,
                source_path TEXT,
                checksum TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(uid_knowledge) REFERENCES "知识索引"(uid_knowledge)
            )
            """
        )
        _create_index_if_table(conn, KNOWLEDGE_ATTACHMENT_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_katt_uid ON {_quote_identifier(KNOWLEDGE_ATTACHMENT_TABLE_NAME)}(uid_knowledge)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {KNOWLEDGE_NOTES_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_note TEXT UNIQUE,
                uid_literature TEXT,
                cite_key TEXT,
                note_type TEXT,
                note_path TEXT,
                title TEXT,
                status TEXT,
                source_stage TEXT,
                source_run_uid TEXT,
                content_hash TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(uid_literature) REFERENCES "文献主表"(uid_literature)
            )
            """
        )
        _create_index_if_table(conn, KNOWLEDGE_NOTES_TABLE_NAME, f"CREATE INDEX IF NOT EXISTS idx_knote_lit ON {KNOWLEDGE_NOTES_TABLE_NAME}(uid_literature)")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {KNOWLEDGE_LINK_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_knowledge TEXT,
                uid_literature TEXT,
                relation_type TEXT,
                is_primary INTEGER,
                cite_key TEXT,
                source_field TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(uid_knowledge, uid_literature, relation_type),
                FOREIGN KEY(uid_knowledge) REFERENCES "知识索引"(uid_knowledge),
                FOREIGN KEY(uid_literature) REFERENCES "文献主表"(uid_literature)
            )
            """
        )
        _create_index_if_table(
            conn,
            KNOWLEDGE_LINK_TABLE_NAME,
            f"CREATE INDEX IF NOT EXISTS idx_kl_link_lit_type ON {KNOWLEDGE_LINK_TABLE_NAME}(uid_literature, relation_type)",
        )
        _create_index_if_table(
            conn,
            KNOWLEDGE_LINK_TABLE_NAME,
            f"CREATE INDEX IF NOT EXISTS idx_kl_link_kn_type ON {KNOWLEDGE_LINK_TABLE_NAME}(uid_knowledge, relation_type)",
        )
        _create_index_if_table(
            conn,
            KNOWLEDGE_LINK_TABLE_NAME,
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_kl_standard_primary ON {KNOWLEDGE_LINK_TABLE_NAME}(uid_literature) WHERE relation_type = 'standard_note' AND COALESCE(is_primary, 0) = 1",
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {KNOWLEDGE_EVIDENCE_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_knowledge TEXT,
                evidence_type TEXT,
                target_uid TEXT,
                evidence_role TEXT,
                source_field TEXT,
                created_at TEXT,
                UNIQUE(uid_knowledge, evidence_type, target_uid, evidence_role),
                FOREIGN KEY(uid_knowledge) REFERENCES "知识索引"(uid_knowledge)
            )
            """
        )
        _create_index_if_table(
            conn,
            KNOWLEDGE_EVIDENCE_TABLE_NAME,
            f"CREATE INDEX IF NOT EXISTS idx_ke_uid_type ON {KNOWLEDGE_EVIDENCE_TABLE_NAME}(uid_knowledge, evidence_type)",
        )

        _migrate_and_drop_legacy_attachment_table(conn)
        _sync_tag_entities(conn)
        _sync_author_entities(conn)
        _migrate_public_runtime_projection_tables(conn)
        _drop_all_views(conn)
        for table_name in (
            LITERATURE_TABLE_NAME,
            ATTACHMENT_TABLE_NAME,
            ATTACHMENT_LINK_TABLE_NAME,
            TAG_TABLE_NAME,
            LITERATURE_TAG_TABLE_NAME,
            AUTHOR_TABLE_NAME,
            AUTHOR_LINK_TABLE_NAME,
            TRANSLATION_ASSET_STORAGE_TABLE_NAME,
            CHUNK_SET_TABLE_NAME,
            CHUNK_TABLE_NAME,
            KNOWLEDGE_NOTES_TABLE_NAME,
            KNOWLEDGE_LINK_TABLE_NAME,
            KNOWLEDGE_EVIDENCE_TABLE_NAME,
            WORKSPACE_NODE_STATE_TABLE_NAME,
        ):
            _rename_table_columns_to_physical_aliases(conn, table_name)
        _refresh_runtime_projection_views(conn)
        _refresh_reading_state_views(conn)
        _refresh_legacy_attachment_projections(conn)
        _refresh_chinese_contract_views(conn)

        conn.commit()
    return resolved


def load_knowledge_literature_links_df(db_path: str | Path) -> pd.DataFrame:
    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {KNOWLEDGE_LINK_TABLE_NAME}", conn)


def load_author_entities_df(db_path: str | Path) -> pd.DataFrame:
    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {AUTHOR_TABLE_NAME}", conn)


def load_literature_author_links_df(db_path: str | Path) -> pd.DataFrame:
    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {AUTHOR_LINK_TABLE_NAME}", conn)


def load_attachment_entities_df(db_path: str | Path) -> pd.DataFrame:
    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {ATTACHMENT_TABLE_NAME}", conn)


def load_literature_attachment_links_df(db_path: str | Path) -> pd.DataFrame:
    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {ATTACHMENT_LINK_TABLE_NAME}", conn)


def load_literature_attachments_df(db_path: str | Path) -> pd.DataFrame:
    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT
                文献标识 AS uid_literature,
                引文键 AS cite_key,
                文献标题 AS title,
                附件标识 AS uid_attachment,
                附件名称 AS attachment_name,
                当前存储路径 AS storage_path,
                原始来源路径 AS source_path,
                附件状态 AS status,
                关联角色 AS link_role,
                是否主附件 AS is_primary,
                更新时间 AS updated_at
            FROM "文献附件总视图"
            """,
            conn,
        )


def load_knowledge_evidence_links_df(db_path: str | Path) -> pd.DataFrame:
    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {KNOWLEDGE_EVIDENCE_TABLE_NAME}", conn)


AUTO_KNOWLEDGE_LINK_SOURCE_FIELDS: tuple[str, ...] = (
    "知识索引",
    "文献主表.standard_note_uid",
)
AUTO_KNOWLEDGE_EVIDENCE_SOURCE_FIELDS: tuple[str, ...] = (
    "知识索引.evidence_uids",
)


def _load_knowledge_relation_source_frames(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    literatures = pd.read_sql_query(
        f"SELECT {_quote_identifier(resolve_content_physical_column(LITERATURE_TABLE_NAME, 'uid_literature'))} AS uid_literature, {_quote_identifier(resolve_content_physical_column(LITERATURE_TABLE_NAME, 'cite_key'))} AS cite_key, {_quote_identifier(resolve_content_physical_column(LITERATURE_TABLE_NAME, 'standard_note_uid'))} AS standard_note_uid FROM {_quote_identifier(LITERATURE_TABLE_NAME)}",
        conn,
    )
    if _sqlite_object_type(conn, KNOWLEDGE_INDEX_TABLE_NAME) == "table":
        uid_knowledge_column = resolve_content_physical_column(KNOWLEDGE_INDEX_TABLE_NAME, "uid_knowledge")
        note_type_column = resolve_content_physical_column(KNOWLEDGE_INDEX_TABLE_NAME, "note_type")
        uid_literature_column = resolve_content_physical_column(KNOWLEDGE_INDEX_TABLE_NAME, "uid_literature")
        cite_key_column = resolve_content_physical_column(KNOWLEDGE_INDEX_TABLE_NAME, "cite_key")
        evidence_uids_column = resolve_content_physical_column(KNOWLEDGE_INDEX_TABLE_NAME, "evidence_uids")
        knowledge = pd.read_sql_query(
            f"SELECT {_quote_identifier(uid_knowledge_column)} AS uid_knowledge, {_quote_identifier(note_type_column)} AS note_type, {_quote_identifier(uid_literature_column)} AS uid_literature, {_quote_identifier(cite_key_column)} AS cite_key, {_quote_identifier(evidence_uids_column)} AS evidence_uids FROM {_quote_identifier(KNOWLEDGE_INDEX_TABLE_NAME)}",
            conn,
        )
    else:
        knowledge = pd.DataFrame(columns=["uid_knowledge", "note_type", "uid_literature", "cite_key", "evidence_uids"])
    return literatures, knowledge


def _build_knowledge_relation_frames(
    literatures: pd.DataFrame,
    knowledge: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    literature_uid_set = {
        str(uid).strip()
        for uid in literatures.get("uid_literature", pd.Series(dtype=str)).tolist()
        if str(uid).strip()
    }
    knowledge_uid_set = {
        str(uid).strip()
        for uid in knowledge.get("uid_knowledge", pd.Series(dtype=str)).tolist()
        if str(uid).strip()
    }
    literature_cite_lookup = {
        str(row.get("uid_literature") or "").strip(): str(row.get("cite_key") or "").strip()
        for _, row in literatures.fillna("").iterrows()
        if str(row.get("uid_literature") or "").strip()
    }

    now = _utc_now_iso()
    link_rows: list[dict[str, object]] = []
    for _, row in knowledge.fillna("").iterrows():
        uid_knowledge = str(row.get("uid_knowledge") or "").strip()
        uid_literature = str(row.get("uid_literature") or "").strip()
        if uid_knowledge and uid_literature and uid_knowledge in knowledge_uid_set and uid_literature in literature_uid_set:
            note_type = str(row.get("note_type") or "").strip()
            relation_type = "standard_note" if note_type == "literature_standard_note" else "mention"
            link_rows.append(
                {
                    "uid_knowledge": uid_knowledge,
                    "uid_literature": uid_literature,
                    "relation_type": relation_type,
                    "is_primary": 1 if relation_type == "standard_note" else 0,
                    "cite_key": str(row.get("cite_key") or literature_cite_lookup.get(uid_literature) or "").strip(),
                    "source_field": "知识索引",
                    "created_at": now,
                    "updated_at": now,
                }
            )

    evidence_rows: list[dict[str, object]] = []
    for _, row in knowledge.fillna("").iterrows():
        uid_knowledge = str(row.get("uid_knowledge") or "").strip()
        if not uid_knowledge or uid_knowledge not in knowledge_uid_set:
            continue
        for evidence_uid in _split_pipe_values(row.get("evidence_uids")):
            evidence_rows.append(
                {
                    "uid_knowledge": uid_knowledge,
                    "evidence_type": "literature" if evidence_uid in literature_uid_set else "unknown",
                    "target_uid": evidence_uid,
                    "evidence_role": "supporting",
                    "source_field": "知识索引.evidence_uids",
                    "created_at": now,
                }
            )

    for _, row in literatures.fillna("").iterrows():
        uid_literature = str(row.get("uid_literature") or "").strip()
        uid_knowledge = str(row.get("standard_note_uid") or "").strip()
        if uid_literature and uid_knowledge and uid_literature in literature_uid_set and uid_knowledge in knowledge_uid_set:
            link_rows.append(
                {
                    "uid_knowledge": uid_knowledge,
                    "uid_literature": uid_literature,
                    "relation_type": "standard_note",
                    "is_primary": 1,
                    "cite_key": str(row.get("cite_key") or "").strip(),
                    "source_field": "文献主表.standard_note_uid",
                    "created_at": now,
                    "updated_at": now,
                }
            )

    link_df = pd.DataFrame(link_rows)
    if not link_df.empty:
        link_df = link_df.drop_duplicates(subset=["uid_knowledge", "uid_literature", "relation_type"], keep="last")
    else:
        link_df = pd.DataFrame(columns=["uid_knowledge", "uid_literature", "relation_type", "is_primary", "cite_key", "source_field", "created_at", "updated_at"])

    evidence_df = pd.DataFrame(evidence_rows)
    if not evidence_df.empty:
        evidence_df = evidence_df.drop_duplicates(subset=["uid_knowledge", "evidence_type", "target_uid", "evidence_role"], keep="last")
    else:
        evidence_df = pd.DataFrame(columns=["uid_knowledge", "evidence_type", "target_uid", "evidence_role", "source_field", "created_at"])

    return link_df, evidence_df


def _upsert_table_rows(
    conn: sqlite3.Connection,
    table_name: str,
    frame: pd.DataFrame,
    *,
    key_columns: Sequence[str],
) -> None:
    if frame is None or frame.empty or _sqlite_object_type(conn, table_name) != "table":
        return

    adapted = adapt_frame_to_content_physical_schema(conn, table_name, frame.where(pd.notnull(frame), None))
    if adapted.empty:
        return
    physical_columns = list(adapted.columns)
    physical_key_columns = [resolve_content_physical_column(table_name, column) for column in key_columns if resolve_content_physical_column(table_name, column) in physical_columns]
    update_columns = [column for column in physical_columns if column not in physical_key_columns]
    insert_sql = (
        f"INSERT INTO {_quote_identifier(table_name)} ({', '.join(_quote_identifier(column) for column in physical_columns)}) "
        f"VALUES ({', '.join(['?'] * len(physical_columns))})"
    )
    update_sql = ""
    if physical_key_columns and update_columns:
        update_sql = (
            f"UPDATE {_quote_identifier(table_name)} SET {', '.join(f'{_quote_identifier(column)} = ?' for column in update_columns)} "
            f"WHERE {' AND '.join(f'{_quote_identifier(column)} = ?' for column in physical_key_columns)}"
        )

    for row in adapted.to_dict(orient="records"):
        if update_sql:
            key_values = [row.get(column) for column in physical_key_columns]
            if all(value not in (None, "") for value in key_values):
                cursor = conn.execute(update_sql, [row.get(column) for column in update_columns] + key_values)
                if cursor.rowcount and cursor.rowcount > 0:
                    continue
        conn.execute(insert_sql, [row.get(column) for column in physical_columns])


def load_translation_assets_df(
    db_path: str | Path,
    *,
    uid_literature: str = "",
    source_kind: str = "",
    target_lang: str = "",
    only_current: bool = False,
) -> pd.DataFrame:
    """读取翻译资产索引。"""

    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        frame = pd.read_sql_query(f"SELECT * FROM {_quote_identifier(TRANSLATION_ASSET_TABLE_NAME)}", conn)

    if frame.empty:
        return frame

    if uid_literature:
        frame = frame[frame["uid_literature"].astype(str) == str(uid_literature)]
    if source_kind:
        source_kind_column = "来源类型" if "来源类型" in frame.columns else "source_kind"
        frame = frame[frame[source_kind_column].astype(str) == str(source_kind)]
    if target_lang:
        target_lang_column = "目标语种" if "目标语种" in frame.columns else "target_lang"
        frame = frame[frame[target_lang_column].astype(str) == str(target_lang)]
    if only_current:
        current_column = "是否当前有效" if "是否当前有效" in frame.columns else "is_current"
        frame = frame[frame[current_column].fillna(0).astype(int) == 1]

    return frame.reset_index(drop=True)


def upsert_translation_asset_rows(
    db_path: str | Path,
    rows: Sequence[dict[str, object]] | pd.DataFrame,
) -> None:
    """写入翻译资产索引并维护 current 标记。"""

    incoming = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows or []))
    if incoming.empty:
        return

    init_content_db(db_path)
    now = _utc_now_iso()
    with connect_sqlite(db_path) as conn:
        for _, row in incoming.fillna("").iterrows():
            uid_literature = str(row.get("uid_literature") or "").strip()
            cite_key = str(row.get("cite_key") or "").strip()
            source_asset_uid = str(row.get("source_asset_uid") or "").strip()
            source_kind = str(row.get("source_kind") or "").strip() or "metadata"
            target_lang = str(row.get("target_lang") or "").strip() or "zh-CN"
            translation_scope = str(row.get("translation_scope") or "").strip() or source_kind
            provider = str(row.get("provider") or "").strip()
            model_name = str(row.get("model_name") or "").strip()
            asset_dir = str(row.get("asset_dir") or "").strip()
            translated_markdown_path = str(row.get("translated_markdown_path") or "").strip()
            translated_structured_path = str(row.get("translated_structured_path") or "").strip()
            translation_audit_path = str(row.get("translation_audit_path") or "").strip()
            status = str(row.get("status") or "").strip() or "ready"
            is_current = int(row.get("is_current") or 1)
            created_at = str(row.get("created_at") or "").strip() or now
            updated_at = str(row.get("updated_at") or "").strip() or now
            translation_uid = str(row.get("translation_uid") or "").strip()

            if not uid_literature and not cite_key:
                continue

            if not translation_uid:
                base = "|".join(
                    [
                        uid_literature,
                        cite_key,
                        source_asset_uid,
                        source_kind,
                        target_lang,
                        translation_scope,
                        translated_markdown_path,
                        translated_structured_path,
                        updated_at,
                    ]
                )
                translation_uid = f"tr-{abs(hash(base))}"

            if is_current:
                conn.execute(
                    f"""
                    UPDATE {_quote_identifier(TRANSLATION_ASSET_STORAGE_TABLE_NAME)}
                    SET {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'is_current'))} = 0,
                        {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'updated_at'))} = ?
                    WHERE {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'uid_literature'))} = ?
                      AND {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'source_kind'))} = ?
                      AND {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'target_lang'))} = ?
                      AND {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translation_scope'))} = ?
                    """,
                    (updated_at, uid_literature, source_kind, target_lang, translation_scope),
                )

            conn.execute(
                f"""
                INSERT INTO {_quote_identifier(TRANSLATION_ASSET_STORAGE_TABLE_NAME)}
                    ({_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translation_uid'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'uid_literature'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'cite_key'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'source_asset_uid'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'source_kind'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'target_lang'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translation_scope'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'provider'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'model_name'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'asset_dir'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translated_markdown_path'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translated_structured_path'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translation_audit_path'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'status'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'is_current'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'created_at'))},
                     {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'updated_at'))})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT({_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translation_uid'))})
                DO UPDATE SET
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'uid_literature'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'uid_literature'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'cite_key'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'cite_key'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'source_asset_uid'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'source_asset_uid'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'source_kind'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'source_kind'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'target_lang'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'target_lang'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translation_scope'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translation_scope'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'provider'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'provider'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'model_name'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'model_name'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'asset_dir'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'asset_dir'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translated_markdown_path'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translated_markdown_path'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translated_structured_path'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translated_structured_path'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translation_audit_path'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'translation_audit_path'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'status'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'status'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'is_current'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'is_current'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'created_at'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'created_at'))},
                    {_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'updated_at'))}=excluded.{_quote_identifier(resolve_content_physical_column(TRANSLATION_ASSET_STORAGE_TABLE_NAME, 'updated_at'))}
                """,
                (
                    translation_uid,
                    uid_literature,
                    cite_key,
                    source_asset_uid,
                    source_kind,
                    target_lang,
                    translation_scope,
                    provider,
                    model_name,
                    asset_dir,
                    translated_markdown_path,
                    translated_structured_path,
                    translation_audit_path,
                    status,
                    is_current,
                    created_at,
                    updated_at,
                ),
            )
        conn.commit()


def backfill_content_relationships(db_path: str | Path) -> None:
    """根据兼容字段回填跨域关系表。"""

    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        literatures = pd.read_sql_query(
            f"SELECT {_quote_identifier(resolve_content_physical_column(LITERATURE_TABLE_NAME, 'uid_literature'))} AS uid_literature, {_quote_identifier(resolve_content_physical_column(LITERATURE_TABLE_NAME, 'cite_key'))} AS cite_key, {_quote_identifier(resolve_content_physical_column(LITERATURE_TABLE_NAME, 'standard_note_uid'))} AS standard_note_uid FROM {_quote_identifier(LITERATURE_TABLE_NAME)}",
            conn,
        )
        if _sqlite_object_type(conn, KNOWLEDGE_INDEX_TABLE_NAME) == "table":
            uid_knowledge_column = resolve_content_physical_column(KNOWLEDGE_INDEX_TABLE_NAME, "uid_knowledge")
            note_type_column = resolve_content_physical_column(KNOWLEDGE_INDEX_TABLE_NAME, "note_type")
            uid_literature_column = resolve_content_physical_column(KNOWLEDGE_INDEX_TABLE_NAME, "uid_literature")
            cite_key_column = resolve_content_physical_column(KNOWLEDGE_INDEX_TABLE_NAME, "cite_key")
            evidence_uids_column = resolve_content_physical_column(KNOWLEDGE_INDEX_TABLE_NAME, "evidence_uids")
            knowledge = pd.read_sql_query(
                f"SELECT {_quote_identifier(uid_knowledge_column)} AS uid_knowledge, {_quote_identifier(note_type_column)} AS note_type, {_quote_identifier(uid_literature_column)} AS uid_literature, {_quote_identifier(cite_key_column)} AS cite_key, {_quote_identifier(evidence_uids_column)} AS evidence_uids FROM {_quote_identifier(KNOWLEDGE_INDEX_TABLE_NAME)}",
                conn,
            )
        else:
            knowledge = pd.DataFrame(columns=["uid_knowledge", "note_type", "uid_literature", "cite_key", "evidence_uids"])

        literature_uid_set = {
            str(uid).strip()
            for uid in literatures.get("uid_literature", pd.Series(dtype=str)).tolist()
            if str(uid).strip()
        }
        knowledge_uid_set = {
            str(uid).strip()
            for uid in knowledge.get("uid_knowledge", pd.Series(dtype=str)).tolist()
            if str(uid).strip()
        }
        literature_cite_lookup = {
            str(row.get("uid_literature") or "").strip(): str(row.get("cite_key") or "").strip()
            for _, row in literatures.fillna("").iterrows()
            if str(row.get("uid_literature") or "").strip()
        }

        link_rows: list[dict[str, object]] = []
        now = _utc_now_iso()
        for _, row in knowledge.fillna("").iterrows():
            uid_knowledge = str(row.get("uid_knowledge") or "").strip()
            uid_literature = str(row.get("uid_literature") or "").strip()
            if uid_knowledge and uid_literature and uid_knowledge in knowledge_uid_set and uid_literature in literature_uid_set:
                note_type = str(row.get("note_type") or "").strip()
                relation_type = "standard_note" if note_type == "literature_standard_note" else "mention"
                link_rows.append(
                    {
                        "uid_knowledge": uid_knowledge,
                        "uid_literature": uid_literature,
                        "relation_type": relation_type,
                        "is_primary": 1 if relation_type == "standard_note" else 0,
                        "cite_key": str(row.get("cite_key") or literature_cite_lookup.get(uid_literature) or "").strip(),
                        "source_field": "知识索引",
                        "created_at": now,
                        "updated_at": now,
                    }
                )

        evidence_rows: list[dict[str, object]] = []
        for _, row in knowledge.fillna("").iterrows():
            uid_knowledge = str(row.get("uid_knowledge") or "").strip()
            if not uid_knowledge or uid_knowledge not in knowledge_uid_set:
                continue
            for evidence_uid in _split_pipe_values(row.get("evidence_uids")):
                evidence_rows.append(
                    {
                        "uid_knowledge": uid_knowledge,
                        "evidence_type": "literature" if evidence_uid in literature_uid_set else "unknown",
                        "target_uid": evidence_uid,
                        "evidence_role": "supporting",
                        "source_field": "知识索引.evidence_uids",
                        "created_at": now,
                    }
                )

        for _, row in literatures.fillna("").iterrows():
            uid_literature = str(row.get("uid_literature") or "").strip()
            uid_knowledge = str(row.get("standard_note_uid") or "").strip()
            if uid_literature and uid_knowledge and uid_literature in literature_uid_set and uid_knowledge in knowledge_uid_set:
                link_rows.append(
                    {
                        "uid_knowledge": uid_knowledge,
                        "uid_literature": uid_literature,
                        "relation_type": "standard_note",
                        "is_primary": 1,
                        "cite_key": str(row.get("cite_key") or "").strip(),
                        "source_field": "文献主表.standard_note_uid",
                        "created_at": now,
                        "updated_at": now,
                    }
                )

        link_df = pd.DataFrame(link_rows)
        if not link_df.empty:
            link_df = link_df.drop_duplicates(subset=["uid_knowledge", "uid_literature", "relation_type"], keep="last")
        else:
            link_df = pd.DataFrame(
                columns=[
                    "uid_knowledge",
                    "uid_literature",
                    "relation_type",
                    "is_primary",
                    "cite_key",
                    "source_field",
                    "created_at",
                    "updated_at",
                ]
            )

        evidence_df = pd.DataFrame(evidence_rows)
        if not evidence_df.empty:
            evidence_df = evidence_df.drop_duplicates(
                subset=["uid_knowledge", "evidence_type", "target_uid", "evidence_role"],
                keep="last",
            )
        else:
            evidence_df = pd.DataFrame(
                columns=[
                    "uid_knowledge",
                    "evidence_type",
                    "target_uid",
                    "evidence_role",
                    "source_field",
                    "created_at",
                ]
            )

        try:
            _replace_table_rows(conn, KNOWLEDGE_LINK_TABLE_NAME, link_df)
            _replace_table_rows(conn, KNOWLEDGE_EVIDENCE_TABLE_NAME, evidence_df)
        except sqlite3.OperationalError:
            # 兼容旧库：部分工作区把关系对象保留为 view 或历史外键契约，回填失败时跳过。
            pass
        conn.commit()


def sync_author_entities_from_literature_rows(
    db_path: str | Path,
    literature_rows: pd.DataFrame | Sequence[dict[str, object]] | None = None,
    *,
    replace_link_scope: Sequence[str] | None = None,
) -> None:
    """按文献主表当前内容重建作者实体与作者关联。

    保留 `literature_rows` 与 `replace_link_scope` 参数仅用于兼容旧调用签名；当前统一以
    content.db 里的 `文献主表` 作为真相源，避免外部再维护第二套作者回写逻辑。
    """

    del literature_rows, replace_link_scope
    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        _sync_author_entities(conn)
        conn.commit()


def sync_knowledge_relationships(
    db_path: str | Path,
    *,
    replace_literature_scope: Sequence[str] | None = None,
    replace_knowledge_scope: Sequence[str] | None = None,
) -> None:
    """按知识索引与文献主表当前内容刷新自动知识关系。"""

    init_content_db(db_path)
    with connect_sqlite(db_path) as conn:
        link_df, evidence_df = _build_knowledge_relation_frames(*_load_knowledge_relation_source_frames(conn))

        literature_scope = {
            str(value).strip()
            for value in (replace_literature_scope or [])
            if str(value).strip()
        }
        knowledge_scope = {
            str(value).strip()
            for value in (replace_knowledge_scope or [])
            if str(value).strip()
        }

        if knowledge_scope:
            if not link_df.empty:
                link_df = link_df.loc[link_df["uid_knowledge"].astype(str).isin(knowledge_scope)].reset_index(drop=True)
            if not evidence_df.empty:
                evidence_df = evidence_df.loc[evidence_df["uid_knowledge"].astype(str).isin(knowledge_scope)].reset_index(drop=True)
        if literature_scope:
            if not link_df.empty:
                link_df = link_df.loc[link_df["uid_literature"].astype(str).isin(literature_scope)].reset_index(drop=True)
            if not evidence_df.empty:
                evidence_df = evidence_df.loc[
                    ~evidence_df["evidence_type"].astype(str).eq("literature")
                    | evidence_df["target_uid"].astype(str).isin(literature_scope)
                ].reset_index(drop=True)

        try:
            _upsert_table_rows(
                conn,
                KNOWLEDGE_LINK_TABLE_NAME,
                link_df,
                key_columns=["uid_knowledge", "uid_literature", "relation_type"],
            )
            _upsert_table_rows(
                conn,
                KNOWLEDGE_EVIDENCE_TABLE_NAME,
                evidence_df,
                key_columns=["uid_knowledge", "evidence_type", "target_uid", "evidence_role"],
            )
        except sqlite3.OperationalError:
            # 兼容旧库：知识关系表可能保留历史外键契约，遇到 mismatch 时跳过自动同步。
            pass
        conn.commit()


def upsert_knowledge_literature_link(
    db_path: str | Path,
    *,
    uid_knowledge: str,
    uid_literature: str,
    relation_type: str = "standard_note",
    is_primary: int = 1,
    cite_key: str = "",
    source_field: str = "manual_bind",
) -> None:
    """直接写入或更新知识-文献关系。"""

    init_content_db(db_path)
    now = _utc_now_iso()
    with connect_sqlite(db_path) as conn:
        conn.execute(
            f"""
            INSERT INTO {KNOWLEDGE_LINK_TABLE_NAME}
                (uid_knowledge, uid_literature, "关联类型", "是否主项", cite_key, "来源字段", "创建时间", "更新时间")
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid_knowledge, uid_literature, "关联类型")
            DO UPDATE SET
                "是否主项" = excluded."是否主项",
                cite_key = excluded.cite_key,
                "来源字段" = excluded."来源字段",
                "更新时间" = excluded."更新时间"
            """,
            (
                uid_knowledge,
                uid_literature,
                relation_type,
                int(is_primary or 0),
                cite_key,
                source_field,
                now,
                now,
            ),
        )
        conn.commit()


def backfill_content_relative_paths(
    db_path: str | Path,
    *,
    dry_run: bool = True,
) -> dict[str, object]:
    """把 content.db 中历史绝对路径回填为相对路径字段。"""

    resolved_db = resolve_content_db_path(db_path)
    init_content_db(resolved_db)
    workspace_root = infer_workspace_root_from_content_db(resolved_db)
    attachment_updates: list[tuple[str, int]] = []
    literature_updates: list[tuple[str, int]] = []

    with connect_sqlite(resolved_db) as conn:
        attachment_rows = conn.execute(
            f"SELECT id, path_rel, storage_path, source_path FROM {ATTACHMENT_TABLE_NAME}"
        ).fetchall()
        for row_id, path_rel, storage_path, source_path in attachment_rows:
            existing_rel = normalize_db_relative_path(path_rel)
            if existing_rel:
                continue
            candidate_rel = ""
            for candidate in (storage_path, source_path):
                candidate_rel = build_relative_path_from_workspace(candidate, workspace_root=workspace_root)
                if candidate_rel:
                    break
            if candidate_rel:
                attachment_updates.append((candidate_rel, int(row_id)))

        literature_rows = conn.execute(
            f"SELECT id, pdf_rel_path, pdf_path FROM {_quote_identifier(LITERATURE_TABLE_NAME)}"
        ).fetchall()
        for row_id, pdf_rel_path, pdf_path in literature_rows:
            existing_rel = normalize_db_relative_path(pdf_rel_path)
            if existing_rel:
                continue
            candidate_rel = build_relative_path_from_workspace(pdf_path, workspace_root=workspace_root)
            if candidate_rel:
                literature_updates.append((candidate_rel, int(row_id)))

        if not dry_run:
            if attachment_updates:
                conn.executemany(
                    f"UPDATE {ATTACHMENT_TABLE_NAME} SET path_rel = ? WHERE id = ?",
                    attachment_updates,
                )
            if literature_updates:
                conn.executemany(
                    f"UPDATE {_quote_identifier(LITERATURE_TABLE_NAME)} SET pdf_rel_path = ? WHERE id = ?",
                    literature_updates,
                )
            conn.commit()

    return {
        "status": "PASS",
        "dry_run": bool(dry_run),
        "content_db": str(resolved_db),
        "workspace_root": str(workspace_root),
        "attachment_update_count": len(attachment_updates),
        "literature_update_count": len(literature_updates),
        "sample_attachment_updates": [
            {"id": row_id, "path_rel": path_rel}
            for path_rel, row_id in attachment_updates[:10]
        ],
        "sample_literature_updates": [
            {"id": row_id, "pdf_rel_path": path_rel}
            for path_rel, row_id in literature_updates[:10]
        ],
    }


__all__ = [
    "AUTO_KNOWLEDGE_EVIDENCE_SOURCE_FIELDS",
    "AUTO_KNOWLEDGE_LINK_SOURCE_FIELDS",
    "ATTACHMENT_LINK_TABLE_NAME",
    "ATTACHMENT_TABLE_NAME",
    "AUTHOR_LINK_TABLE_NAME",
    "AUTHOR_TABLE_NAME",
    "CHUNK_SET_TABLE_NAME",
    "CHUNK_TABLE_NAME",
    "CONTENT_DB_DIRECTORY_NAME",
    "DEFAULT_CONTENT_DB_NAME",
    "FLOW_STATE_OVERVIEW_VIEW_NAME",
    "FLOW_STATE_REQUIRED_COLUMNS",
    "FLOW_STATE_TABLE_NAME",
    "FLOW_STATE_TO_LITERATURE_COLUMN_MAP",
    "KNOWLEDGE_EVIDENCE_TABLE_NAME",
    "KNOWLEDGE_ATTACHMENT_TABLE_NAME",
    "KNOWLEDGE_INDEX_TABLE_NAME",
    "KNOWLEDGE_LINK_TABLE_NAME",
    "KNOWLEDGE_NOTES_TABLE_NAME",
    "LITERATURE_TABLE_NAME",
    "LITERATURE_TAG_TABLE_NAME",
    "PARSE_ASSET_TABLE_NAME",
    "PARSE_ASSET_TO_ATTACHMENT_COLUMN_MAP",
    "PARSE_ASSET_TO_LITERATURE_COLUMN_MAP",
    "READING_QUEUE_TABLE_NAME",
    "READING_QUEUE_TO_LITERATURE_COLUMN_MAP",
    "READING_STATE_TO_LITERATURE_COLUMN_MAP",
    "TRANSLATION_ASSET_TABLE_NAME",
    "TRANSACTION_RELATION_FILTER_VIEWS",
    "TRANSACTION_RELATION_NODE_LABELS",
    "TRANSACTION_RELATION_OVERVIEW_VIEW_NAME",
    "READING_STATE_TABLE_NAME",
    "PDF_STRUCTURED_VARIANT_SPECS",
    "PDF_STRUCTURED_VARIANT_PATH_COLUMNS",
    "TAG_TABLE_NAME",
    "backfill_content_relationships",
    "build_pdf_structured_variant_dir_map",
    "backfill_content_relative_paths",
    "build_relative_path_from_workspace",
    "connect_sqlite",
    "get_pdf_structured_variant_column",
    "get_pdf_structured_variant_spec",
    "infer_workspace_root_from_content_db",
    "init_content_db",
    "load_attachment_entities_df",
    "load_author_entities_df",
    "derive_literature_parse_state",
    "normalize_literature_parse_state",
    "load_knowledge_evidence_links_df",
    "load_knowledge_literature_links_df",
    "load_literature_author_links_df",
    "load_literature_attachment_links_df",
    "load_translation_assets_df",
    "normalize_db_relative_path",
    "resolve_content_path",
    "resolve_content_path_candidates",
    "resolve_content_db_config",
    "resolve_content_db_path",
    "resolve_pdf_structured_variant_output_dir",
    "sync_author_entities_from_literature_rows",
    "sync_knowledge_relationships",
    "upsert_knowledge_literature_link",
    "upsert_translation_asset_rows",
    "WORKSPACE_NODE_STATE_TABLE_NAME",
]
