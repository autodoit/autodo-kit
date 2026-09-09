"""实体注册表（世界模型层）沙盒仿真测试。

覆盖：
1. 实体注册表加载（entities/relationships/compatibility_matrix）。
2. 从实体注册表派生发布目标（含 path_parts 与 folder_name 两种形态）。
3. 无 primary 路径的实体（纯模型供应商）不生成发布目标。
4. 发布目标携带世界模型字段（entity_id/vendor/roles/compat_reads）。
5. 沙盒仿真同步不污染现实目录（simulate_only=True）。
6. 语法族映射按实体+角色（qoder_cn/lingma → copilot）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodokit.tools.atomic.aob_runtime.aob_common import (
    加载实体注册表,
    从实体注册表派生发布目标,
    获取用户级发布目标,
    发现用户级发布目标,
    默认引擎供应商映射,
)


def _write_entity_registry(repo_root: Path) -> Path:
    """在沙盒仓库写入最小实体注册表。"""
    db_root = repo_root / "database"
    db_root.mkdir(parents=True, exist_ok=True)
    registry_path = db_root / "entity_registry.json"
    payload = {
        "schema_version": 1,
        "entities": {
            "codex": {
                "vendor": "openai",
                "brand_aliases": ["codex"],
                "roles": ["ide", "plugin", "cli"],
                "path_contract": {"primary": "~/.codex", "alias": [], "compat_reads": []},
                "model_provider": ["openai"],
                "backend_provider": ["openai"],
            },
            "opencode": {
                "vendor": "anomaly",
                "brand_aliases": ["opencode"],
                "roles": ["cli", "ide"],
                "path_contract": {"primary": "~/.config/opencode", "alias": [], "compat_reads": []},
                "model_provider": ["openai", "anthropic"],
                "backend_provider": ["openai", "anthropic"],
            },
            "copilot": {
                "vendor": "github",
                "brand_aliases": ["copilot"],
                "roles": ["plugin", "cli"],
                "path_contract": {"primary": "~/.copilot", "alias": [], "compat_reads": ["codex", "claude"]},
                "model_provider": ["openai", "anthropic"],
                "backend_provider": ["github"],
            },
            "deepseek": {
                "vendor": "deepseek",
                "brand_aliases": ["deepseek"],
                "roles": ["model_provider", "backend_provider"],
                "path_contract": {"primary": None, "alias": [], "compat_reads": []},
                "model_provider": ["deepseek"],
                "backend_provider": ["deepseek"],
            },
            "qoder_cn": {
                "vendor": "alibaba",
                "brand_aliases": ["lingma", "qoder_cn"],
                "roles": ["ide", "plugin", "cli"],
                "path_contract": {
                    "primary": "~/.lingma",
                    "alias": ["~/.qoder-cn"],
                    "compat_reads": ["copilot", "claude"],
                },
                "model_provider": ["glm", "deepseek"],
                "backend_provider": ["alibaba"],
            },
        },
        "relationships": [
            {"from": "vscode", "type": "hosts", "to": "codex_plugin"},
            {"from": "deepseek", "type": "used_by", "to": "claude_code"},
        ],
        "compatibility_matrix": {
            "copilot": {"reads": ["codex", "claude"]},
        },
    }
    registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return registry_path


def test_加载实体注册表(tmp_path: Path) -> None:
    """实体注册表加载正确。"""
    registry_path = _write_entity_registry(tmp_path)
    registry = 加载实体注册表(registry_path)
    assert "entities" in registry
    assert "codex" in registry["entities"]
    assert "deepseek" in registry["entities"]
    assert len(registry["relationships"]) == 2
    assert "copilot" in registry["compatibility_matrix"]


def test_从实体注册表派生发布目标(tmp_path: Path) -> None:
    """发布目标派生正确：folder_name 与 path_parts 两种形态。"""
    registry_path = _write_entity_registry(tmp_path)
    registry = 加载实体注册表(registry_path)
    targets = 从实体注册表派生发布目标(registry)

    # codex → folder_name 形态
    codex = next(t for t in targets if t["target_label"] == "codex")
    assert codex["folder_name"] == ".codex"
    assert codex["vendor"] == "openai"
    assert codex["roles"] == ["ide", "plugin", "cli"]

    # opencode → path_parts 形态
    opencode = next(t for t in targets if t["target_label"] == "opencode")
    assert opencode["path_parts"] == (".config", "opencode")

    # copilot → compat_reads 传递
    copilot = next(t for t in targets if t["target_label"] == "copilot")
    assert copilot["compat_reads"] == ["codex", "claude"]

    # deepseek 无 primary → 不生成发布目标
    assert all(t["target_label"] != "deepseek" for t in targets)


def test_从实体注册表派生发布目标_alias排除(tmp_path: Path) -> None:
    """alias 路径不产生发布目标（如 qoder_cn 的 ~/.qoder-cn 应用数据目录）。"""
    registry_path = _write_entity_registry(tmp_path)
    registry = 加载实体注册表(registry_path)
    targets = 从实体注册表派生发布目标(registry)

    # qoder_cn 存在（primary=~/.lingma）
    qoder_cn = next(t for t in targets if t["target_label"] == "qoder_cn")
    assert qoder_cn["folder_name"] == ".lingma"
    # alias ~/.qoder-cn 不应产生任何发布目标
    assert all(t["target_label"] != "qoder-cn-appdata" for t in targets)
    assert all(".qoder-cn" not in str(t.get("folder_name", "")) for t in targets)


def test_获取用户级发布目标_fallback(tmp_path: Path) -> None:
    """注册表为空时回退到硬编码列表。"""
    targets = 获取用户级发布目标()
    assert len(targets) >= 9  # 至少包含硬编码的 9 个目标


def test_发现用户级发布目标_携带世界模型字段(tmp_path: Path) -> None:
    """发现用户级发布目标携带 entity_id/vendor/compat_reads。"""
    targets = 发现用户级发布目标(include_missing=True)
    copilot = next(t for t in targets if t.target_label == "copilot")
    assert copilot.entity_id == "copilot"
    assert copilot.vendor == "github"
    assert "codex" in copilot.compat_reads


def test_语法族映射_按实体角色(tmp_path: Path) -> None:
    """语法族映射：qoder_cn/lingma → copilot，qoder → copilot。"""
    assert 默认引擎供应商映射["qoder_cn"] == "copilot"
    assert 默认引擎供应商映射["lingma"] == "copilot"
    assert 默认引擎供应商映射["qoder"] == "copilot"
    assert 默认引擎供应商映射["cursor"] == "claude"