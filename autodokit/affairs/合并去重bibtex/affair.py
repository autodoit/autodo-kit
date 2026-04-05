"""
合并去重bibtex脚本。

该脚本扫描指定目录下的 .bib 文件，解析并合并条目，按配置的去重策略进行去重并输出合并后的 .bib（或 JSON/CSV）。

主要功能：
- 提供 programmatic API `merge_bib_files` 以便被单元测试或其他脚本调用。
- 提供 CLI 接口用于命令行运行。

注意：该脚本使用 `bibtexparser` 作为首选解析/导出库（项目的 `requirements.txt` 已包含该依赖）。
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

import bibtexparser
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.bibdatabase import BibDatabase


def _normalize_doi(doi: str) -> str:
    """归一化 DOI，去掉 URL 前缀并小写。

    Args:
        doi: 原始 DOI 字符串。

    Returns:
        归一化后的 DOI 字符串。
    """
    if not doi:
        return ""
    doi = doi.strip()
    doi = doi.replace('https://doi.org/', '')
    doi = doi.replace('http://doi.org/', '')
    doi = doi.replace('doi:', '')
    return doi.lower()


def _normalize_title(title: str) -> str:
    """简单归一化 title：小写、去掉多余空白与常见标点。

    Args:
        title: 原始标题。

    Returns:
        归一化后的标题。
    """
    if not title:
        return ""
    s = title.lower()
    # 移除大括号，BibTeX 中常用于保护大小写
    for ch in '{}"\'':
        s = s.replace(ch, ' ')
    # 保留字母数字与空白为主
    import re

    s = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", ' ', s)
    s = ' '.join(s.split())
    return s


def _normalize_authors(authors: str) -> str:
    """归一化作者字段，尽量抽取姓氏并以逗号连接（简化处理）。

    Args:
        authors: BibTeX 的 author 字段字符串（authors 用 " and " 分隔）。

    Returns:
        归一化后的作者姓氏串。
    """
    if not authors:
        return ""
    parts = [p.strip() for p in authors.replace('\n', ' ').split(' and ') if p.strip()]
    surnames = []
    for p in parts:
        # 处理常见的 "Last, First" 或 "First Last" 两种格式
        if ',' in p:
            last = p.split(',')[0].strip()
        else:
            last = p.split()[-1].strip()
        surnames.append(last.lower())
    return ','.join(surnames)


def _entry_key(entry: Dict[str, str], strategy: str = 'doi_then_norm') -> Tuple[str, str]:
    """生成条目的匹配键。

    返回 (key_type, key_value)，用于区分不同匹配策略与后续冲突处理。
    key_type 可为 'doi' 或 'norm' 或 'raw'
    """
    doi = _normalize_doi(entry.get('doi', '') or entry.get('DOI', ''))
    if doi:
        return 'doi', doi

    if strategy in ('doi_then_norm', 'title_author_year', 'title_only'):
        title = _normalize_title(entry.get('title', ''))
        authors = _normalize_authors(entry.get('author', '') or entry.get('authors', ''))
        year = (entry.get('year') or entry.get('YEAR') or '')[:4]
        if strategy == 'title_only':
            key = f"title:{title}"
        else:
            key = f"t:{title}|a:{authors}|y:{year}"
        return 'norm', key

    # 回退到 raw key（条目 id 或 key 字段）
    return 'raw', entry.get('ID', '')


def _merge_entries(existing: Dict[str, str], new: Dict[str, str]) -> Dict[str, str]:
    """合并两个条目（existing 为保留条目，new 为可填充的条目）。

    合并策略：
    - 对于空字段，用 new 填充。
    - 对于多值字段（author, keywords），做集合合并。
    - 对于 abstract，保留较长者。

    Args:
        existing: 已存在的条目。
        new: 新条目。

    Returns:
        合并后的条目（修改后的 existing）。
    """
    # 重要字段合并策略
    multi_fields = ['author', 'authors', 'keywords', 'keyword']
    for k, v in new.items():
        if not v:
            continue
        if k in existing and existing.get(k):
            if k in multi_fields:
                # 将多个关键词/作者合并为集合
                exist_vals = set([x.strip() for x in (existing.get(k) or '').replace('\n', ' ').split(';') if x.strip()])
                new_vals = set([x.strip() for x in v.replace('\n', ' ').split(';') if x.strip()])
                merged = '; '.join(sorted(exist_vals.union(new_vals)))
                existing[k] = merged
            elif k == 'abstract':
                # 保留较长的摘要
                if len(v) > len(existing.get(k, '')):
                    existing[k] = v
            else:
                # 其它字段保留 existing（优先），否则填充
                pass
        else:
            existing[k] = v
    return existing


def merge_bib_files(
    input_dir: str | Path,
    output_file: Optional[str | Path] = None,
    dedup_strategy: str = 'doi_then_norm',
    conflict_resolution: str = 'merge',
    dry_run: bool = False,
    output_format: str = 'bib',
    backup: bool = True,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """合并并去重指定目录下的 .bib 文件。

    Args:
        input_dir: 包含 .bib 文件的目录路径。
        output_file: 输出合并文件路径（默认在当前目录下生成 merged_dedup.bib）。
        dedup_strategy: 去重策略，支持 'doi_then_norm', 'title_author_year', 'title_only', 'none'.
        conflict_resolution: 冲突解决策略，'first' 或 'merge'。
        dry_run: 如果为 True，仅返回统计信息并记录将被合并/跳过的条目。
        output_format: 输出格式，'bib'（默认）、'json' 或 'csv'（csv 未实现，留作扩展）。
        backup: 如果输出文件已存在，是否备份旧文件。
        logger: 可选 logger，用于测试时传入自定义 logger。

    Returns:
        一个结果字典，包含统计信息（merged_count, total_input_count, duplicates, errors 等）。
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    input_dir = Path(input_dir)
    if output_file is None:
        raise ValueError("output_file 不能为空：本事务不负责选择默认输出路径，请由调度层提供绝对路径")

    output_file = Path(output_file)
    if not output_file.is_absolute():
        raise ValueError(f"output_file 必须为绝对路径（应由调度层预处理）：{str(output_file)!r}")

    bib_paths = sorted([p for p in input_dir.glob('*.bib')])
    total_in = 0
    db = BibDatabase()
    key_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    # 新增索引以支持 DOI 与归一化键的互相匹配
    doi_index: Dict[str, Tuple[str, str]] = {}
    norm_index: Dict[str, Tuple[str, str]] = {}
    duplicates = []
    errors = []

    for p in bib_paths:
        try:
            with p.open('r', encoding='utf-8') as fh:
                bib = bibtexparser.load(fh)
        except Exception as e:
            logger.warning(f"无法解析文件 {p}: {e}")
            errors.append({'file': str(p), 'error': str(e)})
            continue
        for entry in bib.entries:
            total_in += 1
            # 计算 DOI 与归一化键，便于交叉匹配
            doi = _normalize_doi(entry.get('doi', '') or entry.get('DOI', ''))
            # 始终生成归一化键（title+author+year）用于后备匹配
            title_norm = _normalize_title(entry.get('title', ''))
            authors_norm = _normalize_authors(entry.get('author', '') or entry.get('authors', ''))
            year_norm = (entry.get('year') or entry.get('YEAR') or '')[:4]
            norm_key = f"t:{title_norm}|a:{authors_norm}|y:{year_norm}"

            # 匹配优先级：1) DOI 2) 归一化键 3) 新建条目
            found_map_key: Optional[Tuple[str, str]] = None
            if doi and doi in doi_index:
                found_map_key = doi_index[doi]
            elif norm_key and norm_key in norm_index:
                found_map_key = norm_index[norm_key]

            if found_map_key is not None:
                existing = cast(Dict[str, str], key_map[found_map_key]['entry'])
                source_files = cast(list, key_map[found_map_key]['sources'])
                source_files.append(str(p))
                if conflict_resolution == 'first':
                    pass
                else:
                    merged = _merge_entries(existing, entry)
                    key_map[found_map_key]['entry'] = merged
                duplicates.append({'key': found_map_key, 'kept_from': key_map[found_map_key]['origin_file'], 'merged_from': str(p)})
                # 如果现有条目没有 DOI 而新条目有 DOI，更新 DOI 索引指向该 map_key
                if doi:
                    doi_index[doi] = found_map_key
                continue

            # 新建条目：选择合适的 map_key（优先 DOI，否则用归一化键或生成键）
            if doi:
                map_key = ('doi', doi)
            elif norm_key:
                map_key = ('norm', norm_key)
            else:
                map_key = ('raw', f'__generated__{total_in}')

            key_map[map_key] = {'entry': dict(entry), 'sources': [str(p)], 'origin_file': str(p)}
            # 更新索引
            if doi:
                doi_index[doi] = map_key
            if norm_key:
                norm_index[norm_key] = map_key

    # 将结果写出
    merged_entries = [cast(Dict[str, str], v['entry']) for v in key_map.values()]
    result = {
        'total_input_count': total_in,
        'merged_count': len(merged_entries),
        'duplicates': duplicates,
        'errors': errors,
    }

    if dry_run:
        logger.info(f"Dry run: input={total_in}, merged={len(merged_entries)}, duplicates={len(duplicates)}")
        return result

    # 备份已有输出文件
    if output_file.exists() and backup:
        bak = output_file.with_suffix(output_file.suffix + f".{datetime.now().strftime('%Y%m%d%H%M%S')}.bak")
        shutil.copy(str(output_file), str(bak))
        logger.info(f"已备份旧输出文件到 {bak}")

    if output_format == 'bib':
        db.entries = merged_entries
        writer = BibTexWriter()
        writer.indent = '    '
        writer.order_entries_by = None
        with output_file.open('w', encoding='utf-8') as fh:
            fh.write(writer.write(db))
        logger.info(f"已写入合并后的文件: {output_file}")
    elif output_format == 'json':
        with output_file.open('w', encoding='utf-8') as fh:
            json.dump(merged_entries, fh, ensure_ascii=False, indent=2)
        logger.info(f"已写入 JSON 文件: {output_file}")
    else:
        raise ValueError(f"不支持的输出格式: {output_format}")

    return result


def _build_cli_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='从目录合并并去重 .bib 文件')
    p.add_argument('--input-dir', '-i', required=True, help='包含 .bib 文件的目录')
    p.add_argument('--output-file', '-o', help='输出合并后的文件路径，默认 ./merged_dedup.bib')
    p.add_argument('--dedup-strategy', default='doi_then_norm', choices=['doi_then_norm', 'title_author_year', 'title_only', 'none'])
    p.add_argument('--conflict-resolution', default='merge', choices=['merge', 'first'])
    p.add_argument('--dry-run', action='store_true', help='仅统计不写文件')
    p.add_argument('--output-format', default='bib', choices=['bib', 'json'])
    p.add_argument('--no-backup', dest='backup', action='store_false', help='如果输出文件存在，不备份')
    p.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    return p


def main(argv: Optional[list] = None) -> int:
    """脚本入口。返回 0 表示成功，非 0 表示失败。"""
    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))
    logger = logging.getLogger('合并去重bibtex')

    try:
        res = merge_bib_files(
            input_dir=args.input_dir,
            output_file=args.output_file,
            dedup_strategy=args.dedup_strategy,
            conflict_resolution=args.conflict_resolution,
            dry_run=args.dry_run,
            output_format=args.output_format,
            backup=args.backup,
            logger=logger,
        )
        logger.info(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in res.items()}, ensure_ascii=False))
        return 0
    except Exception as e:
        logger.exception(f"处理失败: {e}")
        return 2


if __name__ == '__main__':
    raise SystemExit(main())


def execute(config_path: Path, workspace_root: Path | None = None, **_: Any) -> List[Path]:
    """事务标准执行入口。

    Args:
        config_path: 配置文件路径。
        workspace_root: 工作区根目录（兼容参数，当前不直接使用）。
        **_: 兼容额外关键字参数。

    Returns:
        输出文件路径列表。

    Raises:
        ValueError: 配置缺失必填字段时抛出。
        RuntimeError: 合并执行失败时抛出。
    """

    _ = workspace_root
    payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    input_dir = payload.get("input_dir")
    output_file = payload.get("output_file")
    if not input_dir:
        raise ValueError("合并去重bibtex 缺少 input_dir")
    if not output_file:
        raise ValueError("合并去重bibtex 缺少 output_file")

    result = merge_bib_files(
        input_dir=input_dir,
        output_file=output_file,
        dedup_strategy=str(payload.get("dedup_strategy") or "doi_then_norm"),
        conflict_resolution=str(payload.get("conflict_resolution") or "merge"),
        dry_run=bool(payload.get("dry_run", False)),
        output_format=str(payload.get("output_format") or "bib"),
        backup=bool(payload.get("backup", True)),
    )
    if result.get("errors"):
        raise RuntimeError(f"合并去重bibtex 出现错误：{result['errors']}")

    return [Path(output_file)]

