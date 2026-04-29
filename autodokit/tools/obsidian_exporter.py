"""Obsidian 关联导出工具。

本模块提供可复用的 Obsidian 笔记依赖导出能力：
- 解析双链与附件引用；
- 递归发现关联笔记与附件；
- 生成导出计划并可执行复制；
- 输出结构化结果，供 affair 层写 manifest。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from typing import Dict, Iterable, List, Literal, Set, Tuple


LinkType = Literal["wikilink", "embed", "markdown_image"]


@dataclass
class LinkCandidate:
    """链接候选对象。

    Attributes:
        source_file: 链接来源文件。
        target_raw: 原始目标文本（未清洗）。
        link_type: 链接类型（双链 / 嵌入 / Markdown 图片）。
        is_note: 是否将目标作为笔记（.md）处理。
    """

    source_file: Path
    target_raw: str
    link_type: LinkType
    is_note: bool


@dataclass
class DependencyEdge:
    """依赖边。

    Attributes:
        source: 来源文件（相对 vault 根目录）。
        target: 目标文件（相对 vault 根目录）。
        link_type: 链接类型。
    """

    source: str
    target: str
    link_type: LinkType


@dataclass
class ObsidianExportResult:
    """导出结果。

    Attributes:
        vault_root: Vault 根目录绝对路径字符串。
        main_note_file: 主笔记绝对路径字符串。
        output_dir: 输出目录绝对路径字符串。
        dry_run: 是否为 dry-run。
        copied_files: 已复制文件相对路径列表。
        planned_files: 计划复制文件相对路径列表。
        missing_targets: 未解析到的目标列表。
        dependency_edges: 依赖边列表。
    """

    vault_root: str
    main_note_file: str
    output_dir: str
    dry_run: bool
    copied_files: List[str]
    planned_files: List[str]
    missing_targets: List[Dict[str, str]]
    dependency_edges: List[DependencyEdge]

    def to_dict(self) -> Dict[str, object]:
        """转为可序列化字典。

        Returns:
            Dict[str, object]: JSON 可序列化字典。
        """

        return {
            "vault_root": self.vault_root,
            "main_note_file": self.main_note_file,
            "output_dir": self.output_dir,
            "dry_run": self.dry_run,
            "copied_files": self.copied_files,
            "planned_files": self.planned_files,
            "missing_targets": self.missing_targets,
            "dependency_edges": [
                {"source": edge.source, "target": edge.target, "link_type": edge.link_type}
                for edge in self.dependency_edges
            ],
        }


_WIKILINK_RE = re.compile(r"(!?)\[\[([^\]]+)\]\]")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _normalize_target(raw_target: str) -> str:
    """清洗目标文本。

    Args:
        raw_target: 原始目标文本。

    Returns:
        str: 归一化后的目标文本。
    """

    normalized = raw_target.strip()
    if "|" in normalized:
        normalized = normalized.split("|", 1)[0].strip()
    if "#" in normalized:
        normalized = normalized.split("#", 1)[0].strip()
    return normalized


def _extract_link_candidates(note_path: Path) -> List[LinkCandidate]:
    """从单个 Markdown 笔记中抽取链接候选。

    Args:
        note_path: 笔记文件绝对路径。

    Returns:
        List[LinkCandidate]: 解析得到的候选项。
    """

    text = note_path.read_text(encoding="utf-8")
    candidates: List[LinkCandidate] = []

    for match in _WIKILINK_RE.finditer(text):
        exclamation = match.group(1)
        body = match.group(2)
        normalized = _normalize_target(body)
        if not normalized:
            continue
        is_embed = exclamation == "!"
        suffix = Path(normalized).suffix.lower()
        is_note = suffix in {"", ".md"}
        candidates.append(
            LinkCandidate(
                source_file=note_path,
                target_raw=normalized,
                link_type="embed" if is_embed else "wikilink",
                is_note=is_note,
            )
        )

    for match in _MD_IMAGE_RE.finditer(text):
        raw_inside = match.group(1).strip()
        if not raw_inside:
            continue
        # Markdown 图片语法允许 path "title"，这里仅取首段路径。
        target = raw_inside.split()[0].strip().strip('"').strip("'")
        if target.startswith("http://") or target.startswith("https://"):
            continue
        target = _normalize_target(target)
        if not target:
            continue
        candidates.append(
            LinkCandidate(
                source_file=note_path,
                target_raw=target,
                link_type="markdown_image",
                is_note=False,
            )
        )

    return candidates


def _build_vault_index(vault_root: Path) -> Tuple[Dict[str, Path], Dict[str, List[Path]], Dict[str, List[Path]]]:
    """构建 Vault 索引。

    Args:
        vault_root: Vault 根目录绝对路径。

    Returns:
        Tuple[Dict[str, Path], Dict[str, List[Path]], Dict[str, List[Path]]]:
            - 相对路径索引（带后缀，键为小写 posix）
            - 文件名索引（带后缀，键为小写文件名）
            - 文件名索引（不带后缀，键为小写 stem）
    """

    by_relpath: Dict[str, Path] = {}
    by_name: Dict[str, List[Path]] = {}
    by_stem: Dict[str, List[Path]] = {}

    for item in vault_root.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(vault_root).as_posix().lower()
        by_relpath[rel] = item

        name_key = item.name.lower()
        by_name.setdefault(name_key, []).append(item)

        stem_key = item.stem.lower()
        by_stem.setdefault(stem_key, []).append(item)

    return by_relpath, by_name, by_stem


def _candidate_paths_for_target(
    *,
    source_file: Path,
    vault_root: Path,
    target_raw: str,
    is_note: bool,
    by_relpath: Dict[str, Path],
    by_name: Dict[str, List[Path]],
    by_stem: Dict[str, List[Path]],
) -> List[Path]:
    """根据目标文本生成候选路径。

    Args:
        source_file: 来源文件绝对路径。
        vault_root: Vault 根目录绝对路径。
        target_raw: 清洗后的目标文本。
        is_note: 是否优先按笔记解析。
        by_relpath: 相对路径索引。
        by_name: 文件名索引。
        by_stem: stem 索引。

    Returns:
        List[Path]: 候选路径列表（按优先级排序，去重后返回）。
    """

    suffix = Path(target_raw).suffix.lower()
    target_for_note = target_raw if suffix or not is_note else f"{target_raw}.md"
    target_path = Path(target_for_note)

    candidates: List[Path] = []

    # 1) 相对 source 文件目录。
    candidates.append((source_file.parent / target_path).resolve())

    # 2) 相对 vault 根目录。
    candidates.append((vault_root / target_path).resolve())

    # 3) 用索引按相对路径直接匹配。
    rel_key = target_path.as_posix().lower()
    if rel_key in by_relpath:
        candidates.append(by_relpath[rel_key])

    # 4) 无路径时按 basename/stem 匹配。
    if "/" not in target_for_note and "\\" not in target_for_note:
        name_key = target_path.name.lower()
        stem_key = Path(target_for_note).stem.lower()
        if name_key in by_name:
            candidates.extend(by_name[name_key])
        if stem_key in by_stem:
            stem_candidates = by_stem[stem_key]
            if is_note:
                md_first = [item for item in stem_candidates if item.suffix.lower() == ".md"]
                non_md = [item for item in stem_candidates if item.suffix.lower() != ".md"]
                candidates.extend(md_first + non_md)
            else:
                candidates.extend(stem_candidates)

    # 去重并保序。
    seen: Set[Path] = set()
    ordered: List[Path] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)

    return ordered


def _pick_existing_file(candidates: Iterable[Path], *, vault_root: Path) -> Path | None:
    """从候选中选择一个存在且位于 vault 内的文件。

    Args:
        candidates: 候选路径序列。
        vault_root: Vault 根目录绝对路径。

    Returns:
        Path | None: 命中的文件路径；未命中返回 None。
    """

    root = vault_root.resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
        except Exception:
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def export_obsidian_note_with_links(
    *,
    vault_root: Path,
    main_note_file: Path,
    output_dir: Path,
    dry_run: bool,
    overwrite: bool,
    fail_on_missing: bool,
) -> ObsidianExportResult:
    """导出主笔记及其关联笔记/附件。

    Args:
        vault_root: Obsidian Vault 根目录绝对路径。
        main_note_file: 主笔记绝对路径。
        output_dir: 导出目录绝对路径。
        dry_run: 是否仅生成计划，不执行复制。
        overwrite: 目标文件存在时是否覆盖。
        fail_on_missing: 遇到未解析目标时是否抛错。

    Returns:
        ObsidianExportResult: 导出结果。

    Raises:
        ValueError: 路径不在 vault 内。
        FileExistsError: 目标文件存在且 overwrite=False。
        RuntimeError: 缺失目标且 fail_on_missing=True。

    Examples:
        >>> from pathlib import Path
        >>> result = export_obsidian_note_with_links(
        ...     vault_root=Path("/home/ethan/Vault"),
        ...     main_note_file=Path("/home/ethan/Vault/Projects/周会.md"),
        ...     output_dir=Path("/home/ethan/Export/周会包"),
        ...     dry_run=True,
        ...     overwrite=False,
        ...     fail_on_missing=False,
        ... )
        >>> isinstance(result.planned_files, list)
        True
    """

    root = vault_root.resolve()
    main_note = main_note_file.resolve()
    output_root = output_dir.resolve()

    try:
        main_note.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"main_note_file 不在 vault_root 内：{main_note}") from exc

    by_relpath, by_name, by_stem = _build_vault_index(root)

    notes_to_visit: List[Path] = [main_note]
    visited_notes: Set[Path] = set()
    all_files: Set[Path] = {main_note}
    dependency_edges: List[DependencyEdge] = []
    missing_targets: List[Dict[str, str]] = []

    while notes_to_visit:
        current_note = notes_to_visit.pop(0)
        if current_note in visited_notes:
            continue
        visited_notes.add(current_note)

        candidates = _extract_link_candidates(current_note)
        for candidate in candidates:
            candidate_paths = _candidate_paths_for_target(
                source_file=current_note,
                vault_root=root,
                target_raw=candidate.target_raw,
                is_note=candidate.is_note,
                by_relpath=by_relpath,
                by_name=by_name,
                by_stem=by_stem,
            )
            selected = _pick_existing_file(candidate_paths, vault_root=root)
            if selected is None:
                missing_targets.append(
                    {
                        "source": str(current_note.relative_to(root).as_posix()),
                        "target_raw": candidate.target_raw,
                        "link_type": candidate.link_type,
                    }
                )
                continue

            all_files.add(selected)
            dependency_edges.append(
                DependencyEdge(
                    source=current_note.relative_to(root).as_posix(),
                    target=selected.relative_to(root).as_posix(),
                    link_type=candidate.link_type,
                )
            )
            if selected.suffix.lower() == ".md" and selected not in visited_notes:
                notes_to_visit.append(selected)

    if missing_targets and fail_on_missing:
        missing_preview = "; ".join(f"{item['source']} -> {item['target_raw']}" for item in missing_targets[:5])
        raise RuntimeError(f"存在未解析目标（示例）：{missing_preview}")

    planned_sorted = sorted(all_files, key=lambda item: item.relative_to(root).as_posix())
    planned_relpaths = [item.relative_to(root).as_posix() for item in planned_sorted]

    copied_relpaths: List[str] = []
    if not dry_run:
        output_root.mkdir(parents=True, exist_ok=True)
        for source_file in planned_sorted:
            relpath = source_file.relative_to(root)
            target_file = (output_root / relpath).resolve()
            target_file.parent.mkdir(parents=True, exist_ok=True)
            if target_file.exists() and not overwrite:
                raise FileExistsError(f"目标文件已存在且 overwrite=False：{target_file}")
            shutil.copy2(source_file, target_file)
            copied_relpaths.append(relpath.as_posix())

    return ObsidianExportResult(
        vault_root=str(root),
        main_note_file=str(main_note),
        output_dir=str(output_root),
        dry_run=dry_run,
        copied_files=copied_relpaths,
        planned_files=planned_relpaths,
        missing_targets=missing_targets,
        dependency_edges=dependency_edges,
    )
