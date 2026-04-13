#!/usr/bin/env python3
"""AOC（autodo 编译器）统一入口。

本脚本负责把 AOL（autodo-lang）Markdown DSL 源文件编译为不同引擎可直接落盘的目录与文件。
当前实现为 v0.2：

- 输入：AOL Markdown 文件或 AOL 源码目录。
- 输出：OpenCode / Claude Code / GitHub Copilot 三种引擎目录结构。
- 策略：以 AOL Markdown DSL 作为单一真源。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


技能名称正则 = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

命名颜色映射: dict[str, str] = {
    "yellow": "#EAB308",
    "blue": "#3B82F6",
    "red": "#EF4444",
    "green": "#22C55E",
    "orange": "#F97316",
    "purple": "#A855F7",
    "pink": "#EC4899",
    "gray": "#6B7280",
    "grey": "#6B7280",
    "black": "#111827",
    "white": "#F9FAFB",
}

引擎泄漏正则: list[re.Pattern[str]] = [
    re.compile(r"\.claude/", re.IGNORECASE),
    re.compile(r"\.opencode/", re.IGNORECASE),
    re.compile(r"\.github/", re.IGNORECASE),
    re.compile(r"~/.claude/", re.IGNORECASE),
    re.compile(r"~/.opencode/", re.IGNORECASE),
    re.compile(r"opencode\.json", re.IGNORECASE),
]

引擎语义化替换规则: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"~/.claude/", re.IGNORECASE), "{{ENGINE_HOME_ROOT}}/"),
    (re.compile(r"~/.opencode/", re.IGNORECASE), "{{ENGINE_HOME_ROOT}}/"),
    (re.compile(r"\.claude/", re.IGNORECASE), "{{ENGINE_ROOT}}/"),
    (re.compile(r"\.opencode/", re.IGNORECASE), "{{ENGINE_ROOT}}/"),
    (re.compile(r"\.github/", re.IGNORECASE), "{{ENGINE_ROOT}}/"),
    (re.compile(r"\bopencode\.json\b", re.IGNORECASE), "{{ENGINE_PROJECT_CONFIG}}"),
    (re.compile(r"\bAGENTS\.md\b", re.IGNORECASE), "{{ENGINE_PROJECT_RULES}}"),
]

目录映射配置相对路径 = Path("database") / "aol_directory_mapping.json"
默认技能布局模式 = "strict"
默认允许兼容非严格技能 = True
默认严格技能必需目录 = ["scripts", "references"]

默认目录映射配置: dict[str, Any] = {
    "agent_dirs": ["agents"],
    "skill_dirs": ["skills"],
    "rule_dirs": [
        "rules",
        "context",
        "docs",
        "prompts",
        "templates",
        "workflow_docs",
        "instructions",
        "hooks",
    ],
    "skill_layout_mode": 默认技能布局模式,
    "allow_legacy_skill_layout": 默认允许兼容非严格技能,
    "strict_skill_required_dirs": list(默认严格技能必需目录),
}

引擎办公区目录映射: dict[str, str] = {
    "opencode": ".opencode",
    "claude": ".claude",
    "copilot": ".github",
}

可迁移附加载体目录: list[str] = [
    "prompts",
    "workflows",
    "templates",
    "hooks",
    "context",
    "docs",
    "instructions",
    "governance",
    "modes",
    "plugins",
    "tools",
    "themes",
    "plans",
]

可迁移附加载体后缀: set[str] = {
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".py",
    ".sh",
    ".ps1",
    ".bat",
    ".cmd",
    ".js",
    ".ts",
    ".rb",
}


def 解析_aob仓库根目录(传入路径: str) -> Path:
    """解析 AOB 仓库根目录。

    解析优先级：
    1. 参数 `--repo-root`
    2. 环境变量 `AOB_REPO_ROOT`
    3. 与 `autodo-kit` 同级的 `autodo-lib`
    4. 当前 `autodo-kit` 仓库（兜底）

    Args:
        传入路径: 命令行显式传入的仓库根目录。

    Returns:
        Path: 解析后的仓库根目录。
    """

    if str(传入路径).strip():
        return Path(传入路径).expanduser().resolve()

    env_root = str(os.environ.get("AOB_REPO_ROOT", "")).strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    kit_root = Path(__file__).resolve().parents[4]
    sibling_aob = kit_root.parent / "autodo-lib"
    if sibling_aob.exists():
        return sibling_aob.resolve()

    return kit_root.resolve()


def 解析仓库内路径(raw_path: str, *, repo_root: Path) -> Path:
    """按 AOB 仓库根目录解析路径。

    Args:
        raw_path: 原始路径文本。
        repo_root: AOB 仓库根目录。

    Returns:
        Path: 绝对路径。
    """

    path_obj = Path(raw_path).expanduser()
    if path_obj.is_absolute():
        return path_obj.resolve()
    return (repo_root / path_obj).resolve()


def 读取目录映射配置(*, libs_root: Path) -> dict[str, Any]:
    """读取 AOL 目录映射配置。

    Args:
        libs_root: `libs` 根目录。

    Returns:
        dict[str, Any]: 目录映射配置。
    """

    default_config: dict[str, Any] = {}
    for key, value in 默认目录映射配置.items():
        if isinstance(value, list):
            default_config[key] = list(value)
        else:
            default_config[key] = value
    repo_root = libs_root.parent if libs_root.name == "libs" else libs_root
    config_path = repo_root / 目录映射配置相对路径
    if not config_path.exists():
        return default_config

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return default_config

    if not isinstance(payload, dict):
        return default_config

    config: dict[str, Any] = {}
    for key, value in default_config.items():
        if isinstance(value, list):
            config[key] = list(value)
        else:
            config[key] = value

    for key in ["agent_dirs", "skill_dirs", "rule_dirs"]:
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip().strip("/").strip("\\")
            if not text or text in seen:
                continue
            cleaned.append(text)
            seen.add(text)
        if cleaned:
            config[key] = cleaned

    skill_layout_mode = str(payload.get("skill_layout_mode", config.get("skill_layout_mode", 默认技能布局模式))).strip().lower()
    if skill_layout_mode not in {"strict", "compat"}:
        skill_layout_mode = 默认技能布局模式
    config["skill_layout_mode"] = skill_layout_mode

    allow_legacy = payload.get("allow_legacy_skill_layout", config.get("allow_legacy_skill_layout", 默认允许兼容非严格技能))
    config["allow_legacy_skill_layout"] = bool(allow_legacy) if isinstance(allow_legacy, bool) else 默认允许兼容非严格技能

    strict_required_dirs_raw = payload.get("strict_skill_required_dirs", config.get("strict_skill_required_dirs", 默认严格技能必需目录))
    strict_required_dirs: list[str] = []
    if isinstance(strict_required_dirs_raw, list):
        seen_required: set[str] = set()
        for item in strict_required_dirs_raw:
            part = str(item).strip().strip("/").strip("\\")
            if not part or part in seen_required:
                continue
            strict_required_dirs.append(part)
            seen_required.add(part)
    if not strict_required_dirs:
        strict_required_dirs = list(默认严格技能必需目录)
    config["strict_skill_required_dirs"] = strict_required_dirs

    return config


def 技能目录符合严格模式(*, skill_dir: Path, required_dirs: list[str]) -> bool:
    """判断技能目录是否符合严格模式约束。

    Args:
        skill_dir: 技能目录路径。
        required_dirs: 严格模式要求存在的子目录列表。

    Returns:
        bool: 符合返回 `True`。
    """

    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists() or not skill_file.is_file():
        return False

    for name in required_dirs:
        if not (skill_dir / name).is_dir():
            return False
    return True


def 解析技能模板文件(
    *,
    path: Path,
    skill_layout_mode: str,
    allow_legacy_skill_layout: bool,
    strict_skill_required_dirs: list[str],
) -> Path | None:
    """解析技能路径对应的模板文件。

    Args:
        path: `skills/` 下的候选路径。
        skill_layout_mode: 技能布局模式，支持 `strict`、`compat`。
        allow_legacy_skill_layout: 严格模式下是否允许兼容非严格文件式技能。
        strict_skill_required_dirs: 严格模式下要求存在的子目录。

    Returns:
        Path | None: 可解析的技能模板文件路径；无法解析返回 `None`。
    """

    mode = skill_layout_mode if skill_layout_mode in {"strict", "compat"} else 默认技能布局模式

    if path.is_dir():
        if mode == "strict":
            return path / "SKILL.md" if 技能目录符合严格模式(skill_dir=path, required_dirs=strict_skill_required_dirs) else None
        skill_file = path / "SKILL.md"
        return skill_file if skill_file.exists() and skill_file.is_file() else None

    if not path.is_file() or not path.name.lower().endswith((".skill.md", ".md")):
        return None
    if mode == "strict" and not allow_legacy_skill_layout:
        return None
    return path


@dataclass(frozen=True)
class 工具策略:
    """工具策略。

    Args:
        mode: 默认策略模式，仅允许 `allow`、`deny`、`ask`。
        tools: 工具开关映射，键为工具名，值为布尔值。
        bash_rules: Bash 命令规则列表。
    """

    mode: str = "ask"
    tools: dict[str, bool] = field(default_factory=dict)
    bash_rules: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class 代理定义:
    """代理定义。

    Args:
        agent_id: 代理唯一标识。
        description: 代理描述。
        prompt: 代理提示词正文。
        kind: 代理类型，支持 `subagent` 与 `primary`。
        model: 模型标识。
        color: 代理颜色（优先使用 `#RRGGBB`）。
        tools_policy: 工具策略。
        engine_overrides: 引擎级覆盖配置。
    """

    agent_id: str
    description: str
    prompt: str
    kind: str = "subagent"
    model: str | None = None
    color: str | None = None
    tools_policy: 工具策略 = field(default_factory=工具策略)
    engine_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class 技能定义:
    """技能定义。

    Args:
        name: 技能名称。
        description: 技能说明。
        body: 技能正文。
        metadata: 技能元数据。
    """

    name: str
    description: str
    body: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class 规则定义:
    """规则定义。

    Args:
        rule_id: 规则标识。
        content: 规则正文。
    """

    rule_id: str
    content: str


@dataclass(frozen=True)
class 命令定义:
    """命令定义。

    Args:
        command_id: 命令标识。
        description: 命令描述。
        argument_hint: 命令参数提示。
        body: 命令正文。
    """

    command_id: str
    description: str
    argument_hint: str
    body: str


@dataclass(frozen=True)
class 附加载体定义:
    """附加载体定义。

    Args:
        relative_path: 相对办公区根目录路径。
        content: 文本内容。
    """

    relative_path: str
    content: str


@dataclass(frozen=True)
class AOL定义:
    """AOL 根定义。

    Args:
        version: DSL 版本。
        title: 配置标题。
        instructions: 指令文本列表。
        agents: 代理定义列表。
        skills: 技能定义列表。
        rules: 规则定义列表。
        commands: 命令定义列表。
        project_instruction: 项目级指令文本（跨引擎统一载体）。
        claude_md: Claude 项目说明（写入 `.claude/CLAUDE.md`）。
        extra_assets: 附加载体列表（prompts/workflows/templates/hooks/...）。
    """

    version: str
    title: str
    instructions: list[str]
    agents: list[代理定义]
    skills: list[技能定义]
    rules: list[规则定义]
    commands: list[命令定义] = field(default_factory=list)
    project_instruction: str | None = None
    claude_md: str | None = None
    extra_assets: list[附加载体定义] = field(default_factory=list)


def 读取_工具策略(raw: Any) -> 工具策略:
    """读取工具策略。

    Args:
        raw: 原始对象。

    Returns:
        工具策略: 解析后的策略对象。

    Raises:
        ValueError: 字段类型不符合要求时抛出。
    """

    if raw is None:
        return 工具策略()
    if not isinstance(raw, dict):
        raise ValueError("toolsPolicy 必须是对象")

    mode = str(raw.get("mode", "ask")).strip().lower()
    if mode not in {"allow", "deny", "ask"}:
        raise ValueError("toolsPolicy.mode 必须是 allow/deny/ask")

    tools_raw = raw.get("tools", {})
    if not isinstance(tools_raw, dict):
        raise ValueError("toolsPolicy.tools 必须是对象")
    tools: dict[str, bool] = {}
    for key, value in tools_raw.items():
        if not isinstance(value, bool):
            raise ValueError(f"toolsPolicy.tools.{key} 必须是布尔值")
        tools[str(key)] = value

    bash_rules_raw = raw.get("bashRules", [])
    if not isinstance(bash_rules_raw, list):
        raise ValueError("toolsPolicy.bashRules 必须是数组")
    bash_rules: list[dict[str, str]] = []
    for item in bash_rules_raw:
        if not isinstance(item, dict):
            raise ValueError("toolsPolicy.bashRules 元素必须是对象")
        command = str(item.get("command", "")).strip()
        policy = str(item.get("policy", "")).strip().lower()
        if not command or policy not in {"allow", "deny", "ask"}:
            raise ValueError("toolsPolicy.bashRules 需要合法的 command 与 policy")
        bash_rules.append({"command": command, "policy": policy})

    return 工具策略(mode=mode, tools=tools, bash_rules=bash_rules)


def 读取_代理列表(raw: Any) -> list[代理定义]:
    """读取代理列表。

    Args:
        raw: 原始对象。

    Returns:
        list[代理定义]: 代理列表。

    Raises:
        ValueError: 字段缺失或类型错误时抛出。
    """

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("agents 必须是数组")

    result: list[代理定义] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("agents 元素必须是对象")
        agent_id = str(item.get("id", "")).strip()
        description = str(item.get("description", "")).strip()
        prompt = str(item.get("prompt", "")).strip()
        if not agent_id or not description or not prompt:
            raise ValueError("agent 需要 id/description/prompt")
        kind = str(item.get("kind", "subagent")).strip().lower()
        if kind not in {"subagent", "primary"}:
            raise ValueError(f"agent.kind 不支持：{kind}")
        model_raw = item.get("model")
        model = str(model_raw).strip() if isinstance(model_raw, str) and model_raw.strip() else None
        color_raw = item.get("color")
        color = str(color_raw).strip() if isinstance(color_raw, str) and color_raw.strip() else None
        color = 规范化颜色值(color)
        overrides_raw = item.get("engineOverrides", {})
        if not isinstance(overrides_raw, dict):
            raise ValueError("engineOverrides 必须是对象")
        engine_overrides: dict[str, dict[str, Any]] = {}
        for engine_id, override in overrides_raw.items():
            if not isinstance(override, dict):
                raise ValueError(f"engineOverrides.{engine_id} 必须是对象")
            engine_overrides[str(engine_id)] = override

        result.append(
            代理定义(
                agent_id=agent_id,
                description=description,
                prompt=prompt,
                kind=kind,
                model=model,
                color=color,
                tools_policy=读取_工具策略(item.get("toolsPolicy")),
                engine_overrides=engine_overrides,
            )
        )
    return result


def 读取_技能列表(raw: Any) -> list[技能定义]:
    """读取技能列表。

    Args:
        raw: 原始对象。

    Returns:
        list[技能定义]: 技能列表。

    Raises:
        ValueError: 字段不合法时抛出。
    """

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("skills 必须是数组")

    result: list[技能定义] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("skills 元素必须是对象")
        name = str(item.get("name", "")).strip()
        description = str(item.get("description", "")).strip()
        body = str(item.get("body", "")).strip()
        if not name or not description or not body:
            raise ValueError("skill 需要 name/description/body")
        metadata_raw = item.get("metadata", {})
        if not isinstance(metadata_raw, dict):
            raise ValueError("skill.metadata 必须是对象")
        metadata: dict[str, str] = {}
        for key, value in metadata_raw.items():
            metadata[str(key)] = str(value)
        result.append(技能定义(name=name, description=description, body=body, metadata=metadata))
    return result


def 读取_规则列表(raw: Any) -> list[规则定义]:
    """读取规则列表。

    Args:
        raw: 原始对象。

    Returns:
        list[规则定义]: 规则列表。

    Raises:
        ValueError: 字段不合法时抛出。
    """

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("rules 必须是数组")
    result: list[规则定义] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("rules 元素必须是对象")
        rule_id = str(item.get("id", "")).strip()
        content = str(item.get("content", "")).strip()
        if not rule_id or not content:
            raise ValueError("rule 需要 id/content")
        result.append(规则定义(rule_id=rule_id, content=content))
    return result


def 读取_命令列表(raw: Any) -> list[命令定义]:
    """读取命令列表。

    Args:
        raw: 原始对象。

    Returns:
        list[命令定义]: 命令列表。

    Raises:
        ValueError: 字段不合法时抛出。
    """

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("commands 必须是数组")

    result: list[命令定义] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("commands 元素必须是对象")
        command_id = str(item.get("id", "")).strip()
        description = str(item.get("description", "")).strip()
        argument_hint = str(item.get("argumentHint", "")).strip()
        body = str(item.get("body", "")).strip()
        if not command_id or not description or not body:
            raise ValueError("command 需要 id/description/body")
        result.append(
            命令定义(
                command_id=command_id,
                description=description,
                argument_hint=argument_hint,
                body=body,
            )
        )
    return result


def 读取_附加载体列表(raw: Any) -> list[附加载体定义]:
    """读取附加载体列表。

    Args:
        raw: 原始对象。

    Returns:
        list[附加载体定义]: 附加载体列表。

    Raises:
        ValueError: 字段不合法时抛出。
    """

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("extraAssets 必须是数组")

    result: list[附加载体定义] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("extraAssets 元素必须是对象")
        relative_path = str(item.get("path", "")).strip().replace("\\", "/")
        content = str(item.get("content", ""))
        if not relative_path:
            raise ValueError("extraAssets.path 不能为空")
        result.append(附加载体定义(relative_path=relative_path, content=content))
    return result


def 读取_aol(path: Path) -> AOL定义:
    """读取 AOL。

    Args:
        path: AOL Markdown 文件路径或 AOL 源码目录路径。

    Returns:
        AOL定义: 解析后的 AOL 对象。

    Raises:
        ValueError: 字段缺失或类型错误时抛出。

    Examples:
        >>> aol = 读取_aol(Path("libs"))
        >>> aol.version
        '0.1'
    """

    target = path.expanduser().resolve()
    if target.is_dir():
        if (target / "agents").exists() or (target / "skills").exists() or (target / "rules").exists():
            aol, _ = 从libs构建_aol(libs_root=target, title=f"{target.name} 模板库 AOL")
            return aol
        return 读取_markdown目录_aol(target)
    if not target.exists() or target.suffix.lower() != ".md":
        raise ValueError("AOL 输入必须是 Markdown 文件或目录")
    frontmatter, body = 分割_frontmatter(target.read_text(encoding="utf-8", errors="ignore"))
    kind = str(frontmatter.get("kind") or "").strip().lower()
    if kind == "agent":
        return AOL定义(
            version="1",
            title="AOL Library",
            instructions=[],
            agents=读取_代理列表(
                [
                    {
                        "id": 规范化标识(str(frontmatter.get("id") or frontmatter.get("name") or 推断模板名(target)), prefix="agent"),
                        "description": str(frontmatter.get("description") or f"来自 AOL：{target.name}").strip(),
                        "prompt": body.strip(),
                        "kind": str(frontmatter.get("mode") or "subagent").strip().lower() or "subagent",
                        "model": str(frontmatter.get("model") or "").strip() or None,
                        "color": str(frontmatter.get("color") or "").strip() or None,
                        "toolsPolicy": {
                            "mode": "ask",
                            "tools": 提取_工具策略(frontmatter).tools,
                            "bashRules": [],
                        },
                        "engineOverrides": {},
                    }
                ]
            ),
            skills=[],
            rules=[],
        )
    if kind == "skill":
        return AOL定义(
            version="1",
            title="AOL Library",
            instructions=[],
            agents=[],
            skills=读取_技能列表(
                [
                    {
                        "name": 规范化标识(str(frontmatter.get("name") or 推断模板名(target)), prefix="skill"),
                        "description": str(frontmatter.get("description") or f"来自 AOL：{target.name}").strip(),
                        "body": body.strip(),
                        "metadata": {
                            str(key): str(value)
                            for key, value in frontmatter.items()
                            if str(key).startswith("meta_")
                        },
                    }
                ]
            ),
            rules=[],
        )
    if kind == "rule":
        return AOL定义(
            version="1",
            title="AOL Library",
            instructions=[],
            agents=[],
            skills=[],
            rules=读取_规则列表(
                [
                    {
                        "id": 规范化标识(str(frontmatter.get("id") or 推断模板名(target)), prefix="rule"),
                        "content": body.strip(),
                    }
                ]
            ),
        )
    raise ValueError("单文件 AOL 需要在 frontmatter 中声明 kind=agent|skill|rule")


def 校验_aol(aol: AOL定义) -> list[str]:
    """执行 AOL 静态校验。

    Args:
        aol: AOL 对象。

    Returns:
        list[str]: 警告信息列表；为空表示无警告。

    Examples:
        >>> 校验_aol(aol)
        []
    """

    warnings: list[str] = []

    seen_agent_ids: set[str] = set()
    for agent in aol.agents:
        if agent.agent_id in seen_agent_ids:
            warnings.append(f"agent.id 重复：{agent.agent_id}")
        seen_agent_ids.add(agent.agent_id)

        if agent.color and not re.match(r"^#[0-9a-fA-F]{6}$", agent.color):
            warnings.append(f"agent.color 非 OpenCode 推荐格式（#RRGGBB）：{agent.agent_id}")

        if agent.kind == "primary":
            warnings.append(f"agent.kind=primary 仅作为抽象概念，部分引擎会降级为 subagent：{agent.agent_id}")

    seen_skill_names: set[str] = set()
    for skill in aol.skills:
        if skill.name in seen_skill_names:
            warnings.append(f"skill.name 重复：{skill.name}")
        seen_skill_names.add(skill.name)

        if not 技能名称正则.match(skill.name):
            warnings.append(
                "skill.name 不符合 OpenCode 严格命名规则（^[a-z0-9]+(-[a-z0-9]+)*$）："
                f"{skill.name}"
            )

    泄漏警告上限 = 40
    泄漏警告计数 = 0
    for agent in aol.agents:
        if 泄漏警告计数 >= 泄漏警告上限:
            break
        片段 = 提取引擎专有片段(agent.prompt)
        if 片段:
            warnings.append(f"检测到引擎专有内容泄漏：agent.{agent.agent_id} -> {', '.join(片段)}")
            泄漏警告计数 += 1

    for skill in aol.skills:
        if 泄漏警告计数 >= 泄漏警告上限:
            break
        片段 = 提取引擎专有片段(skill.body)
        if 片段:
            warnings.append(f"检测到引擎专有内容泄漏：skill.{skill.name} -> {', '.join(片段)}")
            泄漏警告计数 += 1

    for rule in aol.rules:
        if 泄漏警告计数 >= 泄漏警告上限:
            break
        片段 = 提取引擎专有片段(rule.content)
        if 片段:
            warnings.append(f"检测到引擎专有内容泄漏：rule.{rule.rule_id} -> {', '.join(片段)}")
            泄漏警告计数 += 1

    return warnings


def 收集_opencode阻断错误(aol: AOL定义) -> list[str]:
    """收集 OpenCode 编译阻断错误。

    Args:
        aol: AOL 对象。

    Returns:
        list[str]: 阻断错误列表。若为空则可继续编译。

    Examples:
        >>> errors = 收集_opencode阻断错误(aol)
        >>> isinstance(errors, list)
        True
    """

    errors: list[str] = []

    seen_agent_ids: set[str] = set()
    for agent in aol.agents:
        if agent.agent_id in seen_agent_ids:
            errors.append(f"agent.id 重复（OpenCode 阻断）：{agent.agent_id}")
        seen_agent_ids.add(agent.agent_id)

    seen_skill_names: set[str] = set()
    for skill in aol.skills:
        if skill.name in seen_skill_names:
            errors.append(f"skill.name 重复（OpenCode 阻断）：{skill.name}")
        seen_skill_names.add(skill.name)
        if not 技能名称正则.match(skill.name):
            errors.append(
                "skill.name 不符合 OpenCode 严格命名规则（OpenCode 阻断）："
                f"{skill.name}"
            )

    return errors


def 写文本(path: Path, content: str) -> None:
    """写入文本文件。

    Args:
        path: 文件路径。
        content: 文本内容。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(content, encoding="utf-8", newline="\n")
    temp_path.replace(path)


def 分割_frontmatter(markdown_text: str) -> tuple[dict[str, Any], str]:
    """分割 Markdown frontmatter 与正文。

    Args:
        markdown_text: Markdown 原文。

    Returns:
        tuple[dict[str, Any], str]: `(frontmatter对象, 正文)`。
    """

    text = markdown_text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text.strip()

    closing = text.find("\n---\n", 4)
    if closing < 0:
        return {}, text.strip()

    front_text = text[4:closing]
    body = text[closing + 5 :].strip()
    return 解析_简化yaml(front_text), body


def 读取_markdown目录_aol(path: Path) -> AOL定义:
    """从 Markdown 目录读取 AOL 定义。

    Args:
        path: Markdown 目录路径。

    Returns:
        AOL定义: AOL 对象。

    Raises:
        ValueError: 当目录中没有可解析 AOL 条目时抛出。
    """

    root_path = path.expanduser().resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(f"AOL 目录不存在：{root_path}")

    version = "1"
    title = "AOL Library"
    instructions: list[str] = []
    agent_payloads: list[dict[str, Any]] = []
    skill_payloads: list[dict[str, Any]] = []
    rule_payloads: list[dict[str, Any]] = []

    for file_path in sorted(root_path.rglob("*.md")):
        frontmatter, body = 分割_frontmatter(file_path.read_text(encoding="utf-8", errors="ignore"))
        kind = str(frontmatter.get("kind") or "").strip().lower()
        if kind == "library":
            version = str(frontmatter.get("aol_version") or frontmatter.get("version") or "1").strip() or "1"
            title = str(frontmatter.get("title") or "AOL Library").strip() or "AOL Library"
            instructions_value = frontmatter.get("instructions")
            if isinstance(instructions_value, list):
                instructions = [str(item).strip() for item in instructions_value if str(item).strip()]
            elif isinstance(instructions_value, str) and instructions_value.strip():
                instructions = [line.strip() for line in instructions_value.split("|") if line.strip()]
            if not instructions and body.strip():
                instructions = [line.strip("- ").strip() for line in body.splitlines() if line.strip()]
            continue

        if kind == "agent":
            raw_name = str(frontmatter.get("id") or frontmatter.get("name") or 推断模板名(file_path))
            agent_payloads.append(
                {
                    "id": 规范化标识(raw_name, prefix="agent"),
                    "description": str(frontmatter.get("description") or f"来自 AOL：{file_path.name}").strip(),
                    "prompt": body.strip(),
                    "kind": str(frontmatter.get("mode") or "subagent").strip().lower() or "subagent",
                    "model": str(frontmatter.get("model") or "").strip() or None,
                    "color": str(frontmatter.get("color") or "").strip() or None,
                    "toolsPolicy": {
                        "mode": "ask",
                        "tools": 提取_工具策略(frontmatter).tools,
                        "bashRules": [],
                    },
                    "engineOverrides": {},
                }
            )
            continue

        if kind == "skill":
            raw_name = str(frontmatter.get("name") or 推断模板名(file_path))
            skill_payloads.append(
                {
                    "name": 规范化标识(raw_name, prefix="skill"),
                    "description": str(frontmatter.get("description") or f"来自 AOL：{file_path.name}").strip(),
                    "body": body.strip(),
                    "metadata": {
                        str(key): str(value)
                        for key, value in frontmatter.items()
                        if str(key).startswith("meta_")
                    },
                }
            )
            continue

        if kind == "rule":
            raw_rule_id = str(frontmatter.get("id") or 推断模板名(file_path))
            rule_payloads.append(
                {
                    "id": 规范化标识(raw_rule_id, prefix="rule"),
                    "content": body.strip(),
                }
            )

    if not agent_payloads and not skill_payloads and not rule_payloads:
        raise ValueError(f"AOL 目录中未找到任何可解析 Markdown 条目：{root_path}")

    return AOL定义(
        version=version,
        title=title,
        instructions=instructions,
        agents=读取_代理列表(agent_payloads),
        skills=读取_技能列表(skill_payloads),
        rules=读取_规则列表(rule_payloads),
    )


def 解析_简化yaml(yaml_text: str) -> dict[str, Any]:
    """解析简化 YAML（仅支持常见 frontmatter 结构）。

    Args:
        yaml_text: YAML 文本。

    Returns:
        dict[str, Any]: 解析后的对象。
    """

    result: dict[str, Any] = {}
    lines = yaml_text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue

        if ":" not in line:
            index += 1
            continue

        key, value_part = line.split(":", 1)
        key = key.strip()
        value = value_part.strip()

        if value in {"|", ">", "|-", ">-", "|+", ">+"}:
            child_index = index + 1
            block_lines: list[str] = []
            base_indent = len(line) - len(line.lstrip(" "))
            block_indent: int | None = None

            probe_index = child_index
            while probe_index < len(lines):
                probe_line = lines[probe_index]
                if not probe_line.strip():
                    probe_index += 1
                    continue
                probe_indent = len(probe_line) - len(probe_line.lstrip(" "))
                if probe_indent <= base_indent:
                    break
                block_indent = probe_indent
                break

            while child_index < len(lines):
                child_line = lines[child_index]
                if not child_line.strip():
                    if block_lines:
                        block_lines.append("")
                    child_index += 1
                    continue

                child_indent = len(child_line) - len(child_line.lstrip(" "))
                if child_indent <= base_indent:
                    break

                effective_indent = block_indent if block_indent is not None else base_indent + 2
                if child_indent < effective_indent:
                    break
                block_lines.append(child_line[effective_indent:])
                child_index += 1

            result[key] = 折叠块标量(value, block_lines)
            index = child_index
            continue

        if value:
            result[key] = 解析_yaml标量(value)
            index += 1
            continue

        collected_list: list[Any] = []
        collected_dict: dict[str, Any] = {}
        child_index = index + 1
        while child_index < len(lines):
            child_line = lines[child_index]
            if not child_line.startswith("  "):
                break
            child_strip = child_line.strip()
            if child_strip.startswith("- "):
                collected_list.append(解析_yaml标量(child_strip[2:].strip()))
            elif ":" in child_strip:
                child_key, child_value = child_strip.split(":", 1)
                collected_dict[child_key.strip()] = 解析_yaml标量(child_value.strip())
            child_index += 1

        if collected_list:
            result[key] = collected_list
        elif collected_dict:
            result[key] = collected_dict
        else:
            result[key] = ""
        index = child_index

    return result


def 解析_yaml标量(value: str) -> Any:
    """解析 YAML 标量值。

    Args:
        value: 标量字符串。

    Returns:
        Any: 解析后的值。
    """

    text = value.strip()
    if not text:
        return ""
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        return text[1:-1].replace('\\"', '"')
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1]
    lower = text.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if re.match(r"^-?\d+$", text):
        return int(text)
    if re.match(r"^-?\d+\.\d+$", text):
        return float(text)
    return text


def 折叠块标量(style: str, lines: list[str]) -> str:
    """把 YAML 块标量折叠为字符串。

    Args:
        style: 原始样式标记（`|`、`>` 及其 chomping 变体）。
        lines: 块内容行。

    Returns:
        str: 解析后的文本。
    """

    normalized_style = style.strip()
    if normalized_style.startswith("|"):
        return "\n".join(lines).rstrip("\n")

    if normalized_style.startswith(">"):
        paragraphs: list[str] = []
        current: list[str] = []
        for line in lines:
            if line == "":
                if current:
                    paragraphs.append(" ".join(current).strip())
                    current = []
                else:
                    paragraphs.append("")
            else:
                current.append(line.strip())
        if current:
            paragraphs.append(" ".join(current).strip())
        return "\n\n".join(item for item in paragraphs if item is not None).rstrip("\n")

    return "\n".join(lines).rstrip("\n")


def 规范化颜色值(color: str | None) -> str | None:
    """规范化颜色值为 OpenCode 可识别格式。

    Args:
        color: 原始颜色字符串。

    Returns:
        str | None: 标准化颜色；无法识别时返回原值。
    """

    if color is None:
        return None

    raw = str(color).strip()
    if not raw:
        return None

    if re.match(r"^#[0-9a-fA-F]{6}$", raw):
        return raw.upper()

    if re.match(r"^#[0-9a-fA-F]{3}$", raw):
        r, g, b = raw[1], raw[2], raw[3]
        return f"#{r}{r}{g}{g}{b}{b}".upper()

    mapped = 命名颜色映射.get(raw.lower())
    if mapped:
        return mapped
    return raw


def 提取引擎专有片段(text: str) -> list[str]:
    """提取文本中可能的引擎专有片段。

    Args:
        text: 待扫描文本。

    Returns:
        list[str]: 匹配到的片段标识。
    """

    matches: list[str] = []
    for pattern in 引擎泄漏正则:
        if pattern.search(text):
            matches.append(pattern.pattern)
    return matches


def 规范化标识(text: str, *, prefix: str) -> str:
    """把任意名称规范化为 kebab-case 标识。

    Args:
        text: 原始文本。
        prefix: 兜底前缀。

    Returns:
        str: 规范化标识。
    """

    base = str(text or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    normalized = re.sub(r"-+", "-", normalized)
    if normalized:
        return normalized
    digest = hashlib.sha1(str(text or "").encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"{prefix}-{digest}"


def 推断模板名(file_path: Path) -> str:
    """根据文件路径推断模板名称。

    Args:
        file_path: 模板文件路径。

    Returns:
        str: 推断后的名称。
    """

    if file_path.name == "SKILL.md":
        return file_path.parent.name

    name = file_path.name
    for suffix in [".agent.md", ".skill.md", ".hook.md", ".prompt.md", ".md"]:
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return file_path.stem


def 识别模板引擎(*, file_path: Path, frontmatter: dict[str, Any]) -> str:
    """识别模板更接近的引擎语言。

    Args:
        file_path: 模板文件路径。
        frontmatter: frontmatter 对象。

    Returns:
        str: `opencode`、`claude`、`copilot` 或 `unknown`。
    """

    path_text = str(file_path).replace("\\", "/").lower()
    keys = {str(key).strip() for key in frontmatter.keys()}

    if path_text.endswith(".agent.md") or "mcp-servers" in keys or "target" in keys:
        return "copilot"
    if "mode" in keys and "name" not in keys:
        return "opencode"
    if "permissionMode" in keys or "allowed-tools" in keys or "argument-hint" in keys:
        return "claude"
    if ".opencode/" in path_text:
        return "opencode"
    if ".claude/" in path_text:
        return "claude"
    if ".github/" in path_text:
        return "copilot"
    return "unknown"


def 提取_工具策略(frontmatter: dict[str, Any]) -> 工具策略:
    """从 frontmatter 提取 AOL 工具策略。

    Args:
        frontmatter: frontmatter 对象。

    Returns:
        工具策略: 工具策略对象。
    """

    tools_value = frontmatter.get("tools")
    tools: dict[str, bool] = {}

    if isinstance(tools_value, dict):
        for key, value in tools_value.items():
            tools[str(key)] = bool(value)
    elif isinstance(tools_value, list):
        for item in tools_value:
            token = str(item).strip()
            if token:
                tools[token] = True
    elif isinstance(tools_value, str):
        for token in re.split(r"[\s,]+", tools_value):
            clean = token.strip()
            if clean:
                tools[clean] = True

    return 工具策略(mode="ask", tools=tools, bash_rules=[])


def 语义化去引擎专有文本(text: str) -> str:
    """将文本中的引擎专有路径替换为语义化占位符。

    Args:
        text: 原始文本。

    Returns:
        str: 替换后的文本。
    """

    normalized = text
    for pattern, replacement in 引擎语义化替换规则:
        normalized = pattern.sub(replacement, normalized)
    return normalized


def 是否可迁移文本载体(*, file_path: Path) -> bool:
    """判断文件是否属于可迁移文本载体。

    Args:
        file_path: 文件路径。

    Returns:
        bool: 可迁移返回 `True`。
    """

    if not file_path.is_file():
        return False
    return file_path.suffix.lower() in 可迁移附加载体后缀


def 读取项目级指令文本(*, workspace_root: Path, source_engine: str) -> str | None:
    """读取源引擎项目级指令文本。

    Args:
        workspace_root: 源办公区根目录。
        source_engine: 源引擎标识。

    Returns:
        str | None: 指令文本。
    """

    candidates: list[Path] = []
    if source_engine == "claude":
        candidates = [workspace_root / "CLAUDE.md", workspace_root.parent / "CLAUDE.md"]
    elif source_engine == "copilot":
        candidates = [workspace_root / "copilot-instructions.md"]
    elif source_engine == "opencode":
        candidates = [workspace_root / "library.md", workspace_root.parent / "AGENTS.md"]

    for path in candidates:
        if path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                return 语义化去引擎专有文本(text)
    return None


def 收集附加载体(*, workspace_root: Path) -> list[dict[str, str]]:
    """收集办公区中的附加载体文件。

    Args:
        workspace_root: 办公区根目录。

    Returns:
        list[dict[str, str]]: 附加载体列表。
    """

    assets: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for directory_name in 可迁移附加载体目录:
        directory_path = workspace_root / directory_name
        if not directory_path.exists() or not directory_path.is_dir():
            continue
        for file_path in sorted(path for path in directory_path.rglob("*") if path.is_file()):
            if not 是否可迁移文本载体(file_path=file_path):
                continue
            relative_path = str(file_path.relative_to(workspace_root)).replace("\\", "/")
            if relative_path in seen_paths:
                continue
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            assets.append({
                "path": relative_path,
                "content": 语义化去引擎专有文本(text),
            })
            seen_paths.add(relative_path)
    return assets


def 模板代理转aol(*, file_path: Path) -> dict[str, Any] | None:
    """把单个代理模板转换为 AOL 代理定义。

    Args:
        file_path: 代理模板路径。

    Returns:
        dict[str, Any] | None: AOL 代理对象；无法解析返回 `None`。
    """

    markdown_text = file_path.read_text(encoding="utf-8", errors="ignore")
    frontmatter, body = 分割_frontmatter(markdown_text)
    if not body.strip():
        return None

    source_engine = 识别模板引擎(file_path=file_path, frontmatter=frontmatter)
    raw_name = str(frontmatter.get("id") or frontmatter.get("name") or 推断模板名(file_path))
    agent_id = 规范化标识(raw_name, prefix="agent")
    description = str(frontmatter.get("description") or f"来自模板：{file_path.name}").strip()
    description = 语义化去引擎专有文本(description)
    kind = str(frontmatter.get("mode") or "subagent").strip().lower()
    if kind not in {"subagent", "primary"}:
        kind = "subagent"

    payload: dict[str, Any] = {
        "id": agent_id,
        "description": description,
        "prompt": 语义化去引擎专有文本(body),
        "kind": kind,
        "toolsPolicy": {
            "mode": "ask",
            "tools": 提取_工具策略(frontmatter).tools,
            "bashRules": [],
        },
        "engineOverrides": {
            source_engine: {
                "sourcePath": str(file_path).replace("\\", "/"),
                "sourceName": raw_name,
            }
        },
    }
    model = str(frontmatter.get("model") or "").strip()
    if model:
        payload["model"] = model
    color = str(frontmatter.get("color") or "").strip()
    if color:
        payload["color"] = color
    return payload


def 模板技能转aol(*, file_path: Path) -> dict[str, Any] | None:
    """把单个技能模板转换为 AOL 技能定义。

    Args:
        file_path: 技能模板路径。

    Returns:
        dict[str, Any] | None: AOL 技能对象；无法解析返回 `None`。
    """

    markdown_text = file_path.read_text(encoding="utf-8", errors="ignore")
    frontmatter, body = 分割_frontmatter(markdown_text)
    if not body.strip():
        return None

    source_engine = 识别模板引擎(file_path=file_path, frontmatter=frontmatter)
    raw_name = str(frontmatter.get("name") or 推断模板名(file_path))
    skill_name = 规范化标识(raw_name, prefix="skill")
    description = str(frontmatter.get("description") or f"来自模板：{file_path.name}").strip()
    description = 语义化去引擎专有文本(description)
    metadata = {
        "sourceEngine": source_engine,
        "sourcePath": str(file_path).replace("\\", "/"),
        "sourceName": raw_name,
    }
    return {
        "name": skill_name,
        "description": description,
        "body": 语义化去引擎专有文本(body),
        "metadata": metadata,
    }


def 模板规则转aol(*, file_path: Path, rule_prefix: str | None = None) -> dict[str, Any] | None:
    """把单个规则模板转换为 AOL 规则定义。

    Args:
        file_path: 规则模板路径。

    Returns:
        dict[str, Any] | None: AOL 规则对象；无法解析返回 `None`。
    """

    markdown_text = file_path.read_text(encoding="utf-8", errors="ignore")
    frontmatter, body = 分割_frontmatter(markdown_text)
    if not body.strip():
        return None

    raw_rule_id = str(frontmatter.get("id") or frontmatter.get("name") or 推断模板名(file_path))
    if rule_prefix:
        raw_rule_id = f"{rule_prefix}-{raw_rule_id}"
    rule_id = 规范化标识(raw_rule_id, prefix="rule")
    return {
        "id": rule_id,
        "content": 语义化去引擎专有文本(body),
    }


def 模板命令转aol(*, file_path: Path) -> dict[str, Any] | None:
    """把单个命令模板转换为 AOL 命令定义。

    Args:
        file_path: 命令模板路径。

    Returns:
        dict[str, Any] | None: AOL 命令对象；无法解析返回 `None`。
    """

    markdown_text = file_path.read_text(encoding="utf-8", errors="ignore")
    frontmatter, body = 分割_frontmatter(markdown_text)
    if not body.strip():
        return None

    raw_name = str(frontmatter.get("name") or 推断模板名(file_path))
    command_id = 规范化标识(raw_name, prefix="command")
    description = str(frontmatter.get("description") or f"来自模板：{file_path.name}").strip()
    argument_hint = str(frontmatter.get("argument-hint") or frontmatter.get("argument_hint") or "").strip()
    return {
        "id": command_id,
        "description": 语义化去引擎专有文本(description),
        "argumentHint": 语义化去引擎专有文本(argument_hint),
        "body": 语义化去引擎专有文本(body),
    }


def 从libs构建_aol(*, libs_root: Path, title: str) -> tuple[AOL定义, dict[str, int]]:
    """从 `libs/` 构建统一 AOL。

    Args:
        libs_root: `libs` 根目录。
        title: AOL 标题。

    Returns:
        tuple[AOL定义, dict[str, int]]: `(AOL对象, 统计信息)`。
    """

    目录映射 = 读取目录映射配置(libs_root=libs_root)
    agents_dirs = [libs_root / name for name in 目录映射.get("agent_dirs", [])]
    skills_dirs = [libs_root / name for name in 目录映射.get("skill_dirs", [])]
    rules_dirs = [libs_root / name for name in 目录映射.get("rule_dirs", [])]
    skill_layout_mode = str(目录映射.get("skill_layout_mode", 默认技能布局模式)).strip().lower()
    allow_legacy_skill_layout = bool(目录映射.get("allow_legacy_skill_layout", 默认允许兼容非严格技能))
    strict_skill_required_dirs = [str(item).strip() for item in 目录映射.get("strict_skill_required_dirs", 默认严格技能必需目录) if str(item).strip()]
    if not strict_skill_required_dirs:
        strict_skill_required_dirs = list(默认严格技能必需目录)

    agents: list[dict[str, Any]] = []
    skills: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    agent_count = 0
    skill_count = 0
    rule_count = 0

    for agents_dir in agents_dirs:
        if not agents_dir.exists() or not agents_dir.is_dir():
            continue
        for file_path in sorted(path for path in agents_dir.glob("*.md") if path.is_file()):
            payload = 模板代理转aol(file_path=file_path)
            if payload is None:
                continue
            agents.append(payload)
            agent_count += 1

    for skills_dir in skills_dirs:
        if not skills_dir.exists() or not skills_dir.is_dir():
            continue
        for path in sorted(skills_dir.iterdir()):
            skill_file = 解析技能模板文件(
                path=path,
                skill_layout_mode=skill_layout_mode,
                allow_legacy_skill_layout=allow_legacy_skill_layout,
                strict_skill_required_dirs=strict_skill_required_dirs,
            )
            if skill_file is None:
                continue
            payload = 模板技能转aol(file_path=skill_file)
            if payload is None:
                continue
            skills.append(payload)
            skill_count += 1

    for rules_dir in rules_dirs:
        if not rules_dir.exists() or not rules_dir.is_dir():
            continue
        scan_iter = rules_dir.glob("*.md") if rules_dir.name == "rules" else rules_dir.rglob("*.md")
        for file_path in sorted(path for path in scan_iter if path.is_file()):
            prefix = None if rules_dir.name == "rules" else rules_dir.name
            payload = 模板规则转aol(file_path=file_path, rule_prefix=prefix)
            if payload is None:
                continue
            rules.append(payload)
            rule_count += 1

    seen_agent_ids: set[str] = set()
    for payload in agents:
        base_id = str(payload.get("id") or "agent")
        candidate = base_id
        index = 2
        while candidate in seen_agent_ids:
            candidate = f"{base_id}-{index}"
            index += 1
        payload["id"] = candidate
        seen_agent_ids.add(candidate)

    seen_skill_names: set[str] = set()
    for payload in skills:
        base_name = str(payload.get("name") or "skill")
        candidate = base_name
        index = 2
        while candidate in seen_skill_names:
            candidate = f"{base_name}-{index}"
            index += 1
        payload["name"] = candidate
        seen_skill_names.add(candidate)

    seen_rule_ids: set[str] = set()
    for payload in rules:
        base_id = str(payload.get("id") or "rule")
        candidate = base_id
        index = 2
        while candidate in seen_rule_ids:
            candidate = f"{base_id}-{index}"
            index += 1
        payload["id"] = candidate
        seen_rule_ids.add(candidate)

    aol = AOL定义(
        version="0.1",
        title=title,
        instructions=[
            "该 AOL 由 AOC 从 libs 模板自动归一化生成。",
            "优先保证 OpenCode 可编译，再映射到 Claude/Copilot。",
        ],
        agents=读取_代理列表(agents),
        skills=读取_技能列表(skills),
        rules=读取_规则列表(rules),
    )
    return aol, {"agents": agent_count, "skills": skill_count, "rules": rule_count}


def 原位归一化libs_aol(*, libs_root: Path, dry_run: bool) -> dict[str, Any]:
    """把 `libs/` 原位归一化为 AOL Markdown DSL。

    Args:
        libs_root: `libs` 根目录。
        dry_run: 是否预演。

    Returns:
        dict[str, Any]: 归一化统计。
    """

    目录映射 = 读取目录映射配置(libs_root=libs_root)
    agents_dirs = [libs_root / name for name in 目录映射.get("agent_dirs", [])]
    skills_dirs = [libs_root / name for name in 目录映射.get("skill_dirs", [])]
    rules_dirs = [libs_root / name for name in 目录映射.get("rule_dirs", [])]
    skill_layout_mode = str(目录映射.get("skill_layout_mode", 默认技能布局模式)).strip().lower()
    allow_legacy_skill_layout = bool(目录映射.get("allow_legacy_skill_layout", 默认允许兼容非严格技能))
    strict_skill_required_dirs = [str(item).strip() for item in 目录映射.get("strict_skill_required_dirs", 默认严格技能必需目录) if str(item).strip()]
    if not strict_skill_required_dirs:
        strict_skill_required_dirs = list(默认严格技能必需目录)

    touched: list[str] = []
    agent_total = 0
    skill_total = 0
    rule_total = 0

    for agents_dir in agents_dirs:
        if not agents_dir.exists() or not agents_dir.is_dir():
            continue
        for file_path in sorted(path for path in agents_dir.glob("*.md") if path.is_file()):
            payload = 模板代理转aol(file_path=file_path)
            if payload is None:
                continue
            agent_total += 1
            agent = 读取_代理列表([payload])[0]
            rendered = 渲染_aol_agent(agent)
            original = file_path.read_text(encoding="utf-8", errors="ignore")
            if rendered != original:
                touched.append(str(file_path))
                if not dry_run:
                    写文本(file_path, rendered)

    for skills_dir in skills_dirs:
        if not skills_dir.exists() or not skills_dir.is_dir():
            continue
        for path in sorted(skills_dir.iterdir()):
            target_file = 解析技能模板文件(
                path=path,
                skill_layout_mode=skill_layout_mode,
                allow_legacy_skill_layout=allow_legacy_skill_layout,
                strict_skill_required_dirs=strict_skill_required_dirs,
            )
            if target_file is None:
                continue

            payload = 模板技能转aol(file_path=target_file)
            if payload is None:
                continue
            skill_total += 1
            skill = 读取_技能列表([payload])[0]
            rendered = 渲染_aol_skill(skill)
            original = target_file.read_text(encoding="utf-8", errors="ignore")
            if rendered != original:
                touched.append(str(target_file))
                if not dry_run:
                    写文本(target_file, rendered)

    for rules_dir in rules_dirs:
        if not rules_dir.exists() or not rules_dir.is_dir():
            continue
        scan_iter = rules_dir.glob("*.md") if rules_dir.name == "rules" else rules_dir.rglob("*.md")
        for file_path in sorted(path for path in scan_iter if path.is_file()):
            prefix = None if rules_dir.name == "rules" else rules_dir.name
            payload = 模板规则转aol(file_path=file_path, rule_prefix=prefix)
            if payload is None:
                continue
            rule_total += 1
            rule = 读取_规则列表([payload])[0]
            rendered = 渲染_aol_rule(rule)
            original = file_path.read_text(encoding="utf-8", errors="ignore")
            if rendered != original:
                touched.append(str(file_path))
                if not dry_run:
                    写文本(file_path, rendered)

    return {
        "normalized_files": len(touched),
        "agents": agent_total,
        "skills": skill_total,
        "rules": rule_total,
        "paths": touched,
        "dry_run": dry_run,
    }


def 渲染_aol_agent(agent: 代理定义) -> str:
    """渲染 AOL 代理源码文件。

    Args:
        agent: 代理定义。

    Returns:
        str: AOL Markdown 文本。
    """

    lines = ["---"]
    lines.extend(渲染_yaml键值("aol_version", "1"))
    lines.extend(渲染_yaml键值("kind", "agent"))
    lines.extend(渲染_yaml键值("id", agent.agent_id))
    lines.extend(渲染_yaml键值("description", agent.description))
    lines.extend(渲染_yaml键值("mode", agent.kind))
    if agent.model:
        lines.extend(渲染_yaml键值("model", agent.model))
    if agent.color:
        lines.extend(渲染_yaml键值("color", agent.color))
    enabled_tools = [tool_name for tool_name, enabled in sorted(agent.tools_policy.tools.items()) if enabled]
    if enabled_tools:
        lines.extend(渲染_yaml键值("tools", enabled_tools))
    lines.append("---")
    lines.append("")
    lines.append(agent.prompt)
    lines.append("")
    return "\n".join(lines)


def 渲染_aol_skill(skill: 技能定义) -> str:
    """渲染 AOL 技能源码文件。

    Args:
        skill: 技能定义。

    Returns:
        str: AOL Markdown 文本。
    """

    lines = ["---"]
    lines.extend(渲染_yaml键值("aol_version", "1"))
    lines.extend(渲染_yaml键值("kind", "skill"))
    lines.extend(渲染_yaml键值("name", skill.name))
    lines.extend(渲染_yaml键值("description", skill.description))
    for key, value in sorted(skill.metadata.items()):
        lines.extend(渲染_yaml键值(f"meta_{key}", value))
    lines.append("---")
    lines.append("")
    lines.append(skill.body)
    lines.append("")
    return "\n".join(lines)


def 渲染_aol_rule(rule: 规则定义) -> str:
    """渲染 AOL 规则源码文件。

    Args:
        rule: 规则定义。

    Returns:
        str: AOL Markdown 文本。
    """

    lines = ["---"]
    lines.extend(渲染_yaml键值("aol_version", "1"))
    lines.extend(渲染_yaml键值("kind", "rule"))
    lines.extend(渲染_yaml键值("id", rule.rule_id))
    lines.append("---")
    lines.append("")
    lines.append(rule.content)
    lines.append("")
    return "\n".join(lines)


def 渲染_yaml键值(name: str, value: Any) -> list[str]:
    """渲染简单 YAML 键值行。

    Args:
        name: 键名。
        value: 值对象。

    Returns:
        list[str]: 一行或多行 YAML。
    """

    if isinstance(value, bool):
        return [f"{name}: {'true' if value else 'false'}"]
    if isinstance(value, (int, float)):
        return [f"{name}: {value}"]
    if isinstance(value, str):
        if "\n" in value:
            lines = [f"{name}: |"]
            for line in value.splitlines():
                lines.append(f"  {line}" if line else "  ")
            return lines
        escaped = value.replace('"', '\\"')
        return [f'{name}: "{escaped}"']
    if isinstance(value, list):
        lines = [f"{name}:"]
        for item in value:
            item_text = str(item).replace('"', '\\"')
            lines.append(f'  - "{item_text}"')
        return lines
    escaped_value = str(value).replace('"', '\\"')
    return [f'{name}: "{escaped_value}"']


def 渲染_opencode_agent(agent: 代理定义) -> str:
    """渲染 OpenCode 代理文件。

    Args:
        agent: 代理定义。

    Returns:
        str: Markdown 文本。
    """

    lines = ["---"]
    lines.extend(渲染_yaml键值("description", agent.description))
    lines.extend(渲染_yaml键值("mode", "subagent" if agent.kind == "primary" else agent.kind))
    if agent.model:
        lines.extend(渲染_yaml键值("model", agent.model))
    normalized_color = 规范化颜色值(agent.color)
    if normalized_color:
        lines.extend(渲染_yaml键值("color", normalized_color))

    if agent.tools_policy.tools:
        lines.append("tools:")
        for tool_name, enabled in sorted(agent.tools_policy.tools.items()):
            lines.append(f"  {tool_name}: {'true' if enabled else 'false'}")

    lines.append("---")
    lines.append("")
    lines.append(agent.prompt)
    lines.append("")
    return "\n".join(lines)


def 渲染_claude_agent(agent: 代理定义) -> str:
    """渲染 Claude 代理文件。

    Args:
        agent: 代理定义。

    Returns:
        str: Markdown 文本。
    """

    lines = ["---"]
    lines.extend(渲染_yaml键值("name", agent.agent_id))
    lines.extend(渲染_yaml键值("description", agent.description))
    if agent.model:
        lines.extend(渲染_yaml键值("model", agent.model))

    enabled_tools = [tool_name for tool_name, enabled in sorted(agent.tools_policy.tools.items()) if enabled]
    if enabled_tools:
        lines.extend(渲染_yaml键值("tools", enabled_tools))

    lines.append("---")
    lines.append("")
    lines.append(agent.prompt)
    lines.append("")
    return "\n".join(lines)


def 渲染_copilot_agent(agent: 代理定义) -> str:
    """渲染 Copilot 代理文件。

    Args:
        agent: 代理定义。

    Returns:
        str: Markdown 文本。
    """

    lines = ["---"]
    lines.extend(渲染_yaml键值("description", agent.description))
    if agent.model:
        lines.extend(渲染_yaml键值("model", agent.model))

    enabled_tools = [tool_name for tool_name, enabled in sorted(agent.tools_policy.tools.items()) if enabled]
    if enabled_tools:
        lines.extend(渲染_yaml键值("tools", enabled_tools))

    lines.append("---")
    lines.append("")
    lines.append(agent.prompt)
    lines.append("")
    return "\n".join(lines)


def 渲染_skill(name: str, description: str, body: str, metadata: dict[str, str]) -> str:
    """渲染技能 SKILL.md。

    Args:
        name: 技能名称。
        description: 技能描述。
        body: 技能正文。
        metadata: 元数据。

    Returns:
        str: Markdown 文本。
    """

    lines = ["---"]
    lines.extend(渲染_yaml键值("name", name))
    lines.extend(渲染_yaml键值("description", description))
    if metadata:
        lines.append("metadata:")
        for key, value in sorted(metadata.items()):
            escaped = str(value).replace('"', '\\"')
            lines.append(f'  {key}: "{escaped}"')
    lines.append("---")
    lines.append("")
    lines.append(body)
    lines.append("")
    return "\n".join(lines)


def 渲染_claude_command(command: 命令定义) -> str:
    """渲染 Claude slash command 文件。

    Args:
        command: 命令定义。

    Returns:
        str: Markdown 文本。
    """

    lines = ["---"]
    lines.extend(渲染_yaml键值("description", command.description))
    if command.argument_hint:
        lines.extend(渲染_yaml键值("argument-hint", command.argument_hint))
    lines.append("---")
    lines.append("")
    lines.append(command.body)
    lines.append("")
    return "\n".join(lines)


def 编译到_opencode(aol: AOL定义, output_dir: Path) -> None:
    """编译到 OpenCode 目录。

    Args:
        aol: AOL 对象。
        output_dir: 输出根目录。
    """

    opencode_root = output_dir / ".opencode"
    for sub in ["agents", "skills", "rules", "commands", "modes", "plugins", "tools", "themes", "plans"]:
        (opencode_root / sub).mkdir(parents=True, exist_ok=True)

    write_rules = [f".opencode/rules/{rule.rule_id}.md" for rule in aol.rules]
    if not write_rules:
        write_rules = [".opencode/rules/base.md"]
    opencode_json = {
        "$schema": "https://opencode.ai/config.json",
        "instructions": write_rules,
    }
    写文本(output_dir / "opencode.json", json.dumps(opencode_json, ensure_ascii=False, indent=2) + "\n")

    rule_lines = [f"# {aol.title}"]
    if aol.instructions:
        rule_lines.append("")
        rule_lines.extend([f"- {line}" for line in aol.instructions])
    写文本(output_dir / "AGENTS.md", "\n".join(rule_lines) + "\n")

    if aol.rules:
        for rule in aol.rules:
            写文本(opencode_root / "rules" / f"{rule.rule_id}.md", f"# {rule.rule_id}\n\n{rule.content}\n")
    else:
        写文本(opencode_root / "rules" / "base.md", f"# base\n\n{aol.title}\n")

    for agent in aol.agents:
        写文本(opencode_root / "agents" / f"{agent.agent_id}.md", 渲染_opencode_agent(agent))

    for skill in aol.skills:
        写文本(
            opencode_root / "skills" / skill.name / "SKILL.md",
            渲染_skill(skill.name, skill.description, skill.body, skill.metadata),
        )


def 编译到_claude(aol: AOL定义, output_dir: Path) -> None:
    """编译到 Claude Code 目录。

    Args:
        aol: AOL 对象。
        output_dir: 输出根目录。
    """

    claude_root = output_dir / ".claude"
    (claude_root / "agents").mkdir(parents=True, exist_ok=True)
    (claude_root / "skills").mkdir(parents=True, exist_ok=True)

    settings = {
        "aolVersion": aol.version,
        "title": aol.title,
    }
    写文本(claude_root / "settings.json", json.dumps(settings, ensure_ascii=False, indent=2) + "\n")

    claude_md_lines = [f"# {aol.title}"]
    if aol.instructions:
        claude_md_lines.append("")
        claude_md_lines.extend([f"- {line}" for line in aol.instructions])
    写文本(output_dir / "CLAUDE.md", "\n".join(claude_md_lines) + "\n")

    for agent in aol.agents:
        写文本(claude_root / "agents" / f"{agent.agent_id}.md", 渲染_claude_agent(agent))

    for skill in aol.skills:
        写文本(
            claude_root / "skills" / skill.name / "SKILL.md",
            渲染_skill(skill.name, skill.description, skill.body, skill.metadata),
        )


def 编译到_copilot(aol: AOL定义, output_dir: Path) -> None:
    """编译到 GitHub Copilot 目录。

    Args:
        aol: AOL 对象。
        output_dir: 输出根目录。
    """

    github_root = output_dir / ".github"
    (github_root / "agents").mkdir(parents=True, exist_ok=True)
    (github_root / "skills").mkdir(parents=True, exist_ok=True)

    instruction_lines = [f"# {aol.title}"]
    if aol.instructions:
        instruction_lines.append("")
        instruction_lines.extend([f"- {line}" for line in aol.instructions])
    写文本(github_root / "copilot-instructions.md", "\n".join(instruction_lines) + "\n")

    for agent in aol.agents:
        写文本(github_root / "agents" / f"{agent.agent_id}.agent.md", 渲染_copilot_agent(agent))

    for skill in aol.skills:
        写文本(
            github_root / "skills" / skill.name / "SKILL.md",
            渲染_skill(skill.name, skill.description, skill.body, skill.metadata),
        )


def 读取引擎办公区目录名(*, engine: str) -> str:
    """读取引擎办公区目录名。

    Args:
        engine: 引擎标识。

    Returns:
        str: 引擎办公区目录名。

    Raises:
        ValueError: 引擎不受支持时抛出。
    """

    if engine not in 引擎办公区目录映射:
        raise ValueError(f"不支持的引擎：{engine}")
    return 引擎办公区目录映射[engine]


def 从引擎办公区构建_aol(*, source_workspace_dir: Path, source_engine: str, title: str) -> tuple[AOL定义, dict[str, int]]:
    """从单一引擎办公区构建 AOL。

    该函数只负责翻译，不承载流程编排。

    Args:
        source_workspace_dir: 源办公区目录路径。
        source_engine: 源引擎标识。
        title: AOL 标题。

    Returns:
        tuple[AOL定义, dict[str, int]]: `(AOL对象, 统计信息)`。

    Raises:
        ValueError: 参数或目录不合法时抛出。
    """

    if source_engine not in 引擎办公区目录映射:
        raise ValueError(f"不支持的引擎：{source_engine}")

    workspace_root = source_workspace_dir.expanduser().resolve()
    if not workspace_root.exists() or not workspace_root.is_dir():
        raise ValueError(f"源办公区目录不存在：{workspace_root}")

    agents: list[dict[str, Any]] = []
    skills: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    extra_assets: list[dict[str, str]] = []
    agent_count = 0
    skill_count = 0
    rule_count = 0
    command_count = 0

    agents_dir = workspace_root / "agents"
    if agents_dir.exists() and agents_dir.is_dir():
        for file_path in sorted(path for path in agents_dir.iterdir() if path.is_file()):
            if source_engine == "copilot":
                if not file_path.name.lower().endswith((".agent.md", ".md")):
                    continue
            elif not file_path.name.lower().endswith(".md"):
                continue
            payload = 模板代理转aol(file_path=file_path)
            if payload is None:
                continue
            agents.append(payload)
            agent_count += 1

    skills_dir = workspace_root / "skills"
    if skills_dir.exists() and skills_dir.is_dir():
        for path in sorted(skills_dir.iterdir()):
            skill_file = 解析技能模板文件(
                path=path,
                skill_layout_mode="compat",
                allow_legacy_skill_layout=True,
                strict_skill_required_dirs=list(默认严格技能必需目录),
            )
            if skill_file is None:
                continue
            payload = 模板技能转aol(file_path=skill_file)
            if payload is None:
                continue
            skills.append(payload)
            skill_count += 1

    rules_dir = workspace_root / "rules"
    if rules_dir.exists() and rules_dir.is_dir():
        for file_path in sorted(path for path in rules_dir.rglob("*.md") if path.is_file()):
            parent_rel = file_path.parent.relative_to(rules_dir)
            rule_prefix = None if str(parent_rel) == "." else str(parent_rel).replace("\\", "-").replace("/", "-")
            payload = 模板规则转aol(file_path=file_path, rule_prefix=rule_prefix)
            if payload is None:
                continue
            rules.append(payload)
            rule_count += 1

    commands_dir = workspace_root / "commands"
    if commands_dir.exists() and commands_dir.is_dir():
        for file_path in sorted(path for path in commands_dir.glob("*.md") if path.is_file()):
            payload = 模板命令转aol(file_path=file_path)
            if payload is None:
                continue
            commands.append(payload)
            command_count += 1

    extra_assets = 收集附加载体(workspace_root=workspace_root)
    project_instruction = 读取项目级指令文本(workspace_root=workspace_root, source_engine=source_engine)

    claude_md: str | None = None
    if source_engine == "claude":
        claude_md = project_instruction

    if not agents and not skills and not rules and not commands and not extra_assets and not project_instruction:
        raise ValueError(f"源办公区中未找到可转换内容：{workspace_root}")

    seen_agent_ids: set[str] = set()
    for payload in agents:
        base_id = str(payload.get("id") or "agent")
        candidate = base_id
        index = 2
        while candidate in seen_agent_ids:
            candidate = f"{base_id}-{index}"
            index += 1
        payload["id"] = candidate
        seen_agent_ids.add(candidate)

    seen_skill_names: set[str] = set()
    for payload in skills:
        base_name = str(payload.get("name") or "skill")
        candidate = base_name
        index = 2
        while candidate in seen_skill_names:
            candidate = f"{base_name}-{index}"
            index += 1
        payload["name"] = candidate
        seen_skill_names.add(candidate)

    seen_rule_ids: set[str] = set()
    for payload in rules:
        base_id = str(payload.get("id") or "rule")
        candidate = base_id
        index = 2
        while candidate in seen_rule_ids:
            candidate = f"{base_id}-{index}"
            index += 1
        payload["id"] = candidate
        seen_rule_ids.add(candidate)

    seen_command_ids: set[str] = set()
    for payload in commands:
        base_id = str(payload.get("id") or "command")
        candidate = base_id
        index = 2
        while candidate in seen_command_ids:
            candidate = f"{base_id}-{index}"
            index += 1
        payload["id"] = candidate
        seen_command_ids.add(candidate)

    aol = AOL定义(
        version="1",
        title=title,
        instructions=[
            "该 AOL 由 AOC 从引擎办公区自动翻译生成。",
            "流程编排由上层脚本负责。",
        ],
        agents=读取_代理列表(agents),
        skills=读取_技能列表(skills),
        rules=读取_规则列表(rules),
        commands=读取_命令列表(commands),
        project_instruction=project_instruction,
        claude_md=claude_md,
        extra_assets=读取_附加载体列表(extra_assets),
    )
    return aol, {
        "agents": agent_count,
        "skills": skill_count,
        "rules": rule_count,
        "commands": command_count,
        "assets": len(extra_assets),
    }


def 写入附加载体(*, target_root: Path, extra_assets: list[附加载体定义]) -> None:
    """写入附加载体到目标办公区。

    Args:
        target_root: 目标办公区根目录。
        extra_assets: 附加载体列表。
    """

    for asset in extra_assets:
        relative_path = asset.relative_path.replace("\\", "/")
        if not relative_path:
            continue
        target_path = target_root / Path(relative_path)
        写文本(target_path, asset.content)


def 编译_aol到引擎办公区(*, aol: AOL定义, target_workspace_dir: Path, target_engine: str) -> None:
    """将 AOL 编译到目标引擎办公区。

    该函数只负责翻译，不承载流程编排。

    Args:
        aol: AOL 对象。
        target_workspace_dir: 目标办公区目录路径。
        target_engine: 目标引擎标识。

    Raises:
        ValueError: 目标引擎不受支持时抛出。
    """

    if target_engine not in 引擎办公区目录映射:
        raise ValueError(f"不支持的引擎：{target_engine}")

    target_root = target_workspace_dir.expanduser().resolve()
    if target_engine == "opencode":
        for sub in ["agents", "skills", "rules", "commands", "modes", "plugins", "tools", "themes", "plans"]:
            (target_root / sub).mkdir(parents=True, exist_ok=True)

        if aol.rules:
            for rule in aol.rules:
                写文本(target_root / "rules" / f"{rule.rule_id}.md", f"# {rule.rule_id}\n\n{rule.content}\n")
        else:
            写文本(target_root / "rules" / "base.md", f"# base\n\n{aol.title}\n")

        for agent in aol.agents:
            写文本(target_root / "agents" / f"{agent.agent_id}.md", 渲染_opencode_agent(agent))

        for skill in aol.skills:
            写文本(
                target_root / "skills" / skill.name / "SKILL.md",
                渲染_skill(skill.name, skill.description, skill.body, skill.metadata),
            )

        for command in aol.commands:
            写文本(target_root / "commands" / f"{command.command_id}.md", 渲染_claude_command(command))

        if aol.project_instruction and aol.project_instruction.strip():
            写文本(target_root / "library.md", aol.project_instruction.strip() + "\n")

        写入附加载体(target_root=target_root, extra_assets=aol.extra_assets)
        return

    if target_engine == "claude":
        (target_root / "agents").mkdir(parents=True, exist_ok=True)
        (target_root / "skills").mkdir(parents=True, exist_ok=True)
        (target_root / "commands").mkdir(parents=True, exist_ok=True)
        (target_root / "rules").mkdir(parents=True, exist_ok=True)
        settings = {
            "aolVersion": aol.version,
            "title": aol.title,
        }
        写文本(target_root / "settings.json", json.dumps(settings, ensure_ascii=False, indent=2) + "\n")

        if aol.project_instruction and aol.project_instruction.strip():
            claude_md = aol.project_instruction.strip() + "\n"
        elif aol.claude_md and aol.claude_md.strip():
            claude_md = aol.claude_md.strip() + "\n"
        else:
            claude_md_lines = [f"# {aol.title}"]
            if aol.instructions:
                claude_md_lines.append("")
                claude_md_lines.extend([f"- {line}" for line in aol.instructions])
            claude_md = "\n".join(claude_md_lines) + "\n"
        写文本(target_root / "CLAUDE.md", claude_md)

        for agent in aol.agents:
            写文本(target_root / "agents" / f"{agent.agent_id}.md", 渲染_claude_agent(agent))

        for skill in aol.skills:
            写文本(
                target_root / "skills" / skill.name / "SKILL.md",
                渲染_skill(skill.name, skill.description, skill.body, skill.metadata),
            )

        for rule in aol.rules:
            写文本(target_root / "rules" / f"{rule.rule_id}.md", f"# {rule.rule_id}\n\n{rule.content}\n")

        for command in aol.commands:
            写文本(target_root / "commands" / f"{command.command_id}.md", 渲染_claude_command(command))

        写入附加载体(target_root=target_root, extra_assets=aol.extra_assets)
        return

    if target_engine == "copilot":
        (target_root / "agents").mkdir(parents=True, exist_ok=True)
        (target_root / "skills").mkdir(parents=True, exist_ok=True)

        if aol.project_instruction and aol.project_instruction.strip():
            instruction_text = aol.project_instruction.strip() + "\n"
        else:
            instruction_lines = [f"# {aol.title}"]
            if aol.instructions:
                instruction_lines.append("")
                instruction_lines.extend([f"- {line}" for line in aol.instructions])
            instruction_text = "\n".join(instruction_lines) + "\n"
        写文本(target_root / "copilot-instructions.md", instruction_text)

        for agent in aol.agents:
            写文本(target_root / "agents" / f"{agent.agent_id}.agent.md", 渲染_copilot_agent(agent))

        for skill in aol.skills:
            写文本(
                target_root / "skills" / skill.name / "SKILL.md",
                渲染_skill(skill.name, skill.description, skill.body, skill.metadata),
            )

        (target_root / "commands").mkdir(parents=True, exist_ok=True)
        (target_root / "rules").mkdir(parents=True, exist_ok=True)

        for command in aol.commands:
            写文本(target_root / "commands" / f"{command.command_id}.md", 渲染_claude_command(command))

        for rule in aol.rules:
            写文本(target_root / "rules" / f"{rule.rule_id}.md", f"# {rule.rule_id}\n\n{rule.content}\n")

        写入附加载体(target_root=target_root, extra_assets=aol.extra_assets)
        return


def 执行_compile(argv: list[str]) -> int:
    """执行编译子命令。

    Args:
        argv: 子命令参数列表。

    Returns:
        int: 退出码。

    Raises:
        SystemExit: 参数错误时抛出。
    """

    parser = argparse.ArgumentParser(description="把 AOL 编译为目标引擎目录")
    parser.add_argument("--input", required=True, help="AOL Markdown 文件或 AOL 目录路径")
    parser.add_argument("--engine", required=True, choices=["opencode", "claude", "copilot"])
    parser.add_argument("--output-dir", required=True, help="输出目录")
    parser.add_argument("--repo-root", default="", help="AOB 仓库根目录（若不传则自动推断）")
    args = parser.parse_args(argv)

    repo_root = 解析_aob仓库根目录(args.repo_root)
    input_path = 解析仓库内路径(args.input, repo_root=repo_root)
    output_dir = 解析仓库内路径(args.output_dir, repo_root=repo_root)

    aol = 读取_aol(input_path)
    warnings = 校验_aol(aol)
    for warning in warnings:
        print(f"[WARN] {warning}")

    if args.engine == "opencode":
        blocking_errors = 收集_opencode阻断错误(aol)
        if blocking_errors:
            for item in blocking_errors:
                print(f"[ERROR] {item}")
            print("[ERROR] OpenCode 编译已阻断。请先修复 AOL 源码后再编译。")
            return 2

    if args.engine == "opencode":
        编译到_opencode(aol, output_dir)
    elif args.engine == "claude":
        编译到_claude(aol, output_dir)
    elif args.engine == "copilot":
        编译到_copilot(aol, output_dir)

    print(f"[DONE] 已编译到 {args.engine}: {output_dir}")
    return 0


def 执行_validate(argv: list[str]) -> int:
    """执行校验子命令。

    Args:
        argv: 子命令参数列表。

    Returns:
        int: 退出码。
    """

    parser = argparse.ArgumentParser(description="校验 AOL 文件")
    parser.add_argument("--input", required=True, help="AOL Markdown 文件或 AOL 目录路径")
    parser.add_argument("--repo-root", default="", help="AOB 仓库根目录（若不传则自动推断）")
    args = parser.parse_args(argv)

    repo_root = 解析_aob仓库根目录(args.repo_root)
    input_path = 解析仓库内路径(args.input, repo_root=repo_root)
    aol = 读取_aol(input_path)
    warnings = 校验_aol(aol)
    if not warnings:
        print("[OK] AOL 校验通过，无警告")
        return 0
    for warning in warnings:
        print(f"[WARN] {warning}")
    return 0


def 构建顶层解析器() -> argparse.ArgumentParser:
    """构建顶层命令解析器。

    Returns:
        argparse.ArgumentParser: 顶层解析器。
    """

    parser = argparse.ArgumentParser(description="AOC（autodo 编译器）入口")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("compile", help="编译 AOL 到目标引擎")
    sub.add_parser("validate", help="校验 AOL")
    return parser


def main() -> int:
    """程序主入口。

    Returns:
        int: 退出码。
    """

    parser = 构建顶层解析器()
    args, passthrough = parser.parse_known_args()
    if args.command == "compile":
        return 执行_compile(list(passthrough))
    if args.command == "validate":
        return 执行_validate(list(passthrough))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
