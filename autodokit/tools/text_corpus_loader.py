"""参考资料语料加载工具。

本模块用于读取用户提供的参考资料目录（支持子目录递归），把多个文件的内容按“单元”切分后合并，
再作为参考上下文注入到大模型提示词中。

设计原因：
- 参考资料读取/清洗/截断逻辑会被多个事务复用，因此放在 tools/。
- 事务侧只消费“已绝对化的目录路径”，不在事务内做路径解析兜底，符合项目约定。

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from autodokit.tools.document_unit_splitter import (
    DocumentUnit,
    split_document_to_units,
)


@dataclass(frozen=True)
class ReferenceCorpus:
    """参考资料语料加载结果。

    Attributes:
        text: 合并后的参考文本（可直接拼到 prompt）。
        files: 实际读取的文件列表（绝对路径）。
        truncated: 是否发生过截断（任意截断策略生效）。
        chars: text 的字符数。
        debug: 便于复现/调试的摘要信息（例如每文件分配预算、截断单元数等）。
    """

    text: str
    files: List[Path]
    truncated: bool
    chars: int
    debug: Dict[str, object]


def _iter_reference_files(reference_dir: Path, *, exts_norm: set[str], recursive: bool) -> List[Path]:
    """枚举参考资料文件并给出稳定顺序。"""

    if recursive:
        files_all = [p for p in reference_dir.rglob("*") if p.is_file() and p.suffix.lower() in exts_norm]
        files_all.sort(key=lambda p: str(p.relative_to(reference_dir)).replace("\\", "/"))
        return files_all

    files_all = [p for p in reference_dir.iterdir() if p.is_file() and p.suffix.lower() in exts_norm]
    files_all.sort(key=lambda p: p.name)
    return files_all


def _allocate_file_budgets(files: List[Path], *, total_budget: int | None) -> Dict[Path, int]:
    """按文件平均分配字符预算（更公平）。"""

    if total_budget is None or total_budget < 0:
        return {p: -1 for p in files}

    n = max(1, len(files))
    base = int(total_budget) // n
    rem = int(total_budget) % n

    out: Dict[Path, int] = {}
    for idx, p in enumerate(files):
        out[p] = base + (1 if idx < rem else 0)
    return out


def _truncate_units_by_budget(units: List[DocumentUnit], *, budget: int) -> tuple[list[DocumentUnit], bool]:
    """按单元边界截断，避免把段落/公式/图表等切成两半。"""

    if budget is None or budget < 0:
        return units, False

    kept: List[DocumentUnit] = []
    used = 0
    for u in units:
        text = u.text.strip()
        if not text:
            continue

        sep = "\n\n" if kept else ""
        add_len = len(sep) + len(text)

        if kept and used + add_len > budget:
            return kept, True

        if not kept and len(text) > budget:
            # 单个单元就超过预算：不做硬切，直接放弃该文件（或未来可选保留摘要）
            return [], True

        kept.append(u)
        used += add_len

    return kept, False


def load_reference_corpus_from_dir(
    reference_dir: Path,
    *,
    exts: Sequence[str] = (".md", ".tex", ".txt", ".rst"),
    max_files: int | None = None,
    max_chars: int | None = None,
    recursive: bool = True,
    per_file_budget: bool = True,
) -> ReferenceCorpus:
    """从目录加载参考资料并合并为单一语料（按单元切分与截断）。

    Args:
        reference_dir: 参考资料目录（必须为绝对路径）。
        exts: 允许加载的文件后缀列表。
        max_files: 最多读取文件数（None 不限制）。
        max_chars: 总字符预算（None 不限制）。
        recursive: 是否递归扫描子目录。
        per_file_budget: max_chars 生效时是否按文件平均分配预算。

    Returns:
        ReferenceCorpus: 合并后的语料。

    Raises:
        ValueError: reference_dir 非绝对路径/不存在/不是目录。
    """

    if not reference_dir.is_absolute():
        raise ValueError(
            f"reference_materials_dir 必须为绝对路径（应由调度层提前绝对化）：{reference_dir}"
        )
    if not reference_dir.exists():
        raise ValueError(f"reference_materials_dir 不存在：{reference_dir}")
    if not reference_dir.is_dir():
        raise ValueError(f"reference_materials_dir 不是目录：{reference_dir}")

    exts_norm = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts}

    files_all = _iter_reference_files(reference_dir, exts_norm=exts_norm, recursive=bool(recursive))
    files = files_all[: max_files] if (max_files is not None and max_files >= 0) else files_all

    file_budgets = (
        _allocate_file_budgets(files, total_budget=int(max_chars))
        if (max_chars is not None and max_chars >= 0 and per_file_budget)
        else {p: (int(max_chars) if max_chars is not None else -1) for p in files}
    )

    parts: List[str] = []
    used_files: List[Path] = []
    truncated_any = False

    per_file: Dict[str, object] = {}

    for p in files:
        units = split_document_to_units(p)
        budget = int(file_budgets.get(p, -1))
        kept_units, trunc = _truncate_units_by_budget(units, budget=budget)
        truncated_any = truncated_any or trunc

        content = "\n\n".join([u.text.strip() for u in kept_units if u.text.strip()]).strip()
        if content:
            rel = str(p.relative_to(reference_dir)).replace("\\", "/")
            parts.append(f"\n\n---\n[参考资料: {rel}]\n---\n\n{content}\n")
            used_files.append(p)

        per_file[str(p)] = {
            "relative_path": str(p.relative_to(reference_dir)).replace("\\", "/"),
            "budget": budget,
            "units_total": len(units),
            "units_used": len(kept_units),
            "truncated": bool(trunc),
        }

    merged = "".join(parts).strip()

    # 兜底：当 per_file_budget=False 时，仍可能超出 max_chars，这里做整体硬截断（已显式关闭单元截断公平性）
    if max_chars is not None and max_chars >= 0 and (not per_file_budget) and len(merged) > int(max_chars):
        merged = merged[: int(max_chars)].rstrip()
        truncated_any = True

    debug: Dict[str, object] = {
        "recursive": bool(recursive),
        "exts": sorted(list(exts_norm)),
        "max_files": max_files,
        "max_chars": max_chars,
        "per_file_budget": bool(per_file_budget),
        "files_total": len(files_all),
        "files_used": [str(p) for p in used_files],
        "per_file": per_file,
    }

    return ReferenceCorpus(
        text=merged,
        files=used_files,
        truncated=bool(truncated_any),
        chars=len(merged),
        debug=debug,
    )
