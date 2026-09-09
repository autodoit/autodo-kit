"""本地会话的 JSON-first 索引化归档与按需检索工具（v2）。

v2 相对 v1（``chat_session_index_tools``）的核心变化：

1. **归档真相源改为专有 JSON**：``session_storage/session_<id>.json`` 取代
   带 HTML 锚点的 Markdown（``session_storage/session_<id>.md``），按问答对
   （Pair）分段存储，``format`` + ``schema_version`` 标记便于版本化演进。
2. **pair 定位不再依赖正则锚点切割**：``pair_index.json`` 条目从
   ``md_path + md_anchor`` 改为 ``storage_path``，读取时直接在归档 JSON 的
   ``pairs`` 数组中按 ``pair_id`` 建字典定位，无锚点污染误切风险。
3. **索引重建幂等**：``rebuild_indexes`` 直接读取 ``session_storage/*.json``
   重建双层索引，不再用正则反向解析 Markdown。
4. **单一真相源**：Pair 正文只在归档 JSON 中出现一次，``index_db`` 只存指针。

对外 API 与 v1 对齐（``import_markdown`` / ``get_pair_info`` /
``search_by_tag`` / ``search_by_summary`` / ``get_session_inherit_chain`` /
``rebuild_indexes`` / ``list_session_pairs``），消费端（``chat_retrieve.py``、
``attach_manager.py``）可直接切换 import 使用。

归档 JSON 结构（``ao-session-storage`` v2）：

.. code-block:: json

    {
      "format": "ao-session-storage",
      "schema_version": 2,
      "session_id": "session_...",
      "title": "...",
      "created_at": "...",
      "tags": ["..."],
      "source_name": "...",
      "parent_session_id": "",
      "fork_at_pair_id": "",
      "inherit_rule": "snapshot",
      "pairs": [
        {
          "pair_id": "pair_...",
          "pair_index_in_session": 1,
          "title": "...",
          "brief_summary": "...",
          "user": {"local_turn": 1, "role": "user", "content": "..."},
          "assistant": {"local_turn": 2, "role": "assistant", "content": "..."}
        }
      ]
    }

用法（需 autodo-kit 虚拟环境）：

    from autodokit.tools.chat_session_index_tools_v2 import ChatSessionStoreV2

    store = ChatSessionStoreV2("会话_索引库")
    result = store.import_markdown("会话.md", tags=["项目A"])
    pair = store.get_pair_info(result["pair_ids"][0])
    sessions = store.search_by_tag("项目A")
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# v1 模块中的纯函数与数据结构与存储格式无关，直接复用，避免重复实现。
from autodokit.tools.chat_session_index_tools import (
    QAPair,
    SingleMessage,
    _brief,
    _new_id,
    _now,
    _read_json,
    _write_json,
    build_pairs,
    parse_markdown_conversation,
)

STORAGE_FORMAT = "ao-session-storage"
STORAGE_SCHEMA_VERSION = 2

USER_BLOCK_MARK = "### 用户"
ASSISTANT_BLOCK_MARK = "### 助手"


def _render_storage_document(
    *,
    session_id: str,
    title: str,
    tags: list[str],
    source_name: str,
    created_at: str,
    pairs: list[QAPair],
    parent_session_id: str | None,
    fork_at_pair_id: str | None,
) -> dict[str, Any]:
    """把问答对列表渲染为专有归档 JSON 文档（唯一原文真相源）。

    Args:
        session_id: 会话 ID。
        title: 会话标题。
        tags: 会话标签。
        source_name: 来源文件名。
        created_at: 创建时间（ISO 字符串）。
        pairs: 问答对列表。
        parent_session_id: 父会话 ID（分支会话才有）。
        fork_at_pair_id: 分叉节点 PairID（分支会话才有）。

    Returns:
        归档 JSON 文档（``format`` + ``schema_version`` 标记，pair 分段存储）。
    """

    return {
        "format": STORAGE_FORMAT,
        "schema_version": STORAGE_SCHEMA_VERSION,
        "session_id": session_id,
        "title": title or session_id,
        "created_at": created_at,
        "tags": tags,
        "source_name": source_name,
        "inherit_rule": "snapshot",
        "parent_session_id": parent_session_id or "",
        "fork_at_pair_id": fork_at_pair_id or "",
        "pairs": [
            {
                "pair_id": pair.pair_id,
                "pair_index_in_session": pair.pair_index_in_session,
                "title": pair.title,
                "brief_summary": pair.brief_summary,
                "user": {
                    "local_turn": pair.msg_user.local_turn,
                    "role": "user",
                    "content": pair.msg_user.content,
                },
                "assistant": {
                    "local_turn": pair.msg_assistant.local_turn,
                    "role": "assistant",
                    "content": pair.msg_assistant.content,
                },
            }
            for pair in pairs
        ],
    }


def _pair_to_index_entry(pair: QAPair, relative_storage_path: str) -> dict[str, Any]:
    """把单个问答对转换为 pair_index 条目（v2：只存 storage_path 指针）。"""
    return {
        "pair_id": pair.pair_id,
        "session_id": pair.session_id,
        "pair_index_in_session": pair.pair_index_in_session,
        "title": pair.title,
        "brief_summary": pair.brief_summary,
        "storage_path": relative_storage_path,
        "user_turn": pair.msg_user.local_turn,
        "assistant_turn": pair.msg_assistant.local_turn,
    }


def _storage_to_session_entry(
    doc: dict[str, Any],
) -> dict[str, Any]:
    """从归档 JSON 文档生成 session_index 条目（v2：storage_path 指针）。"""
    pair_ids = [pair["pair_id"] for pair in doc.get("pairs", [])]
    return {
        "session_id": doc["session_id"],
        "title": doc.get("title") or doc["session_id"],
        "source_name": doc.get("source_name", ""),
        "created_at": doc.get("created_at", ""),
        "tags": doc.get("tags", []),
        "storage_path": f"session_storage/{doc['session_id']}.json",
        "total_qa_pairs": len(pair_ids),
        "all_pair_ids": pair_ids,
        "latest_pair_id": pair_ids[-1] if pair_ids else None,
        "fork_type": "single" if doc.get("parent_session_id") else "none",
        "parent_session_id": doc.get("parent_session_id", ""),
        "fork_at_pair_id": doc.get("fork_at_pair_id", ""),
        "inherit_rule": doc.get("inherit_rule", "snapshot"),
        "children_session_ids": [],
        "attachments": [],
    }


def _split_user_assistant(content: str) -> tuple[str, str]:
    """把 ``get_pair_info`` 的 content 片段拆分为用户 / 助手正文。

    Args:
        content: 含 ``### 用户`` / ``### 助手`` 标记的片段。

    Returns:
        ``(user_block, assistant_block)``；标记缺失时返回 ``("", content)``。
    """

    user_pos = content.find(USER_BLOCK_MARK)
    assistant_pos = content.find(ASSISTANT_BLOCK_MARK)
    if user_pos >= 0 and assistant_pos > user_pos:
        user_block = content[user_pos + len(USER_BLOCK_MARK):assistant_pos].strip()
        assistant_block = content[assistant_pos + len(ASSISTANT_BLOCK_MARK):].strip()
        return user_block, assistant_block
    return "", content


class ChatSessionStoreV2:
    """管理一个独立的会话归档仓库（v2：JSON-first 存储）。

    对外 API 与 v1 ``ChatSessionStore`` 对齐，消费端可直接切换 import；
    内部真相源为 ``session_storage/session_<id>.json``。
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.storage_dir = self.root / "session_storage"
        self.index_dir = self.root / "index_db"
        self.session_index_path = self.index_dir / "session_index.json"
        self.pair_index_path = self.index_dir / "pair_index.json"

    def initialize(self) -> None:
        """确保仓库目录与索引文件存在。"""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        if not self.session_index_path.exists():
            _write_json(self.session_index_path, {})
        if not self.pair_index_path.exists():
            _write_json(self.pair_index_path, {})

    def import_markdown(
        self,
        source: str | Path,
        *,
        tags: Iterable[str] = (),
        session_id: str | None = None,
        title: str | None = None,
        parent_session_id: str | None = None,
        fork_at_pair_id: str | None = None,
    ) -> dict[str, Any]:
        """从通用格式 Markdown 导入会话并生成双层索引。

        Args:
            source: 通用会话格式（``## 用户`` / ``## 助手``）Markdown 文件。
            tags: 会话标签。
            session_id: 显式会话 ID；为空自动生成。
            title: 会话标题；为空取源文件主名。
            parent_session_id: 父会话 ID（分支会话）。
            fork_at_pair_id: 分叉节点 PairID（分支会话）。

        Returns:
            汇总结果：``session_id`` / ``pair_ids`` / ``storage_path``。
        """

        source_path = Path(source).expanduser().resolve()
        messages = parse_markdown_conversation(source_path.read_text(encoding="utf-8-sig"))
        return self.import_messages(
            messages,
            source_name=source_path.name,
            tags=tags,
            session_id=session_id,
            title=title or source_path.stem,
            parent_session_id=parent_session_id,
            fork_at_pair_id=fork_at_pair_id,
        )

    @staticmethod
    def _pair_dict_to_qapair(pair: dict[str, Any], *, session_id: str) -> QAPair:
        """把归档 JSON 里已有的 Pair 字典恢复为 QAPair，供差异比对与重写。"""
        user = pair.get("user", {})
        assistant = pair.get("assistant", {})
        title = pair.get("title", "")
        brief = pair.get("brief_summary", "")
        return QAPair(
            pair_id=str(pair.get("pair_id", _new_id("pair"))),
            session_id=session_id,
            pair_index_in_session=int(pair.get("pair_index_in_session", 0)),
            title=title,
            brief_summary=brief,
            msg_user=SingleMessage(
                local_turn=int((user or {}).get("local_turn", 0)),
                role="user",
                content=str((user or {}).get("content", "")),
            ),
            msg_assistant=SingleMessage(
                local_turn=int((assistant or {}).get("local_turn", 0)),
                role="assistant",
                content=str((assistant or {}).get("content", "")),
            ),
            md_anchor="",
        )

    def find_existing_session(
        self,
        *,
        source_name: str = "",
        title: str = "",
    ) -> str | None:
        """在仓库中查找与来源/标题匹配的已有会话 ID（auto 模式用）。

        匹配优先级：``source_name`` 完全一致 → ``title`` 完全一致。
        仅当两个条件都未提供时，才以「仓库中仅有一个会话」视为同一会话
        （方案 A 下索引库目录名即会话主名，同目录即同会话）。

        Args:
            source_name: 来源文件名（如 ``xxx.md``）。
            title: 会话标题。

        Returns:
            匹配到的 session_id；未匹配返回 None。
        """
        sessions = _read_json(self.session_index_path)
        if not sessions:
            return None
        if source_name:
            for sid, sess in sessions.items():
                if sess.get("source_name") == source_name:
                    return sid
        if title:
            for sid, sess in sessions.items():
                if (sess.get("title") or "") == title:
                    return sid
        if not source_name and not title and len(sessions) == 1:
            return next(iter(sessions))
        return None

    def reconcile_source_messages(
        self,
        messages: list[dict[str, str]],
        *,
        session_id: str,
        mode: str = "focus",
        title: str | None = None,
        tags: Iterable[str] = (),
        source_name: str = "source.md",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """按模式把消息源与现有会话归档做差异更新。

        模式：
            - ``focus``：以索引顺序做“增量更新”，只更新已变更/新增的问答对；无差异时返回 skipped
            - ``append``：仅向现有会话追加新增问答对，不改已有内容
            - ``create``：创建新会话（兼容外部脚本入口）

        Args:
            dry_run: 为 True 时只计算差异并返回预览，不写归档与索引。
        """
        if mode not in {"focus", "append", "create"}:
            raise ValueError(f"不支持的 mode: {mode}")

        self.initialize()
        sessions = _read_json(self.session_index_path)
        if mode == "create":
            if dry_run:
                preview_pairs = build_pairs(messages, session_id=session_id or "preview")
                return {
                    "status": "created",
                    "session_id": session_id,
                    "pair_ids": [pair.pair_id for pair in preview_pairs],
                    "storage_path": None,
                    "dry_run": True,
                }
            return self.import_messages(
                messages,
                source_name=source_name,
                tags=tags,
                session_id=session_id,
                title=title or source_name,
            )

        if session_id not in sessions:
            raise KeyError(f"会话不存在，无法 reconcile: {session_id}")

        existing_doc = self._load_storage(sessions[session_id]["storage_path"])
        old_pairs = existing_doc.get("pairs", [])
        new_pairs = build_pairs(messages, session_id=session_id)
        if not new_pairs:
            raise ValueError("未找到完整的“用户 -> 助手”问答组")

        normalized_tags = sorted({str(tag).strip() for tag in tags if str(tag).strip()})
        if not normalized_tags:
            normalized_tags = list(sessions[session_id].get("tags", []))

        changes = {"added": 0, "modified": 0, "removed": 0}
        merged_pairs: list[QAPair] = []

        if mode == "append":
            for index, pair in enumerate(new_pairs):
                if index < len(old_pairs):
                    old_pair = old_pairs[index]
                    if old_pair.get("user", {}).get("content") == pair.msg_user.content and old_pair.get("assistant", {}).get("content") == pair.msg_assistant.content:
                        merged_pairs.append(self._pair_dict_to_qapair(old_pair, session_id=session_id))
                    else:
                        # 追加模式下保留原有问答对，若头部内容已变更则按 focus 语义处理
                        merged_pairs.append(pair)
                        changes["modified"] += 1
                else:
                    merged_pairs.append(pair)
                    changes["added"] += 1
            changes["removed"] = max(0, len(old_pairs) - len(new_pairs))
            merged_pairs = merged_pairs[: len(new_pairs)]
        else:
            for index, pair in enumerate(new_pairs):
                if index < len(old_pairs):
                    old_pair = old_pairs[index]
                    if old_pair.get("user", {}).get("content") == pair.msg_user.content and old_pair.get("assistant", {}).get("content") == pair.msg_assistant.content:
                        merged_pairs.append(self._pair_dict_to_qapair(old_pair, session_id=session_id))
                    else:
                        merged_pairs.append(pair)
                        changes["modified"] += 1
                else:
                    merged_pairs.append(pair)
                    changes["added"] += 1
            changes["removed"] = max(0, len(old_pairs) - len(new_pairs))
            # 丢弃尾部超出的旧对，保证 focus 模式按新源为准
            merged_pairs = merged_pairs[: len(new_pairs)]

        if changes["added"] == 0 and changes["modified"] == 0 and changes["removed"] == 0:
            return {
                "status": "skipped",
                "session_id": session_id,
                "changes": changes,
                "pair_ids": [pair.pair_id for pair in merged_pairs],
                "dry_run": dry_run,
            }

        if dry_run:
            return {
                "status": "updated",
                "session_id": session_id,
                "changes": changes,
                "pair_ids": [pair.pair_id for pair in merged_pairs],
                "dry_run": True,
            }

        updated_title = title or sessions[session_id].get("title") or source_name.rstrip(".md")
        doc = _render_storage_document(
            session_id=session_id,
            title=updated_title,
            tags=normalized_tags,
            source_name=source_name,
            created_at=sessions[session_id].get("created_at", _now()),
            pairs=merged_pairs,
            parent_session_id=sessions[session_id].get("parent_session_id", ""),
            fork_at_pair_id=sessions[session_id].get("fork_at_pair_id", ""),
        )
        storage_path = self.storage_dir / f"{session_id}.json"
        _write_json(storage_path, doc)
        relative_storage = str(storage_path.relative_to(self.root)).replace("\\", "/")

        pair_index = _read_json(self.pair_index_path)
        keep_pair_ids = {pair["pair_id"] for pair in doc.get("pairs", [])}
        for stale_id in list(pair_index.keys()):
            if stale_id in sessions[session_id].get("all_pair_ids", []) and stale_id not in keep_pair_ids:
                pair_index.pop(stale_id, None)
        for pair in doc.get("pairs", []):
            pair_index[pair["pair_id"]] = {
                "pair_id": pair["pair_id"],
                "session_id": session_id,
                "pair_index_in_session": pair["pair_index_in_session"],
                "title": pair["title"],
                "brief_summary": pair["brief_summary"],
                "storage_path": relative_storage,
                "user_turn": pair["user"]["local_turn"],
                "assistant_turn": pair["assistant"]["local_turn"],
            }
        sessions[session_id] = _storage_to_session_entry(doc)
        sessions[session_id]["tags"] = normalized_tags
        sessions[session_id]["title"] = updated_title
        sessions[session_id]["source_name"] = source_name
        _write_json(self.pair_index_path, pair_index)
        _write_json(self.session_index_path, sessions)

        return {
            "status": "updated",
            "session_id": session_id,
            "changes": changes,
            "pair_ids": [pair["pair_id"] for pair in doc.get("pairs", [])],
            "storage_path": str(storage_path),
        }

    def import_messages(
        self,
        messages: list[dict[str, str]],
        *,
        source_name: str,
        tags: Iterable[str] = (),
        session_id: str | None = None,
        title: str = "",
        parent_session_id: str | None = None,
        fork_at_pair_id: str | None = None,
    ) -> dict[str, Any]:
        """从消息列表导入会话：切问答对 → 写归档 JSON → 更新双层索引。

        Args:
            messages: ``[{"role": "user"|"assistant", "content": "..."}]`` 列表。
            source_name: 来源文件名（记录用）。
            tags: 会话标签。
            session_id: 显式会话 ID；为空自动生成。
            title: 会话标题。
            parent_session_id: 父会话 ID（分支会话）。
            fork_at_pair_id: 分叉节点 PairID（分支会话）。

        Returns:
            汇总结果：``session_id`` / ``pair_ids`` / ``storage_path``。

        Raises:
            ValueError: session_id 已存在 / 缺少完整问答组 / 分叉参数不匹配。
            KeyError: 父会话不存在或分叉 PairID 不属于父会话。
        """

        self.initialize()
        normalized_tags = sorted({str(tag).strip() for tag in tags if str(tag).strip()})
        session_id = session_id or _new_id("session")
        sessions = _read_json(self.session_index_path)
        pairs_index = _read_json(self.pair_index_path)
        if session_id in sessions:
            raise ValueError(f"session_id 已存在: {session_id}")
        if parent_session_id and parent_session_id not in sessions:
            raise KeyError(f"父会话不存在: {parent_session_id}")
        if bool(parent_session_id) != bool(fork_at_pair_id):
            raise ValueError("parent_session_id 与 fork_at_pair_id 必须同时提供")

        pairs = build_pairs(messages, session_id=session_id)
        if not pairs:
            raise ValueError("未找到完整的“用户 -> 助手”问答组")
        if fork_at_pair_id and fork_at_pair_id not in sessions[parent_session_id]["all_pair_ids"]:
            raise KeyError(f"分叉 PairID 不属于父会话: {fork_at_pair_id}")

        created_at = _now()
        doc = _render_storage_document(
            session_id=session_id,
            title=title or session_id,
            tags=normalized_tags,
            source_name=source_name,
            created_at=created_at,
            pairs=pairs,
            parent_session_id=parent_session_id,
            fork_at_pair_id=fork_at_pair_id,
        )
        storage_path = self.storage_dir / f"{session_id}.json"
        _write_json(storage_path, doc)
        relative_storage = str(storage_path.relative_to(self.root)).replace("\\", "/")

        for pair in pairs:
            pairs_index[pair.pair_id] = _pair_to_index_entry(pair, relative_storage)
        sessions[session_id] = _storage_to_session_entry(doc)
        if parent_session_id:
            sessions[parent_session_id]["children_session_ids"] = sorted(
                set(sessions[parent_session_id].get("children_session_ids", [])) | {session_id}
            )
        _write_json(self.pair_index_path, pairs_index)
        _write_json(self.session_index_path, sessions)
        return {
            "session_id": session_id,
            "pair_ids": [pair.pair_id for pair in pairs],
            "storage_path": str(storage_path),
        }

    def reconcile_session(self, *, source: str | Path, session_id: str, mode: str = "focus") -> dict[str, Any]:
        """从源文件路径直接协调会话更新（脚本入口薄封装）。"""
        source_path = Path(source).expanduser().resolve()
        messages = parse_markdown_conversation(source_path.read_text(encoding="utf-8-sig"))
        return self.reconcile_source_messages(
            messages,
            session_id=session_id,
            mode=mode,
            title=source_path.stem,
            tags=[],
            source_name=source_path.name,
        )

    def _load_storage(self, relative_path: str) -> dict[str, Any]:
        """读取归档 JSON 并返回带 ``pairs_by_id`` 字典的文档。

        Args:
            relative_path: 相对仓库根的归档 JSON 路径（如 ``session_storage/xxx.json``）。

        Returns:
            归档文档（含 ``pairs_by_id`` 便捷索引）。

        Raises:
            ValueError: 路径越界或文件不是 v2 归档 JSON。
        """

        path = (self.root / relative_path).resolve()
        if self.root not in path.parents:
            raise ValueError("归档 JSON 路径必须位于会话仓库内")
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"归档 JSON 无法解析: {path}") from exc
        if not isinstance(doc, dict) or doc.get("format") != STORAGE_FORMAT:
            raise ValueError(f"不是 v2 会话归档 JSON（format={STORAGE_FORMAT!r}）: {path}")
        pairs_by_id = {pair["pair_id"]: pair for pair in doc.get("pairs", [])}
        return {**doc, "pairs_by_id": pairs_by_id}

    def get_pair_info(self, pair_id: str) -> dict[str, Any] | None:
        """按 PairID 读取单组问答（只取该组，不加载完整会话）。

        Args:
            pair_id: 问答对 PairID。

        Returns:
            问答对信息（含 ``content`` 字段：``### 用户`` / ``### 助手`` 标记
            组合片段，兼容 v1 消费端如附件溯源、LLM 批量精读）；
            不存在返回 None。
        """

        entry = _read_json(self.pair_index_path).get(pair_id)
        if entry is None:
            return None
        doc = self._load_storage(entry["storage_path"])
        pair = doc.get("pairs_by_id", {}).get(pair_id)
        if pair is None:
            return None
        user_block = pair.get("user", {}).get("content", "")
        assistant_block = pair.get("assistant", {}).get("content", "")
        return {
            **entry,
            "content": f"{USER_BLOCK_MARK}\n{user_block}\n\n{ASSISTANT_BLOCK_MARK}\n{assistant_block}",
        }

    def search_by_tag(self, keyword: str) -> list[dict[str, Any]]:
        """按标签检索会话。"""
        needle = keyword.casefold().strip()
        return [
            item
            for item in _read_json(self.session_index_path).values()
            if needle in " ".join(item.get("tags", [])).casefold()
        ]

    def search_by_summary(self, keyword: str) -> list[dict[str, Any]]:
        """按关键词在问答对标题/简介里模糊检索。"""
        needle = keyword.casefold().strip()
        return [
            item
            for item in _read_json(self.pair_index_path).values()
            if needle in f"{item['title']}\n{item['brief_summary']}".casefold()
        ]

    def get_session_inherit_chain(self, session_id: str) -> list[dict[str, Any]]:
        """追溯单继承分支链（每个会话只保留分叉前内容）。

        Args:
            session_id: 会话 ID。

        Returns:
            从根到当前会话的链，每个节点含 ``inherited_pair_ids`` 与 ``pairs``。

        Raises:
            KeyError: 会话不存在。
            ValueError: 检测到会话继承环。
        """

        sessions = _read_json(self.session_index_path)
        pairs = _read_json(self.pair_index_path)
        result: list[dict[str, Any]] = []
        current_id = session_id
        visited: set[str] = set()
        while current_id:
            if current_id in visited:
                raise ValueError(f"检测到会话继承环: {current_id}")
            visited.add(current_id)
            session = sessions.get(current_id)
            if not session:
                raise KeyError(f"会话不存在: {current_id}")
            result.append(session)
            current_id = session.get("parent_session_id", "")
        result.reverse()
        for index, session in enumerate(result[:-1]):
            child = result[index + 1]
            cutoff = child["fork_at_pair_id"]
            session["inherited_pair_ids"] = session["all_pair_ids"][: session["all_pair_ids"].index(cutoff) + 1]
        result[-1]["inherited_pair_ids"] = result[-1]["all_pair_ids"]
        for session in result:
            session["pairs"] = [pairs[pair_id] for pair_id in session["inherited_pair_ids"]]
        return result

    def rebuild_indexes(self) -> dict[str, int]:
        """从 ``session_storage/*.json`` 幂等重建双层索引（先备份旧索引）。

        Returns:
            汇总：``sessions`` / ``pairs`` / ``backup``（备份目录）。
        """

        self.initialize()
        backup_dir = self.index_dir / f"backup_{datetime.now():%Y%m%d%H%M%S}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.session_index_path, backup_dir / self.session_index_path.name)
        shutil.copy2(self.pair_index_path, backup_dir / self.pair_index_path.name)

        sessions: dict[str, Any] = {}
        pairs: dict[str, Any] = {}
        for storage_path in sorted(self.storage_dir.glob("*.json")):
            try:
                doc = json.loads(storage_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(doc, dict) or doc.get("format") != STORAGE_FORMAT:
                continue
            sid = doc.get("session_id")
            if not sid:
                continue
            sessions[sid] = _storage_to_session_entry(doc)
            for pair in doc.get("pairs", []):
                pair_id = pair.get("pair_id")
                if not pair_id:
                    continue
                pairs[pair_id] = {
                    "pair_id": pair_id,
                    "session_id": sid,
                    "pair_index_in_session": pair.get("pair_index_in_session"),
                    "title": pair.get("title", ""),
                    "brief_summary": pair.get("brief_summary", ""),
                    "storage_path": f"session_storage/{sid}.json",
                    "user_turn": (pair.get("user") or {}).get("local_turn"),
                    "assistant_turn": (pair.get("assistant") or {}).get("local_turn"),
                }

        for session in sessions.values():
            session["children_session_ids"] = []
        for session_id, session in sessions.items():
            parent = session.get("parent_session_id")
            if parent in sessions:
                sessions[parent]["children_session_ids"].append(session_id)

        # 补回附件元信息：attachments/manifest.json 是附件独立真相源（数组格式），
        # 直接 json.loads（不走 _read_json，其要求 JSON 对象）。
        manifest_path = self.root / "attachments" / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (ValueError, json.JSONDecodeError, OSError):
                manifest = []
            for entry in manifest if isinstance(manifest, list) else []:
                sid = entry.get("session_id")
                if sid in sessions:
                    sessions[sid].setdefault("attachments", []).append(entry)

        _write_json(self.session_index_path, sessions)
        _write_json(self.pair_index_path, pairs)
        return {"sessions": len(sessions), "pairs": len(pairs), "backup": str(backup_dir)}

    def export_readable_markdown(
        self,
        session_id: str,
        *,
        output: str | Path | None = None,
    ) -> str:
        """把归档 JSON 渲染为人类可读 Markdown（可选导出，不进真相源）。

        只作为人类在 Obsidian 等处查看的可读视图；检索/精读仍以 JSON 为准。

        Args:
            session_id: 会话 ID。
            output: 可选输出路径；为空只返回文本不落盘。

        Returns:
            渲染的 Markdown 文本。

        Raises:
            KeyError: 会话不存在。
        """

        sessions = _read_json(self.session_index_path)
        session = sessions.get(session_id)
        if not session:
            raise KeyError(f"会话不存在: {session_id}")
        doc = self._load_storage(session["storage_path"])
        lines = [
            f"# {doc.get('title') or session_id}",
            "",
            f"- SessionID: `{session_id}`",
            f"- 问答对数: {len(doc.get('pairs', []))}",
            f"- 标签: {', '.join(doc.get('tags', [])) or '-'}",
            "",
        ]
        for pair in doc.get("pairs", []):
            lines.extend(
                [
                    f"## Pair {pair.get('pair_index_in_session')}: {pair.get('title', '')}",
                    "",
                    f"### 用户（轮次 {pair.get('user', {}).get('local_turn', '')}）",
                    "",
                    pair.get("user", {}).get("content", ""),
                    "",
                    f"### 助手（轮次 {pair.get('assistant', {}).get('local_turn', '')}）",
                    "",
                    pair.get("assistant", {}).get("content", ""),
                    "",
                ]
            )
        text = "\n".join(lines).rstrip() + "\n"
        if output:
            output_path = Path(output).expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(text, encoding="utf-8")
        return text


def list_session_pairs(store: ChatSessionStoreV2, session_id: str) -> list[dict[str, Any]]:
    """列出某会话的全部问答对（只看 title/brief，不读全文）。

    Args:
        store: v2 会话仓库。
        session_id: 会话 ID。

    Returns:
        问答对轻量列表（pair_id / title / brief_summary / 轮次）。

    Raises:
        KeyError: 会话不存在。
    """

    sessions = _read_json(store.session_index_path)
    pairs = _read_json(store.pair_index_path)
    session = sessions.get(session_id)
    if not session:
        raise KeyError(f"会话不存在: {session_id}")
    result: list[dict[str, Any]] = []
    for pair_id in session.get("all_pair_ids", []):
        entry = pairs.get(pair_id)
        if entry:
            result.append(
                {
                    "pair_id": pair_id,
                    "pair_index_in_session": entry.get("pair_index_in_session"),
                    "title": entry.get("title", ""),
                    "brief_summary": entry.get("brief_summary", ""),
                    "user_turn": entry.get("user_turn"),
                    "assistant_turn": entry.get("assistant_turn"),
                }
            )
    return result


def import_chat_session_markdown_v2(
    store_root: str | Path,
    source: str | Path,
    *,
    tags: Iterable[str] = (),
    session_id: str | None = None,
    mode: str = "create",
) -> dict[str, Any]:
    """将导出的 Markdown 会话入库并生成双层索引（v2 公开入口）。

    支持：``create``（默认新建）、``focus`` / ``append``（在现有 ``session_id`` 上做差异更新）。
    """
    store = ChatSessionStoreV2(store_root)
    if mode in {"focus", "append"} and session_id:
        messages = parse_markdown_conversation(Path(source).expanduser().resolve().read_text(encoding="utf-8-sig"))
        return store.reconcile_source_messages(messages, session_id=session_id, mode=mode)
    return store.import_markdown(source, tags=tags, session_id=session_id)


def get_chat_pair_info_v2(store_root: str | Path, pair_id: str) -> dict[str, Any] | None:
    """按 PairID 读取单组问答，不会加载完整会话（v2 公开入口）。"""
    return ChatSessionStoreV2(store_root).get_pair_info(pair_id)


def main() -> None:
    """命令行入口：import / pair / search / chain / list / rebuild / export-readable。"""
    parser = argparse.ArgumentParser(description="超长会话索引化管理与检索（v2：JSON 归档）")
    parser.add_argument("--store", required=True, help="会话仓库目录")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("import")
    ingest.add_argument("source")
    ingest.add_argument("--tag", action="append", default=[])

    query = subparsers.add_parser("pair")
    query.add_argument("pair_id")

    search = subparsers.add_parser("search")
    search.add_argument("keyword")
    search.add_argument("--by", choices=("tag", "summary"), default="summary")

    chain = subparsers.add_parser("chain")
    chain.add_argument("session_id")

    list_p = subparsers.add_parser("list")
    list_p.add_argument("session_id")

    rebuild_p = subparsers.add_parser("rebuild")
    rebuild_p.add_argument("--export-readable", dest="export_session", default="", help="可选：重建后导出可读 MD 的会话 ID")

    args = parser.parse_args()
    store = ChatSessionStoreV2(args.store)
    if args.command == "import":
        result: Any = store.import_markdown(args.source, tags=args.tag)
    elif args.command == "pair":
        result = store.get_pair_info(args.pair_id)
    elif args.command == "search":
        result = store.search_by_tag(args.keyword) if args.by == "tag" else store.search_by_summary(args.keyword)
    elif args.command == "chain":
        result = store.get_session_inherit_chain(args.session_id)
    elif args.command == "list":
        result = list_session_pairs(store, args.session_id)
    else:
        result = store.rebuild_indexes()
    print(json.dumps(result, ensure_ascii=False, indent=2) if not isinstance(result, str) else result)


if __name__ == "__main__":
    main()
