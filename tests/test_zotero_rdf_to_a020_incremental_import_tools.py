"""Zotero RDF 转 A020 增量输入包工具测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from autodokit.tools import convert_zotero_rdf_to_a020_incremental_package
from autodokit.tools.bibliodb_sqlite import init_db, save_tables
from autodokit.tools.contentdb_sqlite import init_content_db


def _write_rdf_export(path: Path) -> None:
    path.write_text(
        """
<rdf:RDF
 xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:z="http://www.zotero.org/namespaces/export#"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:foaf="http://xmlns.com/foaf/0.1/"
 xmlns:bib="http://purl.org/net/biblio#"
 xmlns:link="http://purl.org/rss/1.0/modules/link/"
 xmlns:dcterms="http://purl.org/dc/terms/">
  <bib:Article rdf:about="#item_001">
    <z:itemType>journalArticle</z:itemType>
    <bib:authors>
      <rdf:Seq>
        <rdf:li>
          <foaf:Person>
            <foaf:surname>Smith</foaf:surname>
            <foaf:givenName>John</foaf:givenName>
          </foaf:Person>
        </rdf:li>
        <rdf:li>
          <foaf:Person>
            <foaf:surname>王五</foaf:surname>
          </foaf:Person>
        </rdf:li>
      </rdf:Seq>
    </bib:authors>
    <link:link rdf:resource="#att_pdf"/>
    <link:link rdf:resource="#att_html"/>
    <link:link rdf:resource="#att_missing"/>
    <dc:title>Demo Paper for RDF Import</dc:title>
    <dcterms:abstract>Example abstract.</dcterms:abstract>
    <dc:date>2024</dc:date>
    <z:language>en</z:language>
    <z:citationKey>demo-2024-paper</z:citationKey>
    <dc:identifier>DOI 10.1234/demo.2024.001</dc:identifier>
  </bib:Article>
  <z:Attachment rdf:about="#att_pdf">
    <z:itemType>attachment</z:itemType>
    <dc:title>Primary Paper.pdf</dc:title>
    <link:type>application/pdf</link:type>
  </z:Attachment>
  <z:Attachment rdf:about="#att_html">
    <z:itemType>attachment</z:itemType>
    <dc:title>Appendix.html</dc:title>
    <link:type>text/html</link:type>
  </z:Attachment>
  <z:Attachment rdf:about="#att_missing">
    <z:itemType>attachment</z:itemType>
    <dc:title>Missing Note.txt</dc:title>
    <link:type>text/plain</link:type>
  </z:Attachment>
</rdf:RDF>
        """.strip(),
        encoding="utf-8",
    )


def test_convert_zotero_rdf_to_a020_incremental_package_should_generate_a020_inputs(tmp_path: Path) -> None:
    """RDF 预处理工具应输出 A020 可消费的主表、附件表与清单。"""

    workspace_root = tmp_path / "workspace"
    content_db = workspace_root / "database" / "content" / "content.db"
    init_content_db(content_db)
    init_db(content_db)

    save_tables(
        content_db,
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-existing-001",
                    "cite_key": "demo-2024-paper",
                    "title": "Demo Paper for RDF Import",
                    "first_author": "Smith",
                    "year": "2024",
                    "created_at": "2026-04-21T00:00:00+00:00",
                    "updated_at": "2026-04-21T00:00:00+00:00",
                }
            ]
        ),
        if_exists="replace",
    )

    rdf_path = tmp_path / "export.rdf"
    _write_rdf_export(rdf_path)

    attachments_root = tmp_path / "zotero-storage"
    (attachments_root / "AAA").mkdir(parents=True, exist_ok=True)
    (attachments_root / "BBB").mkdir(parents=True, exist_ok=True)
    pdf_path = attachments_root / "AAA" / "Primary Paper.pdf"
    html_path = attachments_root / "BBB" / "Appendix.html"
    pdf_path.write_bytes(b"%PDF-1.4")
    html_path.write_text("<html>appendix</html>", encoding="utf-8")

    output_dir = tmp_path / "output"
    result = convert_zotero_rdf_to_a020_incremental_package(
        {
            "rdf_path": str(rdf_path),
            "workspace_root": str(workspace_root),
            "content_db_path": str(content_db),
            "attachments_root": str(attachments_root),
            "output_dir": str(output_dir),
            "dry_run": True,
        }
    )

    items_csv = output_dir / "literature_items.csv"
    files_csv = output_dir / "literature_files.csv"
    manifest_path = output_dir / "literature-manifest.json"
    summary_path = output_dir / "run_summary.md"
    log_path = output_dir / "run_log.txt"
    unmatched_path = output_dir / "unmatched_items.json"

    assert result["status"] == "WARN"
    assert items_csv.exists()
    assert files_csv.exists()
    assert manifest_path.exists()
    assert summary_path.exists()
    assert log_path.exists()
    assert unmatched_path.exists()

    items_df = pd.read_csv(items_csv, encoding="utf-8-sig")
    files_df = pd.read_csv(files_csv, encoding="utf-8-sig")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    unmatched = json.loads(unmatched_path.read_text(encoding="utf-8"))

    assert len(items_df) == 1
    assert len(files_df) == 2
    assert items_df.iloc[0]["uid_literature"] == "lit-existing-001"
    assert items_df.iloc[0]["has_fulltext"] == 1
    assert items_df.iloc[0]["primary_attachment_name"] == "Primary Paper.pdf"
    assert set(files_df["attachment_name"].tolist()) == {"Primary Paper.pdf", "Appendix.html"}
    assert files_df.loc[files_df["attachment_name"] == "Primary Paper.pdf", "is_primary"].iloc[0] == 1
    assert manifest["counts"]["items_matched_existing"] == 1
    assert manifest["counts"]["attachments_total"] == 2
    assert manifest["counts"]["unmatched_items"] == 1
    assert unmatched["count"] == 1
    assert "Missing Note.txt" in json.dumps(unmatched, ensure_ascii=False)
