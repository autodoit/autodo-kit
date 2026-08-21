"""本地 Markdown 会话的索引化归档与按需检索工具。"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROLE_HEADING_RE = re.compile(r"^##\s+(用户|助手|user|assistant)\s*$", re.IGNORECASE)
ANCHOR_RE_TEMPLATE = r'<a\s+id=["\']{anchor}["\']\s*></a>'


@dataclass(frozen=True)
class SingleMessage:
    local_turn: int
    role: str
    content: str


@dataclass(frozen=True)
class QAPair:
    pair_id: str
    session_id: str
    pair_index_in_session: int
    title: str
    brief_summary: str
    msg_user: SingleMessage
    msg_assistant: SingleMessage
    md_anchor: str


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"索引文件必须是 JSON 对象: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class ChatSessionStore:
    """管理一个独立的会话归档仓库。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.storage_dir = self.root / "session_storage"
        self.index_dir = self.root / "index_db"
        self.session_index_path = self.index_dir / "session_index.json"
        self.pair_index_path = self.index_dir / "pair_index.json"

    def initialize(self) -> None:
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

        md_name = f"{session_id}.md"
        md_path = self.storage_dir / md_name
        md_path.write_text(render_session_markdown(session_id, title, normalized_tags, pairs, parent_session_id, fork_at_pair_id), encoding="utf-8")
        relative_md_path = str(md_path.relative_to(self.root)).replace("\\", "/")
        for pair in pairs:
            pairs_index[pair.pair_id] = pair_to_index_entry(pair, relative_md_path)
        sessions[session_id] = {
            "session_id": session_id,
            "title": title or session_id,
            "source_name": source_name,
            "created_at": _now(),
            "tags": normalized_tags,
            "md_path": relative_md_path,
            "total_qa_pairs": len(pairs),
            "all_pair_ids": [pair.pair_id for pair in pairs],
            "latest_pair_id": pairs[-1].pair_id,
            "fork_type": "single" if parent_session_id else "none",
            "parent_session_id": parent_session_id or "",
            "fork_at_pair_id": fork_at_pair_id or "",
            "inherit_rule": "snapshot",
            "children_session_ids": [],
        }
        if parent_session_id:
            sessions[parent_session_id]["children_session_ids"] = sorted(
                set(sessions[parent_session_id].get("children_session_ids", [])) | {session_id}
            )
        _write_json(self.pair_index_path, pairs_index)
        _write_json(self.session_index_path, sessions)
        return {"session_id": session_id, "pair_ids": [pair.pair_id for pair in pairs], "md_path": str(md_path)}

    def get_pair_info(self, pair_id: str) -> dict[str, Any] | None:
        entry = _read_json(self.pair_index_path).get(pair_id)
        if entry is None:
            return None
        return {**entry, "content": self.load_md_snippet(entry["md_path"], entry["md_anchor"])}

    def search_by_tag(self, keyword: str) -> list[dict[str, Any]]:
        needle = keyword.casefold().strip()
        return [item for item in _read_json(self.session_index_path).values() if needle in " ".join(item.get("tags", [])).casefold()]

    def search_by_summary(self, keyword: str) -> list[dict[str, Any]]:
        needle = keyword.casefold().strip()
        return [item for item in _read_json(self.pair_index_path).values() if needle in f"{item['title']}\n{item['brief_summary']}".casefold()]

    def load_md_snippet(self, relative_path: str, anchor_id: str) -> str:
        path = (self.root / relative_path).resolve()
        if self.root not in path.parents:
            raise ValueError("MD 路径必须位于会话仓库内")
        text = path.read_text(encoding="utf-8")
        match = re.search(ANCHOR_RE_TEMPLATE.format(anchor=re.escape(anchor_id)), text, re.IGNORECASE)
        if not match:
            raise KeyError(f"未找到锚点 {anchor_id}: {path}")
        next_anchor = re.search(r'<a\s+id=["\']pair-[^"\']+["\']\s*></a>', text[match.end():], re.IGNORECASE)
        end = match.end() + next_anchor.start() if next_anchor else len(text)
        return text[match.start():end].strip()

    def get_session_inherit_chain(self, session_id: str) -> list[dict[str, Any]]:
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
        self.initialize()
        backup_dir = self.index_dir / f"backup_{datetime.now():%Y%m%d%H%M%S}"
        backup_dir.mkdir()
        shutil.copy2(self.session_index_path, backup_dir / self.session_index_path.name)
        shutil.copy2(self.pair_index_path, backup_dir / self.pair_index_path.name)
        sessions: dict[str, Any] = {}
        pairs: dict[str, Any] = {}
        for md_path in sorted(self.storage_dir.glob("*.md")):
            parsed = parse_indexed_session_markdown(md_path.read_text(encoding="utf-8"), md_path.stem)
            sessions[parsed["session_id"]] = parsed["session"]
            pairs.update(parsed["pairs"])
        for session in sessions.values():
            session["children_session_ids"] = []
        for session_id, session in sessions.items():
            parent = session.get("parent_session_id")
            if parent in sessions:
                sessions[parent]["children_session_ids"].append(session_id)
        _write_json(self.session_index_path, sessions)
        _write_json(self.pair_index_path, pairs)
        return {"sessions": len(sessions), "pairs": len(pairs), "backup": str(backup_dir)}


def parse_markdown_conversation(markdown: str) -> list[dict[str, str]]:
    """只识别顶级 ``## 用户`` / ``## 助手`` 标题，正文保持原样。"""
    messages: list[dict[str, str]] = []
    role: str | None = None
    buffer: list[str] = []
    for line in markdown.splitlines():
        match = ROLE_HEADING_RE.match(line)
        if match:
            if role and "\n".join(buffer).strip():
                messages.append({"role": role, "content": "\n".join(buffer).strip()})
            role = "user" if match.group(1).casefold() in {"用户", "user"} else "assistant"
            buffer = []
        elif role:
            buffer.append(line)
    if role and "\n".join(buffer).strip():
        messages.append({"role": role, "content": "\n".join(buffer).strip()})
    return messages


def build_pairs(messages: list[dict[str, str]], *, session_id: str) -> list[QAPair]:
    pairs: list[QAPair] = []
    pending_user: SingleMessage | None = None
    for turn, raw in enumerate(messages, start=1):
        role = raw["role"].strip().lower()
        content = raw["content"].strip()
        if role == "user":
            pending_user = SingleMessage(turn, role, content)
        elif role == "assistant" and pending_user:
            pair_id = _new_id("pair")
            title = _brief(pending_user.content, 36)
            pairs.append(QAPair(pair_id, session_id, len(pairs) + 1, title, _brief(pending_user.content, 120), pending_user, SingleMessage(turn, role, content), f"pair-{pair_id}"))
            pending_user = None
    return pairs


def _brief(content: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", content).strip()
    return clean if len(clean) <= limit else f"{clean[:limit - 1].rstrip()}..."


def pair_to_index_entry(pair: QAPair, relative_md_path: str) -> dict[str, Any]:
    return {"pair_id": pair.pair_id, "session_id": pair.session_id, "pair_index_in_session": pair.pair_index_in_session, "title": pair.title, "brief_summary": pair.brief_summary, "md_path": relative_md_path, "md_anchor": pair.md_anchor, "user_turn": pair.msg_user.local_turn, "assistant_turn": pair.msg_assistant.local_turn}


def render_session_markdown(session_id: str, title: str, tags: list[str], pairs: list[QAPair], parent_session_id: str | None, fork_at_pair_id: str | None) -> str:
    lines = ["---", f"session_id: {session_id}", f"title: {title or session_id}", f"created_at: {_now()}", f"tags: {json.dumps(tags, ensure_ascii=False)}", "inherit_rule: snapshot"]
    if parent_session_id:
        lines.extend([f"parent_session_id: {parent_session_id}", f"fork_at_pair_id: {fork_at_pair_id}"])
    lines.extend(["---", "", f"# {title or session_id}", ""])
    if parent_session_id:
        lines.extend([f"父会话：[[{parent_session_id}]]", f"分叉节点：`{fork_at_pair_id}`", ""])
    for pair in pairs:
        lines.extend([f'<a id="{pair.md_anchor}"></a>', f"## Pair {pair.pair_index_in_session}: {pair.title}", "", f"- PairID: `{pair.pair_id}`", f"- 简述: {pair.brief_summary}", "", f"### 用户（轮次 {pair.msg_user.local_turn}）", "", pair.msg_user.content, "", f"### 助手（轮次 {pair.msg_assistant.local_turn}）", "", pair.msg_assistant.content, ""])
    return "\n".join(lines).rstrip() + "\n"


def parse_indexed_session_markdown(markdown: str, fallback_session_id: str) -> dict[str, Any]:
    session_id = re.search(r"^session_id:\s*(.+)$", markdown, re.MULTILINE)
    title = re.search(r"^title:\s*(.+)$", markdown, re.MULTILINE)
    tags = re.search(r"^tags:\s*(.+)$", markdown, re.MULTILINE)
    parent = re.search(r"^parent_session_id:\s*(.+)$", markdown, re.MULTILINE)
    fork = re.search(r"^fork_at_pair_id:\s*(.+)$", markdown, re.MULTILINE)
    sid = session_id.group(1).strip() if session_id else fallback_session_id
    parsed_tags = json.loads(tags.group(1)) if tags else []
    entries: dict[str, Any] = {}
    pair_blocks = list(
        re.finditer(
            r'<a id="(?P<anchor>pair-[^"]+)"></a>\n## Pair \d+:\s*(?P<title>.+?)\n\n- PairID: `(?P<pair_id>[^`]+)`\n- 简述:\s*(?P<summary>.+)$',
            markdown,
            re.MULTILINE,
        )
    )
    pair_ids = [match.group("pair_id") for match in pair_blocks]
    for index, match in enumerate(pair_blocks, start=1):
        pair_id = match.group("pair_id")
        entries[pair_id] = {
            "pair_id": pair_id,
            "session_id": sid,
            "pair_index_in_session": index,
            "title": match.group("title"),
            "brief_summary": match.group("summary"),
            "md_path": f"session_storage/{sid}.md",
            "md_anchor": match.group("anchor"),
        }
    session = {"session_id": sid, "title": title.group(1).strip() if title else sid, "created_at": _now(), "tags": parsed_tags, "md_path": f"session_storage/{sid}.md", "total_qa_pairs": len(pair_ids), "all_pair_ids": pair_ids, "latest_pair_id": pair_ids[-1] if pair_ids else None, "fork_type": "single" if parent else "none", "parent_session_id": parent.group(1).strip() if parent else "", "fork_at_pair_id": fork.group(1).strip() if fork else "", "inherit_rule": "snapshot", "children_session_ids": []}
    return {"session_id": sid, "session": session, "pairs": entries}


def repair_exported_chat_markdown(source: str | Path, output: str | Path) -> Path:
    """修复已知 HTML 复制故障的 Python 示例，并保留全部会话正文。"""
    source_path, output_path = Path(source), Path(output)
    text = source_path.read_text(encoding="utf-8-sig")
    replacements = {
        "### 一、数据结构重新定义": "from autodokit.tools.chat_session_index_tools import ChatSessionStore, QAPair, SingleMessage\n",
        "### 二、目录配置 & 工具常量": "from pathlib import Path\n\nstore = ChatSessionStore(Path(\"./chat_store\"))\nstore.initialize()\n",
        "### 三、MD 导出改造：增加 HTML 锚点（精准跳转）": "# ChatSessionStore.import_messages() 会生成带 <a id=\"pair-{pair_id}\"></a> 的 Markdown。\n",
        "### 四、索引读写工具函数": "# 索引由 ChatSessionStore 自动维护：index_db/session_index.json 与 index_db/pair_index.json。\n",
        "### 五、核心入口：录入一组完整会话（自动拆分问答对、生成 ID、构建双索引）": "messages = [{\"role\": \"user\", \"content\": \"问题\"}, {\"role\": \"assistant\", \"content\": \"回答\"}]\nresult = store.import_messages(messages, source_name=\"example.md\", tags=[\"会话索引\"])\nprint(result[\"session_id\"])\n",
        "### 六、给 Agent 调用的检索 API（核心，字典极速查询）": "pair = store.get_pair_info(\"pair_id\")\nsessions = store.search_by_tag(\"会话索引\")\nresults = store.search_by_summary(\"关键词\")\n",
        "### 七、运行测试示例": "result = store.import_markdown(\"conversation.md\", tags=[\"Agent工具\"])\nprint(store.get_pair_info(result[\"pair_ids\"][0]))\n",
    }
    for heading, code in replacements.items():
        start = text.find(heading)
        if start < 0:
            continue
        fence_start = text.find("```python", start)
        next_heading = text.find("\n### ", start + len(heading))
        if fence_start < 0 or (next_heading >= 0 and fence_start > next_heading):
            continue
        fence_end = text.find("```", fence_start + len("```python"))
        if fence_end < 0:
            continue
        text = text[:fence_start] + f"```python\n{code}```" + text[fence_end + 3:]
    extra_replacements = {
        "#### 1. 会话索引新增关系字段定义": (
            "json",
            '{\n  "session_id": "session_20260811_01",\n  "fork_type": "single",\n  "parent_session_id": "session_20260811_00",\n  "fork_at_pair_id": "pair_20260811100000_abc123",\n  "inherit_rule": "snapshot",\n  "children_session_ids": []\n}\n',
        ),
        "#### 索引检索配套小函数（新增）": (
            "python",
            'chain = store.get_session_inherit_chain("session_id")\nfor session in chain:\n    print(session["session_id"], session["inherited_pair_ids"])\n',
        ),
    }
    for heading, (language, code) in extra_replacements.items():
        start = text.find(heading)
        if start < 0:
            continue
        fence_start = text.find("```", start)
        next_heading = text.find("\n###", start + len(heading))
        if fence_start < 0 or (next_heading >= 0 and fence_start > next_heading):
            continue
        line_end = text.find("\n", fence_start)
        fence_end = text.find("```", line_end + 1)
        if fence_end < 0:
            continue
        text = text[:fence_start] + f"```{language}\n{code}```" + text[fence_end + 3:]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return output_path


def import_chat_session_markdown(
    store_root: str | Path, source: str | Path, *, tags: Iterable[str] = ()
) -> dict[str, Any]:
    """将导出的 Markdown 会话入库并生成双层索引。"""
    return ChatSessionStore(store_root).import_markdown(source, tags=tags)


def get_chat_pair_info(store_root: str | Path, pair_id: str) -> dict[str, Any] | None:
    """按 PairID 读取单组问答，不会加载完整会话。"""
    return ChatSessionStore(store_root).get_pair_info(pair_id)


def list_session_pairs(store: ChatSessionStore, session_id: str) -> list[dict[str, Any]]:
    """列出某会话的全部问答对（只看 title/brief，不读全文）。

    供消费 AI 快速浏览会话结构，再决定按哪个 PairID 深读。

    Args:
        store: 会话仓库。
        session_id: 会话 ID。

    Returns:
        问答对轻量列表（pair_id / title / brief_summary / 轮次）。
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
            result.append({
                "pair_id": pair_id,
                "pair_index_in_session": entry.get("pair_index_in_session"),
                "title": entry.get("title", ""),
                "brief_summary": entry.get("brief_summary", ""),
                "user_turn": entry.get("user_turn"),
                "assistant_turn": entry.get("assistant_turn"),
            })
    return result


def batch_read_pairs_by_llm(
    store_root: str | Path,
    *,
    pair_ids: Iterable[str] | None = None,
    provider: str = "auto",
    model: str = "",
    prompt_template: str = (
        "请阅读以下一组问答（来自历史会话归档），并用简洁中文输出：\n"
        "1) 本组问答主题（一句话）；\n"
        "2) 核心结论或要点（200字以内）。\n\n"
        "【用户】\n{user}\n\n【助手】\n{assistant}"
    ),
    system_prompt: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.2,
    result_path: str | Path | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    """逐 Pair 调用大模型批量读取会话内容。

    每个 Pair（一组问答）单独调用一次大模型，天然规避超长上下文问题；
    密钥通过统一密钥仓库间接获取，不写入索引、日志或结果文件。

    Args:
        store_root: 会话仓库目录。
        pair_ids: 要处理的 PairID 列表；为空则处理全部。
        provider: LLM provider 名或 auto（见 ``llm_providers``）。
        model: 显式模型名；为空用 provider 默认。
        prompt_template: 提示词模板，支持 ``{user}`` / ``{assistant}`` 占位。
        system_prompt: 可选系统提示词。
        max_tokens: 每个 Pair 最大输出 token。
        temperature: 采样温度。
        result_path: 结果 JSON 文件路径；默认 ``<store>/index_db/pair_llm_results.json``。
        resume: 为 True 时跳过已处理的 Pair（断点续跑）。

    Returns:
        汇总结果：``total``、``processed``、``skipped``、``failed``、``results``。
    """

    store = ChatSessionStore(store_root)
    store.initialize()
    if result_path is None:
        result_path = store.index_dir / "pair_llm_results.json"
    output = Path(result_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Any] = {}
    if resume and output.exists():
        try:
            loaded = json.loads(output.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                saved = loaded
        except Exception:
            saved = {}

    if pair_ids is None:
        sessions = _read_json(store.session_index_path)
        pair_ids = [pid for session in sessions.values() for pid in session.get("all_pair_ids", [])]
    target_ids = [str(pid) for pid in pair_ids]

    from autodokit.tools.atomic.llm.llm_providers import invoke_llm  # 延迟导入避免循环依赖

    processed = 0
    skipped = 0
    failed = 0
    results: list[dict[str, Any]] = []
    for pair_id in target_ids:
        if resume and pair_id in saved:
            skipped += 1
            results.append(saved[pair_id])
            continue
        entry = store.get_pair_info(pair_id)
        if entry is None:
            failed += 1
            continue
        # 从 content（锚点片段全文）中分离用户/助手正文。
        content = entry.get("content", "")
        user_block = assistant_block = content
        marker_user = "### 用户"
        marker_assistant = "### 助手"
        user_pos = content.find(marker_user)
        assistant_pos = content.find(marker_assistant)
        if user_pos >= 0 and assistant_pos > user_pos:
            user_block = content[user_pos + len(marker_user):assistant_pos].strip()
            assistant_block = content[assistant_pos + len(marker_assistant):].strip()
        prompt = prompt_template.format(user=user_block, assistant=assistant_block)

        try:
            result = invoke_llm(
                prompt=prompt,
                system=system_prompt,
                provider=provider,
                model=model,
                max_tokens=int(max_tokens),
                temperature=float(temperature),
            )
        except Exception as exc:
            result = {"status": "FAIL", "error": str(exc), "response": {}}

        record = {
            "pair_id": pair_id,
            "provider": result.get("provider", provider),
            "model": result.get("selected_model", model),
            "status": result.get("status", "FAIL"),
            "summary": (result.get("response") or {}).get("text", "") if result.get("status") == "PASS" else "",
            "error": result.get("error", "") if result.get("status") != "PASS" else "",
        }
        saved[pair_id] = record
        results.append(record)
        if record["status"] == "PASS":
            processed += 1
        else:
            failed += 1
        # 逐条落盘，支持断点续跑。
        output.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "total": len(target_ids),
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "result_path": str(output),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="超长会话索引化管理与检索")
    parser.add_argument("--store", required=True, help="会话仓库目录")
    subparsers = parser.add_subparsers(dest="command", required=True)
    repair = subparsers.add_parser("repair")
    repair.add_argument("source")
    repair.add_argument("output")
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
    subparsers.add_parser("rebuild")
    args = parser.parse_args()
    store = ChatSessionStore(args.store)
    if args.command == "repair":
        result: Any = str(repair_exported_chat_markdown(args.source, args.output))
    elif args.command == "import":
        result = store.import_markdown(args.source, tags=args.tag)
    elif args.command == "pair":
        result = store.get_pair_info(args.pair_id)
    elif args.command == "search":
        result = store.search_by_tag(args.keyword) if args.by == "tag" else store.search_by_summary(args.keyword)
    elif args.command == "chain":
        result = store.get_session_inherit_chain(args.session_id)
    else:
        result = store.rebuild_indexes()
    print(json.dumps(result, ensure_ascii=False, indent=2) if not isinstance(result, str) else result)


if __name__ == "__main__":
    main()
