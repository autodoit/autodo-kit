"""CNKI 导出产物与第三方接口工具。"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autodokit.tools.time_utils import now_iso


def utc_now_iso() -> str:
    """返回 ISO 时间字符串（默认北京时间）。

    Returns:
        当前 ISO 时间字符串。
    """

    return now_iso()


def slugify_filename(value: str) -> str:
    """将文本转换为适合文件名的 slug。

    Args:
        value: 原始文本。

    Returns:
        规范化文件名。
    """

    collapsed = re.sub(r"\s+", "_", value.strip())
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", collapsed)
    return normalized.strip("._-") or "cnki_item"


def parse_cnkielearning(text: str) -> dict[str, Any]:
    """解析 CNKI ELEARNING 导出文本。

    Args:
        text: ELEARNING 文本。

    Returns:
        结构化字段字典。
    """

    normalized = text.replace("<br>", "\n").replace("\r", "")
    normalized = re.sub(r"<[^>]+>", "", normalized)

    def _get(key: str) -> str:
        """获取指定键的值。

        Args:
            key: CNKI 导出键名。

        Returns:
            对应字段值。
        """

        match = re.search(rf"{re.escape(key)}:\s*(.+?)(?=\n|$)", normalized)
        return match.group(1).strip() if match else ""

    return {
        "title": _get("Title-题名"),
        "authors": [item.strip() for item in _get("Author-作者").split(";") if item.strip()],
        "journal": _get("Source-刊名"),
        "year": _get("Year-年"),
        "pub_time": _get("PubTime-出版时间"),
        "keywords": [item.strip() for item in _get("Keyword-关键词").split(";") if item.strip()],
        "abstract": _get("Summary-摘要"),
        "volume": _get("Roll-卷"),
        "issue": _get("Period-期"),
        "pages": _get("Page-页码"),
        "organizations": _get("Organ-机构"),
        "link": _get("Link-链接"),
        "src_db": _get("SrcDatabase-来源库"),
    }


def build_ris_text(record: dict[str, Any]) -> str:
    """将结构化记录转换为 RIS 文本。

    Args:
        record: 结构化记录。

    Returns:
        RIS 文本。
    """

    lines = ["TY  - JOUR"]
    for author in record.get("authors", []):
        lines.append(f"AU  - {author}")
    title = str(record.get("title") or "")
    if title:
        lines.append(f"TI  - {title}")
    journal = str(record.get("journal") or "")
    if journal:
        lines.append(f"JO  - {journal}")
        lines.append(f"T2  - {journal}")
    year = str(record.get("year") or "")
    pub_time = str(record.get("pub_time") or year)
    if pub_time:
        lines.append(f"PY  - {pub_time}")
        lines.append(f"Y1  - {pub_time}")
    volume = str(record.get("volume") or "")
    if volume:
        lines.append(f"VL  - {volume}")
    issue = str(record.get("issue") or "")
    if issue:
        lines.append(f"IS  - {issue}")
    pages = str(record.get("pages") or "")
    if pages:
        lines.append(f"SP  - {pages}")
    abstract = str(record.get("abstract") or "")
    if abstract:
        lines.append(f"AB  - {abstract}")
    for keyword in record.get("keywords", []):
        lines.append(f"KW  - {keyword}")
    link = str(record.get("link") or record.get("detail_url") or "")
    if link:
        lines.append(f"UR  - {link}")
    doi = str(record.get("doi") or "")
    if doi:
        lines.append(f"DO  - {doi}")
    lines.append("ER  - ")
    return "\n".join(lines) + "\n"


def build_gbt_reference(record: dict[str, Any]) -> str:
    """构造简化 GB/T 7714 引用文本。

    Args:
        record: 结构化记录。

    Returns:
        GB/T 7714 风格引用文本。
    """

    authors = "，".join(record.get("authors", [])) or "佚名"
    title = str(record.get("title") or "未命名文献")
    journal = str(record.get("journal") or "")
    year = str(record.get("year") or record.get("pub_time") or "")
    issue = str(record.get("issue") or "")
    pages = str(record.get("pages") or "")
    segments = [f"{authors}. {title}[J]"]
    if journal:
        segments.append(journal)
    if year:
        segments.append(year)
    tail = ""
    if issue:
        tail += f"({issue})"
    if pages:
        tail += f":{pages}"
    if tail:
        segments.append(tail)
    return "，".join(part for part in segments if part).strip("，") + "."


def build_cnki_citation_key(record: dict[str, Any]) -> str:
    """生成 CNKI 文献引用键。

    Args:
        record: 结构化记录。

    Returns:
        引用键。
    """

    author_token = slugify_filename((record.get("authors") or ["cnki"])[0])
    year_token = slugify_filename(str(record.get("year") or "nd"))
    title_token = slugify_filename(str(record.get("title") or "paper"))[:32]
    return f"{author_token}_{year_token}_{title_token}".strip("_")


def sha256_of_bytes(payload: bytes) -> str:
    """计算字节内容的 SHA256。

    Args:
        payload: 文件字节内容。

    Returns:
        SHA256 十六进制串。
    """

    return hashlib.sha256(payload).hexdigest()


def ensure_json_file(path: Path, default_payload: dict[str, Any]) -> None:
    """确保 JSON 文件存在。

    Args:
        path: 目标路径。
        default_payload: 默认内容。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(default_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_manifest_item(project_root: str | Path, item: dict[str, Any]) -> Path:
    """将条目追加到文献 manifest。

    Args:
        project_root: 项目根目录。
        item: manifest 条目。

    Returns:
        manifest 文件路径。
    """

    root = Path(project_root)
    manifest_path = root / "references" / "normal" / "manifest" / "literature-manifest.json"
    ensure_json_file(
        manifest_path,
        {"schema_version": "1.0", "updated_at": utc_now_iso(), "items": []},
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = list(manifest.get("items", []))
    citation_key = item.get("citation_key")
    items = [existing for existing in items if existing.get("citation_key") != citation_key]
    items.append(item)
    manifest["items"] = items
    manifest["updated_at"] = utc_now_iso()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def append_missing_fulltext_record(
    project_root: str | Path,
    record: dict[str, Any],
    reason: str,
) -> Path:
    """记录未获取全文的条目。

    Args:
        project_root: 项目根目录。
        record: 文献信息。
        reason: 原因说明。

    Returns:
        记录文件路径。
    """

    root = Path(project_root)
    output_path = root / "review" / "plan" / "no-fulltext-catalog.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    line = f"- {record.get('title', '未命名文献')} | {record.get('journal', '')} | {reason}\n"
    if output_path.exists():
        with output_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    else:
        output_path.write_text("# no-fulltext-catalog\n\n" + line, encoding="utf-8")
    return output_path


@dataclass(slots=True, frozen=True)
class CnkiExportArtifacts:
    """CNKI 导出产物路径集合。

    Args:
        json_path: 结构化 JSON 路径。
        ris_path: RIS 路径。
        gbt_path: GB/T 引用路径。
        manifest_path: 文献 manifest 路径。
        restricted_fulltext_path: 受限全文路径。
    """

    json_path: str
    ris_path: str
    gbt_path: str
    manifest_path: str
    restricted_fulltext_path: str

    def to_dict(self) -> dict[str, str]:
        """转换为字典。

        Returns:
            路径字典。
        """

        return {
            "json_path": self.json_path,
            "ris_path": self.ris_path,
            "gbt_path": self.gbt_path,
            "manifest_path": self.manifest_path,
            "restricted_fulltext_path": self.restricted_fulltext_path,
        }


def write_cnki_export_artifacts(
    project_root: str | Path,
    export_record: dict[str, Any],
    raw_export_payload: dict[str, Any],
    fulltext_bytes: bytes | None = None,
    fulltext_suffix: str = ".pdf",
) -> CnkiExportArtifacts:
    """写出 CNKI 导出产物与 manifest。

    Args:
        project_root: 项目根目录。
        export_record: 结构化导出记录。
        raw_export_payload: 原始导出负载。
        fulltext_bytes: 全文字节内容。
        fulltext_suffix: 全文后缀。

    Returns:
        产物路径集合。
    """

    root = Path(project_root)
    citation_key = build_cnki_citation_key(export_record)
    base_name = slugify_filename(citation_key)

    meta_dir = root / "references" / "origin" / "ai_web_subscription_meta" / "cnki"
    ris_dir = root / "references" / "normal" / "bib" / "cnki"
    notes_dir = root / "references" / "normal" / "notes" / "cnki"
    restricted_dir = root / "references" / "origin" / "ai_web_subscription_files" / "cnki"
    for directory in (meta_dir, ris_dir, notes_dir, restricted_dir):
        directory.mkdir(parents=True, exist_ok=True)

    json_path = meta_dir / f"{base_name}.json"
    ris_path = ris_dir / f"{base_name}.ris"
    gbt_path = notes_dir / f"{base_name}.gbt.txt"
    json_path.write_text(json.dumps(raw_export_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    ris_path.write_text(build_ris_text(export_record), encoding="utf-8")
    gbt_path.write_text(build_gbt_reference(export_record), encoding="utf-8")

    restricted_fulltext_path = ""
    sha256 = ""
    access_type = "metadata-only"
    status = "metadata-exported"
    if fulltext_bytes is not None:
        fulltext_path = restricted_dir / f"{base_name}{fulltext_suffix}"
        fulltext_path.write_bytes(fulltext_bytes)
        restricted_fulltext_path = str(fulltext_path)
        sha256 = sha256_of_bytes(fulltext_bytes)
        access_type = "fulltext-restricted"
        status = "fulltext-saved"

    manifest_item = {
        "citation_key": citation_key,
        "title": export_record.get("title", ""),
        "authors": export_record.get("authors", []),
        "year": int(str(export_record.get("year") or "0") or 0),
        "source_platform": "CNKI",
        "source_url": export_record.get("detail_url") or export_record.get("link") or "",
        "access_type": access_type,
        "license_or_terms": "institutional-subscription",
        "file_path": restricted_fulltext_path,
        "sha256": sha256,
        "retrieved_at": utc_now_iso(),
        "retrieved_by": "cn-literature-retriever",
        "permission_proof": "campus-auth-human-gate",
        "status": status,
        "notes": "由 CNKI 导出链写入。",
    }
    manifest_path = append_manifest_item(project_root=root, item=manifest_item)
    if not restricted_fulltext_path:
        append_missing_fulltext_record(project_root=root, record=export_record, reason="未提供受限全文文件，仅保存题录与导出产物")

    return CnkiExportArtifacts(
        json_path=str(json_path),
        ris_path=str(ris_path),
        gbt_path=str(gbt_path),
        manifest_path=str(manifest_path),
        restricted_fulltext_path=restricted_fulltext_path,
    )


def build_zotero_item(record: dict[str, Any]) -> dict[str, Any]:
    """构造 Zotero Connector 兼容 item。

    Args:
        record: 结构化记录。

    Returns:
        Zotero item JSON。
    """

    return {
        "itemType": "journalArticle",
        "title": record.get("title", ""),
        "abstractNote": record.get("abstract", ""),
        "date": record.get("pub_time") or record.get("year", ""),
        "language": "zh-CN",
        "libraryCatalog": "CNKI",
        "publicationTitle": record.get("journal", ""),
        "volume": record.get("volume", ""),
        "issue": record.get("issue", ""),
        "pages": record.get("pages", ""),
        "creators": [{"name": author, "creatorType": "author"} for author in record.get("authors", [])],
        "tags": [{"tag": keyword, "type": 1} for keyword in record.get("keywords", [])],
        "url": record.get("link") or record.get("detail_url") or "",
        "attachments": [],
    }


def push_items_to_zotero(items: list[dict[str, Any]], timeout: int = 15) -> tuple[int, str]:
    """推送条目到 Zotero Connector。

    Args:
        items: Zotero 条目列表。
        timeout: 请求超时时间。

    Returns:
        状态码与说明信息。
    """

    endpoint = "http://127.0.0.1:23119/connector/saveItems"
    body = json.dumps({"items": items}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Zotero-Connector-API-Version": "3",
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
        return response.status, "Zotero 保存成功"
    except urllib.error.HTTPError as error:
        payload = error.read().decode("utf-8", errors="replace")
        return error.code, payload or "Zotero 返回 HTTP 错误"
    except urllib.error.URLError:
        return 0, "Zotero 未运行或 Connector 不可达"
