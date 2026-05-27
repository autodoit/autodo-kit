"""多模态文档 tools 回归测试。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pandas as pd

from autodokit.tools.old.ocr.aliyun_multimodal.aok_pdf_aliyun_multimodal_batch_manage import batch_manage_pdf_with_aliyun_multimodal
from autodokit.tools.old.ocr.aliyun_multimodal.aok_pdf_aliyun_multimodal_parse import parse_pdf_with_aliyun_multimodal
from autodokit.tools.old.ocr.aliyun_multimodal.aliyun_multimodal_postprocess_tools import postprocess_aliyun_multimodal_parse_outputs
from autodokit.tools.bibliodb_sqlite import load_literatures_df, load_parse_assets_df, save_tables, upsert_reading_queue_rows
from autodokit.tools.contentdb_sqlite import init_content_db, resolve_content_physical_column
from autodokit.tools.ocr.classic.pdf_parse_asset_manager import ensure_multimodal_parse_asset


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
    base_url = ""
    routing_info = {}


def test_parse_pdf_with_aliyun_multimodal_should_create_required_outputs(monkeypatch, tmp_path: Path) -> None:
    """默认应创建独立目录并写出结构树、索引、chunks 和报告。"""

    pdf_path = (tmp_path / "demo.pdf").resolve()
    pdf_path.write_bytes(b"%PDF-1.4 demo")
    api_key_file = (tmp_path / "bailian-api-key.txt").resolve()
    api_key_file.write_text("demo-key", encoding="utf-8")
    page_image = (tmp_path / "page_0001.png").resolve()
    page_image.write_bytes(b"png")

    monkeypatch.setattr(
        "autodokit.tools.old.ocr.aliyun_multimodal.aok_pdf_aliyun_multimodal_parse.render_pdf_pages_to_png",
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
        "autodokit.tools.old.ocr.aliyun_multimodal.aok_pdf_aliyun_multimodal_parse.extract_images_with_pymupdf",
        lambda *args, **kwargs: ([], type("Status", (), {"enabled": True, "disabled_reason": ""})()),
    )
    monkeypatch.setattr(
        "autodokit.tools.old.ocr.aliyun_multimodal.aok_pdf_aliyun_multimodal_parse.load_aliyun_llm_config",
        lambda **kwargs: _FakeConfig(),
    )
    monkeypatch.setattr(
        "autodokit.tools.old.ocr.aliyun_multimodal.aok_pdf_aliyun_multimodal_parse.AliyunDashScopeClient",
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
        "autodokit.tools.old.ocr.aliyun_multimodal.aok_pdf_aliyun_multimodal_batch_manage.parse_pdf_with_aliyun_multimodal",
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
        "autodokit.tools.ocr.classic.pdf_parse_asset_manager.parse_pdf_with_aliyun_multimodal",
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
        "autodokit.tools.old.ocr.aliyun_multimodal.aliyun_multimodal_postprocess_tools.load_aliyun_llm_config",
        lambda **kwargs: _FakeLLMConfig(),
    )
    monkeypatch.setattr(
        "autodokit.tools.old.ocr.aliyun_multimodal.aliyun_multimodal_postprocess_tools.AliyunDashScopeClient",
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
    rewritten_payload = json.loads(rewritten_text)
    assert result["contamination_removed_block_count"] == 1
    assert result["contamination_filter_applied"] is True
    assert "学术出版生态" not in markdown_path.read_text(encoding="utf-8")
    assert "学术出版生态" not in str((rewritten_payload.get("text") or {}).get("full_text") or "")
    raw_markdown_path = markdown_path.parent / "reconstructed_content_raw.md"
    postprocessed_markdown_path = markdown_path.parent / "reconstructed_content_postprocessed.md"
    assert raw_markdown_path.exists()
    assert postprocessed_markdown_path.exists()
    assert "学术出版生态" in raw_markdown_path.read_text(encoding="utf-8")
    assert "学术出版生态" not in postprocessed_markdown_path.read_text(encoding="utf-8")
    assert "学术出版生态" in str((rewritten_payload.get("text") or {}).get("raw_full_text") or "")
    assert '"raw_full_text"' in rewritten_text
    assert Path(result["postprocess_audit_path"]).exists()


def test_postprocess_should_prefer_review_packet_clean_body_when_available(monkeypatch, tmp_path: Path) -> None:
    """后处理应优先使用按 elements 顺序重建出的 clean_body。"""

    structured_path = (tmp_path / "normalized.structured.json").resolve()
    markdown_path = (tmp_path / "reconstructed_content.md").resolve()
    structured_path.write_text(
        json.dumps(
            {
                "schema": "aok.pdf_structured.v3",
                "source": {"title": "测试论文", "year": "2024"},
                "text": {
                    "full_text": "目录\n第一章\n第二章\n正文段落顺序混乱\n附录\n参考文献",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    markdown_path.write_text("目录\n第一章\n第二章\n正文段落顺序混乱\n附录\n参考文献\n", encoding="utf-8")

    monkeypatch.setattr(
        "autodokit.tools.review_reading_packet_tools.build_review_reading_packet",
        lambda *args, **kwargs: {"clean_body": "这是按 elements 排序后的正文。\n\n第二段正文。"},
    )

    result = postprocess_aliyun_multimodal_parse_outputs(
        normalized_structured_path=structured_path,
        reconstructed_markdown_path=markdown_path,
        rewrite_structured=True,
        rewrite_markdown=True,
        enable_llm_contamination_filter=False,
        enable_llm_basic_cleanup=False,
        enable_llm_structure_resolution=False,
    )

    rewritten_payload = json.loads(structured_path.read_text(encoding="utf-8"))
    assert result["processing_input_source"] == "review_packet_clean_body"
    assert (rewritten_payload.get("text") or {}).get("full_text", "").startswith("这是按 elements 排序后的正文")


def test_init_content_db_should_auto_migrate_legacy_schema(tmp_path: Path) -> None:
    """旧版 content.db 首次初始化时应自动补齐新列、新表和索引依赖列。"""

    content_db = (tmp_path / "legacy_content.db").resolve()
    with sqlite3.connect(content_db) as conn:
        conn.execute(
            """
            CREATE TABLE "文献主表" (
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
            'INSERT INTO "文献主表" (uid_literature, cite_key, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
            ("lit-legacy-001", "legacy_001", "Legacy Paper", "2026-04-02T00:00:00+00:00", "2026-04-02T00:00:00+00:00"),
        )
        conn.commit()

    init_content_db(content_db)

    uid_literature_column = resolve_content_physical_column("文献主表", "uid_literature")
    cite_key_column = resolve_content_physical_column("文献主表", "cite_key")
    title_column = resolve_content_physical_column("文献主表", "title")
    with sqlite3.connect(content_db) as conn:
        table_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        view_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")
        }
        migrated_row = conn.execute(
            f'SELECT "{uid_literature_column}", "{cite_key_column}", "{title_column}" FROM "文献主表" WHERE "{uid_literature_column}" = ?',
            ("lit-legacy-001",),
        ).fetchone()

    assert migrated_row == ("lit-legacy-001", "legacy_001", "Legacy Paper")
    assert "工作区节点状态" in table_names
    assert "事务关联总视图" in view_names
    assert "A050事务关联视图" in view_names
    assert "A055事务关联视图" in view_names
    assert "A160事务关联视图" in view_names


def test_init_content_db_should_convert_runtime_public_tables_to_views(tmp_path: Path) -> None:
    """旧 public runtime tables 初始化后应迁成 current-state views。"""

    content_db = (tmp_path / "legacy_runtime_tables.db").resolve()
    with sqlite3.connect(content_db) as conn:
        conn.execute(
            """
            CREATE TABLE "文献主表" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_literature TEXT UNIQUE,
                cite_key TEXT,
                title TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            'INSERT INTO "文献主表" (uid_literature, cite_key, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
            ("lit-legacy-001", "legacy_001", "Legacy Paper", "2026-04-02T00:00:00+00:00", "2026-04-02T00:00:00+00:00"),
        )
        conn.execute(
            'CREATE TABLE "文献阅读状态" ("uid_文献" TEXT, "cite_key" TEXT, "阅读待预处理" INTEGER, "阅读更新时间" TEXT)'
        )
        conn.execute(
            'INSERT INTO "文献阅读状态" VALUES (?, ?, ?, ?)',
            ("lit-legacy-001", "legacy_001", 1, "2026-04-03T00:00:00+00:00"),
        )
        conn.execute(
            'CREATE TABLE "文献预处理" ("uid_文献" TEXT, "cite_key" TEXT, "阶段" TEXT, "队列状态" TEXT, "更新时间" TEXT)'
        )
        conn.execute(
            'INSERT INTO "文献预处理" VALUES (?, ?, ?, ?, ?)',
            ("lit-legacy-001", "legacy_001", "A050_REVIEW", "queued", "2026-04-03T00:00:00+00:00"),
        )
        conn.execute(
            'CREATE TABLE "文献流程状态" ("uid_文献" TEXT, "cite_key" TEXT, "当前阶段" TEXT, "节点编码" TEXT, "更新时间" TEXT)'
        )
        conn.execute(
            'INSERT INTO "文献流程状态" VALUES (?, ?, ?, ?, ?)',
            ("lit-legacy-001", "legacy_001", "A050", "A050", "2026-04-03T00:00:00+00:00"),
        )
        conn.execute(
            'CREATE TABLE "文献解析资产" ("uid_资产" TEXT, "uid_文献" TEXT, "uid_附件" TEXT, "解析状态" TEXT, "结构化正文路径" TEXT, "更新时间" TEXT)'
        )
        conn.execute(
            'INSERT INTO "文献解析资产" VALUES (?, ?, ?, ?, ?, ?)',
            ("asset-legacy-001", "lit-legacy-001", "", "done", "C:/tmp/structured.md", "2026-04-03T00:00:00+00:00"),
        )
        conn.execute(
            """
            CREATE TABLE "文献翻译资产" (
                translation_uid TEXT PRIMARY KEY,
                uid_literature TEXT,
                cite_key TEXT,
                source_asset_uid TEXT,
                source_kind TEXT,
                target_lang TEXT,
                translation_scope TEXT,
                provider TEXT,
                model_name TEXT,
                asset_dir TEXT,
                translated_markdown_path TEXT,
                translated_structured_path TEXT,
                translation_audit_path TEXT,
                status TEXT,
                is_current INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            'INSERT INTO "文献翻译资产" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                "tr-legacy-001",
                "lit-legacy-001",
                "legacy_001",
                "asset-legacy-001",
                "parse",
                "zh",
                "full_text",
                "provider",
                "model",
                "C:/tmp/translation",
                "C:/tmp/translation.md",
                "C:/tmp/translation.json",
                "C:/tmp/translation.audit",
                "done",
                1,
                "2026-04-03T00:00:00+00:00",
                "2026-04-03T00:00:00+00:00",
            ),
        )
        conn.commit()

    init_content_db(content_db)

    with sqlite3.connect(content_db) as conn:
        object_types = dict(
            conn.execute(
                "SELECT name, type FROM sqlite_master WHERE name IN (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "文献阅读状态",
                    "文献预处理",
                    "文献流程状态",
                    "文献解析资产",
                    "文献翻译资产",
                    "content_translation_assets_storage",
                    "事务关联总视图",
                    "A050事务关联视图",
                    "A055事务关联视图",
                    "A160事务关联视图",
                ),
            ).fetchall()
        )
        translation_count = conn.execute('SELECT COUNT(*) FROM "文献翻译资产"').fetchone()[0]
        storage_count = conn.execute('SELECT COUNT(*) FROM "content_translation_assets_storage"').fetchone()[0]

    assert object_types["文献阅读状态"] == "view"
    assert object_types["文献预处理"] == "view"
    assert object_types["文献流程状态"] == "view"
    assert object_types["文献解析资产"] == "view"
    assert object_types["文献翻译资产"] == "view"
    assert object_types["content_translation_assets_storage"] == "table"
    assert object_types["事务关联总视图"] == "view"
    assert object_types["A050事务关联视图"] == "view"
    assert object_types["A055事务关联视图"] == "view"
    assert object_types["A160事务关联视图"] == "view"
    assert translation_count == 1
    assert storage_count == 1


def test_transaction_relation_view_should_support_queue_only_rows(tmp_path: Path) -> None:
    """事务关联视图应显示仅存在于预处理队列中的 A075/A080 条目。"""

    content_db = (tmp_path / "transaction_relation.db").resolve()
    init_content_db(content_db)

    uid_column = resolve_content_physical_column("文献主表", "uid_literature")
    cite_key_column = resolve_content_physical_column("文献主表", "cite_key")
    title_column = resolve_content_physical_column("文献主表", "title")
    first_author_column = resolve_content_physical_column("文献主表", "first_author")
    year_column = resolve_content_physical_column("文献主表", "year")
    created_at_column = resolve_content_physical_column("文献主表", "created_at")
    updated_at_column = resolve_content_physical_column("文献主表", "updated_at")

    with sqlite3.connect(content_db) as conn:
        conn.executemany(
            f'''
            INSERT INTO "文献主表" (
                "{uid_column}",
                "{cite_key_column}",
                "{title_column}",
                "{first_author_column}",
                "{year_column}",
                "{created_at_column}",
                "{updated_at_column}"
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            [
                ("lit-queue-001", "queue_001", "Queue Paper", "Author Queue", "2025", "2026-05-27T00:00:00+00:00", "2026-05-27T00:00:00+00:00"),
            ],
        )
        conn.commit()

    upsert_reading_queue_rows(
        content_db,
        [
            {
                "uid_literature": "lit-queue-001",
                "cite_key": "queue_001",
                "stage": "A080",
                "source_affair": "A075",
                "queue_status": "queued",
                "priority": 80,
                "recommended_reason": "human seed",
                "preferred_next_stage": "A090",
                "is_current": 1,
                "updated_at": "2026-05-27T00:00:00+00:00",
            }
        ],
    )
    init_content_db(content_db)

    with sqlite3.connect(content_db) as conn:
        rows = conn.execute(
            '''
            SELECT 事务编码, 引文键, 当前阶段, 当前状态
            FROM "事务关联总视图"
            WHERE 引文键 = 'queue_001'
            ORDER BY 引文键
            '''
        ).fetchall()
        a080_view_type = conn.execute(
            "SELECT type FROM sqlite_master WHERE name = ?",
            ("A080事务关联视图",),
        ).fetchone()

    assert rows == [("A075", "queue_001", "普通文献预处理事务", "待处理")]
    assert a080_view_type == ("view",)
