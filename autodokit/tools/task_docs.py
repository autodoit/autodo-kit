"""任务文档管理工具。

本模块用于把“任务文档管理”的确定性动作工程化，便于被 AOK 的事务（affairs）调用。

当前覆盖的能力（对应【通用文档管理工作流】scripts 的可移植部分）：
- 生成 UID（原 generate_uid.py）
- 创建任务 latest 文件（原 create_latest.py）
- 聚合任务产物为汇总文件（原 aggregate_task.py）

设计原则：
- 不依赖外部命令（不调用 python3 子进程），统一使用纯 Python 实现，Windows 更稳。
- 输入为“显式参数/配置”，输出为“写出的文件路径”，适配 AOK runner 的返回约定。
- 默认采用“同一任务在一次创建动作中共享同一个 UID”，方便后续固化 latest→UID。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class UidSpec:
    """UID 生成规格。

    Attributes:
        mode: UID 生成模式。
            - timestamp: `YYYYMMDDHHMMSS`
            - timestamp-us: `YYYYMMDDHHMMSSffffff`
            - timestamp-rand: `YYYYMMDDHHMMSS` + 随机数字后缀
            - timestamp-us-rand: `YYYYMMDDHHMMSSffffff` + 随机数字后缀
            - uuid: UUID4 hex（32 位）
        random_length: 随机后缀长度，仅在 `*-rand` 模式下生效。
    """

    mode: str = "timestamp-us-rand"
    random_length: int = 2


def generate_uid(spec: UidSpec | None = None) -> str:
    """生成任务文档 UID。

    Args:
        spec: UID 规格；不提供则使用默认（timestamp-us-rand + 2）。

    Returns:
        UID 字符串。

    Raises:
        ValueError: mode 非法，或 random_length 非法。

    Examples:
        >>> uid = generate_uid(UidSpec(mode="timestamp"))
        >>> len(uid) == 14
        True
    """

    spec = spec or UidSpec()
    mode = (spec.mode or "").strip()
    random_length = int(spec.random_length)

    if mode not in {"timestamp", "timestamp-us", "timestamp-rand", "timestamp-us-rand", "uuid"}:
        raise ValueError(f"不支持的 UID mode：{mode}")

    if mode.endswith("-rand") and random_length <= 0:
        raise ValueError("random_length 必须大于 0")

    now = datetime.now()
    if mode == "timestamp":
        return now.strftime("%Y%m%d%H%M%S")
    if mode == "timestamp-us":
        return now.strftime("%Y%m%d%H%M%S%f")

    if mode in {"timestamp-rand", "timestamp-us-rand"}:
        base = (
            now.strftime("%Y%m%d%H%M%S")
            if mode == "timestamp-rand"
            else now.strftime("%Y%m%d%H%M%S%f")
        )
        max_number = 10**random_length - 1
        random_number = random.randint(0, max_number)
        suffix = str(random_number).zfill(random_length)
        return f"{base}{suffix}"

    # uuid
    import uuid

    return uuid.uuid4().hex


def _utc_now_iso_z() -> str:
    """获取 UTC ISO 时间字符串（以 Z 结尾）。

    Returns:
        形如 `2026-02-24T12:34:56Z` 的时间字符串。
    """

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_filename_component(text: str) -> str:
    """把文本转为尽量安全的文件名片段。

    Args:
        text: 原始文本。

    Returns:
        清洗后的文本（去首尾空白、压缩空白为单个 `-`）。

    Examples:
        >>> _safe_filename_component("制作 简历")
        '制作-简历'
    """

    cleaned = "-".join((text or "").strip().split())
    return cleaned or "未命名任务"


def build_front_matter(*, title: str, doc_type: str, uid: str, extra_tags: Optional[List[str]] = None) -> str:
    """构建 YAML front-matter。

    Args:
        title: 文档标题。
        doc_type: 文档类型（需求/设计/过程）。
        uid: 时间戳 UID。
        extra_tags: 额外 tags（每项为完整 tag 字符串）。

    Returns:
        front-matter 文本（以 `---` 包裹，末尾包含一个空行）。
    """

    tags = [f"#时间戳/{uid}"]
    if extra_tags:
        tags.extend([t for t in extra_tags if str(t).strip()])

    # YAML 采用最保守写法（列表），减少解析差异。
    lines = [
        "---",
        f'title: "{title}"',
        f'type: "{doc_type}"',
        f'created: "{_utc_now_iso_z()}"',
        "tags:",
    ]
    for t in tags:
        lines.append(f'  - "{t}"')
    lines.extend(["---", ""])  # 末尾保留空行
    return "\n".join(lines)


def default_body_for_doc_type(task_name: str, doc_type: str) -> str:
    """为不同文档类型生成默认正文骨架。

    约束：必须包含可被聚合脚本识别的小节标题：
    - 需求：`## need`、`## goal`
    - 设计：`## thinking`、`## plan`
    - 过程：`## process`

    Args:
        task_name: 任务名。
        doc_type: 文档类型（需求/设计/过程）。

    Returns:
        正文文本。

    Raises:
        ValueError: doc_type 不支持。
    """

    doc_type = (doc_type or "").strip()

    if doc_type == "需求":
        return (
            f"# {task_name} — 需求（latest）\n\n"
            "## need\n\n"
            "（在此描述需求/问题是什么）\n\n"
            "## goal\n\n"
            "（在此描述目标/验收标准是什么）\n"
        )

    if doc_type == "设计":
        return (
            f"# {task_name} — 设计（latest）\n\n"
            "## thinking\n\n"
            "（在此记录关键思考、方案对比与约束）\n\n"
            "## plan\n\n"
            "（在此写可执行的步骤清单）\n"
        )

    if doc_type == "过程":
        return (
            f"# {task_name} — 过程（latest）\n\n"
            "## process\n\n"
            "（在此记录实施过程、产物与问题）\n"
        )

    raise ValueError(f"不支持的 doc_type：{doc_type}")


def create_latest_files(
    *,
    task_name: str,
    doc_types: Iterable[str],
    output_dir: Path,
    uid_spec: UidSpec | None = None,
    overwrite: bool = False,
    extra_tags: Optional[List[str]] = None,
) -> List[Path]:
    """创建任务 latest 文件。

    Args:
        task_name: 任务名称。
        doc_types: 文档类型列表（建议：需求/设计/过程）。
        output_dir: 输出目录。
        uid_spec: UID 生成规格；不提供则用默认。
        overwrite: 若为 True，则允许覆盖已存在文件。
        extra_tags: 额外 tags。

    Returns:
        生成的文件路径列表。

    Raises:
        FileExistsError: overwrite=False 且目标文件已存在。
        ValueError: doc_types 为空或包含不支持类型。
    """

    task_name_clean = (task_name or "").strip()
    if not task_name_clean:
        raise ValueError("task_name 不能为空")

    doc_type_list = [str(x).strip() for x in doc_types if str(x).strip()]
    if not doc_type_list:
        raise ValueError("doc_types 不能为空")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    uid = generate_uid(uid_spec)
    safe_task = _safe_filename_component(task_name_clean)

    written: List[Path] = []
    for doc_type in doc_type_list:
        filename = f"{safe_task}-{doc_type}-latest.md"
        target = (output_dir / filename).resolve()

        if target.exists() and not overwrite:
            raise FileExistsError(f"目标文件已存在（overwrite=false）：{target}")

        title = f"{task_name_clean}-{doc_type}-latest"
        fm = build_front_matter(title=title, doc_type=doc_type, uid=uid, extra_tags=extra_tags)
        body = default_body_for_doc_type(task_name_clean, doc_type)

        target.write_text(fm + body, encoding="utf-8")
        written.append(target)

    return written


_UID_PATTERN = re.compile(r"-\d{14,}(?:\.md)?$")


def find_task_markdown_files(root_dir: Path, task_name: str) -> List[Path]:
    """在根目录下递归查找任务相关 Markdown 文件。

    匹配规则（最小可用）：
    - 文件名以 `task_name-` 开头
    - 且包含 `-latest` 或包含形如 `-YYYYMMDDHHMMSS...` 的 UID 段

    Args:
        root_dir: 扫描根目录。
        task_name: 任务名（用于文件名前缀匹配）。

    Returns:
        匹配到的 Markdown 文件路径列表（已排序）。
    """

    root_dir = Path(root_dir)
    prefix = f"{task_name}-"

    matched: List[Path] = []
    for path_item in root_dir.rglob("*.md"):
        name = path_item.name
        if not name.startswith(prefix):
            continue
        if "-latest" in name or re.search(r"-\d{14,}", name):
            matched.append(path_item)

    return sorted(matched)


def read_markdown_frontmatter_and_body(path: Path) -> tuple[str, str]:
    """读取 Markdown 文件并拆分 frontmatter 与正文。

    Args:
        path: Markdown 文件路径。

    Returns:
        (frontmatter_raw, body_text)
        - frontmatter_raw：包含 YAML 内容（不含 `---`），若不存在则为空字符串
        - body_text：正文
    """

    text = Path(path).read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[1].strip("\n"), parts[2].lstrip("\n")
    return "", text


def extract_task_sections(body: str) -> dict[str, str]:
    """从正文中提取 需求/设计/过程 三类小节。

    识别规则：
    - `## need` 或 `## goal` -> 需求
    - `## thinking` 或 `## plan` -> 设计
    - `## process` -> 过程

    Args:
        body: Markdown 正文。

    Returns:
        键为 `需求/设计/过程` 的字典（值为提取到的小节文本；可能为空）。
    """

    lines = (body or "").splitlines()

    sections: dict[str, List[str]] = {"需求": [], "设计": [], "过程": []}
    current: Optional[str] = None

    for line in lines:
        header = re.match(r"^##\s*(.+)$", line)
        if header:
            h = header.group(1).strip().lower()
            if h in {"need", "goal"}:
                current = "需求"
            elif h in {"thinking", "plan"}:
                current = "设计"
            elif h == "process":
                current = "过程"
            else:
                current = None

            if current is not None:
                sections[current].append(line)
            continue

        if current is not None:
            sections[current].append(line)

    return {k: "\n".join(v).strip() for k, v in sections.items()}


def build_task_summary_markdown(
    *,
    task_name: str,
    sources: List[Path],
    sections_map: dict[str, str],
    title: Optional[str] = None,
) -> str:
    """构建任务汇总 Markdown。

    Args:
        task_name: 任务名。
        sources: 源文件列表（用于可追溯）。
        sections_map: 三类小节映射（需求/设计/过程）。
        title: 可选标题；不提供则使用默认。

    Returns:
        汇总 Markdown 文本。
    """

    summary_title = title or f"{task_name}-汇总"

    header_lines = [
        "---",
        f'title: "{summary_title}"',
        "tags:",
        '  - "#类型/笔记"',
        "---",
        "",
    ]

    body = [f"# {task_name} — 汇总\n"]
    for sec in ("需求", "设计", "过程"):
        body.append(f"## {sec}\n")
        content = (sections_map.get(sec) or "").strip()
        body.append(content + "\n" if content else "（无）\n")

    body.append("## 来源\n")
    for s in sources:
        body.append(f"- {s.as_posix()}\n")

    return "\n".join(header_lines) + "\n".join(body)


def aggregate_task_documents(
    *,
    root_dir: Path,
    task_name: str,
    output_dir: Path,
    uid_spec: UidSpec | None = None,
    dry_run: bool = False,
) -> Optional[Path]:
    """聚合任务文档并生成汇总文件。

    Args:
        root_dir: 扫描根目录。
        task_name: 任务名。
        output_dir: 输出目录。
        uid_spec: UID 生成规格（用于汇总文件名）。
        dry_run: 若为 True，则不写文件，只返回预期输出路径。

    Returns:
        汇总文件路径；若未找到源文件则返回 None。
    """

    root_dir = Path(root_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = find_task_markdown_files(root_dir, task_name)
    if not candidates:
        return None

    aggregated: dict[str, List[str]] = {"需求": [], "设计": [], "过程": []}

    for path_item in candidates:
        _, body = read_markdown_frontmatter_and_body(path_item)
        sections = extract_task_sections(body)
        for k in aggregated.keys():
            if sections.get(k):
                aggregated[k].append(sections[k])

    sections_map = {k: "\n\n".join(v).strip() for k, v in aggregated.items()}

    uid = generate_uid(uid_spec)
    summary_name = f"{_safe_filename_component(task_name)}-汇总-{uid}.md"
    out_path = (output_dir / summary_name).resolve()

    # 来源路径尽量使用相对 root_dir，便于可读；若失败则退回绝对路径。
    display_sources: List[Path] = []
    for s in candidates:
        try:
            display_sources.append(s.resolve().relative_to(root_dir.resolve()))
        except Exception:
            display_sources.append(s.resolve())

    content = build_task_summary_markdown(task_name=task_name, sources=display_sources, sections_map=sections_map)

    if not dry_run:
        out_path.write_text(content, encoding="utf-8")

    return out_path


def split_frontmatter(text: str) -> tuple[str, str, str]:
    """拆分 Markdown 的 frontmatter 与正文。

    Args:
        text: Markdown 原始文本。

    Returns:
        (prefix, frontmatter, body) 三元组：
        - prefix: frontmatter 之前的文本（通常为空，但保留以兼容异常文件）
        - frontmatter: 不含包裹线 `---` 的 YAML 文本（可能为空）
        - body: 正文文本（可能为空）

    Examples:
        >>> p, fm, body = split_frontmatter('---\nkey: v\n---\n\n# Hi')
        >>> fm.strip() == 'key: v'
        True
    """

    if not text.startswith("---"):
        return "", "", text

    # 仅拆分第一个 frontmatter 区段：--- <yaml> ---
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", "", text

    prefix = parts[0]
    fm = parts[1].strip("\n")
    body = parts[2].lstrip("\n")
    return prefix, fm, body


_UID_TAG_REGEX = re.compile(r"#时间戳/(\d{14,})")


def extract_uid_from_frontmatter(frontmatter: str) -> Optional[str]:
    """从 frontmatter 文本中提取 UID。

    规则：在 frontmatter 中匹配 `#时间戳/<UID>`，其中 UID 为 14 位及以上数字。

    Args:
        frontmatter: YAML frontmatter 文本（不含 `---` 包裹线）。

    Returns:
        提取到的 UID；若未找到则返回 None。
    """

    if not frontmatter:
        return None
    m = _UID_TAG_REGEX.search(frontmatter)
    return m.group(1) if m else None


def ensure_uid_tag_in_frontmatter(frontmatter: str, uid: str) -> str:
    """确保 frontmatter 包含 `#时间戳/<UID>` tag；若不存在则追加。

    轻量策略：
    - 若已存在 `#时间戳/` 则原样返回（不重复写入）。
    - 否则：
      - 若存在 `tags:` 列表块，则在其后追加一条 `  - "#时间戳/<UID>"`
      - 否则在末尾追加一个最小 tags 列表

    Args:
        frontmatter: YAML frontmatter 文本（不含 `---`）。
        uid: 要确保写入的 UID。

    Returns:
        更新后的 frontmatter 文本。
    """

    if extract_uid_from_frontmatter(frontmatter) is not None:
        return frontmatter

    lines = (frontmatter or "").splitlines()
    out: List[str] = []

    inserted = False
    for idx, line in enumerate(lines):
        out.append(line)
        if inserted:
            continue

        # 找到 tags: 行后，在 tags 块中追加（若 tags 为列表）。
        if re.match(r"^tags\s*:\s*$", line.strip()):
            # 在 tags: 后面插入一条列表项（即便后续 tags 原本是字符串，这里也仍是可读但不一定严格 YAML）。
            out.append(f'  - "#时间戳/{uid}"')
            inserted = True

    if not inserted:
        if out and out[-1].strip() != "":
            out.append("")
        out.extend(["tags:", f'  - "#时间戳/{uid}"'])

    return "\n".join(out).strip("\n")


def update_frontmatter_title_and_alias(frontmatter: str, *, old_suffix: str, new_suffix: str) -> str:
    """更新 frontmatter 中的 title/alias，把旧后缀替换为新后缀。

    说明：只做最小文本替换，不尝试完整 YAML 解析。

    Args:
        frontmatter: YAML frontmatter 文本。
        old_suffix: 旧后缀文本（例如 `-latest`）。
        new_suffix: 新后缀文本（例如 `-2026...`）。

    Returns:
        更新后的 frontmatter。
    """

    if not frontmatter:
        return frontmatter

    lines = frontmatter.splitlines()
    out: List[str] = []

    in_alias_block = False
    for line in lines:
        stripped = line.strip()

        if re.match(r"^alias\s*:\s*$", stripped):
            in_alias_block = True
            out.append(line)
            continue

        # alias 块结束的最小判断：遇到新的顶层键（形如 `key:`）
        if in_alias_block and re.match(r"^[A-Za-z_][\w-]*\s*:\s*", stripped):
            in_alias_block = False

        if stripped.startswith("title:"):
            out.append(line.replace(old_suffix, new_suffix))
            continue

        if stripped.startswith("alias:"):
            out.append(line.replace(old_suffix, new_suffix))
            continue

        if in_alias_block and (stripped.startswith("-") or stripped.startswith("- ")):
            out.append(line.replace(old_suffix, new_suffix))
            continue

        out.append(line)

    return "\n".join(out).strip("\n")


def rewrite_archive_tags_in_frontmatter(frontmatter: str) -> str:
    """将 frontmatter 的 tags 更新为“存档”语义。

    轻量规则：
    - 若出现 `#类型/笔记`，则替换为 `#类型/存档`
    - 若未出现 `#类型/存档`，则追加到 tags 列表（或末尾）

    Args:
        frontmatter: YAML frontmatter 文本。

    Returns:
        更新后的 frontmatter。
    """

    if not frontmatter:
        return frontmatter

    updated = frontmatter.replace("#类型/笔记", "#类型/存档")
    if "#类型/存档" in updated:
        return updated

    # 不存在存档 tag：追加
    lines = updated.splitlines()
    out: List[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if inserted:
            continue
        if re.match(r"^tags\s*:\s*$", line.strip()):
            out.append('  - "#类型/存档"')
            inserted = True

    if not inserted:
        if out and out[-1].strip() != "":
            out.append("")
        out.extend(["tags:", '  - "#类型/存档"'])

    return "\n".join(out).strip("\n")


def finalize_latest_file(
    *,
    path: Path,
    generate_if_missing: bool = False,
    uid_spec: UidSpec | None = None,
    dry_run: bool = False,
) -> Path:
    """将单个 `*-latest.md` 文件固化为 `*-<UID>.md`。

    操作：
    - 读取 frontmatter，提取 `#时间戳/<UID>`；
    - 若缺失且允许生成，则生成 UID 并回写到 tags；
    - 重命名文件；
    - 更新 frontmatter 的 title/alias：`-latest` -> `-<UID>`。

    Args:
        path: 待固化文件路径。
        generate_if_missing: UID 缺失时是否生成并回写。
        uid_spec: 生成 UID 时使用的规格。
        dry_run: 若为 True，不写入文件系统，仅返回预期新路径。

    Returns:
        固化后的新路径。

    Raises:
        ValueError: 文件不是 latest 或 UID 无法获取。
        FileExistsError: 新路径已存在。
    """

    path = Path(path).resolve()
    if path.suffix.lower() != ".md":
        raise ValueError(f"仅支持 Markdown：{path}")
    if "-latest" not in path.name:
        raise ValueError(f"不是 latest 文件：{path}")

    original_text = path.read_text(encoding="utf-8")
    _, fm, body = split_frontmatter(original_text)
    uid = extract_uid_from_frontmatter(fm)

    if uid is None:
        if not generate_if_missing:
            raise ValueError(f"未在 frontmatter 找到 #时间戳/UID：{path}")
        uid = generate_uid(uid_spec)
        fm = ensure_uid_tag_in_frontmatter(fm, uid)

    new_name = path.name.replace("-latest", f"-{uid}")
    new_path = (path.parent / new_name).resolve()
    if new_path.exists() and new_path != path:
        raise FileExistsError(f"目标文件已存在：{new_path}")

    fm_updated = update_frontmatter_title_and_alias(fm, old_suffix="-latest", new_suffix=f"-{uid}")

    # 正文显示名轻量同步：仅替换首次出现的“（latest）”，避免大范围误伤。
    body_updated = body
    if "（latest）" in body_updated:
        body_updated = body_updated.replace("（latest）", f"（{uid}）", 1)

    new_text = "---\n" + fm_updated.strip("\n") + "\n---\n\n" + body_updated

    if dry_run:
        return new_path

    # 先写回内容，再重命名，减少“重命名成功但内容未更新”的风险。
    path.write_text(new_text, encoding="utf-8")
    if new_path != path:
        path.replace(new_path)
    return new_path


def archive_task_files(
    *,
    root_dir: Path,
    task_name: str,
    archive_dir: Path,
    include_latest: bool = False,
    dry_run: bool = False,
) -> List[Path]:
    """将任务相关文件移动到归档目录并更新 tags。

    默认策略：
    - 仅匹配已固化 UID 版本（文件名包含 `-\\d{14,}`），除非 include_latest=True。
    - 只移动文件，不处理索引更新。

    Args:
        root_dir: 扫描根目录。
        task_name: 任务名（文件名前缀匹配）。
        archive_dir: 归档目录。
        include_latest: 是否也归档 latest 文件。
        dry_run: 是否干运行。

    Returns:
        移动后的目标路径列表。
    """

    root_dir = Path(root_dir).resolve()
    archive_dir = Path(archive_dir).resolve()
    archive_dir.mkdir(parents=True, exist_ok=True)

    prefix = f"{task_name}-"
    moved: List[Path] = []

    for path_item in root_dir.rglob("*.md"):
        try:
            if path_item.resolve().is_relative_to(archive_dir):
                continue
        except Exception:
            # 兼容旧版本或异常路径：忽略该保护
            pass

        name = path_item.name
        if not name.startswith(prefix):
            continue

        is_latest = "-latest" in name
        has_uid = re.search(r"-\d{14,}", name) is not None

        if not include_latest and is_latest:
            continue
        if not has_uid and not (include_latest and is_latest):
            continue

        text = path_item.read_text(encoding="utf-8")
        pre, fm, body = split_frontmatter(text)
        if fm:
            fm = rewrite_archive_tags_in_frontmatter(fm)
            text = "---\n" + fm.strip("\n") + "\n---\n\n" + body

        target = (archive_dir / path_item.name).resolve()
        if target.exists():
            raise FileExistsError(f"归档目标已存在：{target}")

        if not dry_run:
            path_item.write_text(text, encoding="utf-8")
            path_item.replace(target)

        moved.append(target)

    return moved
