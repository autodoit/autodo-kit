"""中文本地资源管理事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result


def manage_local_library(
    root_dir: str | Path,
    bib_dir_name: str = "bib",
    attachments_dir_name: str = "attachments",
    raw_data_dir_name: str = "raw_data",
) -> dict[str, Any]:
    """初始化本地资源目录结构。"""

    if not bib_dir_name.strip() or not attachments_dir_name.strip() or not raw_data_dir_name.strip():
        raise ValueError("目录名不能为空")

    base = Path(root_dir).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    created_dirs: list[str] = []
    for name in (bib_dir_name, attachments_dir_name, raw_data_dir_name):
        path = base / name
        path.mkdir(parents=True, exist_ok=True)
        created_dirs.append(str(path))
    return {
        "status": "PASS",
        "mode": "cn-local-library-manager",
        "result": {
            "root_dir": str(base),
            "created_dirs": created_dirs,
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = manage_local_library(
        root_dir=str(raw_cfg.get("root_dir") or raw_cfg.get("project_root") or "."),
        bib_dir_name=str(raw_cfg.get("bib_dir_name") or "bib"),
        attachments_dir_name=str(raw_cfg.get("attachments_dir_name") or "attachments"),
        raw_data_dir_name=str(raw_cfg.get("raw_data_dir_name") or "raw_data"),
    )
    return write_affair_json_result(raw_cfg, config_path, "cn_local_library_manager_result.json", result)
