"""计量环境配置事务。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, List

from autodokit.tools import load_json_or_py


class EconometricsRuntimeSetupEngine:
    """计量环境配置引擎。"""

    def run(
        self,
        project_root: str | Path,
        require_r: bool = True,
        require_stata: bool = False,
        python_baseline: str = "3.13",
    ) -> dict[str, Any]:
        """执行环境配置摘要生成。"""

        if not python_baseline.strip():
            raise ValueError("python_baseline 不能为空")

        root = Path(project_root).expanduser().resolve()
        runtime_dir = root / "runtime" / "econometrics"
        runtime_dir.mkdir(parents=True, exist_ok=True)

        return {
            "project_root": str(root),
            "runtime_dir": str(runtime_dir),
            "env_checklist": {
                "python_current": sys.version.split()[0],
                "python_baseline": python_baseline,
                "python_ready": sys.version.startswith(python_baseline),
                "require_r": require_r,
                "require_stata": require_stata,
                "r_ready": False,
                "stata_ready": False,
            },
            "notes": [
                "Python 环境已检测，建议使用 uv 锁定依赖。",
                "R/Stata 检测在后续运行阶段补充。",
            ],
        }


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。"""

    cfg = load_json_or_py(config_path)
    result = EconometricsRuntimeSetupEngine().run(
        project_root=str(cfg.get("project_root") or "."),
        require_r=bool(cfg.get("require_r", True)),
        require_stata=bool(cfg.get("require_stata", False)),
        python_baseline=str(cfg.get("python_baseline") or "3.13"),
    )
    output_dir = Path(str(cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError("output_dir 必须为绝对路径")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "econometrics_runtime_setup_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
