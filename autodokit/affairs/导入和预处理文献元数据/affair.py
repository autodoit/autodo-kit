"""文献梳理初筛工具。

本脚本将 BibTeX 文献导入为 Pandas 数据表，并生成管理字段。

说明：
- 本事务只负责“导入 + 预处理 + 主表落盘”。
- bibtex_path 支持：
  - 单个 BibTeX 文件（.bib/.txt 等，只要内容是 BibTeX 即可）；
  - 一个目录：会遍历该目录下所有 .bib 文件并合并导入（不递归、不去重）。
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import re
import unicodedata

import pandas as pd
from bibtexparser import loads as bibtex_loads

# 归一化规则列表：在此列表中出现的规则会被应用
# 可用规则说明：
# - "punctuation": 将 Unicode 标点符号替换为空格（便于切分/匹配）
# - "greek": 移除希腊字母字符
# - "math": 移除数学符号（数学运算符等 Unicode 块）
# - "diacritics": 去除字母上的重音/变音符，将带重音字符归一为基字符
#
# 默认启用全部规则；你可以在运行时通过 set_normalize_rules([...]) 调整
NORMALIZE_RULES: List[str] = [
    "punctuation",  # 标点
    # "greek",  # 希腊字母
    "math",  # 数学符号
    "diacritics",  # 重音/变音符
]

# 默认配置字典（必须在 merge_config 之前定义以避免 NameError）
DEFAULT_CONFIG: Dict[str, Any] = {
    "bibtex_path": "data/input/records.txt",
    "output_dir": "output",
    "output_table_csv": "文献数据表.csv",
    "tag_list": ["graph", "risk", "bank", "systemic"],
    "tag_match_fields": ["title", "abstract", "keywords"],
    "has_pdf_enable": True,
    "pdf_dir": "pdfs",
    "pdf_match_mode": "title",
}


def set_normalize_rules(rules: Iterable[str]) -> None:
    """设置全局归一化规则（覆盖默认规则）。

    Args:
        rules: 可迭代的规则名列表，规则名参考文件顶部注释。
    """
    global NORMALIZE_RULES
    NORMALIZE_RULES = [str(r) for r in rules]


@dataclass
class Config:
    """配置数据类，表示流水线所需的配置项。

    Args:
        bibtex_path: BibTeX 文件路径或相对路径字符串。
        output_dir: 输出目录路径字符串。
        output_table_csv: 主表 CSV 文件名。
        tag_list: 要匹配的标签列表。
        tag_match_fields: 用于匹配标签的字段列表（例如 title, abstract）。
        has_pdf_enable: 是否启用 PDF 匹配。
        pdf_dir: PDF 目录路径字符串。
        pdf_match_mode: PDF 匹配模式，目前支持 "title"。
    """
    bibtex_path: str
    output_dir: str
    output_table_csv: str
    tag_list: List[str]
    tag_match_fields: List[str]
    has_pdf_enable: bool
    pdf_dir: str
    pdf_match_mode: str


@dataclass
class BibRecord:
    """表示从 BibTeX 解析得到的一条记录。

    Attributes:
        entry_type: 条目的类型（原始或映射后的类型）。
        entry_key: BibTeX 条目的 key。
        fields: 词典形式的字段集合（键为小写字段名）。
    """
    entry_type: str
    entry_key: str
    fields: Dict[str, Any]


def _is_chinese(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def _is_greek(ch: str) -> bool:
    # 常用希腊字符块：\u0370-\u03FF, 扩展希腊 \u1F00-\u1FFF
    o = ord(ch)
    return (0x0370 <= o <= 0x03FF) or (0x1F00 <= o <= 0x1FFF)


def _is_math_symbol(ch: str) -> bool:
    # 常见数学符号块：数学运算符、其他数学符号
    o = ord(ch)
    return (0x2200 <= o <= 0x22FF) or (0x27C0 <= o <= 0x27EF) or (0x2900 <= o <= 0x297F)


def normalize_text(text: str) -> str:
    """根据全局规则对文本做可配置的归一化处理。

    支持的规则见文件顶部 `NORMALIZE_RULES` 注释。规则只在列表中存在时应用。

    处理步骤（按顺序）：
    - 如果启用 "diacritics"，先用 Unicode NFKD 分解并去除组合记号，从而把带重音字母归一为基字符；
    - 将文本小写化；
    - 遍历字符，根据启用规则决定是否删除或替换为空格（对标点执行替换以便后续合并空格）；
    - 合并多个空白为单个空格并修剪首尾空白。

    Args:
        text: 原始字符串。

    Returns:
        经过规则化的字符串。
    """
    rules = set(NORMALIZE_RULES)

    s = text or ""
    # 先处理重音/变音：将 Á -> A 等（如果启用）
    if "diacritics" in rules:
        s = unicodedata.normalize("NFKD", s)
        # 去掉所有的组合记号（类别以 'M' 开头）
        s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("M"))

    s = s.lower()

    out_chars: List[str] = []
    for ch in s:
        # 跳过希腊字母（若启用）
        if "greek" in rules and _is_greek(ch):
            continue
        # 跳过数学符号（若启用）
        if "math" in rules and _is_math_symbol(ch):
            continue
        # 标点处理：若启用则替换为单空格，便于后续合并；否则保留
        cat = unicodedata.category(ch)
        if cat.startswith("P"):
            if "punctuation" in rules:
                out_chars.append(" ")
            else:
                out_chars.append(ch)
            continue
        # 如果是字母数字或中文，保留
        if ch.isalnum() or _is_chinese(ch):
            out_chars.append(ch)
            continue
        # 对于其它字符（符号、控制字符等）：
        # 如果启用了 punctuation，则把它视作空格以统一分隔；否则保留原字符
        if "punctuation" in rules:
            out_chars.append(" ")
        else:
            out_chars.append(ch)

    cleaned = "".join(out_chars)
    # 合并多空白并 trim
    return " ".join(cleaned.split())


def merge_config(raw_config: Dict[str, Any]) -> Dict[str, Any]:
    """将用户配置与默认配置合并，用户配置字段优先覆盖默认值。

    Args:
        raw_config: 从配置文件读取的原始字典。

    Returns:
        合并后的配置字典。
    """
    merged = dict(DEFAULT_CONFIG)
    merged.update(raw_config)
    return merged


def load_config_from_json(config_path: Path) -> Dict[str, Any]:
    """从 JSON 文件加载配置字典。

    Args:
        config_path: JSON 配置文件路径。

    Returns:
        解析后的配置字典。

    Raises:
        ValueError: 当文件无法读取或不是合法 JSON 时抛出（由 json.loads 抛出）。
    """
    text = config_path.read_text(encoding="utf-8", errors="ignore")
    return json.loads(text)


def load_config_from_py(config_path: Path) -> Dict[str, Any]:
    """从 Python 文件加载 CONFIG 变量作为配置字典。

    说明：会以模块方式加载目标文件并查找名为 CONFIG 的全局字典。

    Args:
        config_path: Python 配置文件路径。

    Returns:
        CONFIG 字典内容。

    Raises:
        ValueError: 当无法加载模块或模块中缺少 CONFIG 时抛出。
    """
    module_name = f"config_{config_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, config_path)
    if spec is None or spec.loader is None:
        raise ValueError("无法加载配置模块")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "CONFIG"):
        raise ValueError("Python 配置文件需包含 CONFIG 字典")
    return getattr(module, "CONFIG")


def load_config(config_path: Path) -> Config:
    """根据配置文件路径载入配置并返回 Config 实例。

    支持 .json 和 .py 两种格式，合并默认配置后构造 Config。

    Args:
        config_path: 配置文件路径（.json 或 .py）。

    Returns:
        Config dataclass 实例。

    Raises:
        ValueError: 当配置文件后缀不受支持时抛出。
    """
    if config_path.suffix.lower() == ".json":
        raw_config = load_config_from_json(config_path)
    elif config_path.suffix.lower() == ".py":
        raw_config = load_config_from_py(config_path)
    else:
        raise ValueError("配置文件必须为 .json 或 .py")
    merged = merge_config(raw_config)
    return Config(**merged)


def _iter_bibtex_source_files(bibtex_path: Path) -> List[Path]:
    """将 bibtex_path 规范化为要读取的 BibTeX 文件列表。

    设计原因：
        事务调用链里会把配置路径先解析为绝对路径，所以此处只需要判断“文件 or 目录”。
        对目录做排序遍历可确保输出 uid 顺序稳定，便于复现实验结果。

    Args:
        bibtex_path: BibTeX 文件路径或目录路径。

    Returns:
        需要读取的文件路径列表；若 bibtex_path 是文件则返回单元素列表；若是目录则返回目录下 *.bib。
    """
    if bibtex_path.exists() and bibtex_path.is_dir():
        # 仅遍历当前目录下的 .bib（不递归），并按名称排序以保证可复现。
        return sorted([p for p in bibtex_path.iterdir() if p.is_file() and p.suffix.lower() == ".bib"])

    # 文件路径（保持旧行为：允许 .txt 等扩展名，只要内容是 BibTeX）
    return [bibtex_path]


def _preprocess_bibtex_text_for_parser(bibtex_text: str, *, file_prefix: str) -> str:
    """对单个文件的 BibTeX 文本做预处理。

    关键点：
        bibtexparser 以条目的 key（也就是 @type{<key>, ...} 里的 <key>）作为 ID。
        当我们把多个文件拼在一起时，如果不同文件里出现相同 key，解析库可能会覆盖/丢弃其中一条。
        本事务要求“不去重”，因此这里为每个条目的 key 注入文件级前缀，保证全局唯一。

    Args:
        bibtex_text: 原始 BibTeX 文本。
        file_prefix: 用于唯一化 key 的前缀（建议来自文件名/序号）。

    Returns:
        预处理后的 BibTeX 文本，可安全与其他文件拼接后一起解析。
    """
    text = bibtex_text or ""

    # 先把类型中的空格去掉（比如 @Journal Article{ -> @JournalArticle{）以简化后续匹配
    text = re.sub(r"@([^{]+)\{", lambda m: "@" + re.sub(r"\s+", "", m.group(1)) + "{", text)

    parts = re.split(r"(?=@)", text)
    out_parts: List[str] = []
    auto_idx = 1

    def map_type(orig: str) -> str:
        s = orig.lower().replace(" ", "")
        if "journal" in s or "article" in s:
            return "article"
        if "conference" in s or "inproceedings" in s or "proceedings" in s:
            return "inproceedings"
        if "thesis" in s or "dissertation" in s:
            # 使用 BibTeX 常见的 phdthesis 类型
            return "phdthesis"
        if "book" in s or "proceedings" in s:
            return "book"
        return "misc"

    for part in parts:
        if not part.strip():
            continue
        # 仅处理以 @ 开头的条目，否则直接保留
        if not part.lstrip().startswith("@"):
            out_parts.append(part)
            continue
        # 提取原始类型
        brace_pos = part.find("{")
        if brace_pos == -1:
            out_parts.append(part)
            continue
        orig_type = part[1:brace_pos].strip()
        std_type = map_type(orig_type)

        # 找到 key（第一个逗号之前的内容）
        first_comma = part.find(",", brace_pos + 1)
        if first_comma == -1:
            # 只替换类型
            new_part = "@" + std_type + part[brace_pos:]
            out_parts.append(new_part)
            continue

        key_candidate = part[brace_pos + 1 : first_comma].strip()
        if not key_candidate or "=" in key_candidate:
            # 缺失 key：从 @type{ 后直接是字段，此时 key_candidate 其实是字段开头
            key = f"{file_prefix}auto_{auto_idx}"
            auto_idx += 1
            rest = part[brace_pos + 1 :]
            rest = rest.lstrip()
            new_part = f"@{std_type}{{{key}, orig_entry_type = {{{orig_type}}}," + rest
        else:
            # 有 key：强制加前缀避免跨文件冲突
            key = f"{file_prefix}{key_candidate}"
            rest = part[first_comma + 1 :]
            new_part = f"@{std_type}{{{key}, orig_entry_type = {{{orig_type}}}," + rest

        out_parts.append(new_part)

    return "".join(out_parts)


def load_bib_records_from_text(bibtex_text: str) -> List[BibRecord]:
    """从 BibTeX 文本解析 BibRecord 列表。

    Args:
        bibtex_text: BibTeX 文本内容。

    Returns:
        解析得到的 BibRecord 列表。

    Raises:
        可能会抛出 bibtexparser 的解析异常。
    """
    bib_database = bibtex_loads(bibtex_text)
    records: List[BibRecord] = []
    for entry in bib_database.entries:
        entry_type = entry.get("ENTRYTYPE", "")
        # 如果我们注入了 orig_entry_type 字段，则优先使用它作为记录的原始类型
        orig = entry.get("orig_entry_type") or entry.get("orig_entrytype")
        if orig:
            entry_type = orig
        entry_key = entry.get("ID", "")
        fields = {k.lower(): v for k, v in entry.items() if k not in {"ENTRYTYPE", "ID"}}
        records.append(BibRecord(entry_type=entry_type, entry_key=entry_key, fields=fields))
    return records


def load_bib_records(libtex_path: Path) -> List[BibRecord]:
    """解析 BibTeX 文件并返回结构化的记录列表。

    功能要点：
    - 简化并规范化条目类型（如 Journal Article -> article）。
    - 为缺失 key 的条目自动生成 key 并注入 orig_entry_type 字段以保留原始类型信息。
    - 支持 bibtex_path 为目录：遍历目录下所有 .bib 合并导入（不递归、不去重）。

    注意：
        “不去重”指不会按 DOI/title 等字段做合并；但为了避免 BibTeX key 重复导致解析库覆盖条目，
        会对每个文件的条目 key 注入不同前缀，使其在合并解析时保持全量保留。

    Args:
        bibtex_path: BibTeX 文件路径或目录路径。

    Returns:
        List[BibRecord]，每项包含 entry_type、entry_key 和 fields。

    Raises:
        可能会抛出文件读取或解析相关的异常（由底层库/IO 抛出）。
    """
    # 兼容旧形参名（libtex_path），统一用 bibtex_path 命名
    bibtex_path = libtex_path

    source_files = _iter_bibtex_source_files(bibtex_path)
    if not source_files:
        return []

    merged_parts: List[str] = []
    for idx, p in enumerate(source_files, start=1):
        text = p.read_text(encoding="utf-8", errors="ignore")
        # 用序号+文件名做前缀：既可读，也能避免同名文件造成冲突。
        safe_stem = re.sub(r"[^0-9A-Za-z_\-]+", "_", p.stem)
        prefix = f"f{idx:03d}_{safe_stem}_"
        merged_parts.append(_preprocess_bibtex_text_for_parser(text, file_prefix=prefix))
        merged_parts.append("\n\n")

    merged_text = "".join(merged_parts)
    return load_bib_records_from_text(merged_text)


def load_bib_records_original(bibtex_path: Path) -> List[BibRecord]:
    """原始实现（已废弃）：保留函数名以兼容历史调用点。

    说明：
        旧版本只有“单文件解析”。为支持目录导入与跨文件 key 唯一化，主逻辑已迁移到
        `load_bib_records` + `load_bib_records_from_text`。

    Args:
        bibtex_path: BibTeX 文件路径。

    Returns:
        BibRecord 列表。
    """
    # 保持行为：仍然走新实现
    return load_bib_records(bibtex_path)


def build_pdf_index(pdf_dir: Path) -> Dict[str, str]:
    """遍历 pdf_dir，建立从规范化文件名到 PDF 实际路径的索引字典。

    Args:
        pdf_dir: PDF 根目录路径。

    Returns:
        字典，键为规范化 (normalize_text) 后的文件名，值为文件的绝对/相对路径字符串。
    """
    index: Dict[str, str] = {}
    if not pdf_dir.exists():
        return index
    for pdf_path in pdf_dir.rglob("*.pdf"):
        normalized = normalize_text(pdf_path.stem)
        if normalized:
            index[normalized] = str(pdf_path)
    return index


def match_pdf_paths(records: List[BibRecord], pdf_index: Dict[str, str]) -> List[Tuple[bool, str]]:
    """根据记录的标题在 pdf_index 中查找匹配的 PDF 路径。

    匹配逻辑：
    - 先对标题做 normalize_text，然后查精确键是否存在；
    - 若不存在，尝试子串互包含的模糊匹配，找到第一个匹配即返回。

    Args:
        records: BibRecord 列表。
        pdf_index: build_pdf_index 返回的索引字典。

    Returns:
        与 records 等长的列表，每项为 (bool, str)，表示是否匹配到 PDF 及匹配到的路径（未命中为 ("", False) 对应空路径）。
    """
    results: List[Tuple[bool, str]] = []
    for record in records:
        title = str(record.fields.get("title", ""))
        key = normalize_text(title)
        if not key:
            results.append((False, ""))
            continue
        if key in pdf_index:
            results.append((True, pdf_index[key]))
            continue
        hit = False
        path = ""
        for pdf_key, pdf_path in pdf_index.items():
            if key in pdf_key or pdf_key in key:
                hit = True
                path = pdf_path
                break
        results.append((hit, path))
    return results


def split_authors(raw: str) -> List[str]:
    """将 author 字段拆分为作者列表，支持多种常见分隔符。

    Args:
        raw: 原始作者字段字符串。

    Returns:
        作者列表（已去除空项并做 strip）。
    """
    import re
    if not raw:
        return []
    # 分隔作者时支持常见分隔符；使用 ' and ' 时采用明确的空格匹配，避免重复分支
    parts = re.split(r"\s*(?:;|,|，|、|＆|/|\\|\||\sand\s)\s*", raw)
    return [p.strip() for p in parts if p and p.strip()]


def split_keywords(raw: str) -> List[str]:
    """将 keywords 字段拆分为关键字列表并去重，支持常见分隔符。

    Args:
        raw: 原始关键字字段字符串。

    Returns:
        规范化且去重后的关键字列表。
    """
    import re
    if not raw:
        return []
    # 关键字分隔符去重，使用字符类简洁匹配常见分隔符
    parts = re.split(r"\s*[;,，/\\|]\s*", raw)
    parts = [p.strip() for p in parts if p and p.strip()]
    seen = set()
    out: List[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


from autodokit.tools import load_json_or_py


def build_main_table(records: List[BibRecord], pdf_matches: List[Tuple[bool, str]]) -> pd.DataFrame:
    """根据解析的记录和 PDF 匹配结果构建主数据表（Pandas DataFrame）。

    生成字段包括原有 Bib 字段、title_norm、abstract_norm、是否有原文、pdf_path 等（不再生成 authors_list、keywords_list、year_int）。

    Args:
        records: BibRecord 列表。
        pdf_matches: 与 records 对应的 PDF 匹配结果列表。

    Returns:
        Pandas DataFrame，行表示文献条目，列为若干元数据字段。
    """
    rows: List[Dict[str, Any]] = []
    # 为每条记录生成顺序 uid（从1开始），不再保留 entry_key，uid 将作为唯一索引
    for uid, (record, (has_pdf, pdf_path)) in enumerate(zip(records, pdf_matches), start=1):
        row: Dict[str, Any] = {}
        row["entry_type"] = record.entry_type
        # 不再导出 entry_key，改用数值型 uid 作为唯一标识
        row["uid"] = uid
        for key, value in record.fields.items():
            row[key] = value
        # 不再在主表生成 authors_list、keywords_list、year_int 三列，保留原始 author/keywords/year 字段
        row["title_norm"] = normalize_text(str(record.fields.get("title", "")))
        row["abstract_norm"] = normalize_text(str(record.fields.get("abstract", "")))
        row["是否有原文"] = bool(has_pdf)
        row["pdf_path"] = pdf_path
        rows.append(row)
    df = pd.DataFrame(rows)
    # 将 uid 设为唯一索引，便于在 CSV/后续处理使用数值型主键
    if "uid" in df.columns:
        df.set_index("uid", inplace=True, drop=True)
    return df


def _save_pickle(obj: Any, path: Path) -> Path:
    """将对象以 pickle 序列化写入磁盘。

    Args:
        obj: 任意可序列化对象。
        path: 输出文件路径。

    Returns:
        写入的 Path 对象。
    """
    import pickle

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(obj, f, protocol=4)
    return path


def _save_csc_matrix(csc_mat, path: Path) -> Path | None:
    """将 scipy.sparse 的 csc_matrix 保存为 .npz 文件。

    Args:
        csc_mat: scipy.sparse.csc_matrix 对象。
        path: 输出路径（.npz）。

    Returns:
        成功则返回 path，否则返回 None。
    """
    try:
        # 运行时导入：scipy 在某些环境可能是可选依赖
        from scipy.sparse import save_npz  # type: ignore
        path.parent.mkdir(parents=True, exist_ok=True)
        save_npz(str(path), csc_mat)
        return path
    except Exception:
         return None


def _run_and_write_all_outputs(config_path: Path) -> List[Path]:
    """核心执行逻辑：读取配置、构建主表，并写出主表 CSV。

    说明：
    - 作者/关键词/标签的二分图输出已迁移到 `生成文献元数据关系图.py`。
    - 返回值是“实际写出的文件路径列表”，便于调度器/调用方记录日志。

    Args:
        config_path: 配置文件路径（.json），通常由 main.py 在 .tmp/ 下生成。
        workspace_root: （已废弃）事务内不再做路径解析；请由调度层预处理。

    Returns:
        文件路径列表（List[Path]）。
    """
    raw_cfg = load_json_or_py(config_path)
    merged_cfg = merge_config(raw_cfg)

    # 过滤构造 Config
    try:
        from dataclasses import fields

        allowed_keys = {f.name for f in fields(Config)}
    except Exception:
        import inspect

        sig = inspect.signature(Config)
        allowed_keys = set(sig.parameters.keys()) - {"self"}

    filtered_cfg = {k: v for k, v in merged_cfg.items() if k in allowed_keys}
    config = Config(**filtered_cfg)

    bibtex_path = Path(config.bibtex_path)
    output_dir = Path(config.output_dir)
    pdf_dir = Path(config.pdf_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    if config.pdf_match_mode != "title":
        raise ValueError("当前仅支持 title 匹配模式")

    records = load_bib_records(bibtex_path)
    if not records:
        if bibtex_path.exists() and bibtex_path.is_dir():
            bib_files = _iter_bibtex_source_files(bibtex_path)
            listed = "\n".join([f"- {p.name}" for p in bib_files[:20]])
            more = "" if len(bib_files) <= 20 else f"\n... 另有 {len(bib_files) - 20} 个文件未显示"
            raise RuntimeError(
                "未从 BibTeX 目录解析到任何条目。请检查目录下是否存在可解析的 .bib 文件。\n"
                f"目录路径: {bibtex_path}\n"
                f"扫描到的 .bib 文件数: {len(bib_files)}\n"
                f"文件列表(最多20个):\n{listed}{more}"
            )

        preview = ""
        try:
            preview = bibtex_path.read_text(encoding="utf-8", errors="ignore")[:500]
        except Exception:
            preview = "(无法读取文件内容)"
        raise RuntimeError(
            f"未从 BibTeX 文件解析到任何条目。请检查文件路径和格式。\n文件路径: {bibtex_path}\n文件开头预览:\n{preview}"
        )

    if config.has_pdf_enable:
        pdf_index = build_pdf_index(pdf_dir)
        pdf_matches = match_pdf_paths(records, pdf_index)
    else:
        pdf_matches = [(False, "") for _ in records]

    table = build_main_table(records, pdf_matches)

    written_files: List[Path] = []

    # 写主表
    table_path = output_dir / config.output_table_csv
    table.to_csv(table_path, index=True, index_label="uid", encoding="utf-8-sig")
    written_files.append(table_path)


    return written_files


def execute(config_path: Path) -> List[Path]:
    """供调度器调用的入口：执行并返回写出的文件清单。

    Args:
        config_path: 配置文件路径。

    Returns:
        写出的文件路径列表。
    """
    return _run_and_write_all_outputs(config_path)


def main() -> None:
    """命令行入口：直接运行并打印生成的文件列表。"""
    import sys

    if len(sys.argv) < 2:
        raise SystemExit(
            "用法：python 导入和预处理文献元数据.py <config_path>\n"
            "示例：python 学术研究文献梳理/导入和预处理文献元数据.py workflows/workflow_010/workflow.json"
        )

    cfg_path = Path(sys.argv[1])
    if not cfg_path.exists():
        raise SystemExit(f"配置文件不存在：{cfg_path}")

    written_files = _run_and_write_all_outputs(cfg_path)
    print("生成完成，已写出如下文件：")
    for p in written_files:
        print(f"  - {p}")


if __name__ == "__main__":
    main()
