#!/usr/bin/env python3
r"""
math_delimiter_converter: 专用模块，将 Markdown/LaTeX 文档中的数学定界符转换为 TeX 原生形式。

- 将展示数学 `$$...$$` -> `\[...\]`
- 将行内数学 `$...$` -> `\(...\)`

保留原脚本的行为与边界（跳过 verbatim/listing/minted 等环境、保留注释行、跳过已存在的 `\(...\)`/`\[...\]`）。
提供可导入的 API：`convert_text(tex)`、`process_file(input_path, output_path, ...)` 与 `collect_unescaped_dollar_lines(tex)`。
"""
from __future__ import annotations

import io
import re
import shutil
import os
from typing import List, Tuple

SKIP_ENVS = [
    'verbatim', 'Verbatim', 'lstlisting', 'minted',
    'equation', 'equation*', 'align', 'align*', 'gather', 'gather*',
    'multline', 'multline*', 'eqnarray', 'split', 'flalign', 'math'
]

MAX_DRY_RUN_EXAMPLES = 12


def is_unescaped_at(s: str, pos: int) -> bool:
    bs = 0
    k = pos - 1
    while k >= 0 and s[k] == '\\':
        bs += 1
        k -= 1
    return bs % 2 == 0


def find_unescaped(s: str, delim: str, start: int = 0, stop_at_newline: bool = False) -> int:
    i = s.find(delim, start)
    while i != -1:
        if stop_at_newline:
            newline_pos = s.find('\n', start, i)
            if newline_pos != -1:
                return -1
        if is_unescaped_at(s, i):
            return i
        i = s.find(delim, i + 1)
    return -1


def clip_text(text: str, limit: int = 80) -> str:
    compact = ' '.join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + '...'


def build_skip_ranges(tex: str) -> List[Tuple[int, int]]:
    ranges: List[Tuple[int, int]] = []
    for env in SKIP_ENVS:
        pattern = re.compile(r'\\begin\{' + re.escape(env) + r'\}.*?\\end\{' + re.escape(env) + r'\}', re.DOTALL)
        for m in pattern.finditer(tex):
            ranges.append((m.start(), m.end()))

    for pat in (r'\\\(.*?\\\)', r'\\\[.*?\\\]'):
        for m in re.finditer(pat, tex, re.DOTALL):
            ranges.append((m.start(), m.end()))

    if not ranges:
        return []
    ranges.sort()
    merged: List[Tuple[int, int]] = []
    cur_s, cur_e = ranges[0]
    for s, e in ranges[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))
    return merged


def collect_unescaped_dollar_lines(tex: str, max_items: int = 20) -> Tuple[int, List[Tuple[int, str]]]:
    line_starts = [0]
    for idx, ch in enumerate(tex):
        if ch == '\n':
            line_starts.append(idx + 1)

    def pos_to_line(pos: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if line_starts[mid] <= pos:
                lo = mid + 1
            else:
                hi = mid - 1
        return hi + 1

    lines = tex.splitlines()
    markers = []
    for m in re.finditer(r'\$', tex):
        pos = m.start()
        if is_unescaped_at(tex, pos):
            markers.append(pos)

    samples: List[Tuple[int, str]] = []
    seen = set()
    for pos in markers:
        line_no = pos_to_line(pos)
        if line_no in seen:
            continue
        seen.add(line_no)
        line_text = lines[line_no - 1] if 1 <= line_no <= len(lines) else ''
        samples.append((line_no, clip_text(line_text, 120)))
        if len(samples) >= max_items:
            break
    return len(markers), samples


def convert_text(tex: str) -> Tuple[str, int, int, List[Tuple[str, str, str]]]:
    ranges = build_skip_ranges(tex)
    n = len(tex)
    i = 0
    out_parts: List[str] = []
    inline_count = 0
    display_count = 0
    examples: List[Tuple[str, str, str]] = []

    while i < n:
        skipped = False
        for s, e in ranges:
            if i == s:
                out_parts.append(tex[s:e])
                i = e
                skipped = True
                break
            if s > i:
                break
        if skipped:
            continue

        ch = tex[i]
        if ch == '%' and is_unescaped_at(tex, i):
            j = tex.find('\n', i)
            if j == -1:
                out_parts.append(tex[i:])
                break
            out_parts.append(tex[i:j+1])
            i = j + 1
            continue

        if tex.startswith('$$', i) and is_unescaped_at(tex, i):
            j = find_unescaped(tex, '$$', i + 2)
            if j != -1:
                inner = tex[i+2:j]
                replacement = '\\[' + inner + '\\]'
                out_parts.append(replacement)
                display_count += 1
                if len(examples) < MAX_DRY_RUN_EXAMPLES:
                    examples.append(('display', clip_text('$$' + inner + '$$'), clip_text(replacement)))
                i = j + 2
                continue

        if ch == '$' and is_unescaped_at(tex, i):
            if tex.startswith('$$', i):
                out_parts.append('$')
                i += 1
                continue
            j = find_unescaped(tex, '$', i + 1, stop_at_newline=True)
            if j != -1:
                inner = tex[i+1:j]
                replacement = '\\(' + inner + '\\)'
                out_parts.append(replacement)
                inline_count += 1
                if len(examples) < MAX_DRY_RUN_EXAMPLES:
                    examples.append(('inline', clip_text('$' + inner + '$'), clip_text(replacement)))
                i = j + 1
                continue
        out_parts.append(ch)
        i += 1

    return ''.join(out_parts), inline_count, display_count, examples


def process_file(input_path: str, output_path: str, backup: bool = True, dry_run: bool = False) -> None:
    with io.open(input_path, 'r', encoding='utf-8') as f:
        tex = f.read()

    new_tex, inline_count, display_count, examples = convert_text(tex)
    remaining_markers, remaining_samples = collect_unescaped_dollar_lines(new_tex)

    if new_tex == tex:
        print('未发现需替换的数学定界符。')
        print(f'当前文件未转义 $ 数量: {remaining_markers}')
        if remaining_markers > 0 and remaining_samples:
            print('--- 未转义 $ 示例行（可能是未闭合或非数学用途）---')
            for line_no, content in remaining_samples:
                print(f'  L{line_no}: {content}')
        if dry_run:
            return
    else:
        print('检测到并完成替换。')
        print(f'行内公式替换数量: {inline_count}')
        print(f'行间公式替换数量: {display_count}')
        print(f'替换后未转义 $ 数量: {remaining_markers}')
        if remaining_markers > 0 and remaining_samples:
            print('--- 未转义 $ 示例行（可能是未闭合或非数学用途）---')
            for line_no, content in remaining_samples:
                print(f'  L{line_no}: {content}')

    if dry_run:
        if examples:
            print('--- dry-run 示例替换 ---')
            for index, (kind, before, after) in enumerate(examples, start=1):
                print(f'[{index}] {kind}:')
                print(f'  before: {before}')
                print(f'  after : {after}')
        else:
            print('dry-run 未生成示例。')
        return

    if backup:
        bak = output_path + '.bak'
        shutil.copy2(input_path, bak)
        print(f'已备份原文件到: {bak}')

    with io.open(output_path, 'w', encoding='utf-8') as f:
        f.write(new_tex)
    print(f'已写入: {output_path}')


def main(argv=None) -> int:
    import argparse
    import sys

    p = argparse.ArgumentParser(description='将 $...$ -> \\(...\\) 与 $$...$$ -> \\[...\\]。')
    p.add_argument('--input-dir', required=True, help='包含输入 tex 的文件夹绝对路径')
    p.add_argument('--input-file', required=True, help='输入 tex 文件名（含扩展名）')
    p.add_argument('--output-dir', default=None, help='输出文件夹绝对路径（默认同输入）')
    p.add_argument('--output-file', default=None, help='输出文件名（默认同输入文件名，会覆盖）')
    p.add_argument('--no-backup', dest='backup', action='store_false', help='不生成 .bak 备份')
    p.add_argument('--dry-run', action='store_true', help='仅显示变更摘要，不写文件')
    args = p.parse_args(argv)

    input_path = os.path.join(args.input_dir, args.input_file)
    if not os.path.isfile(input_path):
        print('输入文件不存在:', input_path, file=sys.stderr)
        return 2

    output_dir = args.output_dir or args.input_dir
    os.makedirs(output_dir, exist_ok=True)
    output_file = args.output_file or args.input_file
    output_path = os.path.join(output_dir, output_file)

    process_file(input_path, output_path, backup=args.backup, dry_run=args.dry_run)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
