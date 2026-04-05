#!/usr/bin/env python3
"""OpenCode 部署回归校验脚本。

该脚本用于自动化回归验证，聚焦以下检查项：
1. `scripts/deploy.py workflow` 是否可成功执行。
2. 目标项目根目录 `opencode.json` 是否保留权限字段。
3. `.opencode/agents/*.md` 的 `color` frontmatter 是否为 `#RRGGBB`。

Examples:
    在仓库根目录执行：
        python scripts/aob_tools/regression_opencode_deploy_check.py --target-root C:\\temp
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from .deploy_tool import main as deploy_main


def 构建参数解析器() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    Returns:
        argparse.ArgumentParser: 已配置好的解析器对象。
    """

    parser = argparse.ArgumentParser(description="执行 OpenCode 部署回归校验")
    parser.add_argument(
        "--target-root",
        required=True,
        help="测试项目根目录（将自动创建子项目），必须显式传入以避免硬编码敏感路径",
    )
    parser.add_argument(
        "--repo-root",
        default="",
        help="AOB 仓库根目录（若不传则自动根据环境变量或同级目录推断）",
    )
    parser.add_argument(
        "--agents-dir",
        default=".opencode/agents",
        help="目标项目中 agents 目录的相对路径，默认 '.opencode/agents'",
    )
    parser.add_argument(
        "--opencode-json",
        default="opencode.json",
        help="目标项目中 opencode 配置文件名，默认 'opencode.json'",
    )
    parser.add_argument(
        "--project-name",
        default="",
        help="测试项目名；为空时自动生成",
    )
    parser.add_argument(
        "--tags",
        default="学术研究,文档管理",
        help="部署标签列表（逗号分隔）",
    )
    return parser


def 解析_aob仓库根目录(传入路径: str) -> Path:
    """解析 AOB 仓库根目录。

    解析优先级：
    1. 参数 `--repo-root`
    2. 环境变量 `AOB_REPO_ROOT`
    3. 与 `autodo-kit` 同级的 `autodo-lib`
    4. 当前 `autodo-kit` 仓库（兜底）

    Args:
        传入路径: 命令行参数 `--repo-root`。

    Returns:
        Path: 可用的仓库根目录绝对路径。
    """

    if str(传入路径).strip():
        return Path(传入路径).expanduser().resolve()

    env_root = os.environ.get("AOB_REPO_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    kit_root = Path(__file__).resolve().parents[4]
    sibling_aob = kit_root.parent / "autodo-lib"
    if sibling_aob.exists():
        return sibling_aob.resolve()

    return kit_root.resolve()


def 读取_frontmatter_color(agent_file: Path) -> str | None:
    """读取 agent 文件 frontmatter 中的 `color` 字段。

    Args:
        agent_file: agent Markdown 文件路径。

    Returns:
        str | None: 颜色值；若未声明则返回 `None`。
    """

    text = agent_file.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    frontmatter_text = parts[1]
    color_match = re.search(r"^\s*color\s*:\s*\"?([^\"\n]+)\"?\s*$", frontmatter_text, flags=re.MULTILINE)
    if not color_match:
        return None
    return color_match.group(1).strip()


def 校验项目配置(project_root: Path, opencode_json_file: Path, agents_dir: Path) -> None:
    """校验部署产物中的关键配置。

    Args:
        project_root: 目标项目根目录。
        opencode_json_file: 要校验的 opencode.json 文件路径。
        agents_dir: 要校验的 agents 目录路径。

    Raises:
        SystemExit: 任一检查失败时抛出。
    """

    if not opencode_json_file.exists():
        raise SystemExit(f"[FAIL] 缺少配置文件：{opencode_json_file}")

    payload = json.loads(opencode_json_file.read_text(encoding="utf-8"))
    permission_payload = payload.get("permission")
    if not isinstance(permission_payload, dict):
        raise SystemExit("[FAIL] opencode.json 缺少 permission 对象")

    expected_permission = {
        "external_directory": "deny",
        "bash": "ask",
        "edit": "ask",
    }
    for key, expected_value in expected_permission.items():
        actual_value = permission_payload.get(key)
        if actual_value != expected_value:
            raise SystemExit(
                f"[FAIL] permission.{key} 异常，期望={expected_value}，实际={actual_value}"
            )

    if not agents_dir.exists():
        raise SystemExit(f"[FAIL] 缺少 agents 目录：{agents_dir}")

    hex_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
    invalid_agents: list[str] = []
    for agent_file in sorted(agents_dir.glob("*.md")):
        color = 读取_frontmatter_color(agent_file)
        if color is None:
            continue
        if not hex_pattern.match(color):
            invalid_agents.append(f"{agent_file.name}:{color}")

    if invalid_agents:
        joined = ", ".join(invalid_agents)
        raise SystemExit(f"[FAIL] 检测到非十六进制 color：{joined}")

    print(f"[INFO] 校验通过：{project_root}")


def 执行部署回归(repo_root: Path, target_root: Path, project_name: str, tags: str) -> Path:
    """执行真实部署命令并返回项目目录。

    Args:
        repo_root: AOB 仓库根目录。
        target_root: 目标根目录。
        project_name: 目标项目名称。
        tags: 标签参数。

    Returns:
        Path: 生成的项目目录路径。

    Raises:
        SystemExit: 部署命令失败时抛出。
    """

    command = [
        "workflow",
        "--workflow",
        "academic",
        "--engine",
        "opencode",
        "--target",
        str(target_root),
        "--project-name",
        project_name,
        "--tags",
        tags,
    ]

    print(f"[INFO] 执行部署命令：deploy {' '.join(command)}")

    old_argv = list(sys.argv)
    old_env_repo_root = os.environ.get("AOB_REPO_ROOT")
    sys.argv = ["deploy", *command]
    os.environ["AOB_REPO_ROOT"] = str(repo_root)
    try:
        code = int(deploy_main())
    except SystemExit as exc:
        if isinstance(exc.code, int):
            code = exc.code
        elif exc.code is None:
            code = 0
        else:
            code = 1
    finally:
        sys.argv = old_argv
        if old_env_repo_root is None:
            os.environ.pop("AOB_REPO_ROOT", None)
        else:
            os.environ["AOB_REPO_ROOT"] = old_env_repo_root

    if code != 0:
        raise SystemExit(f"[FAIL] 部署命令失败，退出码={code}")

    return target_root / project_name


def main() -> int:
    """脚本主入口。

    Returns:
        int: 进程退出码。`0` 表示通过。
    """

    parser = 构建参数解析器()
    args = parser.parse_args()

    repo_root = 解析_aob仓库根目录(args.repo_root)
    target_root = Path(args.target_root).expanduser().resolve()

    project_name = str(args.project_name).strip()
    if not project_name:
        project_name = f"【写科研论文】{datetime.now().strftime('%Y%m%d%H%M%S')}-自动回归"

    project_root = 执行部署回归(
        repo_root=repo_root,
        target_root=target_root,
        project_name=project_name,
        tags=str(args.tags),
    )

    opencode_json_file = project_root / str(args.opencode_json)
    agents_dir = project_root / str(args.agents_dir)
    校验项目配置(project_root=project_root, opencode_json_file=opencode_json_file, agents_dir=agents_dir)

    print(f"[PASS] 回归通过：{project_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())