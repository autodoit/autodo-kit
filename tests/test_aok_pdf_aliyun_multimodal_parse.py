"""多模态文档 tools 回归测试。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pandas as pd

from autodokit.tools.aok_pdf_aliyun_multimodal_batch_manage import batch_manage_pdf_with_aliyun_multimodal
from autodokit.tools.aok_pdf_aliyun_multimodal_parse import parse_pdf_with_aliyun_multimodal
from autodokit.tools.aliyun_multimodal_postprocess_tools import postprocess_aliyun_multimodal_parse_outputs
from autodokit.tools.bibliodb_sqlite import load_literatures_df, load_parse_assets_df, save_tables
from autodokit.tools.contentdb_sqlite import init_content_db
from autodokit.tools.pdf_parse_asset_manager import ensure_multimodal_parse_asset


class _FakeClient:
    def __init__(self, config) -> None:
        self._config = config

    def generate_multimodal_text(self, **kwargs) -> str:
        return json.dumps(
            {
                "page_index": 0,
                "page_summary": "demo_page",
                "elements": [
                    {
                        "node_type": "document_title",
                        "text": "Demo Document",
                        "confidence": 0.99,
                        "bbox": None,
                        "heading_level": 0,
                        "reading_order": 1,
                    },
                    {
                        "node_type": "heading",
                        "text": "Overview",
                        "confidence": 0.95,
                        "bbox": None,
                        "heading_level": 1,
                        "reading_order": 2,
                    },
                    {
                        "node_type": "paragraph",
                        "text": "First paragraph.",
                        "confidence": 0.9,
                        "bbox": None,
                        "heading_level": 0,
                        "reading_order": 3,
                    },
                ],
            },
            ensure_ascii=False,
        )


class _FakeConfig:
    model = "qwen3-vl-plus"
    sdk_backend = "openai-compatible"
    region = "cn-beijing"


def test_parse_pdf_with_aliyun_multimodal_should_create_required_outputs(monkeypatch, tmp_path: Path) -> None:
    """默认应创建独立目录并写出结构树、索引、chunks 和报告。"""

    pdf_path = (tmp_path / "demo.pdf").resolve()
    pdf_path.write_bytes(b"%PDF-1.4 demo")
    api_key_file = (tmp_path / "bailian-api-key.txt").resolve()
    api_key_file.write_text("demo-key", encoding="utf-8")
    page_image = (tmp_path / "page_0001.png").resolve()
    page_image.write_bytes(b"png")

    monkeypatch.setattr(
        "autodokit.tools.aok_pdf_aliyun_multimodal_parse.render_pdf_pages_to_png",
        lambda *args, **kwargs: [
            {
                "page_index": 0,
                "page_number": 1,
                "image_path": str(page_image),
                "width": 100,
                "height": 100,
                "text": "Demo Paper\n\nIntroduction\n\nFirst paragraph.",
                "source": "test",
            }
        ],
    )
    monkeypatch.setattr(
        "autodokit.tools.aok_pdf_aliyun_multimodal_parse.extract_images_with_pymupdf",
        lambda *args, **kwargs: ([], type("Status", (), {"enabled": True, "disabled_reason": ""})()),
    )
    monkeypatch.setattr(
        "autodokit.tools.aok_pdf_aliyun_multimodal_parse.load_aliyun_llm_config",
        lambda **kwargs: _FakeConfig(),
    )
    monkeypatch.setattr(
        "autodokit.tools.aok_pdf_aliyun_multimodal_parse.AliyunDashScopeClient",
        _FakeClient,
    )

    result = parse_pdf_with_aliyun_multimodal(
        pdf_path=pdf_path,
        output_root=tmp_path / "outputs",
        api_key_file=api_key_file,
        source_metadata={"title": "Demo Document", "year": "2026"},
    )

    output_dir = Path(result["output_dir"])
    assert output_dir.exists()
    assert (output_dir / "structured_tree.json").exists()
    assert (output_dir / "linear_index.json").exists()
    assert (output_dir / "chunk_manifest.json").exists()
    assert (output_dir / "chunks.jsonl").exists()
    assert (output_dir / "parse_record.json").exists()
    assert (output_dir / "quality_report.json").exists()
    assert result["chunk_count"] >= 1


def test_batch_manage_pdf_with_aliyun_multimodal_should_use_named_output_field(monkeypatch, tmp_path: Path) -> None:
    """批量管理应按指定字段读取输出目录名，并生成汇总与报告。"""

    api_key_file = (tmp_path / "bailian-api-key.txt").resolve()
    api_key_file.write_text("demo-key", encoding="utf-8")
    calls: list[str | None] = []

    def _fake_parse(**kwargs):
        calls.append(kwargs.get("output_name"))
        output_dir = (Path(kwargs["output_root"]).resolve() / str(kwargs.get("output_name") or "auto_generated")).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "result.json").write_text("{}", encoding="utf-8")
        return {
            "output_name": str(kwargs.get("output_name") or "auto_generated"),
            "output_dir": str(output_dir),
            "page_count": 1,
            "element_count": 3,
            "chunk_count": 1,
        }

    monkeypatch.setattr(
        "autodokit.tools.aok_pdf_aliyun_multimodal_batch_manage.parse_pdf_with_aliyun_multimodal",
        _fake_parse,
    )

    summary = batch_manage_pdf_with_aliyun_multimodal(
        output_root=tmp_path / "batch_outputs",
        api_key_file=api_key_file,
        jobs=[
            {"pdf_path": tmp_path / "doc1.pdf", "dir_name": "doc_a", "document_id": "doc1"},
            {"pdf_path": tmp_path / "doc2.pdf", "document_id": "doc2"},
        ],
        output_name_key="dir_name",
        generate_report=True,
    )

    assert calls == ["doc_a", None]
    assert Path(summary["run_summary_path"]).exists()
    assert Path(summary["report_path"]).exists()
    assert summary["success_count"] == 2


def test_ensure_multimodal_parse_asset_should_register_normalized_structured(monkeypatch, tmp_path: Path) -> None:
    """解析资产管理器应注册多模态资产，并回写兼容 structured 入口。"""

    workspace_root = (tmp_path / "workspace").resolve()
    content_db = (workspace_root / "database" / "content" / "content.db").resolve()
    pdf_path = (workspace_root / "references" / "document.pdf").resolve()
    api_key_file = (tmp_path / "bailian-api-key.txt").resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4 demo")
    api_key_file.write_text("demo-key", encoding="utf-8")

    init_content_db(content_db)
    save_tables(
        content_db,
        literatures_df=pd.DataFrame(
            [
                {
                    "uid_literature": "lit-001",
                    "cite_key": "paper_2026",
                    "title": "Demo Document",
                    "year": "2026",
                    "pdf_path": str(pdf_path),
                }
            ]
        ),
        if_exists="replace",
    )

    def _fake_parse(**kwargs):
        output_dir = (Path(kwargs["output_root"]).resolve() / str(kwargs.get("output_name") or "paper_2026")).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "structured_tree.json").write_text("{}", encoding="utf-8")
        (output_dir / "elements.json").write_text("{}", encoding="utf-8")
        (output_dir / "attachments_manifest.json").write_text("{}", encoding="utf-8")
        (output_dir / "linear_index.json").write_text("{}", encoding="utf-8")
        (output_dir / "chunk_manifest.json").write_text("{}", encoding="utf-8")
        (output_dir / "chunks.jsonl").write_text("", encoding="utf-8")
        (output_dir / "reconstructed_content.md").write_text("# Demo Document\n\nReferences\nAlpha (2020).", encoding="utf-8")
        (output_dir / "parse_record.json").write_text(
            json.dumps(
                {
                    "schema": "aok.pdf_aliyun_multimodal_parse_record.v1",
                    "llm_model": "qwen3-vl-plus",
                    "llm_backend": "openai-compatible",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (output_dir / "quality_report.json").write_text("{}", encoding="utf-8")
        return {
            "output_name": str(kwargs.get("output_name") or "paper_2026"),
            "output_dir": str(output_dir),
            "structured_tree_path": str(output_dir / "structured_tree.json"),
            "elements_path": str(output_dir / "elements.json"),
            "attachments_manifest_path": str(output_dir / "attachments_manifest.json"),
            "linear_index_path": str(output_dir / "linear_index.json"),
            "chunk_manifest_path": str(output_dir / "chunk_manifest.json"),
            "chunks_jsonl_path": str(output_dir / "chunks.jsonl"),
            "reconstructed_markdown_path": str(output_dir / "reconstructed_content.md"),
            "parse_record_path": str(output_dir / "parse_record.json"),
            "quality_report_path": str(output_dir / "quality_report.json"),
            "llm_model": "qwen3-vl-plus",
            "llm_backend": "openai-compatible",
        }

    monkeypatch.setattr(
        "autodokit.tools.pdf_parse_asset_manager.parse_pdf_with_aliyun_multimodal",
        _fake_parse,
    )

    result = ensure_multimodal_parse_asset(
        content_db=content_db,
        parse_level="non_review_rough",
        uid_literature="lit-001",
        source_stage="A08",
        api_key_file=api_key_file,
    )

    normalized_path = Path(str(result.get("normalized_structured_path") or ""))
    assert normalized_path.exists()
    parse_assets = load_parse_assets_df(content_db, parse_level="non_review_rough", only_current=True)
    assert not parse_assets.empty
    literatures = load_literatures_df(content_db)
    assert literatures.iloc[0]["structured_abs_path"] == str(normalized_path)
    assert literatures.iloc[0]["latest_parse_level"] == "non_review_rough"


def test_postprocess_aliyun_multimodal_parse_outputs_should_remove_cross_article_contamination(monkeypatch, tmp_path: Path) -> None:
    """后处理应在模型判定后剥离混排进来的外来文章段落。"""

    structured_path = (tmp_path / "normalized.structured.json").resolve()
    markdown_path = (tmp_path / "reconstructed_content.md").resolve()
    structured_path.write_text(
        json.dumps(
            {
                "schema": "aok.pdf_structured.v3",
                "source": {
                        "title": "张三-2008-科学学-科研评价与学术产出关系的协整检验与误差修正模型",
                    "year": "2008",
                },
                "text": {
                    "full_text": """
科研评价指标与学术产出之间存在复杂的动态关系。

在样本期间内，学科间合作与资助分配模式对产出影响显著，但部分段落混入了与目标论文主题无关的文本，涉及学术出版生态的讨论。

结论部分表明，评价制度调整对短期产出有显著效应，但长期关系需要进一步验证。
""".strip(),
                    "meta": {"title": "张三-2008-科学学-科研评价与学术产出关系的协整检验与误差修正模型"},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    markdown_path.write_text(
        "科研评价指标与学术产出之间存在复杂的动态关系。\n\n在样本期间内，学科间合作与资助分配模式对产出影响显著，但部分段落混入了与目标论文主题无关的文本，涉及学术出版生态的讨论。\n\n结论部分表明，评价制度调整对短期产出有显著效应，但长期关系需要进一步验证。\n",
        encoding="utf-8",
    )

    class _FakeLLMConfig:
        model = "qwen-plus"
        sdk_backend = "dashscope"
        region = "cn-beijing"

    class _FakeLLMClient:
        def __init__(self, config) -> None:
            self._config = config

        def generate_text(self, **kwargs) -> str:
            payload = json.loads(kwargs["prompt"])
            remove_ids = [block["block_id"] for block in payload["blocks"] if "学术出版生态" in block["text"]]
            return json.dumps(
                {
                    "remove_block_ids": remove_ids,
                    "keep_block_ids": [block["block_id"] for block in payload["blocks"] if block["block_id"] not in remove_ids],
                    "uncertain_block_ids": [],
                    "block_judgements": [
                        {
                            "block_id": block["block_id"],
                            "decision": "remove" if block["block_id"] in remove_ids else "keep",
                            "reason": "主题与目标论文无关" if block["block_id"] in remove_ids else "属于目标论文正文",
                        }
                        for block in payload["blocks"]
                    ],
                },
                ensure_ascii=False,
            )

    monkeypatch.setattr(
        "autodokit.tools.aliyun_multimodal_postprocess_tools.load_aliyun_llm_config",
        lambda **kwargs: _FakeLLMConfig(),
    )
    monkeypatch.setattr(
        "autodokit.tools.aliyun_multimodal_postprocess_tools.AliyunDashScopeClient",
        _FakeLLMClient,
    )

    result = postprocess_aliyun_multimodal_parse_outputs(
        normalized_structured_path=structured_path,
        reconstructed_markdown_path=markdown_path,
        rewrite_structured=True,
        rewrite_markdown=True,
        enable_llm_contamination_filter=True,
        contamination_llm_model="auto",
        config_path=tmp_path / "config.json",
    )

    rewritten_text = structured_path.read_text(encoding="utf-8")
    assert result["contamination_removed_block_count"] == 1
    assert result["contamination_filter_applied"] is True
    assert "学术出版生态" not in markdown_path.read_text(encoding="utf-8")
    assert "学术出版生态" not in rewritten_text
    assert Path(result["postprocess_audit_path"]).exists()


def test_init_content_db_should_auto_migrate_legacy_schema(tmp_path: Path) -> None:
    """旧版 content.db 首次初始化时应自动补齐新列、新表和索引依赖列。"""

    content_db = (tmp_path / "legacy_content.db").resolve()
    with sqlite3.connect(content_db) as conn:
        conn.execute(
            """
            CREATE TABLE literatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_literature TEXT UNIQUE,
                cite_key TEXT,
                title TEXT,
                first_author TEXT,
                year TEXT,
                entry_type TEXT,
                abstract TEXT,
                keywords TEXT,
                pdf_path TEXT,
                is_placeholder INTEGER,
                has_fulltext INTEGER,
                primary_attachment_name TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO literatures (uid_literature, cite_key, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("lit-legacy-001", "legacy_001", "Legacy Paper", "2026-04-02T00:00:00+00:00", "2026-04-02T00:00:00+00:00"),
        )
        conn.commit()

    init_content_db(content_db)

    with sqlite3.connect(content_db) as conn:
        literature_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(literatures)")
        }
        table_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        index_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        migrated_row = conn.execute(
            "SELECT uid_literature, cite_key, title FROM literatures WHERE uid_literature = ?",
            ("lit-legacy-001",),
        ).fetchone()

    assert migrated_row == ("lit-legacy-001", "legacy_001", "Legacy Paper")
    assert "a07_queue_status" in literature_columns
    assert "a08_queue_status" in literature_columns
    assert "latest_parse_level" in literature_columns
    assert "latest_parse_asset_dir" in literature_columns
    assert "structured_abs_path" in literature_columns
    assert "literature_reading_queue" in table_names
    assert "literature_parse_assets" in table_names
    assert "idx_lit_a07_status" in index_names
    assert "idx_lit_a08_status" in index_names
    assert "idx_parse_asset_lit_level" in index_names