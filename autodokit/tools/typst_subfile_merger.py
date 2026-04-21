"""Typst 子文件合并原子工具。

该工具递归展开常见的 Typst 引入/包含语句（例如 `#include "file.typ"`、
`include("file.typ")`、`import "file.typ"`、`embed("file.typ")` 等），
并把子文件内容内联到主文件中以生成一个完整的合并后的 `.typ` 文件。

设计考虑：保持通用性——支持多种常见包含语法、不重复展开（循环引用保护）、
按引用位置插入、以及相对路径解析。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple


def _require_absolute_file(path_str: str, *, field_name: str, must_exist: bool = True) -> Path:
    """校验并返回绝对路径的 Path 对象。

    Args:
        path_str: 路径字符串
        field_name: 字段名（用于错误信息）
        must_exist: 若为 True 则文件必须存在

    Returns:
        Path: 解析后的绝对路径

    Raises:
        ValueError: 当路径为空或不是绝对路径
        FileNotFoundError: 当 must_exist 为 True 且路径不存在
    """

    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError(f"{field_name} 为空")

    path_obj = Path(path_str)
    if not path_obj.is_absolute():
        raise ValueError(f"{field_name} 必须是绝对路径：{path_str!r}")

    resolved = path_obj.resolve()
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"{field_name} 不存在：{resolved}")
    return resolved


def _read_text(file_path: Path) -> str:
    """以 utf-8 安全方式读取文本文件内容。"""
    # 使用 utf-8-sig 自动吞掉 UTF-8 BOM，跨系统更稳健。
    return file_path.read_text(encoding="utf-8-sig", errors="replace")


def _normalize_utf8_text(text: str) -> Tuple[str, dict]:
    """清洗常见乱码/隐形字符并统一换行。"""

    stats = {
        "bom": 0,
        "zero_width": 0,
        "null": 0,
        "linebreak_normalized": 0,
    }

    stats["bom"] = text.count("\ufeff")
    if stats["bom"]:
        text = text.replace("\ufeff", "")

    zero_width_chars = ("\u200b", "\u200c", "\u200d", "\u2060")
    for ch in zero_width_chars:
        c = text.count(ch)
        if c:
            text = text.replace(ch, "")
            stats["zero_width"] += c

    stats["null"] = text.count("\x00")
    if stats["null"]:
        text = text.replace("\x00", "")

    crlf = text.count("\r\n")
    lone_cr = text.count("\r") - crlf
    if crlf or lone_cr:
        stats["linebreak_normalized"] = crlf + max(0, lone_cr)
        text = text.replace("\r\n", "\n").replace("\r", "\n")

    return text, stats


def _resolve_subfile_path(parent_dir: Path, raw_subfile: str) -> Path:
    """解析子文件相对/绝对路径，默认补充 `.typ` 后缀（若无）。"""

    raw_clean = raw_subfile.strip()
    candidate = Path(raw_clean)
    if not candidate.suffix:
        candidate = candidate.with_suffix(".typ")
    # 若 candidate 是绝对路径则直接使用，否则相对 parent_dir
    if candidate.is_absolute():
        return candidate.resolve()
    return (parent_dir / candidate).resolve()


def _rewrite_resource_paths(text: str, base_dir: Path, logs: List[str]) -> str:
    """重写 Typst 常见资源路径，缺失图片时降级为可编译占位文本。

    目前处理 `image("...")` / `image('...')`：
    - 若资源存在：改写为绝对路径（跨目录编译更稳定）
    - 若资源缺失：替换为文本块，避免编译中断
    """

    image_pattern = re.compile(r"image\(\s*([\"'])([^\"']+)\1(.*?)\)", flags=re.S)

    def image_repl(m: re.Match) -> str:
        raw_path = m.group(2).strip()
        tail_args = m.group(3)
        path_obj = Path(raw_path)
        resolved = path_obj if path_obj.is_absolute() else (base_dir / path_obj)
        resolved = resolved.resolve()

        if resolved.exists():
            abs_path = str(resolved).replace("\\", "/")
            return f'image("{abs_path}"{tail_args})'

        logs.append(f"警告：图片资源不存在，已替换为占位文本：{resolved}")
        safe = raw_path.replace("\\", "/")
        return f'"MISSING_IMAGE: {safe}"'

    return image_pattern.sub(image_repl, text)


def _sanitize_mi_calls(text: str, logs: List[str]) -> str:
    """将高风险的 `#mi(...)` / `#mimath(...)` 调用降级为纯文本，避免插件报错中断编译。"""

    mi_pattern = re.compile(r"#(?:mi|mimath)\(\s*([\"'])(.*?)\1\s*\)", flags=re.S)

    def repl(m: re.Match) -> str:
        logs.append("警告：检测到高风险 #mi/#mimath 调用，已降级为文本占位")
        return '"MATH_EXPR"'

    return mi_pattern.sub(repl, text)


def _sanitize_mitex_calls(text: str, logs: List[str]) -> str:
    """将高风险 `#mitex(...)` 调用降级为纯文本占位，规避插件解析错误。"""

    # 仅处理最常见的字符串参数场景：#mitex("...") / #mitex('...')
    mitex_pattern = re.compile(r"#mitex\(\s*([\"'])(.*?)\1\s*\)", flags=re.S)

    def repl(_: re.Match) -> str:
        logs.append("警告：检测到高风险 #mitex 调用，已降级为文本占位")
        return '"MITEX_EXPR"'

    return mitex_pattern.sub(repl, text)


def merge_typst_subfiles(main_typ_path: Path, output_typ_path: Path) -> Tuple[Path, List[str]]:
    """递归展开 Typst 文件中的子文件引用并输出合并后的 typ 文件。

    支持的常见包含语法（非穷尽）:
    - #include "path.typ"
    - include "path.typ"
    - import "path.typ"
    - include("path.typ")
    - embed("path.typ")

    Args:
        main_typ_path: 主 typ 文件（绝对路径）
        output_typ_path: 合并输出文件（绝对路径，可不存在）

    Returns:
        Tuple[Path, List[str]]: (输出路径, 日志列表)

    Raises:
        FileNotFoundError: 当主文件或某个被包含的子文件缺失
    """

    main_typ = _require_absolute_file(str(main_typ_path), field_name="main_typ_path", must_exist=True)
    output_typ = _require_absolute_file(str(output_typ_path), field_name="output_typ_path", must_exist=False)
    output_typ.parent.mkdir(parents=True, exist_ok=True)

    logs: List[str] = []
    visited: set[Path] = set()

    # 组合正则：每次匹配一行的常见包含形式，并捕获文件路径
    combined_pattern = re.compile(
        r'(?m)^(?!\s*//)\s*(?:#include\(\s*["\'](?P<p1b>[^"\']+)["\']\s*\)|#include\s+["\'](?P<p1>[^"\']+)["\']|'
        r'include\(\s*["\'](?P<p4>[^"\']+)["\']\s*\)|include\s+["\'](?P<p2>[^"\']+)["\']|import\s+["\'](?P<p3>[^"\']+)["\']|'
        r'embed\(\s*["\'](?P<p5>[^"\']+)["\']\s*\))'
    )

    def _merge_one(typ_path: Path) -> str:
        if typ_path in visited:
            logs.append(f"检测到重复引用，跳过再次展开：{typ_path}")
            return ""
        visited.add(typ_path)

        if not typ_path.exists():
            raise FileNotFoundError(f"子文件不存在：{typ_path}")

        logs.append(f"展开文件：{typ_path}")
        text = _read_text(typ_path)
        text, clean_stats = _normalize_utf8_text(text)
        if any(clean_stats.values()):
            logs.append(
                f"UTF-8 清洗：{typ_path} "
                f"(bom={clean_stats['bom']}, zero_width={clean_stats['zero_width']}, "
                f"null={clean_stats['null']}, linebreak_normalized={clean_stats['linebreak_normalized']})"
            )
        text = _rewrite_resource_paths(text, typ_path.parent, logs)
        text = _sanitize_mi_calls(text, logs)
        text = _sanitize_mitex_calls(text, logs)

        # 按位置依次替换匹配到的包含语句
        parts: List[str] = []
        cursor = 0
        for m in combined_pattern.finditer(text):
            s, e = m.span()
            parts.append(text[cursor:s])
            groups = m.groupdict()
            raw_path = None
            for k in ("p1b", "p1", "p2", "p3", "p4", "p5"):
                if groups.get(k):
                    raw_path = groups[k]
                    break
            if not raw_path:
                # 未捕获到路径，保留原匹配文本以免破坏源文件
                parts.append(text[s:e])
                cursor = e
                continue

            sub_path = _resolve_subfile_path(typ_path.parent, raw_path)
            parts.append(_merge_one(sub_path))
            cursor = e

        parts.append(text[cursor:])
        parts.append("\n\n")
        return "".join(parts)

    merged = _merge_one(main_typ)
    merged, merged_clean_stats = _normalize_utf8_text(merged)
    if any(merged_clean_stats.values()):
        logs.append(
            "UTF-8 清洗（合并结果）："
            f"(bom={merged_clean_stats['bom']}, zero_width={merged_clean_stats['zero_width']}, "
            f"null={merged_clean_stats['null']}, linebreak_normalized={merged_clean_stats['linebreak_normalized']})"
        )
    # 简单清洗：把 LaTeX 风格的下划线转义替换为 typst 友好的下划线
    merged = merged.replace("\\_", "_")
    # 把 LaTeX 中的细小空格命令移除/替换为普通空格，降低 Typst 语法冲突风险
    merged = merged.replace("\\,", " ")
    # 将常见的 LaTeX 数学命令替换为 Unicode 字符，减少 Typst math 解析差异
    latex_to_unicode = {
        r"\\alpha": "α",
        r"\\beta": "β",
        r"\\gamma": "γ",
        r"\\delta": "δ",
        r"\\epsilon": "ε",
        r"\\varepsilon": "ε",
        r"\\mu": "μ",
        r"\\theta": "θ",
        r"\\lambda": "λ",
        r"\\sigma": "σ",
        r"\\phi": "φ",
        r"\\psi": "ψ",
        r"\\times": "×",
        r"\\cdot": "·",
    }
    for k, v in latex_to_unicode.items():
        merged = re.sub(k, v, merged)
    # 先做一轮 LaTeX 数学定界符到 Typst 风格的规范化，降低后续解析歧义。
    # 1) \( ... \) -> $ ... $
    # 2) \[ ... \] -> $ ... $
    # 3) 独占一行的 $$ 统一为单个 $（Typst 仅需要一个数学定界符）
    def _normalize_math_delimiters(text: str) -> str:
        normalized = text
        normalized = re.sub(r"\\\\\(", "$", normalized)
        normalized = re.sub(r"\\\\\)", "$", normalized)
        normalized = re.sub(r"\\\\\[", "$", normalized)
        normalized = re.sub(r"\\\\\]", "$", normalized)
        normalized = re.sub(r"(?m)^\s*\$\$\s*$", "$", normalized)
        return normalized

    merged = _normalize_math_delimiters(merged)

    # 对“独立成行且明显为公式”的文本做保守降级，防止在数学定界符失效时被 Typst 当代码求值。
    def _neutralize_formula_like_lines(text: str) -> Tuple[str, int]:
        changed = 0
        out_lines: List[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            is_candidate = (
                stripped
                and not stripped.startswith("#")
                and "=" in stripped
                and "_" in stripped
                and not stripped.startswith("[")
                and len(stripped) > 24
            )
            if is_candidate:
                out_lines.append('"MATH_LINE"')
                changed += 1
            else:
                out_lines.append(line)
        return "\n".join(out_lines), changed

    merged, formula_line_rewritten = _neutralize_formula_like_lines(merged)

    # 检查并修复未配对的数学定界符（$ 和 $$）。
    # 原理：扫描未被反斜杠转义的 $/$ $ 对，若存在未配对的 token，尽量通过转义（在相应 $ 前插入反斜杠）来中和未闭合的定界符，避免 Typst 编译时抛出 unclosed delimiter。
    def _balance_math_delimiters(text: str) -> Tuple[str, dict]:
        # 更稳健的定界符修复：逐字符扫描，维护一个栈以跟踪打开的数学定界符（'$' 或 '$$'）。
        # 当遇到不会合法闭合的定界符（例如在 inline 模式中遇到 $$，或在 display 模式中遇到 $）时，
        # 将该出现位置的美元符号替换为全角美元 '＄'，从而把其“去数学化”。最终把所有未闭合的打开定界符也替换为全角美元。
        chars = list(text)
        L = len(chars)
        i = 0
        stack = []  # 存储 (token, index)
        info = {"singles": 0, "doubles": 0, "replacements": 0}
        while i < L:
            if chars[i] == "\\":
                i += 2
                continue
            if chars[i] == "$":
                # detect $$ or $
                if i + 1 < L and chars[i + 1] == "$":
                    info['doubles'] += 1
                    token = '$$'
                    # if stack empty -> push (open display)
                    if not stack:
                        stack.append((token, i))
                        i += 2
                        continue
                    # if top is same token -> close
                    top_token, top_idx = stack[-1]
                    if top_token == token:
                        stack.pop()
                        i += 2
                        continue
                    # if top is different (e.g., '$' open) then $$ inside inline is invalid -> neutralize this $$
                    # replace both $ with fullwidth
                    chars[i] = '＄'
                    chars[i + 1] = '＄'
                    info['replacements'] += 2
                    i += 2
                    continue
                else:
                    info['singles'] += 1
                    token = '$'
                    if not stack:
                        stack.append((token, i))
                        i += 1
                        continue
                    top_token, top_idx = stack[-1]
                    if top_token == token:
                        stack.pop()
                        i += 1
                        continue
                    # if top is different (e.g., '$$' open) then single $ inside display is invalid -> neutralize
                    chars[i] = '＄'
                    info['replacements'] += 1
                    i += 1
                    continue
            i += 1

        # 把栈中仍未闭合的打开定界符替换为全角美元
        if stack:
            s = ''.join(chars)
            for tok, idx in reversed(stack):
                if tok == '$$':
                    # replace two chars at idx
                    if idx + 1 < len(chars):
                        chars[idx] = '＄'
                        chars[idx + 1] = '＄'
                        info['replacements'] += 2
                    else:
                        chars[idx] = '＄'
                        info['replacements'] += 1
                else:
                    chars[idx] = '＄'
                    info['replacements'] += 1

        return ("".join(chars), info)

    merged_fixed, fix_info = _balance_math_delimiters(merged)

    # 对已归一化后的数学块做额外保守修复：
    # 若一个数学块内部出现明显高风险标记（如 #scale(...) 或残留的 LaTeX 反斜杠命令），
    # 则把整个块转为文本标记，避免 Typst 在该块内继续按数学语法解析。
    def _neutralize_risky_math_blocks(text: str) -> Tuple[str, int]:
        risky_re = re.compile(r"#\w+\(|\\[A-Za-z]+")
        changes = 0

        def repl(m: re.Match) -> str:
            nonlocal changes
            inner = m.group(1)
            if risky_re.search(inner):
                changes += 1
                return '"MATH_TEXT"'
            return m.group(0)

        # 仅处理同一对 $...$（非贪婪）
        return re.sub(r"\$(.+?)\$", repl, text, flags=re.S), changes

    merged_fixed, risky_blocks_rewritten = _neutralize_risky_math_blocks(merged_fixed)
    # 仅输出一个最终合并文件；如需调试，保留在内存中的修复结果与日志即可。
    output_typ.write_text(merged, encoding="utf-8")
    logs.append(f"合并完成：{output_typ}")
    logs.append(
        f"合并后清洗统计：math tokens singles={fix_info['singles']}, doubles={fix_info['doubles']}, "
        f"risky_blocks_rewritten={risky_blocks_rewritten}"
    )
    if formula_line_rewritten:
        logs.append(f"已降级独立公式行：{formula_line_rewritten}")
    return output_typ, logs


if __name__ == "__main__":
    # 简易命令行示例（不依赖额外库）
    import argparse

    parser = argparse.ArgumentParser(description="Merge Typst subfiles into a single .typ file")
    parser.add_argument("main", help="absolute path to main .typ file")
    parser.add_argument("output", help="absolute path to write merged .typ file")
    args = parser.parse_args()

    out_path, log = merge_typst_subfiles(Path(args.main), Path(args.output))
    for line in log:
        print(line)
