"""TeX DAG 扫描与重连工具。

用于扫描论文仓库中的 TeX 引用关系，并批量更新父子连接与 subfiles 根引用。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
import subprocess


INCLUDE_PATTERN = re.compile(r"\\(?P<kind>subfile|input|include)\{(?P<target>[^}]+)\}")
DOCCLASS_PATTERN = re.compile(r"\\documentclass\[(?P<root>[^\]]+)\]\{subfiles\}")
TEX_ROOT_MAGIC_PATTERN = re.compile(r"^(?P<prefix>\s*%\s*!TeX\s+root\s*=\s*)(?P<root>[^\s].*?)(?P<suffix>\s*)$")


@dataclass(frozen=True)
class TexEdge:
    source: Path
    target: Path
    kind: str
    raw_target: str
    line_no: int


@dataclass(frozen=True)
class TexRootRef:
    file: Path
    root: Path
    raw_root: str
    line_no: int


@dataclass(frozen=True)
class TexGraph:
    root_dir: Path
    edges: list[TexEdge]
    root_refs: dict[Path, TexRootRef]

    @property
    def parents_map(self) -> dict[Path, list[Path]]:
        return build_parents_map(self.edges)

    @property
    def children_map(self) -> dict[Path, list[Path]]:
        return build_children_map(self.edges)

    @property
    def node_paths(self) -> set[Path]:
        node_set: set[Path] = set()
        for edge in self.edges:
            node_set.add(edge.source)
            node_set.add(edge.target)
        node_set.update(self.root_refs.keys())
        node_set.update(ref.root for ref in self.root_refs.values())
        return node_set


def _to_posix(path: Path) -> str:
    return path.as_posix()


def strip_line_comment(line: str) -> str:
    escaped = False
    for index, char in enumerate(line):
        if char == "\\" and not escaped:
            escaped = True
            continue
        if char == "%" and not escaped:
            return line[:index]
        escaped = False
    return line


def ensure_tex_suffix(text: str) -> str:
    value = text.strip()
    if not value.lower().endswith(".tex"):
        return value + ".tex"
    return value


def resolve_reference(base_file: Path, target_text: str) -> Path:
    candidate = Path(ensure_tex_suffix(target_text))
    if candidate.is_absolute():
        return candidate.resolve()
    return (base_file.parent / candidate).resolve()


def repo_rel(root_dir: Path, path: Path) -> str:
    return _to_posix(path.resolve().relative_to(root_dir.resolve()))


def iter_tex_files(root_dir: Path, exclude_globs: Sequence[str]) -> Iterable[Path]:
    for path in root_dir.rglob("*.tex"):
        rel_text = _to_posix(path.relative_to(root_dir))
        excluded = any(path.match(pattern) or rel_text.startswith(pattern.rstrip("/**")) for pattern in exclude_globs)
        if excluded:
            continue
        yield path.resolve()


def parse_tex_graph(root_dir: str | Path, exclude_globs: Sequence[str] | None = None) -> TexGraph:
    root = Path(root_dir).resolve()
    edges: list[TexEdge] = []
    roots: dict[Path, TexRootRef] = {}
    exclude = list(exclude_globs or [])

    for tex_file in iter_tex_files(root, exclude):
        with tex_file.open("r", encoding="utf-8") as handle:
            for line_no, original_line in enumerate(handle, start=1):
                active_line = strip_line_comment(original_line)

                docclass_match = DOCCLASS_PATTERN.search(active_line)
                if docclass_match:
                    raw_root = docclass_match.group("root").strip()
                    roots[tex_file] = TexRootRef(
                        file=tex_file,
                        root=resolve_reference(tex_file, raw_root),
                        raw_root=raw_root,
                        line_no=line_no,
                    )

                for include_match in INCLUDE_PATTERN.finditer(active_line):
                    raw_target = include_match.group("target").strip()
                    edges.append(
                        TexEdge(
                            source=tex_file,
                            target=resolve_reference(tex_file, raw_target),
                            kind=include_match.group("kind"),
                            raw_target=raw_target,
                            line_no=line_no,
                        )
                    )
    return TexGraph(root_dir=root, edges=edges, root_refs=roots)


def build_children_map(edges: Sequence[TexEdge]) -> dict[Path, list[Path]]:
    children: dict[Path, list[Path]] = {}
    for edge in edges:
        children.setdefault(edge.source, []).append(edge.target)
    return children


def build_parents_map(edges: Sequence[TexEdge]) -> dict[Path, list[Path]]:
    parents: dict[Path, list[Path]] = {}
    for edge in edges:
        parents.setdefault(edge.target, []).append(edge.source)
    return parents


def infer_root_for_parent(parent_file: Path, root_refs: dict[Path, TexRootRef]) -> Path:
    if parent_file in root_refs:
        return root_refs[parent_file].root
    return parent_file.resolve()


def descendants(start: Path, children_map: dict[Path, list[Path]]) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    stack = [start]
    while stack:
        current = stack.pop()
        for child in children_map.get(current, []):
            if child in seen:
                continue
            seen.add(child)
            ordered.append(child)
            stack.append(child)
    return ordered


def relative_tex_reference(from_file: Path, to_file: Path, keep_extension: bool) -> str:
    ref = os.path.relpath(str(to_file.resolve()), start=str(from_file.resolve().parent))
    ref = _to_posix(Path(ref))
    if not keep_extension and ref.lower().endswith(".tex"):
        ref = ref[:-4]
    return ref


def update_parent_edge(parent_file: Path, old_target: Path, new_target: Path, dry_run: bool = False) -> tuple[int, list[str]]:
    changed = 0
    previews: list[str] = []
    lines = parent_file.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines: list[str] = []
    for line_no, original_line in enumerate(lines, start=1):
        active_line = strip_line_comment(original_line)
        matches = list(INCLUDE_PATTERN.finditer(active_line))
        updated_line = original_line
        for match in reversed(matches):
            raw_target = match.group("target").strip()
            resolved = resolve_reference(parent_file, raw_target)
            if resolved != old_target.resolve():
                continue
            keep_extension = raw_target.lower().endswith(".tex")
            replacement = relative_tex_reference(parent_file, new_target, keep_extension)
            if raw_target == replacement:
                continue
            start, end = match.span("target")
            previews.append(f"{parent_file}:{line_no}: {raw_target} -> {replacement}")
            updated_line = updated_line[:start] + replacement + updated_line[end:]
            changed += 1
        new_lines.append(updated_line)
    if changed and not dry_run:
        parent_file.write_text("".join(new_lines), encoding="utf-8")
    return changed, previews


def update_subfiles_root(file_path: Path, new_root: Path, dry_run: bool = False) -> tuple[bool, list[str]]:
    lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = False
    previews: list[str] = []
    replacement = relative_tex_reference(file_path, new_root, keep_extension=True)
    new_lines: list[str] = []
    for line_no, original_line in enumerate(lines, start=1):
        updated_line = original_line
        active_line = strip_line_comment(updated_line)

        docclass_match = DOCCLASS_PATTERN.search(active_line)
        if docclass_match:
            current_root = docclass_match.group("root").strip()
            if current_root != replacement:
                start, end = docclass_match.span("root")
                updated_line = updated_line[:start] + replacement + updated_line[end:]
                previews.append(f"{file_path}:{line_no}: subfiles-root {current_root} -> {replacement}")
                changed = True

        magic_source = updated_line.rstrip("\r\n")
        bom_prefix = ""
        if magic_source.startswith("\ufeff"):
            bom_prefix = "\ufeff"
            magic_source = magic_source[1:]
        magic_match = TEX_ROOT_MAGIC_PATTERN.match(magic_source)
        if magic_match:
            current_root = magic_match.group("root").strip()
            if current_root != replacement:
                line_ending = ""
                if updated_line.endswith("\r\n"):
                    line_ending = "\r\n"
                elif updated_line.endswith("\n"):
                    line_ending = "\n"
                updated_line = (
                    f"{bom_prefix}{magic_match.group('prefix')}{replacement}{magic_match.group('suffix')}{line_ending}"
                )
                previews.append(f"{file_path}:{line_no}: tex-root {current_root} -> {replacement}")
                changed = True

        new_lines.append(updated_line)
    if changed and not dry_run:
        file_path.write_text("".join(new_lines), encoding="utf-8")
    return changed, previews


def graph_payload(graph: TexGraph) -> dict[str, Any]:
    node_set = graph.node_paths
    parents_map = graph.parents_map
    children_map = graph.children_map

    nodes: list[dict[str, Any]] = []
    for node in sorted(node_set):
        nodes.append(
            {
                "path": repo_rel(graph.root_dir, node),
                "parents": sorted(repo_rel(graph.root_dir, parent) for parent in parents_map.get(node, [])),
                "children": sorted(repo_rel(graph.root_dir, child) for child in children_map.get(node, [])),
                "subfiles_root": repo_rel(graph.root_dir, graph.root_refs[node].root) if node in graph.root_refs else None,
            }
        )

    edge_items = [
        {
            "source": repo_rel(graph.root_dir, edge.source),
            "target": repo_rel(graph.root_dir, edge.target),
            "kind": edge.kind,
            "line": edge.line_no,
            "raw_target": edge.raw_target,
        }
        for edge in sorted(graph.edges, key=lambda item: (repo_rel(graph.root_dir, item.source), item.line_no, item.kind))
    ]

    root_items = [
        {
            "file": repo_rel(graph.root_dir, root_ref.file),
            "root": repo_rel(graph.root_dir, root_ref.root),
            "line": root_ref.line_no,
            "raw_root": root_ref.raw_root,
        }
        for root_ref in sorted(graph.root_refs.values(), key=lambda item: repo_rel(graph.root_dir, item.file))
    ]

    return {"root_dir": str(graph.root_dir.resolve()), "nodes": nodes, "edges": edge_items, "subfiles_roots": root_items}


def render_mermaid(graph: TexGraph) -> str:
    node_set = graph.node_paths
    id_map: dict[Path, str] = {path: f"N{index}" for index, path in enumerate(sorted(node_set), start=1)}
    lines = ["graph TD"]
    for path in sorted(node_set):
        label = repo_rel(graph.root_dir, path).replace('"', "'")
        lines.append(f'    {id_map[path]}["{label}"]')
    for edge in graph.edges:
        lines.append(f"    {id_map[edge.source]} -->|{edge.kind}| {id_map[edge.target]}")
    for root_ref in graph.root_refs.values():
        lines.append(f"    {id_map[root_ref.file]} -.root.-> {id_map[root_ref.root]}")
    return "\n".join(lines) + "\n"


def render_dot(graph: TexGraph) -> str:
    node_set = graph.node_paths
    id_map: dict[Path, str] = {path: f"n{index}" for index, path in enumerate(sorted(node_set), start=1)}
    lines = ["digraph tex_dag {", "  rankdir=LR;"]
    for path in sorted(node_set):
        label = repo_rel(graph.root_dir, path).replace('"', '\\"')
        lines.append(f'  {id_map[path]} [label="{label}"];')
    for edge in graph.edges:
        lines.append(f'  {id_map[edge.source]} -> {id_map[edge.target]} [label="{edge.kind}"];')
    for root_ref in graph.root_refs.values():
        lines.append(f'  {id_map[root_ref.file]} -> {id_map[root_ref.root]} [style=dashed,label="root"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_text_summary(graph: TexGraph) -> str:
    parents_map = graph.parents_map
    children_map = graph.children_map
    node_set = set(children_map.keys()) | set(parents_map.keys()) | set(graph.root_refs.keys()) | {r.root for r in graph.root_refs.values()}
    lines: list[str] = []
    for node in sorted(node_set):
        lines.append(f"FILE {repo_rel(graph.root_dir, node)}")
        if node in graph.root_refs:
            lines.append(f"  ROOT   {repo_rel(graph.root_dir, graph.root_refs[node].root)}")
        for child in sorted(children_map.get(node, [])):
            lines.append(f"  CHILD  {repo_rel(graph.root_dir, child)}")
        for parent in sorted(parents_map.get(node, [])):
            lines.append(f"  PARENT {repo_rel(graph.root_dir, parent)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_output(text: str, output: Optional[Path]) -> None:
    if output is None:
        sys.stdout.write(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def resolve_user_path(root_dir: Path, value: str) -> Path:
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else (root_dir / candidate)
    if path.suffix.lower() != ".tex":
        path = path.with_suffix(".tex")
    return path.resolve()


def _derive_clone_target_path(source_path: Path, from_tag: str | None, to_tag: str) -> Path:
    source_name = source_path.name
    if from_tag:
        if from_tag not in source_name:
            raise ValueError(f"源文件名未包含 from_tag={from_tag}: {source_path}")
        target_name = source_name.replace(from_tag, to_tag)
    else:
        if source_name.lower().endswith(".tex"):
            target_name = source_name[:-4] + f"_{to_tag}.tex"
        else:
            target_name = source_name + f"_{to_tag}"
    return source_path.with_name(target_name)


def _resolve_clone_map(
    *,
    root: Path,
    source_files: Sequence[str | Path],
    from_tag: str | None,
    to_tag: str,
    target_files: Sequence[str | Path] | None,
) -> dict[Path, Path]:
    resolved_sources = [resolve_user_path(root, str(item)) for item in source_files]
    if not resolved_sources:
        raise ValueError("source_files 不能为空。")

    clone_map: dict[Path, Path] = {}
    if target_files:
        resolved_targets = [resolve_user_path(root, str(item)) for item in target_files]
        if len(resolved_targets) != len(resolved_sources):
            raise ValueError("target_files 数量必须与 source_files 相同。")
        for source, target in zip(resolved_sources, resolved_targets):
            clone_map[source] = target
    else:
        for source in resolved_sources:
            clone_map[source] = _derive_clone_target_path(source, from_tag=from_tag, to_tag=to_tag)

    target_values = list(clone_map.values())
    if len(set(target_values)) != len(target_values):
        raise ValueError("推导得到重复的目标文件路径，请检查 from_tag/to_tag 或 target_files。")
    return clone_map


def _rewrite_cloned_file_links(
    file_path: Path,
    clone_map: dict[Path, Path],
    dry_run: bool,
    source_file_for_dry_run: Path | None = None,
) -> list[str]:
    previews: list[str] = []
    read_from = source_file_for_dry_run if dry_run and source_file_for_dry_run is not None else file_path
    lines = read_from.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines: list[str] = []

    for line_no, original_line in enumerate(lines, start=1):
        updated_line = original_line
        active_line = strip_line_comment(updated_line)

        include_matches = list(INCLUDE_PATTERN.finditer(active_line))
        for match in reversed(include_matches):
            raw_target = match.group("target").strip()
            resolved = resolve_reference(file_path, raw_target)
            if resolved not in clone_map:
                continue
            keep_extension = raw_target.lower().endswith(".tex")
            replacement = relative_tex_reference(file_path, clone_map[resolved], keep_extension=keep_extension)
            if replacement == raw_target:
                continue
            start, end = match.span("target")
            updated_line = updated_line[:start] + replacement + updated_line[end:]
            previews.append(f"{file_path}:{line_no}: include {raw_target} -> {replacement}")

        active_line = strip_line_comment(updated_line)
        docclass_match = DOCCLASS_PATTERN.search(active_line)
        if docclass_match:
            raw_root = docclass_match.group("root").strip()
            resolved_root = resolve_reference(file_path, raw_root)
            if resolved_root in clone_map:
                replacement_root = relative_tex_reference(file_path, clone_map[resolved_root], keep_extension=True)
                if replacement_root != raw_root:
                    start, end = docclass_match.span("root")
                    updated_line = updated_line[:start] + replacement_root + updated_line[end:]
                    previews.append(f"{file_path}:{line_no}: subfiles-root {raw_root} -> {replacement_root}")

        magic_source = updated_line.rstrip("\r\n")
        bom_prefix = ""
        if magic_source.startswith("\ufeff"):
            bom_prefix = "\ufeff"
            magic_source = magic_source[1:]
        magic_match = TEX_ROOT_MAGIC_PATTERN.match(magic_source)
        if magic_match:
            raw_root = magic_match.group("root").strip()
            resolved_root = resolve_reference(file_path, raw_root)
            if resolved_root in clone_map:
                replacement_root = relative_tex_reference(file_path, clone_map[resolved_root], keep_extension=True)
                if replacement_root != raw_root:
                    line_ending = ""
                    if updated_line.endswith("\r\n"):
                        line_ending = "\r\n"
                    elif updated_line.endswith("\n"):
                        line_ending = "\n"
                    updated_line = (
                        f"{bom_prefix}{magic_match.group('prefix')}{replacement_root}{magic_match.group('suffix')}{line_ending}"
                    )
                    previews.append(f"{file_path}:{line_no}: tex-root {raw_root} -> {replacement_root}")

        new_lines.append(updated_line)

    if previews and not dry_run:
        file_path.write_text("".join(new_lines), encoding="utf-8")
    return previews


def compile_tex(tex_path: Path, timeout_seconds: int = 120) -> dict[str, Any]:
    """Run xelatex on the given tex file in its directory and return result.

    Returns dict with keys: returncode, stdout, stderr.
    """
    cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", str(tex_path.name)]
    try:
        proc = subprocess.run(cmd, cwd=str(tex_path.parent), capture_output=True, text=True, timeout=timeout_seconds)
        return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired as exc:
        return {"returncode": -1, "stdout": getattr(exc, "stdout", ""), "stderr": "timeout"}


def clone_tex_version(
    *,
    root_dir: str | Path = ".",
    source_files: Sequence[str | Path],
    to_tag: str,
    from_tag: str | None = None,
    target_files: Sequence[str | Path] | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    compile: bool = False,
    compile_target: str | Path | None = None,
    compile_timeout: int = 120,
) -> dict[str, Any]:
    root = Path(root_dir).resolve()
    clone_map = _resolve_clone_map(
        root=root,
        source_files=source_files,
        from_tag=from_tag,
        to_tag=to_tag,
        target_files=target_files,
    )

    missing_sources = [item for item in clone_map if not item.exists()]
    if missing_sources:
        raise FileNotFoundError("以下源文件不存在:\n" + "\n".join(str(item) for item in missing_sources))

    existing_targets = [item for item in clone_map.values() if item.exists() and not overwrite]
    if existing_targets:
        raise FileExistsError(
            "以下目标文件已存在（如需覆盖请设置 overwrite=True）:\n" + "\n".join(str(item) for item in existing_targets)
        )

    copied_pairs: list[tuple[Path, Path]] = []
    for source_file, target_file in clone_map.items():
        copied_pairs.append((source_file, target_file))
        if dry_run:
            continue
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target_file)

    rewrite_previews: list[str] = []
    for source_file, target_file in copied_pairs:
        file_previews = _rewrite_cloned_file_links(
            target_file,
            clone_map=clone_map,
            dry_run=dry_run,
            source_file_for_dry_run=source_file,
        )
        rewrite_previews.extend(file_previews)

    result: dict[str, Any] = {
        "status": "PASS",
        "dry_run": dry_run,
        "overwrite": overwrite,
        "copied": [{"source": str(src), "target": str(dst)} for src, dst in copied_pairs],
        "rewrites": rewrite_previews,
    }

    # optional compile step
    if compile:
        if dry_run:
            # preview compile command
            cmd_preview = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", str(Path(compile_target).name if compile_target else next(iter(clone_map.values())).name)]
            result["compile_preview"] = {"cmd": cmd_preview, "cwd": str(Path(root_dir))}
        else:
            if compile_target:
                compile_path = Path(root_dir) / Path(compile_target)
            else:
                # pick first target that is likely a root
                compile_path = Path(root_dir) / next(iter(clone_map.values()))
            compile_res = compile_tex(compile_path, timeout_seconds=compile_timeout)
            result["compile"] = {"target": str(compile_path), **compile_res}

    return result


def scan_tex_graph(root_dir: str | Path = ".", exclude_glob: Sequence[str] | None = None) -> TexGraph:
    return parse_tex_graph(root_dir=root_dir, exclude_globs=exclude_glob)


def export_tex_graph(
    root_dir: str | Path = ".",
    *,
    format: str = "text",
    output: str | Path | None = None,
    exclude_glob: Sequence[str] | None = None,
) -> TexGraph:
    graph = scan_tex_graph(root_dir=root_dir, exclude_glob=exclude_glob)
    if format == "json":
        write_output(json.dumps(graph_payload(graph), ensure_ascii=False, indent=2) + "\n", Path(output) if output else None)
    elif format == "mermaid":
        write_output(render_mermaid(graph), Path(output) if output else None)
    elif format == "dot":
        write_output(render_dot(graph), Path(output) if output else None)
    else:
        write_output(render_text_summary(graph), Path(output) if output else None)
    return graph


def rewire_tex_reference(
    *,
    root_dir: str | Path = ".",
    parent: str | Path,
    old_target: str | Path,
    new_target: str | Path,
    sync_root: bool = False,
    recursive: bool = False,
    dry_run: bool = False,
    exclude_glob: Sequence[str] | None = None,
) -> dict[str, Any]:
    root = Path(root_dir).resolve()
    parent_file = resolve_user_path(root, str(parent))
    old_path = resolve_user_path(root, str(old_target))
    new_path = resolve_user_path(root, str(new_target))

    if not parent_file.exists():
        raise FileNotFoundError(f"父文件不存在: {parent_file}")
    if not old_path.exists():
        raise FileNotFoundError(f"旧目标不存在: {old_path}")
    if not new_path.exists():
        raise FileNotFoundError(f"新目标不存在: {new_path}")

    graph = scan_tex_graph(root_dir=root, exclude_glob=exclude_glob)
    changed_edges, previews = update_parent_edge(parent_file, old_path, new_path, dry_run=dry_run)
    if changed_edges == 0:
        return {"status": "EMPTY", "changed_edges": 0, "previews": [], "dry_run": dry_run}

    changed_files: list[Path] = []
    root_previews: list[str] = []
    if sync_root:
        new_root = infer_root_for_parent(parent_file, graph.root_refs)
        changed, previews_for_file = update_subfiles_root(new_path, new_root, dry_run=dry_run)
        if changed:
            changed_files.append(new_path)
            root_previews.extend(previews_for_file)

        if recursive:
            for descendant_file in descendants(new_path, graph.children_map):
                changed, previews_for_file = update_subfiles_root(descendant_file, new_root, dry_run=dry_run)
                if changed:
                    changed_files.append(descendant_file)
                    root_previews.extend(previews_for_file)

    return {
        "status": "PASS",
        "dry_run": dry_run,
        "parent": str(parent_file),
        "old_target": str(old_path),
        "new_target": str(new_path),
        "changed_edges": changed_edges,
        "previews": previews,
        "synced_root_files": [str(item) for item in changed_files],
        "root_previews": root_previews,
    }


def set_tex_root(
    *,
    root_dir: str | Path = ".",
    file: str | Path,
    root: str | Path,
    recursive: bool = False,
    dry_run: bool = False,
    exclude_glob: Sequence[str] | None = None,
) -> dict[str, Any]:
    workspace_root = Path(root_dir).resolve()
    target_file = resolve_user_path(workspace_root, str(file))
    new_root = resolve_user_path(workspace_root, str(root))

    if not target_file.exists():
        raise FileNotFoundError(f"目标文件不存在: {target_file}")
    if not new_root.exists():
        raise FileNotFoundError(f"根文件不存在: {new_root}")

    graph = scan_tex_graph(root_dir=workspace_root, exclude_glob=exclude_glob)
    changed_files: list[Path] = []
    previews: list[str] = []

    changed, previews_for_file = update_subfiles_root(target_file, new_root, dry_run=dry_run)
    if changed:
        changed_files.append(target_file)
        previews.extend(previews_for_file)

    if recursive:
        for descendant_file in descendants(target_file, graph.children_map):
            changed, previews_for_file = update_subfiles_root(descendant_file, new_root, dry_run=dry_run)
            if changed:
                changed_files.append(descendant_file)
                previews.extend(previews_for_file)

    if not changed_files:
        return {"status": "EMPTY", "changed_files": [], "previews": [], "dry_run": dry_run}

    return {
        "status": "PASS",
        "dry_run": dry_run,
        "file": str(target_file),
        "root": str(new_root),
        "changed_files": [str(item) for item in changed_files],
        "previews": previews,
    }


def cmd_graph(args: argparse.Namespace) -> int:
    graph = scan_tex_graph(root_dir=args.root_dir, exclude_glob=args.exclude_glob)
    export_tex_graph(root_dir=graph.root_dir, format=args.format, output=args.output, exclude_glob=args.exclude_glob)
    return 0


def cmd_rewire(args: argparse.Namespace) -> int:
    result = rewire_tex_reference(
        root_dir=args.root_dir,
        parent=args.parent,
        old_target=args.old_target,
        new_target=args.new_target,
        sync_root=args.sync_root,
        recursive=args.recursive,
        dry_run=args.dry_run,
        exclude_glob=args.exclude_glob,
    )
    if result.get("status") == "EMPTY":
        print("未在父文件中找到匹配的引用边。", file=sys.stderr)
        return 3

    if args.dry_run:
        print(f"预演：将在父文件中更新 {result['changed_edges']} 处引用。")
    else:
        print(f"已在父文件中更新 {result['changed_edges']} 处引用。")
    for preview in result.get("previews", []):
        print(f"  {preview}")

    changed_root_files = result.get("synced_root_files", [])
    root_previews = result.get("root_previews", [])
    if changed_root_files:
        if args.dry_run:
            print("预演：将同步更新以下文件的 subfiles 根引用:")
        else:
            print("已同步更新以下文件的 subfiles 根引用:")
        for item in changed_root_files:
            print(f"  {repo_rel(Path(args.root_dir).resolve(), Path(item))}")
        for preview in root_previews:
            print(f"    {preview}")
    elif args.sync_root:
        print("没有检测到需要同步更新的 subfiles 根引用。")
    return 0


def cmd_set_root(args: argparse.Namespace) -> int:
    result = set_tex_root(
        root_dir=args.root_dir,
        file=args.file,
        root=args.root,
        recursive=args.recursive,
        dry_run=args.dry_run,
        exclude_glob=args.exclude_glob,
    )
    if result.get("status") == "EMPTY":
        print("未找到可更新的 subfiles 根引用。")
        return 0

    if args.dry_run:
        print("预演：将更新以下文件的 subfiles 根引用:")
    else:
        print("已更新以下文件的 subfiles 根引用:")
    for item in result.get("changed_files", []):
        print(f"  {repo_rel(Path(args.root_dir).resolve(), Path(item))}")
    for item in result.get("previews", []):
        print(f"    {item}")
    return 0


def cmd_clone_version(args: argparse.Namespace) -> int:
    result = clone_tex_version(
        root_dir=args.root_dir,
        source_files=args.source,
        to_tag=args.to_tag,
        from_tag=args.from_tag,
        target_files=args.target,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        compile=args.compile if hasattr(args, "compile") else False,
        compile_target=args.compile_target if hasattr(args, "compile_target") else None,
        compile_timeout=args.compile_timeout if hasattr(args, "compile_timeout") else 120,
    )
    if args.dry_run:
        print("预演：将复制以下文件:")
    else:
        print("已复制以下文件:")
    root = Path(args.root_dir).resolve()
    for pair in result.get("copied", []):
        print(f"  {repo_rel(root, Path(pair['source']))} -> {repo_rel(root, Path(pair['target']))}")

    rewrites = result.get("rewrites", [])
    if rewrites:
        if args.dry_run:
            print("预演：将同步更新以下关联引用:")
        else:
            print("已同步更新以下关联引用:")
        for preview in rewrites:
            print(f"  {preview}")
    else:
        print("未检测到需要重写的内部引用。")
    # compile feedback
    if "compile_preview" in result:
        print("预演：如果执行，将运行以下编译命令:")
        preview = result["compile_preview"]
        print(f"  cwd: {preview.get('cwd')}")
        print(f"  cmd: {' '.join(preview.get('cmd', []))}")
    if "compile" in result:
        comp = result["compile"]
        status = comp.get("returncode")
        print(f"编译目标: {comp.get('target')}")
        if status == 0:
            print("编译成功 (returncode=0)")
        elif status == -1:
            print("编译超时或被中止")
        else:
            print(f"编译失败 (returncode={status})")
        stdout = comp.get("stdout", "")
        stderr = comp.get("stderr", "")
        if stdout:
            print("编译 stdout 摘要:")
            for line in stdout.splitlines()[-10:]:
                print(f"  {line}")
        if stderr:
            print("编译 stderr 摘要:")
            for line in stderr.splitlines()[-10:]:
                print(f"  {line}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="扫描 TeX DAG，并更新父子引用与 subfiles 根引用。")
    parser.add_argument("--root-dir", default=".", help="论文根目录")
    parser.add_argument(
        "--exclude-glob",
        action="append",
        default=[],
        help="排除的 glob，例如 backups/** 或 **/exports/**，可重复指定",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    graph_parser = subparsers.add_parser("graph", help="导出引用关系图")
    graph_parser.add_argument("--format", choices=["json", "mermaid", "dot", "text"], default="text")
    graph_parser.add_argument("--output", type=Path, default=None, help="输出文件路径")
    graph_parser.set_defaults(func=cmd_graph)

    rewire_parser = subparsers.add_parser("rewire", help="把父文件中的旧子节点引用改为新子节点")
    rewire_parser.add_argument("--parent", required=True, help="父 tex 文件，相对 root-dir 或绝对路径")
    rewire_parser.add_argument("--old-target", required=True, help="旧子 tex 文件")
    rewire_parser.add_argument("--new-target", required=True, help="新子 tex 文件")
    rewire_parser.add_argument("--sync-root", action="store_true", help="同步更新新子文件的 subfiles 根引用")
    rewire_parser.add_argument("--recursive", action="store_true", help="递归同步新子树的 subfiles 根引用")
    rewire_parser.add_argument("--dry-run", action="store_true", help="只预演，不写回文件")
    rewire_parser.set_defaults(func=cmd_rewire)

    set_root_parser = subparsers.add_parser("set-root", help="设置某个 subfile 或其子树的根文件")
    set_root_parser.add_argument("--file", required=True, help="目标 tex 文件")
    set_root_parser.add_argument("--root", required=True, help="新的主根 tex 文件")
    set_root_parser.add_argument("--recursive", action="store_true", help="递归更新整个子树")
    set_root_parser.add_argument("--dry-run", action="store_true", help="只预演，不写回文件")
    set_root_parser.set_defaults(func=cmd_set_root)

    clone_parser = subparsers.add_parser("clone-version", help="复制一组 tex 源文件为新版本，并保持组内关联引用")
    clone_parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="源 tex 文件，可重复指定多次",
    )
    clone_parser.add_argument(
        "--target",
        action="append",
        default=None,
        help="目标 tex 文件，可重复指定；若不提供则按 from-tag/to-tag 推导",
    )
    clone_parser.add_argument("--from-tag", default=None, help="源文件名中的旧版本标记（可选）")
    clone_parser.add_argument("--to-tag", required=True, help="新版本标记，用于目标文件名推导")
    clone_parser.add_argument("--overwrite", action="store_true", help="允许覆盖已存在的目标文件")
    clone_parser.add_argument("--dry-run", action="store_true", help="只预演，不写回文件")
    clone_parser.add_argument("--compile", action="store_true", help="复制后编译主文件（仅在非 dry-run 时执行）")
    clone_parser.add_argument(
        "--compile-target",
        default=None,
        help="要编译的主文件（相对 root-dir 或绝对路径），若未提供将使用推导的第一个目标",
    )
    clone_parser.add_argument("--compile-timeout", type=int, default=120, help="编译超时秒数")
    clone_parser.set_defaults(func=cmd_clone_version)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1


__all__ = [
    "TexEdge",
    "TexRootRef",
    "TexGraph",
    "scan_tex_graph",
    "export_tex_graph",
    "render_mermaid",
    "render_dot",
    "render_text_summary",
    "rewire_tex_reference",
    "set_tex_root",
    "clone_tex_version",
    "build_parser",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())