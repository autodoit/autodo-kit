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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

import bibtexparser

from autodokit.tools import load_json_or_py

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
    """返回 UTC ISO 时间字符串。

    Returns:
        UTC ISO 时间字符串。
    """

    return datetime.now(tz=UTC).isoformat()


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
        """导出为 `literature_items.csv` 所需字段。

        Returns:
            数据库写入行。
        """

        return {
            "item_uid": self.item_uid,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "source_type": self.source_type,
            "origin_path": self.origin_path,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
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
        """导出为 `literature_files.csv` 所需字段。

        Returns:
            数据库写入行。
        """

        return {
            "file_uid": self.file_uid,
            "item_uid": self.item_uid,
            "file_path": self.file_path,
            "file_type": self.file_type,
            "checksum": self.checksum,
            "created_at": self.created_at,
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

        references_db_dir = project_root / "database" / "references"
        manifest_dir = project_root / "references" / "normal" / "manifest"
        references_db_dir.mkdir(parents=True, exist_ok=True)
        manifest_dir.mkdir(parents=True, exist_ok=True)

        items_csv = references_db_dir / "literature_items.csv"
        files_csv = references_db_dir / "literature_files.csv"
        manifest_json = manifest_dir / "literature-manifest.json"

        merged_items = self._merge_csv_rows(
            csv_path=items_csv,
            primary_key="item_uid",
            new_rows=[record.to_db_row() for record in item_records],
            fieldnames=["item_uid", "title", "authors", "year", "source_type", "origin_path", "status", "created_at", "updated_at"],
        )
        merged_files = self._merge_csv_rows(
            csv_path=files_csv,
            primary_key="file_uid",
            new_rows=[record.to_db_row() for record in file_records],
            fieldnames=["file_uid", "item_uid", "file_path", "file_type", "checksum", "created_at"],
        )

        manifest = {
            "schema_version": "0.2.0",
            "generated_at": utc_now_iso(),
            "item_count": len(merged_items),
            "file_count": len(merged_files),
            "metadata_sources": [str(path) for path in metadata_paths],
            "vector_index_ready": False,
            "latest_stage": "local_reference_ingestion",
        }
        manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _merge_csv_rows(
        self,
        csv_path: Path,
        primary_key: str,
        new_rows: list[dict[str, str]],
        fieldnames: list[str],
    ) -> list[dict[str, str]]:
        """合并 CSV 记录。

        Args:
            csv_path: CSV 路径。
            primary_key: 主键字段。
            new_rows: 新记录。
            fieldnames: 字段顺序。

        Returns:
            合并后的记录列表。
        """

        merged: dict[str, dict[str, str]] = {}
        if csv_path.exists():
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    if row.get(primary_key):
                        merged[str(row[primary_key])] = {key: str(row.get(key, "")) for key in fieldnames}

        for row in new_rows:
            primary_value = row.get(primary_key, "")
            if not primary_value:
                continue
            existing = merged.get(primary_value, {key: "" for key in fieldnames})
            merged[primary_value] = {key: str(row.get(key) or existing.get(key) or "") for key in fieldnames}

        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in merged.values():
                writer.writerow(row)
        return list(merged.values())


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
