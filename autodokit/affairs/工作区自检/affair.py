"""工作区自检事务。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List

from autodokit.tools import load_json_or_py


ROOT_BROWSER_LEAK_ITEMS = [
    "Ad Blocking",
    "Crashpad",
    "Default",
    "GraphiteDawnCache",
    "GrShaderCache",
    "Nurturing",
    "ShaderCache",
    "SmartScreen",
    "Safe Browsing",
    "component_crx_cache",
    "extensions_crx_cache",
    "Local State",
    "Last Browser",
    "Last Version",
    "FirstLaunchAfterInstallation",
    "first_party_sets.db-journal",
    "Variations",
]

TARGET_PROFILE_RELATIVE = Path("sandbox") / "runtime" / "web_brower_profiles" / "cnki_main"
DEFAULT_REPORT_RELATIVE = Path(".opencode") / "logs" / "workspace_sanity"


@dataclass(slots=True)
class SanityIssue:
    """自检问题项。

    Args:
        level: 问题等级。
        category: 问题分类。
        path: 路径。
        message: 说明信息。
    """

    level: str
    category: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """转换为字典。

        Returns:
            可序列化的问题字典。
        """

        return {
            "level": self.level,
            "category": self.category,
            "path": self.path,
            "message": self.message,
        }


class WorkspaceSanityCheckEngine:
    """工作区自检引擎。"""

    def run(
        self,
        project_root: str | Path = ".",
        mode: str = "full",
        auto_migrate: bool = False,
        write_report: bool = True,
        report_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """执行工作区自检。

        Args:
            project_root: 项目根目录。
            mode: 自检模式，仅支持 `full` 或 `fast`。
            auto_migrate: 是否自动迁移根目录浏览器数据。
            write_report: 是否落盘报告。
            report_dir: 报告目录；为空时写入默认目录。

        Returns:
            自检结果摘要。

        Raises:
            ValueError: 当 `mode` 非法时抛出。
        """

        if mode not in {"full", "fast"}:
            raise ValueError("mode 仅支持 full 或 fast。")

        root = Path(project_root).resolve()
        target_profile_dir = (root / TARGET_PROFILE_RELATIVE).resolve()
        issues: list[SanityIssue] = []

        leak_paths = _collect_root_browser_leaks(root)
        migrated_paths: list[dict[str, str]] = []

        if leak_paths:
            for leak in leak_paths:
                issues.append(
                    SanityIssue(
                        level="high",
                        category="root_browser_leak",
                        path=str(leak),
                        message="检测到浏览器数据落在项目根目录。",
                    )
                )

        if auto_migrate and leak_paths:
            target_profile_dir.mkdir(parents=True, exist_ok=True)
            for source in leak_paths:
                moved_to = _move_to_target(source, target_profile_dir)
                migrated_paths.append({"from": str(source), "to": str(moved_to)})

        detailed_inventory = mode == "full"
        inventory = _collect_governance_inventory(root, detailed=detailed_inventory)
        if detailed_inventory:
            issues.extend(_collect_inventory_issues(inventory))

        if mode == "full":
            issues.extend(_collect_gitignore_issues(root))

        result = {
            "status": "PASS" if not issues else "BLOCKED",
            "mode": mode,
            "project_root": str(root),
            "target_profile_dir": str(target_profile_dir),
            "auto_migrate": auto_migrate,
            "migrated_paths": migrated_paths,
            "inventory": inventory,
            "issues": [item.to_dict() for item in issues],
            "summary": {
                "issue_count": len(issues),
                "high_count": sum(1 for item in issues if item.level == "high"),
                "medium_count": sum(1 for item in issues if item.level == "medium"),
                "low_count": sum(1 for item in issues if item.level == "low"),
            },
        }

        if write_report:
            out_dir = (root / (Path(report_dir) if report_dir else DEFAULT_REPORT_RELATIVE)).resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            _write_report(out_dir, result)

        return result


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。

    Args:
        config_path: 事务配置路径。

    Returns:
        输出文件路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    result = WorkspaceSanityCheckEngine().run(
        project_root=str(raw_cfg.get("project_root") or "."),
        mode=str(raw_cfg.get("mode") or "full"),
        auto_migrate=bool(raw_cfg.get("auto_migrate") or False),
        write_report=bool(raw_cfg.get("write_report") if "write_report" in raw_cfg else True),
        report_dir=raw_cfg.get("report_dir"),
    )

    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认已在 tools 层完成统一路径预处理，"
            f"当前值={str(raw_cfg.get('output_dir') or '')!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / "workspace_sanity_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]


def _collect_root_browser_leaks(root: Path) -> list[Path]:
    """收集根目录浏览器数据泄漏路径。

    Args:
        root: 项目根目录。

    Returns:
        泄漏路径列表。
    """

    leaks: list[Path] = []
    for name in ROOT_BROWSER_LEAK_ITEMS:
        candidate = root / name
        if candidate.exists():
            leaks.append(candidate)
    return leaks


def _move_to_target(source: Path, target_dir: Path) -> Path:
    """迁移单个路径到目标目录。

    Args:
        source: 原路径。
        target_dir: 目标目录。

    Returns:
        迁移后的目标路径。
    """

    destination = target_dir / source.name
    if not destination.exists():
        shutil.move(str(source), str(destination))
        return destination

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = target_dir / f"{source.name}.migrated-{timestamp}"
    shutil.move(str(source), str(destination))
    return destination


def _collect_governance_inventory(root: Path, detailed: bool = True) -> dict[str, Any]:
    """收集事务、智能体、技能清单。

    Args:
        root: 项目根目录。
        detailed: 是否收集详细技能清单。

    Returns:
        清单摘要。
    """

    opencode_root = root / ".opencode"
    agents = sorted((opencode_root / "agents").glob("*.md"))
    workflows = sorted((opencode_root / "workflows").glob("*.md"))
    commands = sorted((opencode_root / "commands").glob("*.md"))
    skill_root = opencode_root / "skills"
    skill_dirs = sorted([item for item in skill_root.iterdir() if item.is_dir()]) if skill_root.exists() else []

    skill_details: list[dict[str, Any]] = []
    if detailed:
        for skill_dir in skill_dirs:
            skill_md = skill_dir / "SKILL.md"
            script_files = sorted(skill_dir.glob("scripts/*.py"))
            skill_details.append(
                {
                    "name": skill_dir.name,
                    "path": str(skill_dir),
                    "has_skill_md": skill_md.exists(),
                    "script_count": len(script_files),
                    "scripts": [str(path) for path in script_files],
                }
            )

    return {
        "transactions": {
            "workflow_count": len(workflows),
            "workflows": [path.name for path in workflows],
            "command_count": len(commands),
            "commands": [path.name for path in commands],
        },
        "agents": {
            "count": len(agents),
            "items": [path.name for path in agents],
        },
        "skills": {
            "count": len(skill_dirs),
            "items": skill_details,
            "sample": [] if detailed else [item.name for item in skill_dirs[:10]],
        },
    }


def _collect_inventory_issues(inventory: dict[str, Any]) -> list[SanityIssue]:
    """根据清单收集结构问题。

    Args:
        inventory: 清单摘要。

    Returns:
        问题列表。
    """

    issues: list[SanityIssue] = []
    skill_items = inventory.get("skills", {}).get("items", [])
    for item in skill_items:
        name = str(item.get("name") or "")
        path = str(item.get("path") or "")
        if not bool(item.get("has_skill_md")):
            issues.append(
                SanityIssue(
                    level="medium",
                    category="skill_contract_missing",
                    path=path,
                    message=f"技能 {name} 缺少 SKILL.md 契约文档。",
                )
            )
    return issues


def _collect_gitignore_issues(root: Path) -> list[SanityIssue]:
    """检查 .gitignore 是否覆盖浏览器数据路径。

    Args:
        root: 项目根目录。

    Returns:
        问题列表。
    """

    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return [
            SanityIssue(
                level="medium",
                category="gitignore_missing",
                path=str(gitignore),
                message="未找到 .gitignore 文件。",
            )
        ]

    content = gitignore.read_text(encoding="utf-8", errors="ignore")
    expected_rules = [
        "sandbox/runtime/web_brower_profiles/",
        "Default/",
        "Crashpad/",
        "Local State",
    ]
    issues: list[SanityIssue] = []
    for rule in expected_rules:
        if rule not in content:
            issues.append(
                SanityIssue(
                    level="low",
                    category="gitignore_rule_missing",
                    path=str(gitignore),
                    message=f".gitignore 缺少规则：{rule}",
                )
            )
    return issues


def _write_report(out_dir: Path, result: dict[str, Any]) -> None:
    """写入 JSON 与 Markdown 报告。

    Args:
        out_dir: 输出目录。
        result: 自检结果。
    """

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"workspace-sanity-{timestamp}.json"
    md_path = out_dir / f"workspace-sanity-{timestamp}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = result.get("summary", {})
    inventory = result.get("inventory", {})
    lines = [
        f"# workspace-sanity-{timestamp}",
        "",
        f"- 状态：`{result.get('status')}`",
        f"- 模式：`{result.get('mode')}`",
        f"- 项目根：`{result.get('project_root')}`",
        f"- 目标 profile：`{result.get('target_profile_dir')}`",
        f"- 问题总数：`{summary.get('issue_count', 0)}`",
        f"- 高风险：`{summary.get('high_count', 0)}`",
        f"- 中风险：`{summary.get('medium_count', 0)}`",
        f"- 低风险：`{summary.get('low_count', 0)}`",
        "",
        "## 事务覆盖",
        f"- workflow 数：`{inventory.get('transactions', {}).get('workflow_count', 0)}`",
        f"- command 数：`{inventory.get('transactions', {}).get('command_count', 0)}`",
        "",
        "## 智能体覆盖",
        f"- agent 数：`{inventory.get('agents', {}).get('count', 0)}`",
        "",
        "## 技能覆盖",
        f"- skill 数：`{inventory.get('skills', {}).get('count', 0)}`",
        "",
        "## 问题明细",
    ]
    for issue in result.get("issues", []):
        lines.append(
            f"- [{issue.get('level')}] {issue.get('category')} | `{issue.get('path')}` | {issue.get('message')}"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
