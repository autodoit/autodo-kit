#!/usr/bin/env python3
"""
根据 JSON 布局参数批量替换 LaTeX 双栏 frame 的 column 宽度。

使用示例：
    python apply_layout_params.py --latex PPT.tex --json layout_params.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List


def load_params(json_path: Path) -> List[Dict]:
    """加载 JSON 参数文件"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['frames']


def apply_column_ratios(latex_text: str, frames: List[Dict]) -> str:
    """
    对每个 frame，找到其 columns 环境内的 column 宽度并替换为计算值。

    策略：以 frame title 定位，在 frame 内找到 columns 块，
    替换其中的两个 \begin{column}{X\textwidth} 为计算值。
    """
    lines = latex_text.split('\n')
    # 标记哪些行已被修改（避免同一 frame 被多次匹配）
    modified_lines = set()

    for frame in frames:
        title = frame['frame_title']
        left_ratio = frame['left_col_ratio']
        right_ratio = frame['right_col_ratio']

        # 在 LaTeX 中定位 frame
        frame_start = None
        for i, line in enumerate(lines):
            if i in modified_lines:
                continue
            # 匹配 \begin{frame}{...title...}
            if '\\begin{frame}' in line and re.escape(title[:30]) in re.escape(line):
                frame_start = i
                break

        if frame_start is None:
            print(f"  ⚠ 未找到 frame: {title[:50]}")
            continue

        # 从 frame_start 开始找到 \begin{columns}
        columns_start = None
        columns_end = None
        for i in range(frame_start, min(frame_start + 200, len(lines))):
            if '\\begin{columns}' in lines[i]:
                columns_start = i
            if columns_start is not None and '\\end{columns}' in lines[i]:
                columns_end = i
                break

        if columns_start is None or columns_end is None:
            print(f"  ⚠ {title[:40]}: 未找到 columns 环境")
            continue

        # 在 columns 内替换两个 \begin{column}{X\textwidth}
        col_count = 0
        for i in range(columns_start, columns_end + 1):
            match = re.match(r'(\s*\\begin\{column\}\{)[\d.]+(\\textwidth\})', lines[i])
            if match:
                col_count += 1
                ratio = left_ratio if col_count == 1 else right_ratio
                old_line = lines[i]
                lines[i] = f"{match.group(1)}{ratio}{match.group(2)}"
                modified_lines.add(i)
                print(f"  ✓ {title[:40]}: col{col_count} {old_line.strip()} → {lines[i].strip()}")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='应用 JSON 布局参数到 LaTeX 文件')
    parser.add_argument('--latex', '-l', type=Path, required=True, help='LaTeX 文件路径')
    parser.add_argument('--json', '-j', type=Path, required=True, help='JSON 参数文件路径')
    parser.add_argument('--output', '-o', type=Path, help='输出文件路径（默认覆盖原文件）')
    args = parser.parse_args()

    # 读取文件
    latex_text = args.latex.read_text(encoding='utf-8')
    frames = load_params(args.json)

    print(f"共 {len(frames)} 个 frame 待处理\n")

    # 应用替换
    new_text = apply_column_ratios(latex_text, frames)

    # 写入
    output_path = args.output or args.latex
    output_path.write_text(new_text, encoding='utf-8')
    print(f"\n✓ 已写入: {output_path}")


if __name__ == '__main__':
    main()
