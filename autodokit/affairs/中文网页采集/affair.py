"""中文网页采集事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result


def plan_cn_web_acquisition(query: str, seed_urls: list[str], output_dir: str | Path) -> dict[str, Any]:
    """规划中文网页采集动作。"""

    if not query.strip():
        raise ValueError("query 不能为空")
    normalized_urls = [url.strip() for url in seed_urls if url.strip()]
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "status": "PASS",
        "mode": "cn-web-acquisition",
        "result": {
            "query": query,
            "seed_urls": normalized_urls,
            "output_dir": str(out_dir),
            "plan": [
                {"step": 1, "action": "页面访问与可达性检查", "target_count": len(normalized_urls)},
                {"step": 2, "action": "正文抽取与结构化字段映射", "target_count": len(normalized_urls)},
                {"step": 3, "action": "结果落盘与去重", "target_path": str(out_dir / "cn_web_acquisition_results.json")}
            ]
        }
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = plan_cn_web_acquisition(
        query=str(raw_cfg.get("query") or ""),
        seed_urls=list(raw_cfg.get("seed_urls") or []),
        output_dir=str(raw_cfg.get("output_dir") or config_path.parent),
    )
    return write_affair_json_result(raw_cfg, config_path, "cn_web_acquisition_result.json", result)
