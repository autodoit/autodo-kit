"""导入和预处理文献元数据

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
import shutil
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import re
import unicodedata

import pandas as pd
from bibtexparser import loads as bibtex_loads
from autodokit.tools import bibliodb_sqlite
from autodokit.tools import normalize_primary_fulltext_attachment_names
from autodokit.tools import resolve_primary_attachment_normalization_settings
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit
from autodokit.tools.literature_translation_tools import run_literature_translation

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
    "output_table_csv": "literatures.csv",
    "storage_backend": "sqlite",
    "sqlite_db_path": "database/references/references.db",
    "tag_list": ["graph", "risk", "bank", "systemic"],
    "tag_match_fields": ["title", "abstract", "keywords"],
    "has_pdf_enable": True,
    "pdf_dir": "pdfs",
    "pdf_match_mode": "title",
}


def _build_task_instance_dir(workspace_root: Path, node_code: str) -> Path:
    task_instance_dir = workspace_root / "tasks" / f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{node_code}"
    task_instance_dir.mkdir(parents=True, exist_ok=False)
    (task_instance_dir / "task_manifest.json").write_text(
        json.dumps(
            {
                "task_uid": task_instance_dir.name,
                "node_code": node_code,
                "workspace_root": str(workspace_root),
                "task_instance_dir": str(task_instance_dir),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return task_instance_dir


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


def load_json_or_py(config_path: Path) -> Dict[str, Any]:
    """读取 JSON 或 Python 配置文件。

    Args:
        config_path: 配置文件路径。

    Returns:
        配置字典。
    """
    config_path = Path(config_path)
    if config_path.suffix.lower() == ".json":
        return json.loads(config_path.read_text(encoding="utf-8-sig"))

    if config_path.suffix.lower() == ".py":
        spec = importlib.util.spec_from_file_location("a02_runtime_config", config_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"无法加载 Python 配置文件: {config_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "CONFIG"):
            return dict(getattr(module, "CONFIG"))
        raise ValueError(f"Python 配置文件缺少 CONFIG 变量: {config_path}")

    raise ValueError(f"不支持的配置文件类型: {config_path.suffix}")


def sparse_from_inverted(inv: Dict[str, List[int]], row_ids: List[int]):
    """把倒排索引转换为 CSC 稀疏矩阵。

    Args:
        inv: 实体到文献 id 列表的映射。
        row_ids: 主表文献 id 顺序。

    Returns:
        稀疏矩阵与列标签列表。
    """
    from scipy.sparse import csc_matrix  # type: ignore

    row_pos = {int(rid): idx for idx, rid in enumerate(row_ids)}
    labels = list(inv.keys())
    data: List[int] = []
    rows: List[int] = []
    cols: List[int] = []

    for col_idx, label in enumerate(labels):
        for rid in inv.get(label, []):
            pos = row_pos.get(int(rid))
            if pos is None:
                continue
            rows.append(pos)
            cols.append(col_idx)
            data.append(1)

    matrix = csc_matrix((data, (rows, cols)), shape=(len(row_ids), len(labels)), dtype=int)
    return matrix, labels


from autodokit.tools.literature_main_table_tools import build_literature_main_table
from autodokit.tools.literature_attachment_tools import build_literature_attachment_inverted_index
from autodokit.tools.literature_tag_tools import build_literature_tag_inverted_index
from autodokit.tools.literature_audit_table_tools import build_entity_to_literatures_csv
from autodokit.tools.literature_audit_table_tools import build_literature_main_audit_csv


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


def _build_index_map_csv(keys: List[str], key_name: str) -> pd.DataFrame:
    """把稀疏矩阵列顺序输出为映射表。"""
    rows = [{"col_index": i, key_name: key} for i, key in enumerate(keys)]
    return pd.DataFrame(rows, columns=["col_index", key_name])


def _resolve_source_paths(raw_value: Any) -> List[Path]:
    """把 origin_bib_paths 统一解析为路径列表。

    Args:
        raw_value: 配置中的原始值。

    Returns:
        规范化后的路径列表。
    """
    if raw_value is None:
        return []
    if isinstance(raw_value, (str, Path)):
        return [Path(raw_value)]
    return [Path(item) for item in list(raw_value)]


def _merge_bib_sources(origin_bib_paths: List[Path], target_bib_path: Path) -> Path | None:
    """把原始 bib 文件合并去重后写入标准 bib 位置。"""
    if not origin_bib_paths:
        return None

    resolved_files: List[Path] = []
    for source in origin_bib_paths:
        if source.is_dir():
            resolved_files.extend(sorted([item for item in source.iterdir() if item.is_file() and item.suffix.lower() == ".bib"]))
        else:
            resolved_files.append(source)

    dedup_files: List[Path] = []
    seen_files: set[Path] = set()
    for item in resolved_files:
        normalized = item.expanduser().resolve()
        if normalized in seen_files:
            continue
        seen_files.add(normalized)
        dedup_files.append(normalized)

    if not dedup_files:
        return None

    target_bib_path.parent.mkdir(parents=True, exist_ok=True)
    seen_entries: set[str] = set()
    merged_entries: List[str] = []
    for path in dedup_files:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        parts = re.split(r"(?=@)", text)
        for part in parts:
            entry = part.strip()
            if not entry:
                continue
            entry_key = re.sub(r"\s+", " ", entry.lower())
            if entry_key in seen_entries:
                continue
            seen_entries.add(entry_key)
            merged_entries.append(entry)

    merged_text = "\n\n".join(merged_entries)
    if merged_text:
        target_bib_path.write_text(merged_text + "\n", encoding="utf-8")
    else:
        target_bib_path.write_text("", encoding="utf-8")
    return target_bib_path


def _sync_attachments(origin_root: Path | None, target_root: Path) -> List[Path]:
    """把原始附件复制到标准附件目录。"""
    if origin_root is None or not origin_root.exists():
        return []

    target_root.mkdir(parents=True, exist_ok=True)
    copied: List[Path] = []
    for source in origin_root.rglob("*"):
        if not source.is_file():
            continue
        relative_path = source.relative_to(origin_root)
        target_path = target_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if not target_path.exists() or source.stat().st_size != target_path.stat().st_size:
            shutil.copy2(source, target_path)
        copied.append(target_path)
    return copied


def _write_csv_if_requested(df: pd.DataFrame, raw_path: Any) -> Path | None:
    """当配置给出路径时写出 CSV。"""
    if not raw_path:
        return None
    path = Path(str(raw_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _save_relation_sparse_bundle(
    output_dir: Path,
    prefix: str,
    inv: Dict[str, List[int]],
    uid_numeric_list: List[int],
) -> List[Path]:
    """保存关系稀疏数据包（inverted pkl + csc npz + 列映射 csv）。

    Args:
        output_dir: 输出目录。
        prefix: 文件名前缀。
        inv: 反向索引。
        uid_numeric_list: 主表 id 序列。

    Returns:
        实际写出的文件列表。
    """
    written: List[Path] = []

    inv_path = output_dir / f"{prefix}_inverted_index.pkl"
    _save_pickle(inv, inv_path)
    written.append(inv_path)

    labels = list(inv.keys())
    try:
        csc_mat, labels_from_sparse = sparse_from_inverted(inv, uid_numeric_list)
        csc_path = output_dir / f"{prefix}_csc.npz"
        saved = _save_csc_matrix(csc_mat, csc_path)
        if saved is not None:
            written.append(saved)
            labels = [str(x) for x in labels_from_sparse]
    except Exception:
        # 稀疏矩阵是性能优化项；失败时保留倒排索引和边表，保证流程可继续。
        pass

    idx_map = _build_index_map_csv(labels, "entity")
    idx_map_path = output_dir / f"{prefix}_entity_index.csv"
    idx_map.to_csv(idx_map_path, index=False, encoding="utf-8-sig")
    written.append(idx_map_path)

    return written


def _run_and_write_all_outputs(config_path: Path) -> List[Path]:
    """核心执行逻辑：读取配置、构建主表，并写出主表 CSV。

    说明：
    - 本事务会输出主表以及 A02 阶段所需的附件绑定关系与标签关系。
    - 关系数据以“倒排索引 + 稀疏矩阵”为主，另附边表 CSV 便于审计。
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

    origin_bib_paths = _resolve_source_paths(merged_cfg.get("origin_bib_paths"))
    origin_attachments_root_raw = merged_cfg.get("origin_attachments_root")
    origin_attachments_root = Path(origin_attachments_root_raw) if origin_attachments_root_raw else None
    released_artifacts = merged_cfg.get("released_artifacts") or {}

    bibtex_path = Path(config.bibtex_path)
    legacy_output_dir = Path(str(merged_cfg.get("legacy_output_dir") or config.output_dir))
    pdf_dir = Path(config.pdf_dir)
    workspace_root = Path(merged_cfg.get("workspace_root") or config_path.parents[2]).resolve()
    workspace_references_dir = workspace_root / "references"
    workspace_bib_dir = workspace_references_dir / "bib"
    workspace_bib_path = workspace_bib_dir / bibtex_path.name
    workspace_attachments_dir = workspace_references_dir / "attachments"
    output_dir = _build_task_instance_dir(workspace_root, "A020")
    legacy_output_dir.mkdir(parents=True, exist_ok=True)

    merged_bib_path = _merge_bib_sources(origin_bib_paths, workspace_bib_path)
    if merged_bib_path is not None:
        bibtex_path = merged_bib_path

    synced_attachments = _sync_attachments(origin_attachments_root, workspace_attachments_dir)
    if origin_attachments_root is not None:
        pdf_dir = workspace_attachments_dir

    if merged_bib_path is not None:
        written_files = [merged_bib_path]
    else:
        written_files = []
    written_files.extend(synced_attachments)

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

    table = build_literature_main_table(records, pdf_matches, normalize_text_fn=normalize_text)

    # 写主表：支持后端选择（csv 或 sqlite），默认 csv（向后兼容）
    backend = str(merged_cfg.get("storage_backend") or merged_cfg.get("backend") or "csv").strip().lower()
    db_path_str = (
        released_artifacts.get("content_db")
        or merged_cfg.get("sqlite_db_path")
        or merged_cfg.get("db_path")
    )
    db_path = Path(db_path_str) if db_path_str else None
    translation_summary: Dict[str, Any] = {
        "status": "SKIP",
        "translated_count": 0,
        "failed_count": 0,
        "audit_path": "",
    }
    attachment_normalization_summary: Dict[str, Any] = {
        "status": "SKIPPED",
        "reason": "disabled",
        "audit_path": "",
    }
    merge_summary: Dict[str, Any] = {
        "incoming_count": int(len(table)),
        "matched_existing_count": 0,
        "inserted_count": int(len(table)),
        "final_literature_count": int(len(table)),
    }
    published_literature_df = table.reset_index()

    uid_numeric_list = [int(x) for x in list(table.index)]

    # 附件绑定关系：使用稀疏结构（npz + 倒排索引）为主。
    attachment_inv = build_literature_attachment_inverted_index(table)
    written_files.extend(
        _save_relation_sparse_bundle(
            output_dir=output_dir,
            prefix="attachments",
            inv=attachment_inv,
            uid_numeric_list=uid_numeric_list,
        )
    )

    # 文献标签关系：按 tag_list 与 tag_match_fields 生成。
    tag_inv = build_literature_tag_inverted_index(
        table,
        config.tag_list,
        config.tag_match_fields,
        normalize_text_fn=normalize_text,
    )
    written_files.extend(
        _save_relation_sparse_bundle(
            output_dir=output_dir,
            prefix="tags",
            inv=tag_inv,
            uid_numeric_list=uid_numeric_list,
        )
    )

    # 审计友好 CSV（长表/聚合表），替代稠密矩阵类输出。
    literature_main_audit_df = build_literature_main_audit_csv(table, attachment_inv, tag_inv)
    literature_main_audit_path = output_dir / "literature_relations.csv"
    literature_main_audit_df.to_csv(literature_main_audit_path, index=False, encoding="utf-8-sig")
    written_files.append(literature_main_audit_path)

    tags_main_audit_df = build_entity_to_literatures_csv(tag_inv, "tag")
    tags_main_audit_path = output_dir / "tags_to_literatures.csv"
    tags_main_audit_df.to_csv(tags_main_audit_path, index=False, encoding="utf-8-sig")
    written_files.append(tags_main_audit_path)

    attachments_main_audit_df = build_entity_to_literatures_csv(attachment_inv, "attachment_path")
    attachments_main_audit_path = output_dir / "attachments_to_literatures.csv"
    attachments_main_audit_df.to_csv(attachments_main_audit_path, index=False, encoding="utf-8-sig")
    written_files.append(attachments_main_audit_path)

    if backend == "csv":
        from autodokit.tools.storage_backend import persist_literature_table

        persisted = persist_literature_table(table, output_dir, config.output_table_csv, backend=backend, db_path=db_path)
        written_files.extend(persisted)
    elif backend == "sqlite" and db_path is not None:
        incoming_literatures_df = table.reset_index()
        incoming_attachment_relations_df = bibliodb_sqlite.build_attachments_df_from_literatures(incoming_literatures_df)
        incoming_tag_relations_df = bibliodb_sqlite.build_tags_df_from_inverted_index(
            incoming_literatures_df,
            tag_inv,
            normalize_text_fn=normalize_text,
        )
        existing_literatures_df = bibliodb_sqlite.load_literatures_df(db_path) if db_path.exists() else pd.DataFrame()
        existing_attachment_relations_df = bibliodb_sqlite.load_attachments_df(db_path) if db_path.exists() else pd.DataFrame()
        existing_tag_relations_df = bibliodb_sqlite.load_tags_df(db_path) if db_path.exists() else pd.DataFrame()
        merged_literatures_df, merged_attachment_relations_df, merged_tag_relations_df, merge_summary = bibliodb_sqlite.merge_reference_records(
            existing_literatures_df=existing_literatures_df,
            existing_attachments_df=existing_attachment_relations_df,
            existing_tags_df=existing_tag_relations_df,
            incoming_literatures_df=incoming_literatures_df,
            incoming_attachments_df=incoming_attachment_relations_df,
            incoming_tags_df=incoming_tag_relations_df,
        )
        bibliodb_sqlite.replace_reference_tables_only(
            db_path,
            literatures_df=merged_literatures_df,
            attachments_df=merged_attachment_relations_df,
            tags_df=merged_tag_relations_df,
        )
        published_literature_df = merged_literatures_df
        written_files.append(db_path)

    published_paths = [
        _write_csv_if_requested(published_literature_df, released_artifacts.get("literature_table")),
        _write_csv_if_requested(literature_main_audit_df, released_artifacts.get("literature_relations")),
        _write_csv_if_requested(tags_main_audit_df, released_artifacts.get("tags_to_literatures")),
        _write_csv_if_requested(attachments_main_audit_df, released_artifacts.get("attachments_to_literatures")),
    ]
    written_files.extend([path for path in published_paths if path is not None])

    if backend == "sqlite" and db_path is not None:
        translation_policy = merged_cfg.get("translation_policy") or {}
        try:
            translation_summary = run_literature_translation(
                content_db=db_path,
                translation_scope="metadata",
                translation_policy=translation_policy,
                workspace_root=workspace_root,
                max_items=int(merged_cfg.get("translation_max_items") or 0),
                affair_name="A020",
                config_path=config_path,
            )
            translation_audit_path = Path(str(translation_summary.get("audit_path") or "").strip())
            if translation_audit_path.exists() and translation_audit_path.is_file():
                written_files.append(translation_audit_path)
        except Exception as translation_exc:
            translation_summary = {
                "status": "FAIL",
                "translated_count": 0,
                "failed_count": 0,
                "audit_path": "",
                "error": str(translation_exc),
            }

        normalization_settings = resolve_primary_attachment_normalization_settings(merged_cfg, workspace_root=workspace_root)
        if normalization_settings.get("enabled"):
            attachment_normalization_summary = normalize_primary_fulltext_attachment_names(
                {
                    "content_db": str(db_path),
                    "workspace_root": str(workspace_root),
                    "output_dir": str(output_dir),
                    **normalization_settings,
                }
            )
            normalization_audit_path = Path(str(attachment_normalization_summary.get("audit_path") or "").strip())
            if normalization_audit_path.exists() and normalization_audit_path.is_file():
                written_files.append(normalization_audit_path)

    gate_review_path = released_artifacts.get("gate_review")
    if gate_review_path:
        match_count = int(table["has_fulltext"].astype(str).isin(["1", "true", "True"]).sum()) if "has_fulltext" in table.columns else 0
        gate_payload = {
            "gate_code": "G020",
            "affair_code": "A020",
            "summary": {
                "literature_count": int(len(table)),
                "matched_existing_count": int(merge_summary.get("matched_existing_count") or 0),
                "inserted_count": int(merge_summary.get("inserted_count") or 0),
                "final_literature_count": int(merge_summary.get("final_literature_count") or len(table)),
                "attachment_file_count": int(len(synced_attachments)) if synced_attachments else int(len(attachment_inv)),
                "matched_fulltext_count": match_count,
                "metadata_translation_status": str(translation_summary.get("status") or "SKIP"),
                "metadata_translation_count": int(translation_summary.get("translated_count") or 0),
                "metadata_translation_failed_count": int(translation_summary.get("failed_count") or 0),
                "attachment_normalization_status": str(attachment_normalization_summary.get("status") or "SKIPPED"),
                "attachment_normalization_renamed_count": int(attachment_normalization_summary.get("renamed_count") or 0),
                "attachment_normalization_conflict_count": int(attachment_normalization_summary.get("conflict_count") or 0),
            },
            "decision_suggestion": "pass_next" if len(table) > 0 else "revise_current_iteration",
        }
        gate_path = Path(str(gate_review_path))
        gate_path.parent.mkdir(parents=True, exist_ok=True)
        gate_path.write_text(json.dumps(gate_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written_files.append(gate_path)

        if legacy_output_dir != output_dir:
            for artifact_path in [
                output_dir / config.output_table_csv,
                output_dir / "literature_relations.csv",
                output_dir / "tags_to_literatures.csv",
                output_dir / "attachments_to_literatures.csv",
                gate_path,
            ]:
                if artifact_path.exists():
                    legacy_target = legacy_output_dir / artifact_path.name
                    if artifact_path.is_file():
                        legacy_target.write_text(artifact_path.read_text(encoding="utf-8"), encoding="utf-8")


    return written_files


@affair_auto_git_commit("A020")
def execute(config_path: Path) -> List[Path]:
    """供调度器调用的入口：执行并返回写出的文件清单。

    Args:
        config_path: 配置文件路径。

    Returns:
        写出的文件路径列表。
    """
    written = _run_and_write_all_outputs(config_path)
    try:
        raw_cfg = load_json_or_py(config_path)
        workspace_root = Path(str(raw_cfg.get("workspace_root") or config_path.parents[2])).resolve()
        content_db = workspace_root / "database" / "content" / "content.db"
        bibliodb_sqlite.upsert_workspace_node_state_rows(
            content_db,
            [
                {
                    "node_code": "A020",
                    "node_name": "文献导入与预处理",
                    "pending_run": 0,
                    "in_progress": 0,
                    "completed": 1,
                    "gate_status": "pass_next",
                    "summary": "A020 导入与预处理完成",
                    "next_node_code": "A030",
                    "failure_reason": "",
                    "retry_count": 0,
                }
            ],
        )
    except Exception:
        pass
    return written


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
