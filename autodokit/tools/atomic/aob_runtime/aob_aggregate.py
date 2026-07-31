# -*- coding: utf-8 -*-
"""AOB 聚合原子工具（aggregate-user-content）。

将各引擎办公区的 AI 内容收集、反编译为 AOL、合并后写入 canonical.aol.json。
"""

from __future__ import annotations

from .aob_common import *

import shutil
import tempfile
import json
from pathlib import Path
from typing import Any


def 准备来源办公区(source: 聚合来源) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    """将来源转换为可供 AOC ingest 的办公区结构。"""

    if source.layout == "structured_root":
        return source.source_path, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"aob-aggregate-{source.source_label}-")
    workspace_root = Path(temp_dir.name) / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    if source.layout == "prompt_root":
        for child in sorted(source.source_path.rglob("*")):
            if not child.is_file():
                continue
            content_type = 推断单文件内容类型(child)
            if not content_type:
                continue
            relative = child.relative_to(source.source_path)
            if content_type == "instructions":
                复制文件到临时办公区(source_file=child, target_file=workspace_root / "instructions" / relative)
            elif content_type == "settings":
                复制文件到临时办公区(source_file=child, target_file=workspace_root / "settings" / relative)
            else:
                复制文件到临时办公区(source_file=child, target_file=workspace_root / "prompts" / relative)
        return workspace_root, temp_dir

    content_type = 推断单文件内容类型(source.source_path)
    if not content_type:
        return workspace_root, temp_dir
    if content_type == "instructions":
        复制文件到临时办公区(source_file=source.source_path, target_file=workspace_root / "instructions" / source.source_path.name)
    elif content_type == "settings":
        复制文件到临时办公区(source_file=source.source_path, target_file=workspace_root / "settings" / source.source_path.name)
    else:
        复制文件到临时办公区(source_file=source.source_path, target_file=workspace_root / "prompts" / source.source_path.name)
    return workspace_root, temp_dir

def 来源构建AOL(paths: 路径配置, *, source: 聚合来源) -> tuple[Any | None, dict[str, Any], list[str]]:
    """把单个来源转换为 AOL 对象。"""

    stats = 构建聚合统计(source)
    warnings: list[str] = []
    contract_level, contract_note = 解析供应商载体契约级别(
        layout=source.layout,
        engine_vendor=source.engine_vendor,
        ide_vendor=source.ide_vendor,
        scope=source.scope,
    )
    stats["contract_level"] = contract_level
    stats["contract_note"] = contract_note
    if contract_level == "heuristic":
        warnings.append(
            f"来源 {source.source_label} 使用经验性载体契约（layout={source.layout}, engine={source.engine_vendor}, ide={source.ide_vendor}）：{contract_note}"
        )
    if not AOL运行时可用():
        stats["errors"].append("aoc runtime 不可用，无法聚合来源")
        return None, stats, warnings

    source_engine = 归一化引擎供应商(engine_vendor=source.engine_vendor, ide_vendor=source.ide_vendor)
    if str(source.engine_vendor or "").strip().lower() not in 默认AOC支持引擎:
        warnings.append(
            f"来源 {source.source_label} 的 engine_vendor={source.engine_vendor} 不在 AOC 支持列表，已映射为 {source_engine}"
        )

    workspace_root, temp_dir = 准备来源办公区(source)
    try:
        aol, counts = 从引擎办公区构建_aol(
            source_workspace_dir=workspace_root,
            source_engine=source_engine,
            title=f"{source.source_label} canonical AOL",
        )
    except Exception as exc:  # noqa: BLE001
        stats["errors"].append(f"来源 AOL 转换失败：{exc}")
        return None, stats, warnings
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    stats["aol_source_engine"] = source_engine
    stats["aol_counts"] = {
        "agents": int(counts.get("agents", 0)),
        "skills": int(counts.get("skills", 0)),
        "rules": int(counts.get("rules", 0)),
        "commands": int(counts.get("commands", 0)),
        "assets": int(counts.get("assets", 0)),
        "hooks": int(counts.get("hooks", 0)),
        "configs": int(counts.get("configs", 0)),
    }
    stats["added"] = (
        stats["aol_counts"]["agents"]
        + stats["aol_counts"]["skills"]
        + stats["aol_counts"]["rules"]
        + stats["aol_counts"]["commands"]
        + stats["aol_counts"]["assets"]
    )
    return aol, stats, warnings

def 生成唯一名称(*, base: str, used: set[str]) -> str:
    """生成不冲突名称。"""

    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate

def 合并来源AOL(paths: 路径配置, *, aol_entries: list[tuple[聚合来源, Any]]) -> tuple[Any, list[str]]:
    """把多个来源 AOL 合并为一个 canonical AOL。"""

    warnings: list[str] = []
    if not aol_entries:
        merged_payload = {
            "version": "1",
            "title": f"{paths.repo_root.name} canonical AOL",
            "instructions": [],
            "agents": [],
            "skills": [],
            "rules": [],
            "commands": [],
            "project_instruction": None,
            "claude_md": None,
            "hooks": [],
            "mcp_servers": {},
            "settings": {},
            "policies": {},
            "engine_native": {},
            "extra_assets": [],
        }
        return payload转AOL对象(merged_payload), warnings

    merged_payload: dict[str, Any] = {
        "version": "1",
        "title": f"{paths.repo_root.name} canonical AOL",
        "instructions": [],
        "agents": [],
        "skills": [],
        "rules": [],
        "commands": [],
        "project_instruction": None,
        "claude_md": None,
        "hooks": [],
        "mcp_servers": {},
        "settings": {},
        "policies": {},
        "engine_native": {},
        "extra_assets": [],
    }

    instructions_seen: set[str] = set()
    project_instruction_parts: list[str] = []
    claude_md_parts: list[str] = []

    agent_signatures: dict[str, str] = {}
    skill_signatures: dict[str, str] = {}
    rule_signatures: dict[str, str] = {}
    command_signatures: dict[str, str] = {}
    hook_contents: dict[str, str] = {}
    extra_contents: dict[str, str] = {}

    used_agents: set[str] = set()
    used_skills: set[str] = set()
    used_rules: set[str] = set()
    used_commands: set[str] = set()

    for source, aol in aol_entries:
        for item in list(aol.instructions or []):
            text = str(item).strip()
            if not text or text in instructions_seen:
                continue
            instructions_seen.add(text)
            merged_payload["instructions"].append(text)

        if aol.project_instruction and str(aol.project_instruction).strip():
            text = str(aol.project_instruction).strip()
            if text not in project_instruction_parts:
                project_instruction_parts.append(text)

        if aol.claude_md and str(aol.claude_md).strip():
            text = str(aol.claude_md).strip()
            if text not in claude_md_parts:
                claude_md_parts.append(text)

        merged_payload["mcp_servers"].update(dict(aol.mcp_servers or {}))
        merged_payload["settings"].update(dict(aol.settings or {}))
        merged_payload["policies"].update(dict(aol.policies or {}))
        merged_payload["engine_native"].update(dict(aol.engine_native or {}))

        for agent in list(aol.agents or []):
            payload = 代理对象转payload(agent)
            base = str(payload["id"]).strip() or "agent"
            signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            existing_sig = agent_signatures.get(base)
            if existing_sig == signature:
                continue
            if existing_sig is None and base not in used_agents:
                final_id = 生成唯一名称(base=base, used=used_agents)
            else:
                final_id = 生成唯一名称(base=f"{base}-{source.source_label}", used=used_agents)
                warnings.append(f"代理 ID 冲突：{base} -> {final_id}")
            payload["id"] = final_id
            agent_signatures[final_id] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            merged_payload["agents"].append(payload)

        for skill in list(aol.skills or []):
            payload = 技能对象转payload(skill)
            base = str(payload["name"]).strip() or "skill"
            signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            existing_sig = skill_signatures.get(base)
            if existing_sig == signature:
                continue
            if existing_sig is None and base not in used_skills:
                final_name = 生成唯一名称(base=base, used=used_skills)
            else:
                final_name = 生成唯一名称(base=f"{base}-{source.source_label}", used=used_skills)
                warnings.append(f"技能名称冲突：{base} -> {final_name}")
            payload["name"] = final_name
            skill_signatures[final_name] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            merged_payload["skills"].append(payload)

        for rule in list(aol.rules or []):
            payload = 规则对象转payload(rule)
            base = str(payload["id"]).strip() or "rule"
            signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            existing_sig = rule_signatures.get(base)
            if existing_sig == signature:
                continue
            if existing_sig is None and base not in used_rules:
                final_id = 生成唯一名称(base=base, used=used_rules)
            else:
                final_id = 生成唯一名称(base=f"{base}-{source.source_label}", used=used_rules)
                warnings.append(f"规则 ID 冲突：{base} -> {final_id}")
            payload["id"] = final_id
            rule_signatures[final_id] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            merged_payload["rules"].append(payload)

        for command in list(aol.commands or []):
            payload = 命令对象转payload(command)
            base = str(payload["id"]).strip() or "command"
            signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            existing_sig = command_signatures.get(base)
            if existing_sig == signature:
                continue
            if existing_sig is None and base not in used_commands:
                final_id = 生成唯一名称(base=base, used=used_commands)
            else:
                final_id = 生成唯一名称(base=f"{base}-{source.source_label}", used=used_commands)
                warnings.append(f"命令 ID 冲突：{base} -> {final_id}")
            payload["id"] = final_id
            command_signatures[final_id] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            merged_payload["commands"].append(payload)

        for asset in list(aol.hooks or []):
            payload = 载体对象转payload(asset)
            rel = str(payload["path"]).strip().replace("\\", "/")
            if not rel:
                continue
            content = str(payload["content"])
            existing = hook_contents.get(rel)
            if existing == content:
                continue
            if existing is not None and existing != content:
                rel = f"sources/{source.source_label}/{rel}"
                warnings.append(f"hooks 载体冲突，已重命名为：{rel}")
            hook_contents[rel] = content
            merged_payload["hooks"].append({"path": rel, "content": content})

        for asset in list(aol.extra_assets or []):
            payload = 载体对象转payload(asset)
            rel = str(payload["path"]).strip().replace("\\", "/")
            if not rel:
                continue
            content = str(payload["content"])
            existing = extra_contents.get(rel)
            if existing == content:
                continue
            if existing is not None and existing != content:
                rel = f"sources/{source.source_label}/{rel}"
                warnings.append(f"extra_assets 载体冲突，已重命名为：{rel}")
            extra_contents[rel] = content
            merged_payload["extra_assets"].append({"path": rel, "content": content})

    if project_instruction_parts:
        merged_payload["project_instruction"] = "\n\n".join(project_instruction_parts)
    if claude_md_parts:
        merged_payload["claude_md"] = "\n\n".join(claude_md_parts)

    merged_aol = payload转AOL对象(merged_payload)
    return merged_aol, warnings

def 准备用户级内容聚合沙盒(
    paths: 路径配置,
    *,
    sources: list[聚合来源],
    home_dir: str = "",
    sandbox_dir: str,
) -> tuple[路径配置, list[聚合来源], dict[str, Any]]:
    """把当前 libs canonical 与聚合来源复制到独立沙盒。"""

    sandbox_root = 解析唯一沙盒根目录(home_dir=home_dir, sandbox_dir=sandbox_dir)
    sandbox_paths = 构建沙盒路径配置(sandbox_root=sandbox_root)
    复制用户级内容沙盒仓库基线(paths, sandbox_paths=sandbox_paths)

    sandbox_sources: list[聚合来源] = []
    sandbox_source_summaries: list[dict[str, Any]] = []
    path_mappings: list[dict[str, str]] = []
    for source in sources:
        if source.scope == "project":
            source_container_root = source.source_path.parent
            mirror_rel = 计算沙盒镜像相对路径(real_path=source_container_root, home_dir=home_dir)
            sandbox_container_root = (sandbox_root / mirror_rel).resolve()
            if source_container_root.exists():
                复制到沙盒镜像(source=source_container_root, destination=sandbox_container_root)
            sandbox_source_path = sandbox_container_root / source.source_path.name
        else:
            mirror_rel = 计算沙盒镜像相对路径(real_path=source.source_path, home_dir=home_dir)
            sandbox_source_path = (sandbox_root / mirror_rel).resolve()
            if source.source_path.exists():
                复制到沙盒镜像(source=source.source_path, destination=sandbox_source_path)

        sandbox_sources.append(
            聚合来源(
                source_path=sandbox_source_path,
                source_label=source.source_label,
                layout=source.layout,
                engine_vendor=source.engine_vendor,
                ide_vendor=source.ide_vendor,
                scope=source.scope,
            )
        )
        sandbox_source_summaries.append(
            {
                "source_label": source.source_label,
                "layout": source.layout,
                "scope": source.scope,
                "original_path": str(source.source_path),
                "container_root": str(source.source_path.parent if source.scope == "project" else source.source_path),
                "sandbox_path": str(sandbox_source_path),
                "exists_in_source": bool(source.source_path.exists()),
            }
        )
        path_mappings.append(
            {
                "role": "source",
                "label": source.source_label,
                "scope": source.scope,
                "real_path": str(source.source_path),
                "sandbox_path": str(sandbox_source_path),
            }
        )

    # 落盘 path_mapping.json
    mapping_payload = {
        "sandbox_root": str(sandbox_root),
        "home_dir": str(用户主目录(home_dir)),
        "layout_mode": "mirror_real_paths",
        "mappings": path_mappings,
    }
    mapping_path = sandbox_root / "path_mapping.json"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(json.dumps(mapping_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return sandbox_paths, sandbox_sources, {
        "enabled": True,
        "sandbox_root": str(sandbox_root),
        "layout_mode": "mirror_real_paths",
        "path_mappings": path_mappings,
        "sources": sandbox_source_summaries,
        "path_mapping_file": str(mapping_path),
    }

def 执行聚合用户级内容阶段(
    paths: 路径配置,
    *,
    source_paths: list[str],
    home_dir: str,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool,
    sync_items_after: bool,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    resolved_sources_override: list[聚合来源] | None = None,
) -> tuple[dict[str, Any], Any]:
    """执行聚合阶段并返回聚合摘要与合并后的 AOL。"""

    if not AOL运行时可用():
        raise ValueError("aoc runtime 不可用，无法执行 aggregate-user-content")

    if resolved_sources_override is not None:
        sources = list(resolved_sources_override)
    else:
        sources = 解析聚合来源(
            source_paths,
            paths=paths,
            home_dir=home_dir,
            scopes=scopes,
            project_dirs=project_dirs,
        )

    if simulate_only:
        sandbox_paths, sandbox_sources, sandbox_summary = 准备用户级内容聚合沙盒(
            paths,
            sources=sources,
            home_dir=home_dir,
            sandbox_dir=sandbox_dir,
        )
        sandbox_result, merged_aol = 执行聚合用户级内容阶段(
            sandbox_paths,
            source_paths=[],
            home_dir="",
            scopes=scopes,
            project_dirs=project_dirs,
            dry_run=dry_run,
            sync_items_after=sync_items_after,
            simulate_only=False,
            sandbox_dir="",
            resolved_sources_override=sandbox_sources,
        )
        sandbox_result["sandbox"] = sandbox_summary
        sandbox_result["simulate_only"] = True
        sandbox_result["source_repo_root"] = str(paths.repo_root)
        return sandbox_result, merged_aol

    summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "source_count": len(sources),
        "added": 0,
        "updated": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "sources": [],
        "errors": [],
        "touched_paths": [],
        "aggregate_warnings": [],
        "sandbox": {"enabled": False},
        "simulate_only": False,
    }

    source_aol_entries: list[tuple[聚合来源, Any]] = []

    for source in sources:
        aol, part, warnings = 来源构建AOL(paths, source=source)
        合并聚合统计(summary, part)
        summary["aggregate_warnings"].extend(warnings)
        if aol is not None:
            source_aol_entries.append((source, aol))

    merged_aol, merge_warnings = 合并来源AOL(paths, aol_entries=source_aol_entries)
    summary["aggregate_warnings"].extend(merge_warnings)
    canonical_write = 写入canonical_AOL(paths, aol=merged_aol, dry_run=dry_run)
    summary["canonical_aol"] = canonical_write
    summary["added"] = 1 if canonical_write["status"].endswith("added") else 0
    summary["updated"] = 1 if canonical_write["status"].endswith("updated") else 0
    summary["skipped_same"] = 1 if canonical_write["status"].endswith("unchanged") else 0
    if canonical_write.get("path"):
        summary["touched_paths"].append(str(canonical_write["path"]))

    if sync_items_after and not dry_run and (summary["added"] or summary["updated"]):
        summary["items_sync"] = 同步_items(paths, dry_run=False)
    elif sync_items_after:
        summary["items_sync"] = {
            "enabled": False,
            "reason": "dry_run 模式或无新增变更，跳过 items sync",
            "dry_run": dry_run,
        }
    else:
        summary["items_sync"] = {
            "enabled": False,
            "reason": "显式关闭 items sync",
            "dry_run": dry_run,
        }

    if dry_run:
        summary["aol_intermediate"] = 构建AOL摘要(
            merged_aol,
            source="in_memory_dry_run",
            canonical_path=Path(str(canonical_write.get("path") or "")) if canonical_write.get("path") else None,
            warnings=list(summary["aggregate_warnings"]),
        )
    else:
        summary["aol_intermediate"] = 构建libs_aol中转摘要(paths)

    return summary, merged_aol

def 聚合用户级内容(
    paths: 路径配置,
    *,
    source_paths: list[str],
    home_dir: str,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool,
    sync_items_after: bool,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    resolved_sources_override: list[聚合来源] | None = None,
) -> dict[str, Any]:
    """聚合当前设备用户级 AI 内容到 libs。"""

    summary, _merged_aol = 执行聚合用户级内容阶段(
        paths,
        source_paths=source_paths,
        home_dir=home_dir,
        scopes=scopes,
        project_dirs=project_dirs,
        dry_run=dry_run,
        sync_items_after=sync_items_after,
        simulate_only=simulate_only,
        sandbox_dir=sandbox_dir,
        resolved_sources_override=resolved_sources_override,
    )
    return summary



# --- items/tags 委托到 aob_items / aob_tags ---

from .aob_items import 读取_items, 写入_items, 写入关系表, 读取关系表, 同步_items, 执行_items
from .aob_tags import 执行_tags

def 执行聚合用户级内容(argv: list[str], paths: 路径配置) -> int:
    """执行用户级内容聚合子命令。"""

    parser = argparse.ArgumentParser(description="按范围聚合当前设备或项目中的 AI 内容到 libs")
    parser.add_argument("--source-path", action="append", default=[], help="可选：显式指定来源路径，可重复传入")
    parser.add_argument("--scope", action="append", default=[], help="可选：自动发现范围，可重复传入 global/system/user/project")
    parser.add_argument("--project-dir", action="append", default=[], help="可选：项目级自动发现根目录，可重复传入")
    parser.add_argument("--home-dir", default="", help="可选：覆盖自动发现使用的用户主目录")
    parser.add_argument("--dry-run", action="store_true", help="仅输出变更预览，不写入磁盘")
    parser.add_argument("--skip-items-sync", action="store_true", help="聚合完成后跳过 items sync")
    parser.add_argument("--simulate-only", action="store_true", help="仅在沙盒副本中执行聚合，不修改真实目录")
    parser.add_argument("--sandbox-dir", default="", help="可选：沙盒根目录；不传则默认使用 Downloads 下的时间戳目录")
    args = parser.parse_args(argv)

    stats = 聚合用户级内容(
        paths,
        source_paths=[str(item).strip() for item in list(args.source_path or []) if str(item).strip()],
        home_dir=str(args.home_dir or "").strip(),
        scopes=[str(item).strip() for item in list(args.scope or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(args.project_dir or []) if str(item).strip()],
        dry_run=bool(args.dry_run),
        sync_items_after=not bool(args.skip_items_sync),
        simulate_only=bool(args.simulate_only),
        sandbox_dir=str(args.sandbox_dir or "").strip(),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0
