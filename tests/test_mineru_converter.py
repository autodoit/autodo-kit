"""MinerU 转换器与运行器测试。"""

from __future__ import annotations

import json
from pathlib import Path


def test_resolve_mineru_cli_raises_when_missing(monkeypatch) -> None:
    """未安装 MinerU 时应抛出带安装提示的 RuntimeError。"""

    from autodokit.tools.ocr.mineru.mineru_runner import resolve_mineru_cli

    monkeypatch.delenv("MINERU_CLI_PATH", raising=False)
    monkeypatch.delenv("AUTODOKIT_MINERU_CLI", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    try:
        resolve_mineru_cli()
    except RuntimeError as exc:
        assert "mineru" in str(exc).lower()
        assert "uv pip install" in str(exc)
    else:
        raise AssertionError("resolve_mineru_cli 应抛出 RuntimeError")


def test_normalize_backend_rejects_unknown() -> None:
    """非法后端应抛出 ValueError。"""

    from autodokit.tools.ocr.mineru.mineru_runner import _normalize_backend

    try:
        _normalize_backend("unknown-backend")
    except ValueError as exc:
        assert "不支持" in str(exc)
    else:
        raise AssertionError("_normalize_backend 应抛出 ValueError")


def test_build_mineru_command_defaults(tmp_path: Path) -> None:
    """默认命令应包含 hybrid-engine 与 medium effort。"""

    from autodokit.tools.ocr.mineru.mineru_runner import _build_mineru_command

    pdf = tmp_path / "demo.pdf"
    out = tmp_path / "out"
    command = _build_mineru_command(
        cli_path="/usr/local/bin/mineru",
        pdf_path=pdf,
        output_dir=out,
        backend="hybrid-engine",
        effort="medium",
        method="auto",
        lang="ch",
        formula=True,
        table=True,
        image_analysis=True,
        start_page=None,
        end_page=None,
        client_side_output=True,
    )
    text = " ".join(command)
    assert "-b" in command
    assert "hybrid-engine" in command
    assert "--effort" in command
    assert "medium" in command
    assert "--image-analysis" in command
    assert "--client-side-output-generation" in command
    assert str(pdf) in text
    assert str(out) in text


def test_discover_mineru_output_files(tmp_path: Path) -> None:
    """输出文件发现应返回按名称排序的文件清单。"""

    from autodokit.tools.ocr.mineru.mineru_runner import discover_mineru_output_files

    out_dir = tmp_path / "mineru_out"
    out_dir.mkdir(parents=True)
    (out_dir / "demo_content_list.json").write_text("[]", encoding="utf-8")
    (out_dir / "demo.md").write_text("# demo", encoding="utf-8")

    files = discover_mineru_output_files(out_dir)
    names = [item["name"] for item in files]
    assert "demo_content_list.json" in names
    assert "demo.md" in names
    assert names == sorted(names)


def test_content_list_v2_flatten_and_structured(tmp_path: Path) -> None:
    """content_list_v2（按页分组）应被拍平并正确映射到 structured payload。"""

    import autodokit.tools.ocr.mineru.pdf_to_structure_data_converter_use_mineru as module

    content_list_v2 = [
        [
            {
                "type": "title",
                "content": {"title_content": [{"type": "text", "content": "Introduction"}], "level": 1},
                "bbox": [83, 121, 917, 156],
            },
            {
                "type": "paragraph",
                "content": {"paragraph_content": [{"type": "text", "content": "This is a test paragraph."}]},
                "bbox": [83, 180, 917, 220],
            },
        ],
        [
            {
                "type": "equation_interline",
                "content": {"math_content": "E = mc^2", "math_type": "latex"},
                "bbox": [83, 300, 500, 330],
            },
            {
                "type": "table",
                "content": {"table_content": "<table><tr><td>a</td><td>b</td></tr></table>", "table_caption": ["Table 1"]},
                "bbox": [83, 400, 900, 500],
            },
        ],
    ]
    (tmp_path / "demo_content_list_v2.json").write_text(
        json.dumps(content_list_v2), encoding="utf-8"
    )

    items, source_name, path = module._load_mineru_content_list(tmp_path)
    assert len(items) == 4
    assert source_name and "v2" in source_name
    assert path is not None

    # 用伪 PDF 验证 build 链路（不实际运行 CLI）
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%demo\n")

    from autodokit.tools.ocr.classic.pdf_structured_data_tools import build_structured_data_payload

    full_text = "\n\n".join(
        module._extract_text_from_content_list_item(item) for item in items if module._extract_text_from_content_list_item(item)
    )
    tables = [module._extract_table_body(item) for item in items if _stringify_lower(item) == "table"]
    formulas = [module._extract_formula_text(item) for item in items if _stringify_lower(item) == "equation_interline"]
    layout = module._extract_layout_pages(items)

    payload = build_structured_data_payload(
        pdf_path=pdf,
        backend="mineru",
        backend_family="mineru",
        task_type="full_fine_grained",
        full_text=full_text,
        extract_error=None,
        text_meta={"content_source": source_name},
        uid_literature="lit-1",
        cite_key="demo2026",
        title="Demo",
        year="2026",
        tables=[{"table_html": body} for body in tables if body],
        formulas=[{"latex": text} for text in formulas if text],
        layout=layout,
    )

    assert payload["schema"] == "aok.pdf_structured.v3"
    assert payload["source"]["backend"] == "mineru"
    assert "Introduction" in payload["text"]["full_text"]
    assert "E = mc^2" in payload["text"]["full_text"]
    assert payload["formulas"] and "E = mc^2" in payload["formulas"][0]["latex"]


def _stringify_lower(item: dict) -> str:
    return str(item.get("type") or "").strip().lower()
