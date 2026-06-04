#!/usr/bin/env python3
"""AOB 同步撤销专用脚本。

用法：
    # 列出所有可撤销会话
    python -m autodokit.tools.atomic.aob_runtime.aob_undo_sync --list

    # 预览撤销（不执行）
    python -m autodokit.tools.atomic.aob_runtime.aob_undo_sync --session-id <ID> --dry-run

    # 执行撤销
    python -m autodokit.tools.atomic.aob_runtime.aob_undo_sync --session-id <ID>

    # 指定撤销数据库路径
    python -m autodokit.tools.atomic.aob_runtime.aob_undo_sync --session-id <ID> --db-path <path>

注意：
    撤销操作是幂等的——多次执行同一 session_id 的撤销不会重复回滚。
    撤销不依赖 LLM，纯确定性操作。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .aob_sync_undo import 执行撤销, 列出撤销会话, 撤销数据库文件名


def _默认数据库路径() -> Path:
    """推断默认撤销数据库路径。"""

    import os

    env_root = str(os.environ.get("AOB_REPO_ROOT", "")).strip()
    if env_root:
        return Path(env_root).expanduser().resolve() / "datastore" / "sync_undo" / 撤销数据库文件名

    here = Path(__file__).resolve()
    candidate = here.parents[5] / "autodo-lib" / "datastore" / "sync_undo" / 撤销数据库文件名
    if candidate.parent.exists():
        return candidate

    sibling = here.parents[5] / "datastore" / "sync_undo" / 撤销数据库文件名
    return sibling


def main() -> int:
    """撤销脚本主入口。"""

    parser = argparse.ArgumentParser(
        description="AOB 同步撤销脚本（幂等、不依赖 LLM）",
    )
    parser.add_argument("--session-id", default="", help="要撤销的会话 ID")
    parser.add_argument("--db-path", default="", help="撤销数据库路径（不传则自动推断）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览撤销操作，不实际执行")
    parser.add_argument("--list", action="store_true", dest="list_sessions", help="列出所有可撤销会话")
    args = parser.parse_args()

    db_path = Path(args.db_path).expanduser().resolve() if str(args.db_path).strip() else _默认数据库路径()

    if not db_path.exists():
        print(f"[ERROR] 撤销数据库不存在：{db_path}", file=sys.stderr)
        print("提示：请先执行一次同步（update-user-content），系统会自动生成撤销账本。", file=sys.stderr)
        return 1

    if args.list_sessions:
        sessions = 列出撤销会话(db_path)
        if not sessions:
            print("当前没有可撤销的会话。")
            return 0
        print(json.dumps(sessions, ensure_ascii=False, indent=2))
        return 0

    if not str(args.session_id).strip():
        print("[ERROR] 请指定 --session-id 或使用 --list 查看可用会话", file=sys.stderr)
        return 1

    result = 执行撤销(
        db_path,
        session_id=str(args.session_id).strip(),
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PASS", "DRY_RUN"} else 1


if __name__ == "__main__":
    sys.exit(main())
