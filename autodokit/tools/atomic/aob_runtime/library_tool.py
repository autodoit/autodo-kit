#!/usr/bin/env python3
"""AOB CLI 路由层。共享基础设施已拆分到 aob_common.py。"""
from __future__ import annotations
from .aob_common import *
import argparse, json, sys
from pathlib import Path
from typing import Any
try:
    from .aob_sync_undo import 创建撤销账本 as _撤销账本
except Exception:
    _撤销账本 = None
try:
    from .aob_zh_index import 生成中文索引, 查询中文索引, 默认输出目录 as _默认zh输出目录
except Exception:
    生成中文索引 = None
    查询中文索引 = None
    _默认zh输出目录 = None
def 发布到单个目标并同步删除(
    *,
    aol: Any,
    target: 发布目标,
    dry_run: bool,
    warnings: list[str],
    previous_managed_files: set[str],
    journal: Any = None,
    cleanup_unknown: bool = False,
) -> tuple[dict[str, Any], set[str]]:
    """发布到单个目标并同步删除过期托管文件。"""

    stats = 构建发布统计(target)
    target_engine = 归一化引擎供应商(engine_vendor=target.engine_vendor, ide_vendor=target.ide_vendor)
    if str(target.engine_vendor or "").strip().lower() not in 默认AOC支持引擎:
        warnings.append(
            f"目标 {target.target_label} 的 engine_vendor={target.engine_vendor} 不在 AOC 支持列表，已映射为 {target_engine}"
        )
    stats["aoc_target_engine"] = target_engine

    temp_dir = tempfile.TemporaryDirectory(prefix=f"aob-update-{target.target_label}-")
    managed_files: set[str] = set()
    try:
        compile_workspace_root = Path(temp_dir.name) / "workspace"
        compile_workspace_root.mkdir(parents=True, exist_ok=True)
        编译_aol到引擎办公区(
            aol=aol,
            target_workspace_dir=compile_workspace_root,
            target_engine=target_engine,
        )

        if target.layout == "prompt_root":
            发布编译结果到提示词目录(
                compile_workspace_root=compile_workspace_root,
                target=target,
                dry_run=dry_run,
                stats=stats,
                journal=journal,
            )
            managed_files = 收集提示词目标托管文件(compile_workspace_root)
        else:
            发布编译结果到结构化目录(
                compile_workspace_root=compile_workspace_root,
                target=target,
                dry_run=dry_run,
                stats=stats,
                journal=journal,
            )
            managed_files = 收集结构化目标托管文件(compile_workspace_root, target=target)
    finally:
        temp_dir.cleanup()

    stale_files = {item for item in previous_managed_files if item and item not in managed_files}
    stats["stale_managed_file_count"] = len(stale_files)
    删除目标过期托管文件(target=target, stale_files=stale_files, dry_run=dry_run, stats=stats, journal=journal)
    if cleanup_unknown and target.layout != "prompt_root":
        清理目标未跟踪文件(target=target, managed_files=managed_files, dry_run=dry_run, stats=stats, journal=journal)
    stats["managed_file_count"] = len(managed_files)
    return stats, managed_files


def 文件内容一致(source_file: Path, target_file: Path) -> bool:
    """判断两个文件内容是否一致。"""

    if not source_file.exists() or not target_file.exists() or not source_file.is_file() or not target_file.is_file():
        return False
    return filecmp.cmp(str(source_file), str(target_file), shallow=False)


def 复制聚合文件(*, source_file: Path, target_file: Path, dry_run: bool, stats: dict[str, Any], journal: Any = None) -> None:
    """按“较新优先”策略复制单个聚合文件。

    Args:
        source_file: 来源文件。
        target_file: 目标文件。
        dry_run: 是否预演。
        stats: 发布统计累加器。
        journal: 可选撤销账本；存在时在覆盖/新增前后登记撤销操作。
    """

    is_overwrite = False
    if target_file.exists():
        if target_file.is_dir():
            stats["errors"].append(f"目标路径为目录，无法覆盖文件：{target_file}")
            return
        if 文件内容一致(source_file, target_file):
            stats["skipped_same"] += 1
            return
        if source_file.stat().st_mtime <= target_file.stat().st_mtime:
            stats["skipped_target_newer"] += 1
            return
        stats["updated"] += 1
        is_overwrite = True
    else:
        stats["added"] += 1

    stats["touched_paths"].append(str(target_file))
    if dry_run:
        return

    if journal is not None:
        if is_overwrite:
            journal.记录将覆盖(target_file)
        else:
            journal.记录将创建(target_file)

    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, target_file)

    if journal is not None:
        journal.标记同步后哈希(target_file)


def 复制聚合条目(*, source_path: Path, target_path: Path, dry_run: bool, stats: dict[str, Any], journal: Any = None) -> None:
    """复制单个聚合条目，支持文件或目录。"""

    if source_path.is_dir():
        for child in sorted(source_path.rglob("*")):
            if not child.is_file():
                continue
            relative = child.relative_to(source_path)
            复制聚合文件(
                source_file=child,
                target_file=target_path / relative,
                dry_run=dry_run,
                stats=stats,
                journal=journal,
            )
        return

    复制聚合文件(source_file=source_path, target_file=target_path, dry_run=dry_run, stats=stats, journal=journal)


def 是否提示词发布文件(file_path: Path, *, content_type: str) -> bool:
    """判断文件是否适合发布到 prompts 根目录。"""

    if not file_path.is_file():
        return False
    lowered = file_path.name.lower()
    if content_type == "prompts":
        return lowered.endswith(".prompt.md")
    if content_type == "instructions":
        return lowered.endswith(".instructions.md")
    return False


def 复制文件到临时办公区(*, source_file: Path, target_file: Path) -> None:
    """复制文件到临时办公区。"""

    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, target_file)


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


def 发布编译结果到结构化目录(*, compile_workspace_root: Path, target: 发布目标, dry_run: bool, stats: dict[str, Any], journal: Any = None) -> None:
    """把 AOC 编译结果发布到结构化目标目录。"""

    for source_file in sorted(path for path in compile_workspace_root.rglob("*") if path.is_file()):
        relative = source_file.relative_to(compile_workspace_root)
        复制聚合文件(
            source_file=source_file,
            target_file=target.target_path / relative,
            dry_run=dry_run,
            stats=stats,
            journal=journal,
        )

    for root_name in ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "opencode.json"]:
        source_file = compile_workspace_root.parent / root_name
        if not source_file.exists() or not source_file.is_file():
            continue
        if target.scope == "project":
            target_file = target.target_path.parent / root_name
        else:
            target_file = target.target_path / root_name
        复制聚合文件(
            source_file=source_file,
            target_file=target_file,
            dry_run=dry_run,
            stats=stats,
            journal=journal,
        )


def 发布编译结果到提示词目录(*, compile_workspace_root: Path, target: 发布目标, dry_run: bool, stats: dict[str, Any], journal: Any = None) -> None:
    """把 AOC 编译结果中的 prompts/instructions 投影到 prompts 根目录。"""

    for content_type in ["prompts", "instructions"]:
        source_root = compile_workspace_root / content_type
        if not source_root.exists() or not source_root.is_dir():
            continue
        for source_file in sorted(path for path in source_root.rglob("*") if path.is_file()):
            if not 是否提示词发布文件(source_file, content_type=content_type):
                continue
            relative = source_file.relative_to(source_root)
            复制聚合文件(
                source_file=source_file,
                target_file=target.target_path / relative,
                dry_run=dry_run,
                stats=stats,
                journal=journal,
            )


def 发布到单个目标(*, aol: Any, target: 发布目标, dry_run: bool, warnings: list[str]) -> dict[str, Any]:
    """把 AOL 编译后发布到单个目标目录。"""

    stats = 构建发布统计(target)
    contract_level, contract_note = 解析供应商载体契约级别(
        layout=target.layout,
        engine_vendor=target.engine_vendor,
        ide_vendor=target.ide_vendor,
        scope=target.scope,
    )
    stats["contract_level"] = contract_level
    stats["contract_note"] = contract_note
    if contract_level == "heuristic":
        warnings.append(
            f"目标 {target.target_label} 使用经验性载体契约（layout={target.layout}, engine={target.engine_vendor}, ide={target.ide_vendor}）：{contract_note}"
        )
    target_engine = 归一化引擎供应商(engine_vendor=target.engine_vendor, ide_vendor=target.ide_vendor)
    if str(target.engine_vendor or "").strip().lower() not in 默认AOC支持引擎:
        warnings.append(
            f"目标 {target.target_label} 的 engine_vendor={target.engine_vendor} 不在 AOC 支持列表，已映射为 {target_engine}"
        )
    stats["aoc_target_engine"] = target_engine

    temp_dir = tempfile.TemporaryDirectory(prefix=f"aob-publish-{target.target_label}-")
    try:
        compile_workspace_root = Path(temp_dir.name) / "workspace"
        compile_workspace_root.mkdir(parents=True, exist_ok=True)
        编译_aol到引擎办公区(
            aol=aol,
            target_workspace_dir=compile_workspace_root,
            target_engine=target_engine,
        )

        if target.layout == "prompt_root":
            发布编译结果到提示词目录(
                compile_workspace_root=compile_workspace_root,
                target=target,
                dry_run=dry_run,
                stats=stats,
            )
        else:
            发布编译结果到结构化目录(
                compile_workspace_root=compile_workspace_root,
                target=target,
                dry_run=dry_run,
                stats=stats,
            )
    finally:
        temp_dir.cleanup()

    return stats


def 发布用户级内容(
    paths: 路径配置,
    *,
    target_paths: list[str],
    home_dir: str,
    engine_vendors: list[str],
    ide_vendors: list[str],
    include_missing: bool,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool,
    simulate_only: bool = False,
    sandbox_dir: str = "",
    resolved_targets_override: list[发布目标] | None = None,
) -> dict[str, Any]:
    """把集中在 libs 的内容发布到当前设备的用户级 AI 办公区。"""

    if not AOL运行时可用():
        raise ValueError("aoc runtime 不可用，无法执行 publish-user-content")

    if resolved_targets_override is not None:
        targets = list(resolved_targets_override)
    else:
        targets = 解析发布目标(
            target_paths,
            paths=paths,
            home_dir=home_dir,
            engine_vendors=engine_vendors,
            ide_vendors=ide_vendors,
            scopes=scopes,
            project_dirs=project_dirs,
            include_missing=include_missing,
        )

    if simulate_only:
        sandbox_paths, sandbox_targets, sandbox_summary = 准备用户级内容同步沙盒(
            paths,
            targets=targets,
            home_dir=home_dir,
            sandbox_dir=sandbox_dir,
        )
        sandbox_result = 发布用户级内容(
            sandbox_paths,
            target_paths=[],
            home_dir="",
            engine_vendors=[],
            ide_vendors=[],
            include_missing=True,
            dry_run=dry_run,
            simulate_only=False,
            sandbox_dir="",
            resolved_targets_override=sandbox_targets,
        )
        sandbox_result["sandbox"] = sandbox_summary
        sandbox_result["simulate_only"] = True
        sandbox_result["source_repo_root"] = str(paths.repo_root)
        return sandbox_result

    aol_intermediate = 构建libs_aol中转摘要(paths)
    if aol_intermediate.get("enabled") and aol_intermediate.get("status") != "ok":
        raise ValueError(f"AOL 中转构建失败：{aol_intermediate}")

    aol = 读取canonical_AOL(paths)

    summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "target_count": len(targets),
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "targets": [],
        "errors": [],
        "touched_paths": [],
        "aol_intermediate": aol_intermediate,
        "publish_warnings": [],
        "sandbox": {"enabled": False},
        "simulate_only": False,
    }

    for target in targets:
        part = 发布到单个目标(
            aol=aol,
            target=target,
            dry_run=dry_run,
            warnings=summary["publish_warnings"],
        )
        合并发布统计(summary, part)

    return summary


def 默认用户内容备份根目录(paths: 路径配置) -> Path:
    """获取用户内容备份根目录。"""

    sibling_root = paths.repo_root.parent / "autodo-lib"
    return (sibling_root / "datastore").resolve()


def 构造备份快照目录(*, backup_root: Path, prefix: str = "aob-user-content-backup") -> Path:
    """构造不冲突的备份快照目录。"""

    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    base = backup_root / f"{prefix}-{stamp}"
    candidate = base
    index = 2
    while candidate.exists():
        candidate = backup_root / f"{prefix}-{stamp}-{index}"
        index += 1
    return candidate


def 统计文件数量(path: Path) -> int:
    """统计路径内文件数量。"""

    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for item in path.rglob("*") if item.is_file())


def 复制到备份快照(*, source: Path, destination: Path) -> None:
    """复制来源到备份快照。"""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copy2(source, destination)
        return
    shutil.copytree(source, destination)


def 复制到沙盒镜像(*, source: Path, destination: Path) -> None:
    """把来源复制到沙盒镜像路径，允许目标目录已存在（合并复制）。

    与 `复制到备份快照` 不同，本函数在目标已存在时进行合并复制，
    以支持多个共享同一镜像树的目标（如同一项目根下的多个 carrier 根）。

    Args:
        source: 来源文件或目录。
        destination: 沙盒镜像目标路径。
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copy2(source, destination)
        return
    shutil.copytree(source, destination, dirs_exist_ok=True)


def 备份用户级内容(
    paths: 路径配置,
    *,
    target_paths: list[str],
    home_dir: str,
    engine_vendors: list[str],
    ide_vendors: list[str],
    include_missing: bool,
    backup_dir: str,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool,
    resolved_targets_override: list[发布目标] | None = None,
) -> dict[str, Any]:
    """备份 libs 与用户级目标 AI 内容。"""

    if resolved_targets_override is not None:
        targets = list(resolved_targets_override)
    else:
        targets = 解析发布目标(
            target_paths,
            paths=paths,
            home_dir=home_dir,
            engine_vendors=engine_vendors,
            ide_vendors=ide_vendors,
            scopes=scopes,
            project_dirs=project_dirs,
            include_missing=include_missing,
        )

    backup_root = (
        Path(str(backup_dir).strip()).expanduser().resolve()
        if str(backup_dir).strip()
        else 默认用户内容备份根目录(paths)
    )
    snapshot_dir = 构造备份快照目录(backup_root=backup_root)

    summary: dict[str, Any] = {
        "enabled": True,
        "status": "ok",
        "dry_run": dry_run,
        "backup_root": str(backup_root),
        "snapshot_dir": str(snapshot_dir),
        "target_count": len(targets),
        "sources": [],
        "skipped_missing": 0,
        "errors": [],
        "warnings": [],
        "touched_paths": [],
        "file_count": 0,
    }

    source_specs: list[tuple[str, Path, Path, str, str]] = []
    source_specs.append(("libs", paths.libs_root, snapshot_dir / "libs", "libs", "global"))
    for target in targets:
        backup_source_path = target.target_path.parent if target.scope == "project" else target.target_path
        source_specs.append(
            (
                f"target:{target.target_label}",
                backup_source_path,
                snapshot_dir / "targets" / f"{target.target_label}__{target.layout}",
                target.layout,
                target.scope,
            )
        )

    manifest_sources: list[dict[str, Any]] = []
    for source_id, source_path, destination_path, layout, scope in source_specs:
        if not source_path.exists():
            summary["skipped_missing"] += 1
            summary["warnings"].append(f"来源不存在，跳过备份：{source_path}")
            manifest_sources.append(
                {
                    "source_id": source_id,
                    "layout": layout,
                    "scope": scope,
                    "source_path": str(source_path),
                    "destination_path": str(destination_path),
                    "status": "missing",
                    "file_count": 0,
                }
            )
            continue

        file_count = 统计文件数量(source_path)
        manifest_sources.append(
            {
                "source_id": source_id,
                "layout": layout,
                "scope": scope,
                "source_path": str(source_path),
                "destination_path": str(destination_path),
                "status": "copied" if not dry_run else "dry_run_preview",
                "file_count": file_count,
            }
        )
        summary["file_count"] += file_count
        summary["touched_paths"].append(str(destination_path))

        if dry_run:
            continue

        try:
            if destination_path.exists():
                if destination_path.is_file():
                    destination_path.unlink()
                else:
                    shutil.rmtree(destination_path)
            复制到备份快照(source=source_path, destination=destination_path)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"备份失败：{source_path} -> {destination_path} ({exc})")

    summary["sources"] = manifest_sources
    if summary["errors"]:
        summary["status"] = "error"

    manifest_payload = {
        "schema": "aob_user_content_backup_manifest_v1",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "backup_root": str(backup_root),
        "snapshot_dir": str(snapshot_dir),
        "dry_run": dry_run,
        "source_count": len(source_specs),
        "file_count": summary["file_count"],
        "sources": manifest_sources,
        "warnings": list(summary["warnings"]),
        "errors": list(summary["errors"]),
    }
    summary["manifest"] = manifest_payload

    if not dry_run:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = snapshot_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["manifest_path"] = str(manifest_path)
        summary["touched_paths"].append(str(manifest_path))
    else:
        summary["manifest_path"] = str(snapshot_dir / "manifest.json")

    return summary


def 收集用户级内容同步侧(
    paths: 路径配置,
    *,
    targets: list[发布目标],
) -> tuple[
    dict[str, dict[str, dict[str, Any]]],
    dict[str, float],
    list[dict[str, Any]],
    list[str],
    list[str],
    str,
]:
    """收集用于同步决策的 libs/target side AOL 与元数据。"""

    side_entries: dict[str, dict[str, dict[str, Any]]] = {"libs": {}}
    side_observe_times: dict[str, float] = {"libs": 0.0}
    source_summaries: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    title_fallback = f"{paths.repo_root.name} canonical AOL"

    canonical_path = 解析AOL规范文件路径(paths)
    side_observe_times["libs"] = 获取路径最近修改时间(canonical_path)
    libs_summary: dict[str, Any] = {
        "side_id": "libs",
        "source": str(canonical_path),
        "source_label": "libs",
        "layout": "canonical_aol",
        "engine_vendor": "aol",
        "ide_vendor": "aol",
        "scope": "global",
        "contract_level": "canonical",
        "contract_note": "libs canonical AOL 是内部语义真源，不依赖外部供应商目录契约。",
        "observe_at_epoch": side_observe_times["libs"],
        "logical_entry_count": 0,
        "status": "missing",
    }
    if canonical_path.exists() and canonical_path.is_file():
        try:
            libs_aol = 读取canonical_AOL(paths)
            libs_payload = AOL对象转payload(libs_aol)
            side_entries["libs"] = AOL扁平化逻辑条目(libs_payload)
            title_fallback = str(libs_payload.get("title") or title_fallback)
            libs_summary["logical_entry_count"] = len(side_entries["libs"])
            libs_summary["status"] = "loaded"
        except Exception as exc:  # noqa: BLE001
            libs_summary["status"] = "error"
            libs_summary["error"] = str(exc)
            errors.append(f"libs canonical 读取失败：{exc}")
    source_summaries.append(libs_summary)

    for target in targets:
        side_id = f"target:{target.target_label}"
        source = 发布目标转聚合来源(target)
        contract_level, contract_note = 解析供应商载体契约级别(
            layout=source.layout,
            engine_vendor=source.engine_vendor,
            ide_vendor=source.ide_vendor,
            scope=source.scope,
        )
        observe_at = 获取路径最近修改时间(source.source_path)
        side_observe_times[side_id] = observe_at
        side_entries.setdefault(side_id, {})
        source_summary: dict[str, Any] = {
            "side_id": side_id,
            "source": str(source.source_path),
            "source_label": source.source_label,
            "target_label": target.target_label,
            "layout": source.layout,
            "engine_vendor": source.engine_vendor,
            "ide_vendor": source.ide_vendor,
            "scope": source.scope,
            "contract_level": contract_level,
            "contract_note": contract_note,
            "observe_at_epoch": observe_at,
            "logical_entry_count": 0,
            "status": "missing",
        }
        if not source.source_path.exists():
            source_summaries.append(source_summary)
            continue

        if not 是否包含可聚合内容(source.source_path, layout=source.layout, scope=source.scope):
            source_summary["status"] = "empty_or_unsupported"
            source_summaries.append(source_summary)
            continue

        aol, part, part_warnings = 来源构建AOL(paths, source=source)
        warnings.extend(part_warnings)
        if part.get("aol_counts"):
            source_summary["aol_counts"] = dict(part.get("aol_counts") or {})

        part_errors = [str(item) for item in list(part.get("errors") or []) if str(item).strip()]
        if part_errors:
            source_summary["status"] = "error"
            source_summary["error"] = "; ".join(part_errors)
            errors.extend([f"{target.target_label} 反编译失败：{item}" for item in part_errors])
            source_summaries.append(source_summary)
            continue

        if aol is None:
            source_summary["status"] = "empty"
            source_summaries.append(source_summary)
            continue

        payload = AOL对象转payload(aol)
        entries = AOL扁平化逻辑条目(payload)
        side_entries[side_id] = entries
        source_summary["logical_entry_count"] = len(entries)
        source_summary["status"] = "loaded"
        source_summaries.append(source_summary)

    return side_entries, side_observe_times, source_summaries, warnings, errors, title_fallback


def 准备用户级内容同步沙盒(
    paths: 路径配置,
    *,
    targets: list[发布目标],
    home_dir: str = "",
    sandbox_dir: str,
) -> tuple[路径配置, list[发布目标], dict[str, Any]]:
    """把当前 libs canonical 与目标目录复制到独立沙盒。"""

    sandbox_root = 解析唯一沙盒根目录(home_dir=home_dir, sandbox_dir=sandbox_dir)
    sandbox_paths = 构建沙盒路径配置(sandbox_root=sandbox_root)
    复制用户级内容沙盒仓库基线(paths, sandbox_paths=sandbox_paths)

    sandbox_targets: list[发布目标] = []
    sandbox_target_summaries: list[dict[str, Any]] = []
    path_mappings: list[dict[str, str]] = []
    for target in targets:
        if target.scope == "project":
            # project 范围：复制整个项目根，并在沙盒里复刻项目根 -> carrier 根的层级。
            container_root = target.target_path.parent
            mirror_rel = 计算沙盒镜像相对路径(real_path=container_root, home_dir=home_dir)
            sandbox_container_root = (sandbox_root / mirror_rel).resolve()
            if container_root.exists():
                复制到沙盒镜像(source=container_root, destination=sandbox_container_root)
            sandbox_target_path = sandbox_container_root / target.target_path.name
        else:
            container_root = target.target_path
            mirror_rel = 计算沙盒镜像相对路径(real_path=target.target_path, home_dir=home_dir)
            sandbox_target_path = (sandbox_root / mirror_rel).resolve()
            if target.target_path.exists():
                复制到沙盒镜像(source=target.target_path, destination=sandbox_target_path)

        sandbox_targets.append(
            发布目标(
                target_path=sandbox_target_path,
                target_label=target.target_label,
                layout=target.layout,
                engine_vendor=target.engine_vendor,
                ide_vendor=target.ide_vendor,
                scope=target.scope,
            )
        )
        sandbox_target_summaries.append(
            {
                "target_label": target.target_label,
                "layout": target.layout,
                "scope": target.scope,
                "original_path": str(target.target_path),
                "container_root": str(container_root),
                "sandbox_path": str(sandbox_target_path),
                "exists_in_source": bool(target.target_path.exists()),
            }
        )
        path_mappings.append(
            {
                "role": "target",
                "label": target.target_label,
                "scope": target.scope,
                "real_path": str(target.target_path),
                "sandbox_path": str(sandbox_target_path),
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

    return sandbox_paths, sandbox_targets, {
        "enabled": True,
        "sandbox_root": str(sandbox_root),
        "layout_mode": "mirror_real_paths",
        "targets": sandbox_target_summaries,
        "path_mappings": path_mappings,
        "path_mapping_file": str(mapping_path),
    }


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


def 更新用户级内容(
    paths: 路径配置,
    *,
    target_paths: list[str],
    home_dir: str,
    engine_vendors: list[str],
    ide_vendors: list[str],
    include_missing: bool,
    scopes: list[str] | None = None,
    project_dirs: list[str] | None = None,
    dry_run: bool,
    sync_items_after: bool,
    backup_before_sync: bool = True,
    backup_dir: str = "",
    simulate_only: bool = False,
    sandbox_dir: str = "",
    enable_undo_journal: bool = True,
    undo_journal_dir: str = "",
    cleanup_unknown: bool = False,
    resolved_targets_override: list[发布目标] | None = None,
) -> dict[str, Any]:
    """执行用户级内容同步（基于 logical key + SQLite 元数据决策）。

    Args:
        cleanup_unknown: 是否清理目标目录中不在编译输出中的未跟踪文件。
            建议首次同步或沙盒模拟时启用。
    """

    if not AOL运行时可用():
        raise ValueError("aoc runtime 不可用，无法执行 update-user-content")

    if resolved_targets_override is not None:
        resolved_targets = list(resolved_targets_override)
    else:
        resolved_targets = 解析发布目标(
            target_paths,
            paths=paths,
            home_dir=home_dir,
            engine_vendors=engine_vendors,
            ide_vendors=ide_vendors,
            scopes=scopes,
            project_dirs=project_dirs,
            include_missing=include_missing,
        )

    if simulate_only:
        sandbox_paths, sandbox_targets, sandbox_summary = 准备用户级内容同步沙盒(
            paths,
            targets=resolved_targets,
            home_dir=home_dir,
            sandbox_dir=sandbox_dir,
        )
        sandbox_journal_dir = str(sandbox_paths.repo_root / "datastore" / "sync_undo")
        sandbox_result = 更新用户级内容(
            sandbox_paths,
            target_paths=[],
            home_dir="",
            engine_vendors=[],
            ide_vendors=[],
            include_missing=True,
            scopes=scopes,
            project_dirs=project_dirs,
            dry_run=dry_run,
            sync_items_after=sync_items_after,
            backup_before_sync=False,
            backup_dir="",
            simulate_only=False,
            sandbox_dir="",
            enable_undo_journal=enable_undo_journal,
            undo_journal_dir=sandbox_journal_dir,
            cleanup_unknown=True,
            resolved_targets_override=sandbox_targets,
        )
        sandbox_result["sandbox"] = sandbox_summary
        sandbox_result["simulate_only"] = True
        sandbox_result["source_repo_root"] = str(paths.repo_root)
        return sandbox_result

    summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "source_count": 0,
        "target_count": 0,
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "targets": [],
        "errors": [],
        "touched_paths": [],
        "update_warnings": [],
        "aggregate_warnings": [],
        "publish_warnings": [],
        "sync_mode": "logical_key_registry_compare_then_publish",
        "decision_summary": {"added": 0, "updated": 0, "deleted": 0},
        "registry_summary": {"registry_hit_count": 0, "fallback_count": 0, "active_side_count": 0, "logical_key_count": 0},
        "sync_registry": {"enabled": False, "dry_run": dry_run},
        "undo_journal": {"enabled": False, "dry_run": dry_run},
        "sandbox": {"enabled": False},
        "simulate_only": False,
    }

    if backup_before_sync:
        backup_summary = 备份用户级内容(
            paths,
            target_paths=[str(item.target_path) for item in resolved_targets],
            home_dir=home_dir,
            engine_vendors=engine_vendors,
            ide_vendors=ide_vendors,
            include_missing=include_missing,
            backup_dir=backup_dir,
            scopes=scopes,
            project_dirs=project_dirs,
            dry_run=dry_run,
            resolved_targets_override=resolved_targets,
        )
        summary["backup"] = backup_summary
        summary["update_warnings"].extend(list(backup_summary.get("warnings") or []))
        summary["errors"].extend(list(backup_summary.get("errors") or []))
        summary["touched_paths"].extend(list(backup_summary.get("touched_paths") or []))
        if backup_summary.get("status") != "ok":
            raise ValueError(f"备份失败，已停止同步：{backup_summary}")
    else:
        summary["backup"] = {
            "enabled": False,
            "status": "skipped",
            "reason": "显式关闭备份",
            "dry_run": dry_run,
            "warnings": [],
            "errors": [],
            "touched_paths": [],
        }

    previous_registry, previous_target_files = 读取用户内容同步数据库基线(paths)
    side_entries, side_observe_times, source_summaries, aggregate_warnings, sync_errors, title_fallback = 收集用户级内容同步侧(
        paths,
        targets=resolved_targets,
    )
    # 去污染：过滤 canonical AOL 中旧同步 bug 产生的 vendor 后缀条目
    side_entries, decontam_stats = 过滤旧同步污染条目(side_entries)
    if decontam_stats.get("removed", 0) > 0:
        per_side = decontam_stats.get("per_side", {})
        side_detail = ", ".join(f"{k}={v}" for k, v in sorted(per_side.items()))
        aggregate_warnings.append(
            f"已过滤 {decontam_stats['removed']} 个旧同步 vendor 后缀污染条目（{side_detail}）"
        )
    side_priority = ["libs", *[f"target:{item.target_label}" for item in resolved_targets]]
    final_entries, registry_rows, registry_summary = 计算一键更新决策(
        side_entries=side_entries,
        side_observe_times=side_observe_times,
        previous_registry=previous_registry,
        side_priority=side_priority,
    )
    decision_summary = 计算canonical变更摘要(
        libs_entries=side_entries.get("libs", {}),
        final_entries=final_entries,
    )
    final_payload = 逻辑条目转AOL_payload(final_entries, title_fallback=title_fallback)
    merged_aol = payload转AOL对象(final_payload)
    canonical_write = {
        "path": str(解析AOL规范文件路径(paths)),
        "status": "blocked",
        "written": False,
        "dry_run": dry_run,
    }
    if not sync_errors:
        canonical_write = 写入canonical_AOL(paths, aol=merged_aol, dry_run=dry_run)

    aggregate_summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "source_count": len(source_summaries),
        "added": int(decision_summary.get("added") or 0),
        "updated": int(decision_summary.get("updated") or 0),
        "deleted": int(decision_summary.get("deleted") or 0),
        "sources": source_summaries,
        "errors": list(sync_errors),
        "touched_paths": [str(canonical_write.get("path") or "")] if canonical_write.get("path") else [],
        "aggregate_warnings": list(aggregate_warnings),
        "canonical_aol": canonical_write,
        "decision_summary": decision_summary,
        "registry_summary": registry_summary,
    }

    if sync_items_after and not dry_run and sum(int(value) for value in decision_summary.values()) > 0 and not sync_errors:
        aggregate_summary["items_sync"] = 同步_items(paths, dry_run=False)
    elif sync_items_after:
        aggregate_summary["items_sync"] = {
            "enabled": False,
            "reason": "dry_run 模式、无 canonical 变更或同步侧异常，跳过 items sync",
            "dry_run": dry_run,
        }
    else:
        aggregate_summary["items_sync"] = {
            "enabled": False,
            "reason": "显式关闭 items sync",
            "dry_run": dry_run,
        }

    if dry_run:
        aggregate_summary["aol_intermediate"] = 构建AOL摘要(
            merged_aol,
            source="in_memory_sync_dry_run",
            canonical_path=Path(str(canonical_write.get("path") or "")) if canonical_write.get("path") else None,
            warnings=list(aggregate_warnings),
        )
    elif sync_errors:
        aggregate_summary["aol_intermediate"] = {
            "enabled": False,
            "status": "blocked",
            "reason": "同步侧存在反编译错误，已阻止 canonical 写入与发布",
            "warnings": list(sync_errors),
        }
    else:
        aggregate_summary["aol_intermediate"] = 构建libs_aol中转摘要(paths)

    summary["aggregate"] = aggregate_summary
    summary["source_count"] = int(aggregate_summary.get("source_count") or 0)
    summary["canonical_aol"] = aggregate_summary.get("canonical_aol")
    summary["items_sync"] = aggregate_summary.get("items_sync")
    summary["aol_intermediate"] = aggregate_summary.get("aol_intermediate")
    summary["aggregate_warnings"] = list(aggregate_summary.get("aggregate_warnings") or [])
    summary["update_warnings"].extend(summary["aggregate_warnings"])
    summary["errors"].extend(list(aggregate_summary.get("errors") or []))
    summary["touched_paths"].extend(list(aggregate_summary.get("touched_paths") or []))
    summary["decision_summary"] = dict(decision_summary)
    summary["registry_summary"] = dict(registry_summary)

    publish_summary: dict[str, Any] = {
        "repo_root": str(paths.repo_root),
        "libs_root": str(paths.libs_root),
        "dry_run": dry_run,
        "target_count": len(resolved_targets),
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped_same": 0,
        "skipped_target_newer": 0,
        "targets": [],
        "errors": [],
        "touched_paths": [],
        "aol_intermediate": aggregate_summary.get("aol_intermediate"),
        "publish_warnings": [],
    }

    undo_journal: Any = None
    if enable_undo_journal and not sync_errors and 创建撤销账本 is not None:
        undo_journal = 创建撤销账本(
            repo_root=paths.repo_root,
            journal_root=Path(str(undo_journal_dir).strip()).expanduser() if str(undo_journal_dir).strip() else None,
            dry_run=dry_run,
            summary_meta={
                "repo_root": str(paths.repo_root),
                "target_labels": [item.target_label for item in resolved_targets],
                "decision_summary": dict(decision_summary),
            },
        )

    managed_target_files: dict[tuple[str, str], set[str]] = {}
    if sync_errors:
        publish_summary["errors"].append("同步侧存在反编译错误，已跳过正式发布")
    else:
        publish_aol = merged_aol if dry_run else 读取canonical_AOL(paths)
        for target in resolved_targets:
            part, managed_files = 发布到单个目标并同步删除(
                aol=publish_aol,
                target=target,
                dry_run=dry_run,
                warnings=publish_summary["publish_warnings"],
                previous_managed_files=previous_target_files.get((target.target_label, target.layout), set()),
                journal=undo_journal,
                cleanup_unknown=cleanup_unknown,
            )
            managed_target_files[(target.target_label, target.layout)] = managed_files
            合并发布统计(publish_summary, part)

    if undo_journal is not None:
        summary["undo_journal"] = undo_journal.结果摘要()
    else:
        summary["undo_journal"] = {
            "enabled": False,
            "reason": "显式关闭撤销账本或同步侧存在错误",
            "dry_run": dry_run,
        }

    summary["sync_registry"] = 写入用户内容同步数据库(
        paths,
        registry_rows=registry_rows,
        target_files=managed_target_files,
        dry_run=dry_run,
    )

    summary["publish"] = publish_summary
    summary["target_count"] = publish_summary["target_count"]
    summary["targets"] = list(publish_summary["targets"])
    summary["added"] = publish_summary["added"]
    summary["updated"] = publish_summary["updated"]
    summary["deleted"] = publish_summary["deleted"]
    summary["skipped_same"] = publish_summary["skipped_same"]
    summary["skipped_target_newer"] = publish_summary["skipped_target_newer"]
    summary["publish_warnings"] = list(publish_summary["publish_warnings"])
    summary["errors"].extend(list(publish_summary.get("errors") or []))
    summary["touched_paths"].extend(list(publish_summary.get("touched_paths") or []))

    return summary


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


def 执行发布用户级内容(argv: list[str], paths: 路径配置) -> int:
    """执行用户级内容发布子命令。"""

    parser = argparse.ArgumentParser(description="按范围把 libs 中的 AI 内容发布到当前设备、项目或显式目标")
    parser.add_argument("--target-path", action="append", default=[], help="可选：显式指定发布目标路径，可重复传入")
    parser.add_argument("--scope", action="append", default=[], help="可选：自动发现范围，可重复传入 global/system/user/project")
    parser.add_argument("--project-dir", action="append", default=[], help="可选：项目级自动发现根目录，可重复传入")
    parser.add_argument("--home-dir", default="", help="可选：覆盖自动发现使用的用户主目录")
    parser.add_argument("--engine", action="append", default=[], help="可选：按 engine_vendor 过滤自动发现目标，可重复传入")
    parser.add_argument("--ide", action="append", default=[], help="可选：按 ide_vendor 过滤自动发现目标，可重复传入")
    parser.add_argument("--include-missing", action="store_true", help="自动发现时包含当前尚不存在的候选目标目录")
    parser.add_argument("--dry-run", action="store_true", help="仅输出变更预览，不写入磁盘")
    parser.add_argument("--simulate-only", action="store_true", help="仅在沙盒副本中执行发布，不修改真实目录")
    parser.add_argument("--sandbox-dir", default="", help="可选：沙盒根目录；不传则默认使用 Downloads 下的时间戳目录")
    args = parser.parse_args(argv)

    stats = 发布用户级内容(
        paths,
        target_paths=[str(item).strip() for item in list(args.target_path or []) if str(item).strip()],
        home_dir=str(args.home_dir or "").strip(),
        engine_vendors=[str(item).strip() for item in list(args.engine or []) if str(item).strip()],
        ide_vendors=[str(item).strip() for item in list(args.ide or []) if str(item).strip()],
        include_missing=bool(args.include_missing),
        scopes=[str(item).strip() for item in list(args.scope or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(args.project_dir or []) if str(item).strip()],
        dry_run=bool(args.dry_run),
        simulate_only=bool(args.simulate_only),
        sandbox_dir=str(args.sandbox_dir or "").strip(),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def 执行备份用户级内容(argv: list[str], paths: 路径配置) -> int:
    """执行用户级内容备份子命令。"""

    parser = argparse.ArgumentParser(description="按范围备份当前设备或项目的 AI 内容（libs + 参与目标）")
    parser.add_argument("--target-path", action="append", default=[], help="可选：显式指定备份目标路径，可重复传入")
    parser.add_argument("--scope", action="append", default=[], help="可选：自动发现范围，可重复传入 global/system/user/project")
    parser.add_argument("--project-dir", action="append", default=[], help="可选：项目级自动发现根目录，可重复传入")
    parser.add_argument("--home-dir", default="", help="可选：覆盖自动发现使用的用户主目录")
    parser.add_argument("--engine", action="append", default=[], help="可选：按 engine_vendor 过滤自动发现目标，可重复传入")
    parser.add_argument("--ide", action="append", default=[], help="可选：按 ide_vendor 过滤自动发现目标，可重复传入")
    parser.add_argument("--include-missing", action="store_true", help="自动发现时包含当前尚不存在的候选目标目录")
    parser.add_argument("--backup-dir", default="", help="可选：备份根目录，默认使用 autodo-lib/datastore")
    parser.add_argument("--dry-run", action="store_true", help="仅输出备份计划，不写入磁盘")
    args = parser.parse_args(argv)

    stats = 备份用户级内容(
        paths,
        target_paths=[str(item).strip() for item in list(args.target_path or []) if str(item).strip()],
        home_dir=str(args.home_dir or "").strip(),
        engine_vendors=[str(item).strip() for item in list(args.engine or []) if str(item).strip()],
        ide_vendors=[str(item).strip() for item in list(args.ide or []) if str(item).strip()],
        include_missing=bool(args.include_missing),
        backup_dir=str(args.backup_dir or "").strip(),
        scopes=[str(item).strip() for item in list(args.scope or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(args.project_dir or []) if str(item).strip()],
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def 执行更新用户级内容(argv: list[str], paths: 路径配置) -> int:
    """执行用户级内容一键更新子命令。"""

    parser = argparse.ArgumentParser(description="按范围与 logical key + SQLite 元数据基线同步当前设备或项目的 AI 内容")
    parser.add_argument("--target-path", action="append", default=[], help="可选：显式指定同步参与目标路径，可重复传入")
    parser.add_argument("--scope", action="append", default=[], help="可选：自动发现范围，可重复传入 global/system/user/project")
    parser.add_argument("--project-dir", action="append", default=[], help="可选：项目级自动发现根目录，可重复传入")
    parser.add_argument("--home-dir", default="", help="可选：覆盖自动发现使用的用户主目录")
    parser.add_argument("--engine", action="append", default=[], help="可选：按 engine_vendor 过滤自动发现的同步参与方，可重复传入")
    parser.add_argument("--ide", action="append", default=[], help="可选：按 ide_vendor 过滤自动发现的同步参与方，可重复传入")
    parser.add_argument("--include-missing", action="store_true", help="自动发现时包含当前尚不存在的候选目标目录")
    parser.add_argument("--backup-dir", default="", help="可选：备份根目录，默认使用 autodo-lib/datastore")
    parser.add_argument("--dry-run", action="store_true", help="仅输出变更预览，不写入磁盘")
    parser.add_argument("--skip-backup", action="store_true", help="更新开始前跳过自动备份")
    parser.add_argument("--skip-items-sync", action="store_true", help="更新完成后跳过 items sync")
    parser.add_argument("--simulate-only", action="store_true", help="仅在沙盒副本中执行同步，不修改真实目录")
    parser.add_argument("--sandbox-dir", default="", help="可选：沙盒根目录；不传则默认使用 Downloads 下的时间戳目录")
    parser.add_argument("--skip-undo-journal", action="store_true", help="本次同步不记录可撤销的增删改账本")
    parser.add_argument("--undo-journal-dir", default="", help="可选：撤销账本根目录；不传则默认使用 autodo-lib/datastore/sync_undo")
    args = parser.parse_args(argv)

    stats = 更新用户级内容(
        paths,
        target_paths=[str(item).strip() for item in list(args.target_path or []) if str(item).strip()],
        home_dir=str(args.home_dir or "").strip(),
        engine_vendors=[str(item).strip() for item in list(args.engine or []) if str(item).strip()],
        ide_vendors=[str(item).strip() for item in list(args.ide or []) if str(item).strip()],
        include_missing=bool(args.include_missing),
        scopes=[str(item).strip() for item in list(args.scope or []) if str(item).strip()],
        project_dirs=[str(item).strip() for item in list(args.project_dir or []) if str(item).strip()],
        dry_run=bool(args.dry_run),
        sync_items_after=not bool(args.skip_items_sync),
        backup_before_sync=not bool(args.skip_backup),
        backup_dir=str(args.backup_dir or "").strip(),
        simulate_only=bool(args.simulate_only),
        sandbox_dir=str(args.sandbox_dir or "").strip(),
        enable_undo_journal=not bool(args.skip_undo_journal),
        undo_journal_dir=str(args.undo_journal_dir or "").strip(),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def _执行生成中文索引(argv: list[str], paths: 路径配置) -> int:
    """执行 generate-zh-index 子命令。"""
    parser = argparse.ArgumentParser(description="扫描技能/智能体的 metadata.display_zh 并生成中文索引")
    parser.add_argument("--source-root", action="append", default=[], help="源根目录（可重复）")
    parser.add_argument("--output-dir", default="", help="输出目录，默认 autodo-lib/datastore")
    parser.add_argument("--dry-run", action="store_true", help="仅显示统计，不写文件")
    args = parser.parse_args(argv)

    if 生成中文索引 is None:
        print("[ERROR] aob_zh_index 模块不可用", file=sys.stderr)
        return 2

    from pathlib import Path
    source_roots = [Path(p) for p in args.source_root] if args.source_root else None
    output_dir = Path(args.output_dir) if args.output_dir else (_默认zh输出目录 or Path("."))
    result = 生成中文索引(source_roots=source_roots, output_dir=output_dir, dry_run=bool(args.dry_run))
    print(f"索引{'预览' if args.dry_run else '已生成'}:")
    print(f"  技能: {result['skills_count']}, 智能体: {result['agents_count']}, 合计: {result['total']}")
    if not args.dry_run:
        print(f"  YAML: {result.get('output_yaml', 'N/A')}")
        print(f"  MD:   {result.get('output_md', 'N/A')}")
    return 0


def _执行查询中文索引(argv: list[str], paths: 路径配置) -> int:
    """执行 query-zh-index 子命令。"""
    parser = argparse.ArgumentParser(description="按中文关键词或分类查询技能/智能体索引")
    parser.add_argument("--source-root", action="append", default=[], help="源根目录（可重复）")
    parser.add_argument("--keyword", default="", help="关键词搜索")
    parser.add_argument("--category", default="", help="按分类筛选")
    parser.add_argument("--all", action="store_true", help="列出全部条目")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    args = parser.parse_args(argv)

    if 查询中文索引 is None:
        print("[ERROR] aob_zh_index 模块不可用", file=sys.stderr)
        return 2

    from pathlib import Path
    source_roots = [Path(p) for p in args.source_root] if args.source_root else None
    results = 查询中文索引(
        source_roots=source_roots,
        keyword=args.keyword,
        category=args.category,
        list_all=bool(args.all),
    )
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"\n查询结果: {len(results)} 条")
        for r in results:
            display = r.get("display_zh", "") or r["name"]
            typ = "技能" if r["type"] == "skill" else "智能体"
            aliases = ", ".join(r.get("aliases_zh", [])[:3])
            cat = f" [{r.get('category_zh', '')}]" if r.get("category_zh") else ""
            print(f"  {display}{cat}  ({typ})  `{r['name']}`")
            if aliases:
                print(f"    触发词: {aliases}")
    return 0


def 构建解析器() -> argparse.ArgumentParser:
    """构建顶层解析器。

    Returns:
        argparse.ArgumentParser: 顶层解析器。
    """

    parser = argparse.ArgumentParser(description="本地库管理统一入口")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("items", help="条目清单同步与 CRUD")
    sub.add_parser("tags", help="标签与关系表管理")
    sub.add_parser("aggregate-user-content", help="按范围聚合当前设备或项目 AI 内容到 libs")
    sub.add_parser("publish-user-content", help="按范围把 libs 中的 AI 内容发布到当前设备、项目或显式目标")
    sub.add_parser("backup-user-content", help="按范围备份当前设备或项目 AI 内容（libs + 参与目标）")
    sub.add_parser("update-user-content", help="按范围执行 参与方反编译 -> logical key 决策 -> canonical 回写 -> 定向发布 的同步")
    sub.add_parser("generate-zh-index", help="扫描技能/智能体的 metadata.display_zh 并生成中文索引（yaml + md）")
    sub.add_parser("query-zh-index", help="按中文关键词或分类查询技能/智能体索引")
    sub.add_parser("flow-backup-aggregate", help="【流程】备份 → 聚合")
    sub.add_parser("flow-backup-publish", help="【流程】备份 → 发布")
    sub.add_parser("flow-backup-update", help="【流程】备份 → 同步")
    sub.add_parser("flow-aggregate-publish", help="【流程】聚合 → 发布")
    sub.add_parser("flow-full-sync", help="【流程】备份 → 聚合 → 发布 → 中文索引（一键全流程）")
    return parser


def main() -> int:
    """程序主入口。

    Returns:
        int: 退出码。
    """

    paths = 默认路径()
    parser = 构建解析器()
    args, passthrough = parser.parse_known_args()

    try:
        if args.command == "items":
            return 执行_items(list(passthrough), paths)
        if args.command == "tags":
            return 执行_tags(list(passthrough), paths)
        if args.command == "aggregate-user-content":
            return 执行聚合用户级内容(list(passthrough), paths)
        if args.command == "publish-user-content":
            return 执行发布用户级内容(list(passthrough), paths)
        if args.command == "backup-user-content":
            return 执行备份用户级内容(list(passthrough), paths)
        if args.command == "update-user-content":
            return 执行更新用户级内容(list(passthrough), paths)
        if args.command == "generate-zh-index":
            return _执行生成中文索引(list(passthrough), paths)
        if args.command == "query-zh-index":
            return _执行查询中文索引(list(passthrough), paths)
        if args.command == "flow-backup-aggregate":
            from .aob_flow_pipeline import _execute_flow_backup_aggregate
            return _execute_flow_backup_aggregate(list(passthrough), paths)
        if args.command == "flow-backup-publish":
            from .aob_flow_pipeline import _execute_flow_backup_publish
            return _execute_flow_backup_publish(list(passthrough), paths)
        if args.command == "flow-backup-update":
            from .aob_flow_pipeline import _execute_flow_backup_update
            return _execute_flow_backup_update(list(passthrough), paths)
        if args.command == "flow-aggregate-publish":
            from .aob_flow_pipeline import _execute_flow_aggregate_publish
            return _execute_flow_aggregate_publish(list(passthrough), paths)
        if args.command == "flow-full-sync":
            from .aob_flow_pipeline import _execute_flow_full_sync
            return _execute_flow_full_sync(list(passthrough), paths)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
