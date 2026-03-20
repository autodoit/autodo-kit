"""Skill 渲染事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result

try:
    from autodoengine.utils.skill_renderer import SkillRenderer
except ImportError:
    SkillRenderer = None


def render_skill(skill_path: str | Path, params: dict[str, Any]) -> dict[str, Any]:
    """渲染 Skill 文件并返回结构化结果。

    Args:
        skill_path: `SKILL.md` 文件绝对路径。
        params: 渲染所需的参数字典。

    Returns:
        dict[str, Any]: 渲染后的结构化结果字典。

    Raises:
        RuntimeError: 未安装 `autodo-engine` 或缺少 `SkillRenderer` 时抛出。
        ValueError: `skill_path` 为空或 `params` 不是字典时抛出。
        FileNotFoundError: `skill_path` 指向的文件不存在时抛出。

    Examples:
        >>> render_skill(r"D:/workspace/skills/demo/SKILL.md", {"topic": "测试"})
        {"status": "PASS", ...}
    """

    skill_path_text = str(skill_path or "").strip()
    if not skill_path_text:
        raise ValueError("skill_path 不能为空")
    if not isinstance(params, dict):
        raise ValueError("params 必须为字典")

    resolved_skill_path = Path(skill_path_text)
    if not resolved_skill_path.is_absolute():
        raise ValueError(
            "skill_path 必须为绝对路径：请确认已在 tools 层完成统一路径预处理，"
            f"当前值={skill_path_text!r}"
        )
    if not resolved_skill_path.exists():
        raise FileNotFoundError(f"SKILL.md 文件不存在: {resolved_skill_path}")
    if SkillRenderer is None:
        raise RuntimeError("SkillRenderer 未在环境中找到，请检查 autodo-engine 安装情况")

    renderer = SkillRenderer()
    meta, _ = renderer.load_skill(str(resolved_skill_path))
    rendered_prompt = renderer.render(str(resolved_skill_path), params)
    return {
        "status": "PASS",
        "mode": "skill-render",
        "prompt": rendered_prompt,
        "meta": meta,
        "skill_name": str(meta.get("name") or resolved_skill_path.stem),
        "skill_path": str(resolved_skill_path),
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。

    Args:
        config_path: 调度器传入的事务配置文件路径。

    Returns:
        list[Path]: 事务产物路径列表。

    Raises:
        ValueError: 配置缺少必填字段或字段类型不合法时抛出。
        RuntimeError: 渲染器不可用时抛出。
        FileNotFoundError: Skill 文件不存在时抛出。

    Examples:
        >>> execute(Path(r"D:/workspace/configs/skill_render.json"))
        [Path(r"D:/workspace/output/skill_render_result.json")]
    """

    raw_cfg = load_json_or_py(config_path)
    params = raw_cfg.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("params 必须为字典")
    result = render_skill(
        skill_path=str(raw_cfg.get("skill_path") or ""),
        params=params,
    )
    return write_affair_json_result(raw_cfg, config_path, "skill_render_result.json", result)
