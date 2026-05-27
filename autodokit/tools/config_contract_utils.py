"""配置中文主契约与旧英文契约之间的标准化工具。"""

from __future__ import annotations

from typing import Any


LEGACY_TO_CHINESE_KEY_MAP: dict[str, str] = {
    "workflow_name": "工作流名称",
    "root_path": "工程根路径",
    "workspace_root": "工作区根路径",
    "project_root": "工程根路径",
    "venv_path": "虚拟环境路径",
    "project": "项目",
    "project_name": "项目名称",
    "project_goal": "项目目标",
    "git": "版本控制设置",
    "author_name": "作者名称",
    "author_email": "作者邮箱",
    "committer_name": "提交者名称",
    "committer_email": "提交者邮箱",
    "runtime": "运行时",
    "start_node": "开始节点",
    "end_node": "结束节点",
    "workflow_graph_uid": "流程图唯一标识",
    "workflow_graph_version": "流程图版本",
    "workflow_graph_path": "流程图路径",
    "workflow_aof_source_path": "流程图AOF源路径",
    "user_action_routing": "用户动作路由",
    "default_note_timezone": "默认笔记时区",
    "postprocess_mode": "后处理模式",
    "postprocess_after_each_node": "是否每节点后处理",
    "postprocess_required_skill": "后处理必需技能",
    "allow_affair_inline_postprocess": "是否允许事务内联后处理",
    "run_affair_postprocess_fallback": "事务后处理失败是否回退统一后处理",
    "enabled_nodes": "启用节点",
    "gate_mode": "闸门模式",
    "stop_at_each_gate": "是否在每个闸门暂停",
    "bootstrap_workspace": "是否初始化工作区",
    "postprocess_orchestration": "后处理编排",
    "required_skill": "必需技能",
    "enforce_after_each_node": "是否强制每节点执行",
    "logging": "日志",
    "enabled": "是否启用",
    "snapshot_mode": "快照模式",
    "bootstrap": "初始化",
    "template_root": "模板根路径",
    "task_uid": "任务唯一标识",
    "workflow_uid": "工作流唯一标识",
    "self_check_report_path": "自检报告路径",
    "require_zero_content_db_views": "是否要求零旧视图",
    "llm": "模型",
    "aliyun_api_key_file": "阿里云密钥文件",
    "monkeyocr_parse_model": "MonkeyOCR解析模型",
    "reference_parse_model": "参考文献解析模型",
    "reference_block_model": "参考文献分块模型",
    "review_state_model": "综述状态模型",
    "synthesis_model": "综合模型",
    "paths": "路径",
    "config_dir": "配置目录",
    "content_db_dir": "内容数据库目录",
    "content_db_path": "内容数据库路径",
    "decision_db_dir": "决策数据库目录",
    "decision_db_path": "决策数据库路径",
    "log_db_path": "日志数据库路径",
    "tasks_db_dir": "任务数据库目录",
    "tasks_db_path": "任务数据库路径",
    "literature_store_dir": "文献库目录",
    "attachments_dir": "附件目录",
    "bib_dir": "题录目录",
    "pdf_structured_dirs": "PDF结构化目录",
    "knowledge_root": "知识根目录",
    "docs_root": "文档根目录",
    "runtime_root": "运行时根目录",
    "logs_dir": "日志目录",
    "literature_views_dir": "文献视图目录",
    "affair_entry_registry_path": "事务入口注册表路径",
    "node_inputs": "节点输入",
    "node_contracts": "节点契约",
    "entry_config": "入口配置",
    "execute_function": "执行函数",
    "structured_source_priority": "结构化来源优先级",
    "disallowed_primary_text_source": "禁止主文本来源",
    "required_sections": "必需章节",
    "citation_suffix_format": "引文后缀格式",
    "primary_transport": "主传输通道",
    "contracts": "全局契约",
    "version": "版本",
    "updated_at": "更新时间",
    "scope": "作用范围",
    "summary": "摘要",
    "agent_overrides": "智能体覆盖",
    "is_auto_git_commit": "是否自动Git提交",
    "schema_version": "契约版本",
    "generated_at": "生成时间",
    "timezone": "时区",
    "records": "记录",
    "node_code": "节点编码",
    "node_name": "节点名称",
    "affair_uid": "事务唯一标识",
    "module": "模块路径",
    "callable": "入口函数",
    "implemented": "是否已实现",
    "config_path": "配置路径",
    "notes": "备注",
    "output_dir": "输出目录",
    "self_check_output_path": "自检输出路径",
    "create_missing_dirs": "是否创建缺失目录",
    "required_dirs": "必需目录",
    "log_level": "日志级别",
    "dry_run": "是否仅预演",
    "retry": "重试设置",
    "max_attempts": "最大尝试次数",
    "backoff_seconds": "退避秒数",
    "processing": "处理设置",
    "postprocess_contract": "后处理契约",
    "trigger_stage": "触发阶段",
    "content_db": "内容数据库路径",
    "attachments_target_dir": "附件目标目录",
    "query": "检索主题",
    "keyword_list": "关键词列表",
    "year_start": "起始年份",
    "year_end": "结束年份",
    "seed_items": "种子条目",
    "enable_local_retrieval": "是否启用本地检索",
    "max_local_hits": "最大本地命中数",
    "local_hit_threshold": "本地命中阈值",
    "enable_online_retrieval": "是否启用在线检索",
    "online_trigger_policy": "在线触发策略",
    "online_sources": "在线来源",
    "online_max_pages": "在线最大页数",
    "en_per_page": "英文每页条数",
    "online_acquisition_mode": "在线获取方式",
    "primary_attachment_normalization": "主附件规范化",
    "rename_mode": "重命名模式",
    "allowed_attachment_types": "允许附件类型",
    "update_parse_assets": "是否更新解析资产",
    "execution_mode": "执行模式",
    "profile": "预处理画像",
    "max_items": "最大条目数",
    "auto_fill_literature_type": "是否自动补全文献类型",
    "state_contract": "状态契约",
    "truth_source": "真相源",
    "consume_flags": "消费标记",
    "write_flags": "写回标记",
    "parse_model": "解析模型",
    "structured_converter": "结构化转换器",
    "structured_task_type": "结构化任务类型",
    "run_mode": "运行模式",
    "origin_bib_paths": "原始题录路径列表",
    "origin_attachments_root": "原始附件根目录",
    "origin_attachments_roots": "原始附件根目录列表",
    "graph_uid": "流程图唯一标识",
    "graph_name": "流程图名称",
    "graph_version": "流程图版本",
    "workflow_meta": "流程图元信息",
    "policies": "策略",
    "nodes": "节点",
    "edges": "边",
    "containers": "容器",
    "node_uid": "节点唯一标识",
    "node_type": "节点类型",
    "edge_uid": "边唯一标识",
    "from_node_uid": "起点节点唯一标识",
    "to_node_uid": "终点节点唯一标识",
    "condition_expr": "条件表达式",
    "route_mode": "路由模式",
    "task_mode": "任务模式",
    "decision_mode": "决策模式",
    "intervention_condition": "介入条件",
    "decision_candidates": "决策候选",
    "decision": "动作决策",
    "recommendation": "建议动作",
}

CHINESE_TO_LEGACY_KEY_MAP: dict[str, str] = {value: key for key, value in LEGACY_TO_CHINESE_KEY_MAP.items()}

LEGACY_TO_CHINESE_VALUE_MAP_BY_KEY: dict[str, dict[str, str]] = {
    "request_profile": {"zh": "中文", "en": "英文", "mixed": "混合"},
    "online_trigger_policy": {"gap_only": "仅缺口触发", "manual_seed_only": "仅人工种子触发"},
    "online_acquisition_mode": {"none": "不获取", "download_pdf": "下载PDF", "html_extract": "提取HTML"},
    "rename_mode": {"preview": "预演", "apply": "执行"},
    "execution_mode": {"priority_only": "仅生成优先级", "full_preprocess": "执行完整预处理"},
    "profile": {"review": "综述", "non_review": "非综述", "mixed": "混合", "default": "默认"},
    "structured_task_type": {
        "review_deep": "综述深度解析",
        "non_review_rough": "普通文献粗解析",
        "non_review_deep": "普通文献深解析",
        "reference_context": "参考文献上下文",
        "full_fine_grained": "全文细粒度",
    },
    "run_mode": {
        "local_only": "仅本地",
        "local_dispatch_remote": "本地分发远端",
        "remote_only_tmux": "仅远端Tmux",
        "record_parse_results": "仅登记解析结果",
    },
    "postprocess_mode": {"pa_unified": "PA统一调度"},
    "mode": {"pa_unified": "PA统一调度"},
    "gate_mode": {"manual_confirm": "人工确认", "auto_pass": "自动通过", "strict": "严格模式"},
    "snapshot_mode": {"log_only": "仅日志快照", "git_snapshot": "Git快照", "none": "不生成快照"},
    "route_mode": {"direct": "直达", "decision": "决策"},
    "task_mode": {"workspace_lite": "工作区轻账本"},
    "decision_mode": {"JOINT": "联合", "PA-only": "仅PA", "HUMAN-only": "仅人工"},
    "intervention_condition": {"abnormal_upgrade": "异常升级", "always": "总是"},
    "decision": {"pass_next": "放行下一步", "retry_current": "重试当前", "pause_current": "暂停当前", "fallback_current": "回退当前"},
    "recommendation": {"pass_next": "放行下一步", "retry_current": "重试当前", "pause_current": "暂停当前", "fallback_current": "回退当前"},
    "gate_action": {"pass_next": "放行下一步", "retry_current": "重试当前", "pause_current": "暂停当前", "fallback_current": "回退当前"},
    "decision_candidates": {"pass_next": "放行下一步", "retry_current": "重试当前", "pause_current": "暂停当前", "fallback_current": "回退当前"},
}

CHINESE_TO_LEGACY_VALUE_MAP_BY_KEY: dict[str, dict[str, str]] = {
    key: {translated: legacy for legacy, translated in mapping.items()}
    for key, mapping in LEGACY_TO_CHINESE_VALUE_MAP_BY_KEY.items()
}


def _translate_scalar(value: Any, key_name: str, mapping_by_key: dict[str, dict[str, str]]) -> Any:
    if not isinstance(value, str):
        return value
    mapping = mapping_by_key.get(key_name)
    if not mapping:
        return value
    direct = mapping.get(value)
    if direct is not None:
        return direct

    normalized_value = value.casefold()
    for source, target in mapping.items():
        if isinstance(source, str) and source.casefold() == normalized_value:
            return target
    return value


def _translate_payload(
    payload: Any,
    *,
    key_map: dict[str, str],
    value_map_by_key: dict[str, dict[str, str]],
    current_key: str = "",
) -> Any:
    if isinstance(payload, dict):
        translated: dict[str, Any] = {}
        for key, value in payload.items():
            source_key = str(key)
            target_key = key_map.get(source_key, source_key)
            normalized_key = CHINESE_TO_LEGACY_KEY_MAP.get(target_key, target_key)
            translated[target_key] = _translate_payload(
                value,
                key_map=key_map,
                value_map_by_key=value_map_by_key,
                current_key=normalized_key,
            )
        return translated
    if isinstance(payload, list):
        return [
            _translate_payload(
                item,
                key_map=key_map,
                value_map_by_key=value_map_by_key,
                current_key=current_key,
            )
            for item in payload
        ]
    return _translate_scalar(payload, current_key, value_map_by_key)


def normalize_to_legacy_contract(payload: Any) -> Any:
    """把中文主契约转换为兼容旧执行层的英文内部契约。"""

    return _translate_payload(
        payload,
        key_map=CHINESE_TO_LEGACY_KEY_MAP,
        value_map_by_key=CHINESE_TO_LEGACY_VALUE_MAP_BY_KEY,
    )


def export_to_chinese_contract(payload: Any) -> Any:
    """把旧英文内部契约导出为中文主契约。"""

    return _translate_payload(
        payload,
        key_map=LEGACY_TO_CHINESE_KEY_MAP,
        value_map_by_key=LEGACY_TO_CHINESE_VALUE_MAP_BY_KEY,
    )


def get_alias_value(mapping: dict[str, Any], legacy_key: str, default: Any = None) -> Any:
    """优先读旧键，其次读中文主契约键。"""

    if legacy_key in mapping:
        return mapping.get(legacy_key)
    chinese_key = LEGACY_TO_CHINESE_KEY_MAP.get(legacy_key)
    if chinese_key and chinese_key in mapping:
        return mapping.get(chinese_key)
    return default


__all__ = [
    "LEGACY_TO_CHINESE_KEY_MAP",
    "LEGACY_TO_CHINESE_VALUE_MAP_BY_KEY",
    "CHINESE_TO_LEGACY_KEY_MAP",
    "CHINESE_TO_LEGACY_VALUE_MAP_BY_KEY",
    "normalize_to_legacy_contract",
    "export_to_chinese_contract",
    "get_alias_value",
]