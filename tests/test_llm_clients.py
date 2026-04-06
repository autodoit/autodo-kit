"""阿里百炼客户端配置测试。"""

from __future__ import annotations

import json
from pathlib import Path

from autodokit.tools.llm_clients import _resolve_model_and_backend, load_api_key_from_config


def test_load_api_key_from_config_should_accept_env_var_alias_and_secrets_file(tmp_path: Path, monkeypatch) -> None:
    """应兼容 env_var_name 调用方式，并能通过 secrets_file 读取密钥。"""

    secrets_path = (tmp_path / "bailian_api_key.txt").resolve()
    secrets_path.write_text("DASHSCOPE_API_KEY=sk-demo\n", encoding="utf-8")

    config_path = (tmp_path / "config.json").resolve()
    config_path.write_text(
        json.dumps({"secrets_file": str(secrets_path)}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    api_key = load_api_key_from_config(
        config_path=config_path,
        env_var_name="DASHSCOPE_API_KEY",
    )

    assert api_key == "sk-demo"


def test_resolve_model_and_backend_should_route_explicit_vision_model_to_compatible_backend() -> None:
    """显式视觉模型在 manual mode 下也应默认走兼容后端。"""

    model, backend, _base_url, routing_info = _resolve_model_and_backend(
        model="qwen3-vl-plus",
        sdk_backend=None,
        base_url=None,
        region="cn-beijing",
        affair_name="阿里百炼多模态 PDF 单篇解析",
        route_hints={"task_type": "vision", "need_vision": True},
    )

    assert model == "qwen3-vl-plus"
    assert backend == "openai-compatible"
    assert routing_info["mode"] == "manual"
    assert routing_info["task_type"] == "vision"