#!/usr/bin/env python3
"""
Beamer 双栏布局参数计算器

解析 LaTeX Beamer 文件中的双栏布局（columns 环境），计算最佳栏宽比例，
输出 JSON 参数供技能读取并替换 LaTeX 参数。

架构：
    LaTeX PPT 文件 → Python 计算脚本 → JSON 参数文件
         ↑                                      ↓
         └────── 技能读取并替换 ←───────────────┘

使用示例：
    python beamer_layout_calculator.py --input presentation.tex --output layout_params.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class FrameLayoutParams:
    """单个双栏帧的布局参数"""
    frame_id: str  # 帧标识（如 "表6-1"）
    frame_title: str  # 帧标题
    left_col_ratio: float  # 左栏宽度比例
    right_col_ratio: float  # 右栏宽度比例
    table_rows: int  # 表格行数
    table_cols: int  # 表格列数
    text_items: int  # 右栏 itemize 条目数
    text_needs_condense: bool  # 是否需要文本精简
    scale_factor: float  # 文本缩放因子
    line_number: int  # 帧在源文件中的行号


class BeamerLayoutCalculator:
    """Beamer 双栏布局计算器"""

    # 常量配置
    MIN_LEFT_RATIO = 0.45  # 左栏最小比例
    MAX_LEFT_RATIO = 0.65  # 左栏最大比例
    COL_SEP_RATIO = 0.04  # 栏间隔比例
    CHAR_WIDTH_FACTOR = 0.12  # 字符宽度系数（cm per char，近似值）
    PAGE_WIDTH_CM = 25.4  # 16:9 页面宽度（cm，近似值）
    MAX_TEXT_HEIGHT_RATIO = 0.85  # 文本最大高度比例
    MIN_SCALE_FACTOR = 0.7  # 最小缩放因子

    def __init__(self, latex_content: str):
        """
        初始化计算器

        Args:
            latex_content: LaTeX 文件内容
        """
        self.latex_content = latex_content
        self.frames: List[FrameLayoutParams] = []

    def parse_columns_environments(self) -> List[dict]:
        """
        解析所有 columns 环境

        Returns:
            包含 columns 环境信息的字典列表
        """
        pattern = r'\\begin\{columns\}(.*?)\\end\{columns\}'
        matches = re.finditer(pattern, self.latex_content, re.DOTALL)

        columns_list = []
        for match in matches:
            content = match.group(1)
            start_pos = match.start()
            line_number = self.latex_content[:start_pos].count('\n') + 1

            # 提取两个 column 环境
            col_pattern = r'\\begin\{column\}\{([\d.]+)\\textwidth\}(.*?)\\end\{column\}'
            col_matches = re.findall(col_pattern, content, re.DOTALL)

            if len(col_matches) == 2:
                left_ratio = float(col_matches[0][0])
                left_content = col_matches[0][1]
                right_ratio = float(col_matches[1][0])
                right_content = col_matches[1][1]

                columns_list.append({
                    'line_number': line_number,
                    'left_ratio': left_ratio,
                    'left_content': left_content,
                    'right_ratio': right_ratio,
                    'right_content': right_content,
                    'full_match': match.group(0)
                })

        return columns_list

    def extract_frame_title(self, line_number: int) -> tuple[str, str]:
        """
        提取帧标题和 ID

        Args:
            line_number: 帧所在行号

        Returns:
            (frame_id, frame_title) 元组
        """
        lines = self.latex_content.split('\n')
        # 向前搜索 \begin{frame}
        for i in range(line_number - 1, max(0, line_number - 50), -1):
            line = lines[i]
            frame_match = re.search(r'\\begin\{frame\}\{(.+?)\}', line)
            if frame_match:
                title = frame_match.group(1)
                # 提取 ID（如 "表6-1"）
                id_match = re.search(r'【(.+?)】', title)
                frame_id = id_match.group(1) if id_match else title[:20]
                return frame_id, title
        return f"frame_{line_number}", "Unknown Frame"

    def analyze_table(self, content: str) -> tuple[int, int]:
        """
        分析表格结构

        Args:
            content: 左栏内容

        Returns:
            (行数, 列数) 元组
        """
        # 检查是否包含 tabular 环境
        if '\\begin{tabular}' not in content:
            return 0, 0

        # 提取 tabular 内容
        tabular_pattern = r'\\begin\{tabular\}\{.*?\}(.*?)\\end\{tabular\}'
        tabular_match = re.search(tabular_pattern, content, re.DOTALL)
        if not tabular_match:
            return 0, 0

        tabular_content = tabular_match.group(1)

        # 计算列数（从 tabular 参数）
        col_spec_match = re.search(r'\\begin\{tabular\}\{(.+?)\}', content)
        if col_spec_match:
            col_spec = col_spec_match.group(1)
            # 计算列数（l, c, r, p{} 等）
            num_cols = len(re.findall(r'[lcrp]', col_spec))
        else:
            num_cols = 0

        # 计算行数（通过 \\ 分隔）
        rows = tabular_content.split('\\\\')
        num_rows = len([r for r in rows if r.strip()])

        return num_rows, num_cols

    def analyze_text_content(self, content: str) -> tuple[int, int]:
        """
        分析文本内容

        Args:
            content: 右栏内容

        Returns:
            (条目数, 总字符数) 元组
        """
        # 统计 itemize 条目
        itemize_pattern = r'\\item\s+'
        items = re.findall(itemize_pattern, content)
        num_items = len(items)

        # 统计总字符数（去除 LaTeX 命令）
        clean_content = re.sub(r'\\[a-zA-Z]+', '', content)
        clean_content = re.sub(r'[{}$]', '', clean_content)
        char_count = len(clean_content.strip())

        return num_items, char_count

    def calculate_optimal_ratio(
        self,
        table_rows: int,
        table_cols: int,
        text_items: int,
        text_char_count: int
    ) -> tuple[float, float]:
        """
        计算最佳栏宽比例

        Args:
            table_rows: 表格行数
            table_cols: 表格列数
            text_items: 文本条目数
            text_char_count: 文本字符数

        Returns:
            (left_ratio, right_ratio) 元组
        """
        # 如果没有表格，使用默认比例
        if table_cols == 0:
            return 0.50, 0.46

        # 估算表格宽度（cm）
        # 假设每列平均宽度为 3cm（包含内容和间距）
        estimated_table_width = table_cols * 3.0

        # 计算左栏比例
        left_ratio = estimated_table_width / self.PAGE_WIDTH_CM

        # 限制在合理范围内
        left_ratio = max(self.MIN_LEFT_RATIO, min(self.MAX_LEFT_RATIO, left_ratio))

        # 计算右栏比例
        right_ratio = 1.0 - left_ratio - self.COL_SEP_RATIO

        return round(left_ratio, 2), round(right_ratio, 2)

    def estimate_text_height(
        self,
        text_items: int,
        text_char_count: int,
        right_ratio: float
    ) -> float:
        """
        估算文本高度比例

        Args:
            text_items: 文本条目数
            text_char_count: 文本字符数
            right_ratio: 右栏宽度比例

        Returns:
            预估高度比例（相对于页面高度）
        """
        if text_items == 0:
            return 0.0

        # 估算每行字符数（基于右栏宽度）
        chars_per_line = int(right_ratio * self.PAGE_WIDTH_CM / 0.12)
        if chars_per_line == 0:
            chars_per_line = 30

        # 估算总行数
        total_lines = text_char_count / chars_per_line

        # 每个 itemize 条目额外占 1.5 行（包括间距）
        total_lines += text_items * 1.5

        # 估算高度比例（假设每行 0.5cm，页面高度 14cm）
        estimated_height_cm = total_lines * 0.5
        height_ratio = estimated_height_cm / 14.0

        return min(height_ratio, 1.0)

    def calculate_scale_factor(self, height_ratio: float) -> float:
        """
        计算缩放因子

        Args:
            height_ratio: 预估高度比例

        Returns:
            缩放因子
        """
        if height_ratio <= self.MAX_TEXT_HEIGHT_RATIO:
            return 1.0

        # 需要缩放
        scale = self.MAX_TEXT_HEIGHT_RATIO / height_ratio
        return max(self.MIN_SCALE_FACTOR, round(scale, 2))

    def calculate_all_frames(self) -> List[FrameLayoutParams]:
        """
        计算所有双栏帧的参数

        Returns:
            FrameLayoutParams 列表
        """
        columns_list = self.parse_columns_environments()

        for col_info in columns_list:
            frame_id, frame_title = self.extract_frame_title(col_info['line_number'])

            # 分析左栏表格
            table_rows, table_cols = self.analyze_table(col_info['left_content'])

            # 分析右栏文本
            text_items, text_char_count = self.analyze_text_content(col_info['right_content'])

            # 计算最佳比例
            left_ratio, right_ratio = self.calculate_optimal_ratio(
                table_rows, table_cols, text_items, text_char_count
            )

            # 估算文本高度
            height_ratio = self.estimate_text_height(text_items, text_char_count, right_ratio)

            # 计算缩放因子
            scale_factor = self.calculate_scale_factor(height_ratio)

            # 判断是否需要精简
            needs_condense = scale_factor < self.MIN_SCALE_FACTOR

            params = FrameLayoutParams(
                frame_id=frame_id,
                frame_title=frame_title,
                left_col_ratio=left_ratio,
                right_col_ratio=right_ratio,
                table_rows=table_rows,
                table_cols=table_cols,
                text_items=text_items,
                text_needs_condense=needs_condense,
                scale_factor=scale_factor,
                line_number=col_info['line_number']
            )

            self.frames.append(params)

        return self.frames

    def export_to_json(self, output_path: Path) -> None:
        """
        导出参数到 JSON 文件

        Args:
            output_path: 输出文件路径
        """
        data = {
            'metadata': {
                'total_frames': len(self.frames),
                'generator': 'beamer_layout_calculator.py',
                'version': '1.0'
            },
            'frames': [asdict(frame) for frame in self.frames]
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"✓ 已导出 {len(self.frames)} 个帧参数到: {output_path}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='Beamer 双栏布局参数计算器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python beamer_layout_calculator.py --input presentation.tex --output layout_params.json
        """
    )

    parser.add_argument(
        '--input', '-i',
        type=Path,
        required=True,
        help='输入的 LaTeX 文件路径'
    )

    parser.add_argument(
        '--output', '-o',
        type=Path,
        required=True,
        help='输出的 JSON 文件路径'
    )

    args = parser.parse_args()

    # 检查输入文件
    if not args.input.exists():
        print(f"✗ 错误: 输入文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    # 读取 LaTeX 文件
    print(f"正在读取: {args.input}")
    latex_content = args.input.read_text(encoding='utf-8')

    # 创建计算器
    calculator = BeamerLayoutCalculator(latex_content)

    # 计算所有帧参数
    print("正在计算双栏布局参数...")
    frames = calculator.calculate_all_frames()

    if not frames:
        print("⚠ 警告: 未找到任何双栏帧（columns 环境）", file=sys.stderr)
        sys.exit(0)

    print(f"✓ 找到 {len(frames)} 个双栏帧")

    # 导出到 JSON
    calculator.export_to_json(args.output)

    # 打印摘要
    print("\n参数摘要:")
    for frame in frames:
        condense_mark = " ⚠需精简" if frame.text_needs_condense else ""
        print(f"  {frame.frame_id}: 左{frame.left_col_ratio}/右{frame.right_col_ratio}, "
              f"缩放{frame.scale_factor}{condense_mark}")


if __name__ == '__main__':
    main()
