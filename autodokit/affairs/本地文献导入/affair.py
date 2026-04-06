"""本地文献导入事务。

该事务负责扫描本地 `bib` / `rdf` 元数据与附件引用关系，
并在需要时把结果持久化到项目文献数据库模板目录。
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import xml.etree.ElementTree as element_tree
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import bibtexparser
import pandas as pd

from autodokit.tools import load_json_or_py
from autodokit.tools.storage_backend import load_reference_tables, persist_reference_tables
from autodokit.tools.time_utils import now_iso

SUPPORTED_METADATA_SUFFIXES = {".bib", ".rdf"}
ATTACHMENT_SUFFIXES = {".pdf", ".md", ".docx", ".doc", ".html", ".txt", ".caj"}
RDF_NAMESPACES = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "z": "http://www.zotero.org/namespaces/export#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "bib": "http://purl.org/net/biblio#",
    "dcterms": "http://purl.org/dc/terms/",
}


def utc_now_iso() -> str:
    """返回 ISO 时间字符串（默认北京时间）。

    Returns:
        ISO 时间字符串。
    """

    return now_iso()


def normalize_text(value: str) -> str:
    """规范化文本，便于做最小去重和匹配。

    Args:
        value: 原始文本。

    Returns:
        规范化后的文本。
    """

    collapsed = re.sub(r"\s+", " ", value).strip().lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff ]+", "", collapsed)


@dataclass(slots=True, frozen=True)
class LocalReferenceItemRecord:
    """文献条目记录。

    Args:
        item_uid: 文献条目 UID。
        title: 标题。
        authors: 作者字符串。
        year: 年份。
        source_type: 来源类型。
        origin_path: 原始元数据路径。
        status: 当前状态。
        created_at: 创建时间。
        updated_at: 更新时间。
        citation_key: 引用键。
        abstract: 摘要。
        tags: 标签集合。
    """

    item_uid: str
    title: str
    authors: str
    year: str
    source_type: str
    origin_path: str
    status: str
    created_at: str
    updated_at: str
    citation_key: str = ""
    abstract: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_db_row(self) -> dict[str, str]:
        """导出为 `literatures.csv` 所需字段。

        Returns:
            数据库写入行。
        """

        return {
            "uid_literature": self.item_uid,
            "cite_key": self.citation_key,
            "title": self.title,
            "title_norm": normalize_text(self.title),
            "first_author": self.authors.split(";")[0].strip() if self.authors.strip() else "",
            "year": self.year,
            "entry_type": "article",
            "is_placeholder": "0",
            "has_fulltext": "0",
            "primary_attachment_name": "",
            "standard_note_uid": "",
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "authors": self.authors,
            "abstract": self.abstract,
            "keywords": "|".join(self.tags),
            "source_type": self.source_type,
            "origin_path": self.origin_path,
            "source": self.status,
            "clean_title": normalize_text(self.title).replace(" ", "_"),
        }


@dataclass(slots=True, frozen=True)
class LocalReferenceFileRecord:
    """文献附件记录。

    Args:
        file_uid: 附件 UID。
        item_uid: 归属条目 UID。
        file_path: 文件路径。
        file_type: 文件类型。
        checksum: 文件校验摘要。
        created_at: 创建时间。
    """

    file_uid: str
    item_uid: str
    file_path: str
    file_type: str
    checksum: str
    created_at: str

    def to_db_row(self) -> dict[str, str]:
        """导出为 `literature_attachments.csv` 所需字段。

        Returns:
            数据库写入行。
        """

        return {
            "uid_literature": self.item_uid,
            "attachment_name": Path(self.file_path).name,
            "attachment_type": self.file_type or Path(self.file_path).suffix.lower().lstrip("."),
            "is_primary": "1" if Path(self.file_path).suffix.lower() == ".pdf" else "0",
            "note": self.checksum,
        }


@dataclass(slots=True, frozen=True)
class LocalReferenceIngestionResult:
    """本地文献导入结果。

    Args:
        item_records: 文献条目记录。
        file_records: 附件记录。
        metadata_sources: 元数据源路径。
        unmatched_files: 未归属附件列表。
        persisted: 是否已写入数据库。
        next_node: 推荐后续节点。
    """

    item_records: tuple[LocalReferenceItemRecord, ...]
    file_records: tuple[LocalReferenceFileRecord, ...]
    metadata_sources: tuple[str, ...]
    unmatched_files: tuple[str, ...]
    persisted: bool
    next_node: str

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。

        Returns:
            可序列化结果。
        """

        return {
            "items": [asdict(record) for record in self.item_records],
            "files": [asdict(record) for record in self.file_records],
            "metadata_sources": list(self.metadata_sources),
            "unmatched_files": list(self.unmatched_files),
            "persisted": self.persisted,
            "next_node": self.next_node,
        }


class LocalReferenceIngestionEngine:
    """本地文献导入引擎。"""

    def run(
        self,
        project_root: str | Path,
        source_paths: list[str] | tuple[str, ...],
        persist: bool = False,
    ) -> LocalReferenceIngestionResult:
        """执行本地文献导入。

        Args:
            project_root: 项目根目录。
            source_paths: 本地元数据或目录路径列表。
            persist: 是否写入文献数据库模板。

        Returns:
            导入结果。
        """

        root = Path(project_root)
        expanded_paths = self._expand_source_paths(source_paths=source_paths)
        metadata_paths = [path for path in expanded_paths if path.suffix.lower() in SUPPORTED_METADATA_SUFFIXES]
        attachment_paths = [path for path in expanded_paths if path.suffix.lower() in ATTACHMENT_SUFFIXES]

        item_records: dict[str, LocalReferenceItemRecord] = {}
        file_records: dict[str, LocalReferenceFileRecord] = {}
        linked_files: set[str] = set()

        for metadata_path in metadata_paths:
            if metadata_path.suffix.lower() == ".bib":
                parsed_items = self._parse_bib_file(metadata_path=metadata_path)
                for item_record in parsed_items:
                    item_records[item_record.item_uid] = item_record
                continue

            parsed_items, parsed_files = self._parse_rdf_file(metadata_path=metadata_path)
            for item_record in parsed_items:
                item_records[item_record.item_uid] = item_record
            for file_record in parsed_files:
                file_records[file_record.file_uid] = file_record
                linked_files.add(file_record.file_path)

        unmatched_files = tuple(str(path) for path in attachment_paths if str(path) not in linked_files)

        if persist:
            self._persist_records(
                project_root=root,
                item_records=tuple(item_records.values()),
                file_records=tuple(file_records.values()),
                metadata_paths=metadata_paths,
            )

        return LocalReferenceIngestionResult(
            item_records=tuple(item_records.values()),
            file_records=tuple(file_records.values()),
            metadata_sources=tuple(str(path) for path in metadata_paths),
            unmatched_files=unmatched_files,
            persisted=persist,
            next_node="knowledge_prescreen",
        )

    def _expand_source_paths(self, source_paths: list[str] | tuple[str, ...]) -> list[Path]:
        """展开输入路径列表。

        Args:
            source_paths: 输入路径列表。

        Returns:
            展开后的文件路径列表。
        """

        expanded: list[Path] = []
        for raw_path in source_paths:
            path = Path(raw_path)
            if path.is_dir():
                expanded.extend(file for file in path.rglob("*") if file.is_file())
                continue
            if path.is_file():
                expanded.append(path)
        return expanded

    def _parse_bib_file(self, metadata_path: Path) -> tuple[LocalReferenceItemRecord, ...]:
        """解析 BibTeX 文件。

        Args:
            metadata_path: BibTeX 文件路径。

        Returns:
            解析得到的文献条目集合。
        """

        with metadata_path.open("r", encoding="utf-8") as handle:
            database = bibtexparser.load(handle)

        now = utc_now_iso()
        records: list[LocalReferenceItemRecord] = []
        for entry in database.entries:
            title = str(entry.get("title") or "").strip()
            if not title:
                continue
            authors = str(entry.get("author") or "").replace("\n", " ").strip()
            year = str(entry.get("year") or "").strip()
            citation_key = str(entry.get("ID") or "").strip()
            item_uid = self._build_item_uid(
                title=title,
                year=year,
                citation_key=citation_key,
            )
            tags = self._split_tags(str(entry.get("keywords") or ""))
            records.append(
                LocalReferenceItemRecord(
                    item_uid=item_uid,
                    title=title,
                    authors=authors,
                    year=year,
                    source_type="local_bib",
                    origin_path=str(metadata_path),
                    status="ingested",
                    created_at=now,
                    updated_at=now,
                    citation_key=citation_key,
                    abstract=str(entry.get("abstract") or "").strip(),
                    tags=tags,
                )
            )
        return tuple(records)

    def _parse_rdf_file(
        self,
        metadata_path: Path,
    ) -> tuple[tuple[LocalReferenceItemRecord, ...], tuple[LocalReferenceFileRecord, ...]]:
        """解析 Zotero RDF 文件。

        Args:
            metadata_path: RDF 文件路径。

        Returns:
            文献条目与附件记录。
        """

        tree = element_tree.parse(metadata_path)
        root = tree.getroot()
        attachments_by_anchor = self._collect_rdf_attachments(root=root, metadata_path=metadata_path)
        item_records: list[LocalReferenceItemRecord] = []
        file_records: list[LocalReferenceFileRecord] = []
        now = utc_now_iso()

        for node in root:
            item_type = self._find_text(node=node, xpath="z:itemType")
            if item_type in {"attachment", "note"}:
                continue

            title = self._find_text(node=node, xpath="dc:title")
            if not title:
                continue
            year = self._extract_year(node=node)
            authors = "; ".join(self._extract_rdf_authors(node=node))
            citation_key = self._find_text(node=node, xpath="z:citationKey")
            abstract = self._find_text(node=node, xpath="dcterms:abstract")
            tags = tuple(self._extract_rdf_tags(node=node))
            item_uid = self._build_item_uid(
                title=title,
                year=year,
                citation_key=citation_key,
            )
            item_records.append(
                LocalReferenceItemRecord(
                    item_uid=item_uid,
                    title=title,
                    authors=authors,
                    year=year,
                    source_type="local_rdf",
                    origin_path=str(metadata_path),
                    status="ingested",
                    created_at=now,
                    updated_at=now,
                    citation_key=citation_key,
                    abstract=abstract,
                    tags=tags,
                )
            )

            for anchor in self._extract_attachment_anchors(node=node):
                attachment = attachments_by_anchor.get(anchor)
                if attachment is None:
                    continue
                file_records.append(
                    LocalReferenceFileRecord(
                        file_uid=self._build_file_uid(item_uid=item_uid, file_path=attachment["file_path"]),
                        item_uid=item_uid,
                        file_path=attachment["file_path"],
                        file_type=attachment["file_type"],
                        checksum=attachment["checksum"],
                        created_at=now,
                    )
                )

        return tuple(item_records), tuple(file_records)

    def _collect_rdf_attachments(
        self,
        root: element_tree.Element,
        metadata_path: Path,
    ) -> dict[str, dict[str, str]]:
        """收集 RDF 附件节点。

        Args:
            root: RDF 根节点。
            metadata_path: RDF 文件路径。

        Returns:
            `anchor -> 附件信息` 映射。
        """

        attachments: dict[str, dict[str, str]] = {}
        for node in root.findall("z:Attachment", RDF_NAMESPACES):
            anchor = str(node.attrib.get(f"{{{RDF_NAMESPACES['rdf']}}}about") or "").strip()
            if not anchor:
                continue
            title = self._find_text(node=node, xpath="dc:title")
            path_resource = node.find("z:path", RDF_NAMESPACES)
            if path_resource is not None:
                relative_path = str(path_resource.attrib.get(f"{{{RDF_NAMESPACES['rdf']}}}resource") or "").strip()
                file_path = str((metadata_path.parent / relative_path).resolve()) if relative_path else title
            else:
                file_path = title
            attachments[anchor] = {
                "file_path": file_path,
                "file_type": self._find_text(node=node, xpath="link:type") or Path(file_path).suffix.lower().lstrip("."),
                "checksum": self._build_checksum(value=file_path),
            }
        return attachments

    def _extract_attachment_anchors(self, node: element_tree.Element) -> tuple[str, ...]:
        """提取条目引用的附件锚点。

        Args:
            node: RDF 条目节点。

        Returns:
            附件锚点集合。
        """

        anchors: list[str] = []
        for link_node in node.findall("link:link", {**RDF_NAMESPACES, "link": "http://purl.org/rss/1.0/modules/link/"}):
            anchor = str(link_node.attrib.get(f"{{http://www.w3.org/1999/02/22-rdf-syntax-ns#}}resource") or "").strip()
            if anchor:
                anchors.append(anchor)
        return tuple(anchors)

    def _extract_rdf_authors(self, node: element_tree.Element) -> list[str]:
        """提取 RDF 作者信息。

        Args:
            node: RDF 条目节点。

        Returns:
            作者列表。
        """

        authors: list[str] = []
        author_root = node.find("bib:authors/rdf:Seq", RDF_NAMESPACES)
        if author_root is None:
            return authors
        for author_node in author_root.findall("rdf:li", RDF_NAMESPACES):
            surname = author_node.findtext("foaf:Person/foaf:surname", default="", namespaces=RDF_NAMESPACES).strip()
            given_name = author_node.findtext("foaf:Person/foaf:givenName", default="", namespaces=RDF_NAMESPACES).strip()
            full_name = " ".join(part for part in [surname, given_name] if part).strip()
            if full_name:
                authors.append(full_name)
        return authors

    def _extract_rdf_tags(self, node: element_tree.Element) -> list[str]:
        """提取 RDF 标签。

        Args:
            node: RDF 条目节点。

        Returns:
            标签列表。
        """

        tags: list[str] = []
        for tag_node in node.findall("dc:subject", RDF_NAMESPACES):
            text = (tag_node.text or "").strip()
            if text:
                tags.append(text)
                continue
            auto_tag = tag_node.findtext("z:AutomaticTag/rdf:value", default="", namespaces=RDF_NAMESPACES).strip()
            if auto_tag:
                tags.append(auto_tag)
        return tags

    def _extract_year(self, node: element_tree.Element) -> str:
        """从 RDF 条目中抽取年份。

        Args:
            node: RDF 条目节点。

        Returns:
            年份字符串。
        """

        raw_date = self._find_text(node=node, xpath="dc:date")
        if len(raw_date) >= 4:
            return raw_date[:4]
        return raw_date

    def _find_text(self, node: element_tree.Element, xpath: str) -> str:
        """查找 XML 文本内容。

        Args:
            node: 当前节点。
            xpath: 带命名空间前缀的 XPath。

        Returns:
            文本值。
        """

        return node.findtext(xpath, default="", namespaces={**RDF_NAMESPACES, "link": "http://purl.org/rss/1.0/modules/link/"}).strip()

    def _split_tags(self, raw_tags: str) -> tuple[str, ...]:
        """拆分标签字段。

        Args:
            raw_tags: 原始标签字符串。

        Returns:
            标签元组。
        """

        return tuple(tag.strip() for tag in re.split(r"[;,|]", raw_tags) if tag.strip())

    def _build_item_uid(self, title: str, year: str, citation_key: str) -> str:
        """构建稳定文献 UID。

        Args:
            title: 标题。
            year: 年份。
            citation_key: 引用键。

        Returns:
            文献 UID。
        """

        base = citation_key or f"{normalize_text(title)}::{year}"
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
        return f"lit-{digest}"

    def _build_file_uid(self, item_uid: str, file_path: str) -> str:
        """构建稳定附件 UID。

        Args:
            item_uid: 文献 UID。
            file_path: 文件路径。

        Returns:
            附件 UID。
        """

        digest = hashlib.sha1(f"{item_uid}::{file_path}".encode("utf-8")).hexdigest()[:12]
        return f"file-{digest}"

    def _build_checksum(self, value: str) -> str:
        """构建轻量校验摘要。

        Args:
            value: 摘要来源字符串。

        Returns:
            校验摘要。
        """

        return hashlib.sha1(value.encode("utf-8")).hexdigest()

    def _persist_records(
        self,
        project_root: Path,
        item_records: tuple[LocalReferenceItemRecord, ...],
        file_records: tuple[LocalReferenceFileRecord, ...],
        metadata_paths: list[Path],
    ) -> None:
        """持久化导入结果。

        Args:
            project_root: 项目根目录。
            item_records: 条目记录。
            file_records: 附件记录。
            metadata_paths: 元数据路径列表。
        """

        content_db_dir = project_root / "database" / "content"
        manifest_dir = project_root / "references" / "normal" / "manifest"
        content_db_dir.mkdir(parents=True, exist_ok=True)
        manifest_dir.mkdir(parents=True, exist_ok=True)

        content_db = content_db_dir / "content.db"
        manifest_json = manifest_dir / "literature-manifest.json"

        primary_attachments: dict[str, str] = {}
        for file_record in file_records:
            file_name = Path(file_record.file_path).name
            if file_record.item_uid not in primary_attachments and Path(file_record.file_path).suffix.lower() == ".pdf":
                primary_attachments[file_record.item_uid] = file_name

        item_rows = []
        for record in item_records:
            row = record.to_db_row()
            primary_name = primary_attachments.get(record.item_uid, "")
            if primary_name:
                row["primary_attachment_name"] = primary_name
                row["has_fulltext"] = "1"
            item_rows.append(row)

        existing_items, existing_files, _ = load_reference_tables(db_path=content_db)

        new_items_df = pd.DataFrame(item_rows)
        new_files_df = pd.DataFrame([record.to_db_row() for record in file_records])

        merged_items_df = pd.concat([existing_items, new_items_df], ignore_index=True) if not existing_items.empty else new_items_df
        if not merged_items_df.empty and "uid_literature" in merged_items_df.columns:
            merged_items_df = merged_items_df.drop_duplicates(subset=["uid_literature"], keep="last").reset_index(drop=True)

        merged_files_df = pd.concat([existing_files, new_files_df], ignore_index=True) if not existing_files.empty else new_files_df
        if not merged_files_df.empty and "attachment_name" in merged_files_df.columns:
            merged_files_df = merged_files_df.drop_duplicates(subset=["attachment_name"], keep="last").reset_index(drop=True)

        persist_reference_tables(
            literatures_df=merged_items_df,
            attachments_df=merged_files_df,
            db_path=content_db,
        )

        manifest = {
            "schema_version": "0.4.0-sqlite-primary",
            "generated_at": utc_now_iso(),
            "item_count": int(len(merged_items_df)),
            "file_count": int(len(merged_files_df)),
            "metadata_sources": [str(path) for path in metadata_paths],
            "primary_backend": "sqlite",
            "primary_db_path": str(content_db.resolve()),
            "vector_index_ready": False,
            "latest_stage": "local_reference_ingestion",
        }
        manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。

    Args:
        config_path: 事务配置路径。

    Returns:
        输出文件路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    engine = LocalReferenceIngestionEngine()
    result = engine.run(
        project_root=str(raw_cfg.get("project_root") or ""),
        source_paths=list(raw_cfg.get("source_paths") or []),
        persist=bool(raw_cfg.get("persist") or False),
    )

    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认已在 tools 层完成统一路径预处理，"
            f"当前值={str(raw_cfg.get('output_dir') or '')!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / "local_reference_ingestion_result.json"
    out_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
