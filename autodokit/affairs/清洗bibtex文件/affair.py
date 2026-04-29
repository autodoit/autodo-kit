"""
清洗 BibTeX 文件事务。

本事务用于处理“作者栏（author 字段）末尾多余分号”的常见脏数据：
- 单个作者被错误地写成 "Author;"；
- 多个作者用分号分隔时，最后一个作者末尾也多了一个 ";"。

事务行为（保持低风险、尽量不改变语义）：
- 仅对每条记录的 `author` 字段做清洗。
- 先移除尾部（末尾）一个或多个分号以及其后的空白。
- 对常见的分号分隔作者（`;` / `；`）规范化为 BibTeX 标准分隔符 ` and `，以便 Zotero 正确拆分多作者。
- 若已是 `and` 分隔，则仅做空白规范化，不重复改写。

输入/输出契约（必须遵守开发者指南）：
- 所有参与业务 IO 的路径字段必须为绝对路径；若收到相对路径应直接失败。

Args:
    config_path: 调度器写出的合并后临时配置文件路径（.json）。

Returns:
    清洗后写出的 BibTeX 文件路径列表（通常为 1 个文件）。

Examples:
    >>> from pathlib import Path
    >>> # 说明：此处仅展示调用方式；具体配置由调度器写入 .tmp/*.json
    >>> # from autodokit.affairs.清洗bibtex文件 import execute
    >>> # execute(Path("/home/ethan/workspace/.tmp/affair_config.json"))
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from autodokit.tools import load_json_or_py


@dataclass
class BibtexCleanConfig:
    """BibTeX 清洗配置。

    Attributes:
        input_bibtex_path: 输入 bib 文件路径（绝对路径）。
        output_bibtex_path: 输出清洗后 bib 文件路径（绝对路径）。
        dry_run: 若为 True，仅返回统计信息但不写文件。
        backup: 若输出文件已存在，是否备份旧文件。
    """

    input_bibtex_path: str  # 输入 bib 路径（绝对路径）
    output_bibtex_path: str  # 输出 bib 路径（绝对路径）
    dry_run: bool = False  # 是否仅模拟运行
    backup: bool = True  # 是否备份已存在的输出


# 兼容中英文分号；先去尾部再按分号拆分作者
_AUTHOR_TRAILING_SEMI_RE = re.compile(r"[;；]+\s*$")
_AUTHOR_SEP_RE = re.compile(r"\s*[;；]+\s*")
_AUTHOR_AND_SEP_RE = re.compile(r"\s+and\s+", flags=re.IGNORECASE)

# 支持清洗的“人名类”字段集合（最小改动：把 author 的逻辑复用到 editor/translator 等）
_NAME_FIELDS_RE = re.compile(r"^(?P<prefix>\s*(?:author|editor|translator|bookauthor|reviewauthor)\s*=\s*)\{", flags=re.IGNORECASE)


def _normalize_author_value(value: str) -> str:
    """规范化 author 值为标准 BibTeX 多作者格式。

    处理策略：
    - 去掉 author 值末尾多余分号；
    - 若值内存在分号分隔作者，则转换为 ` and `；
    - 若已存在 `and` 分隔，则仅压缩多余空白。

    注意：这里仅处理 author 字段的“值部分”，不包含末尾的 `},`、`",` 等 BibTeX 语法。

    Args:
        value: author 字段的原始值文本（不包含外围花括号）。

    Returns:
        规范化后的 author 值文本。
    """

    cleaned = _AUTHOR_TRAILING_SEMI_RE.sub("", value).strip()
    if not cleaned:
        return cleaned

    # 已经使用 and 分隔时，不做结构改写，仅规范空白。
    if _AUTHOR_AND_SEP_RE.search(cleaned):
        return re.sub(r"\s+", " ", cleaned).strip()

    # 常见 CNKI 导出为分号分隔，转换为 BibTeX 标准 author 分隔符。
    if ";" in cleaned or "；" in cleaned:
        parts = [part.strip() for part in _AUTHOR_SEP_RE.split(cleaned) if part.strip()]
        if len(parts) > 1:
            return " and ".join(parts)

    return cleaned


def _clean_bibtex_text_author_fields(text: str) -> tuple[str, int]:
    """在原始 BibTeX 文本层面清洗 author 字段。

    设计原因：
    - 你当前的 `.bib` 使用 `@general{ ... }` 这种非标准 entry type。
    - `bibtexparser` 在写回时可能会把未知类型/不规范结构转换成 `@comment{...}`，导致文献工具无法识别。
    - 因此这里采用“纯文本、最小修改”的策略：只修改 author 字段的内容，其它内容完全保持原样。

    支持形式：
    - 单行：`author = {翟金林;},`
    - 多行（author 值中可能换行）：
      `author = {李政;涂晓枫;\n卜林;},`

    Args:
        text: 原始 BibTeX 文件文本。

    Returns:
        (new_text, touched_count)
    """

    # 逐行扫描，进入 author 字段后做括号配对，直到 author 值闭合
    lines = text.splitlines(keepends=True)

    touched = 0
    out_lines: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # 匹配人名类字段开始（例如 author/editor/translator 等，大小写不敏感，允许前置空白）
        m = _NAME_FIELDS_RE.match(line)
        if not m:
            out_lines.append(line)
            i += 1
            continue

        prefix = m.group("prefix")
        # 从 '{' 后开始累积 author 值
        after_brace = line[m.end() :]

        buf_value_parts: list[str] = [after_brace]

        # 计数：已遇到 1 个 '{'，需要找到与之匹配的 '}'
        brace_depth = 1

        j = i
        # 从当前行剩余部分开始计算括号深度
        # 说明：BibTeX 的 author 值不太会嵌套大括号，但这里仍做保守处理
        def _count_delta(s: str) -> int:
            return s.count("{") - s.count("}")

        brace_depth += _count_delta(after_brace)

        # 如果当前行就闭合，brace_depth 会变成 0
        while brace_depth > 0 and j + 1 < len(lines):
            j += 1
            buf_value_parts.append(lines[j])
            brace_depth += _count_delta(lines[j])

        # 现在 buf_value_parts 含有从 '{' 后到闭合 '}'（以及可能后续字符）的所有文本
        raw_tail = "".join(buf_value_parts)

        # 找到第一个与外层匹配的 '}' 的位置（从左到右扫描深度）
        depth = 1
        close_pos = None
        for idx, ch in enumerate(raw_tail):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    close_pos = idx
                    break

        if close_pos is None:
            # 非法结构：找不到闭合，直接原样输出（不做冒险修复）
            out_lines.append(line)
            i += 1
            continue

        value_text = raw_tail[:close_pos]
        suffix_text = raw_tail[close_pos + 1 :]

        cleaned_value_text = _normalize_author_value(value_text)
        if cleaned_value_text != value_text:
            touched += 1

        # 重建：prefix + '{' + cleaned_value + '}' + suffix
        rebuilt = prefix + "{" + cleaned_value_text + "}" + suffix_text

        # rebuilt 可能跨多行；为了保持其余行不变，这里直接把 rebuilt 作为一个整体写出
        out_lines.append(rebuilt)

        # 跳过已经消费的行
        i = j + 1

    return "".join(out_lines), touched


def clean_bibtex_file(
    *,
    input_bibtex_path: str | Path,
    output_bibtex_path: str | Path,
    dry_run: bool = False,
    backup: bool = True,
) -> Dict[str, Any]:
    """清洗单个 bib 文件并写出。

    Args:
        input_bibtex_path: 输入 bib 文件（必须为绝对路径）。
        output_bibtex_path: 输出 bib 文件（必须为绝对路径）。
        dry_run: 若为 True，不写文件。
        backup: 若输出已存在，是否写出 .bak 备份。

    Returns:
        统计信息字典。

    Raises:
        ValueError: 路径为空、不是绝对路径，或输入不是 .bib。
        FileNotFoundError: 输入文件不存在。
    """

    in_path = Path(input_bibtex_path)
    out_path = Path(output_bibtex_path)

    if not str(in_path).strip() or not str(out_path).strip():
        raise ValueError("input_bibtex_path/output_bibtex_path 不能为空")

    # 关键约定：事务只接收绝对路径；相对路径属于调度层缺陷
    if not in_path.is_absolute():
        raise ValueError(f"input_bibtex_path 必须为绝对路径（应由调度层预处理）：{str(in_path)!r}")
    if not out_path.is_absolute():
        raise ValueError(f"output_bibtex_path 必须为绝对路径（应由调度层预处理）：{str(out_path)!r}")

    if in_path.suffix.lower() != ".bib":
        raise ValueError(f"输入文件不是 .bib：{in_path}")

    if not in_path.exists():
        raise FileNotFoundError(f"找不到输入 bib 文件：{in_path}")

    # 纯文本读写，避免 bibtexparser 改写 entry type
    raw_text = in_path.read_text(encoding="utf-8", errors="ignore")
    cleaned_text, touched_entries = _clean_bibtex_text_author_fields(raw_text)

    result = {
        "touched_entries": int(touched_entries),
        "input_bibtex_path": str(in_path),
        "output_bibtex_path": str(out_path),
        "dry_run": bool(dry_run),
    }

    if dry_run:
        return result

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and backup:
        bak_path = out_path.with_suffix(out_path.suffix + ".bak")
        bak_path.write_bytes(out_path.read_bytes())

    out_path.write_text(cleaned_text, encoding="utf-8")
    return result


def execute(config_path: Path) -> List[Path]:
    """调度器事务入口：读取临时配置并执行 bibtex 清洗。

    Args:
        config_path: 调度器写入的临时 JSON 配置文件路径。

    Returns:
        写出的文件路径列表（dry_run=True 时返回空列表）。

    Raises:
        ValueError: 配置缺失或路径不合法。
    """

    cfg = load_json_or_py(config_path)

    input_bibtex_path = str(cfg.get("input_bibtex_path") or "").strip()
    output_bibtex_path = str(cfg.get("output_bibtex_path") or "").strip()

    if not input_bibtex_path:
        raise ValueError("配置缺少 input_bibtex_path")
    if not output_bibtex_path:
        raise ValueError("配置缺少 output_bibtex_path")

    dry_run = bool(cfg.get("dry_run", False))
    backup = bool(cfg.get("backup", True))

    clean_bibtex_file(
        input_bibtex_path=input_bibtex_path,
        output_bibtex_path=output_bibtex_path,
        dry_run=dry_run,
        backup=backup,
    )

    if dry_run:
        return []
    return [Path(output_bibtex_path)]
