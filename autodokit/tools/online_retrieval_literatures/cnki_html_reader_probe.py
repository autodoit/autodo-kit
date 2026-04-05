"""CNKI 在线阅读 HTML 探测与结构化抽取脚本。"""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import importlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from playwright.sync_api import BrowserContext, Page, Playwright


def _discover_repo_root(start_path: Path) -> Path:
    for candidate in [start_path, *start_path.parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "autodokit").is_dir():
            return candidate
    raise RuntimeError("未找到 autodo-kit 仓库根目录。")


REPO_ROOT = _discover_repo_root(Path(__file__).resolve().parent)


def _load_cnki_debug_module() -> Any:
    return importlib.import_module(__package__ + ".cnki_paged_retrieval")


CNKI_DEBUG = _load_cnki_debug_module()


def _resolve_repo_path(raw_path: str | Path | None, default_relative: str) -> Path:
    raw_text = str(raw_path or "").strip()
    if not raw_text:
        return (REPO_ROOT / default_relative).resolve()
    candidate = Path(raw_text).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (REPO_ROOT / candidate).resolve()


def _load_debug_inputs() -> dict[str, Any]:
    path = (REPO_ROOT / "sandbox" / "online_retrieval_debug" / "debug_inputs.json").resolve()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _slugify(value: str) -> str:
    return CNKI_DEBUG.slugify_filename(value)[:80]


def _build_probe_config(args: argparse.Namespace) -> dict[str, Any]:
    defaults = _load_debug_inputs()
    browser_config = dict(defaults.get("cnki_browser_config") or {})
    return {
        "query": str(args.query or defaults.get("zh_query") or "系统性风险"),
        "detail_url": str(args.detail_url or "").strip(),
        "result_index": int(args.result_index or 0),
        "prefer_database_tokens": [
            token.strip() for token in str(args.prefer_database_tokens or "学术期刊,中国学术期刊,学位论文").split(",") if token.strip()
        ],
        "entry_url": str(args.entry_url or defaults.get("cnki_entry_url") or "https://kns.cnki.net/kns8s/search"),
        "cdp_url": str(args.cdp_url or defaults.get("cnki_cdp_url") or f"http://127.0.0.1:{int(defaults.get('cnki_cdp_port') or 9222)}"),
        "cdp_port": int(args.cdp_port or defaults.get("cnki_cdp_port") or 9222),
        "skip_launch": bool(args.skip_launch),
        "keep_browser_open": bool(args.keep_browser_open),
        "timeout_ms": int(args.timeout_ms or browser_config.get("timeout_ms") or 15000),
        "user_data_dir": _resolve_repo_path(browser_config.get("user_data_dir"), "sandbox/runtime/web_brower_profiles/cnki_debug"),
        "output_root": _resolve_repo_path(args.output_dir, "sandbox/online_retrieval_debug/outputs/cnki_reader_probe"),
    }


def _open_context(config: dict[str, Any]) -> tuple[Playwright, BrowserContext, Any | None]:
    browser_proc = None
    if not config["skip_launch"]:
        browser_proc = CNKI_DEBUG._launch_edge_with_cdp(
            profile_dir=Path(config["user_data_dir"]),
            port=int(config["cdp_port"]),
            start_url=str(config["entry_url"]),
        )
        time.sleep(2)
    try:
        playwright, context = CNKI_DEBUG._connect_context(str(config["cdp_url"]))
    except Exception:
        if config["skip_launch"]:
            browser_proc = CNKI_DEBUG._launch_edge_with_cdp(
                profile_dir=Path(config["user_data_dir"]),
                port=int(config["cdp_port"]),
                start_url=str(config["entry_url"]),
            )
            time.sleep(2)
            playwright, context = CNKI_DEBUG._connect_context(str(config["cdp_url"]))
        else:
            raise
    return playwright, context, browser_proc


def _select_working_page(context: BrowserContext, config: dict[str, Any]) -> Page:
    try:
        page = CNKI_DEBUG._select_existing_page(context, preferred_url=str(config["entry_url"]))
    except Exception:
        page = context.new_page()
        page.goto(str(config["entry_url"]), wait_until="domcontentloaded")
    page.set_default_timeout(int(config["timeout_ms"]))
    return page


def _choose_result(results: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    if not results:
        raise RuntimeError("检索结果为空，无法选择详情页。")

    result_index = int(config["result_index"])
    if 0 <= result_index < len(results):
        return dict(results[result_index])

    preferred = list(config["prefer_database_tokens"] or [])
    for item in results:
        database = str(item.get("database") or "")
        if preferred and any(token in database for token in preferred):
            return dict(item)
        if database and "外文" not in database:
            return dict(item)
    return dict(results[0])


def _ensure_detail_page(page: Page, config: dict[str, Any]) -> dict[str, Any]:
    manual_events: list[dict[str, Any]] = []
    query = str(config["query"])
    if config["detail_url"]:
        page.goto(str(config["detail_url"]), wait_until="domcontentloaded")
        CNKI_DEBUG._human_pause(page)
        manual_events.extend(CNKI_DEBUG._wait_for_human_if_needed(page, "", True))
        detail = page.evaluate(CNKI_DEBUG._build_paper_detail_script())
        return {
            "selected_result": {},
            "detail": detail,
            "manual_events": manual_events,
        }

    page.goto(str(config["entry_url"]), wait_until="domcontentloaded")
    manual_events.extend(CNKI_DEBUG._wait_for_human_if_needed(page, "", True))
    if not CNKI_DEBUG._is_result_page(page):
        page.evaluate(CNKI_DEBUG._build_submit_search_script(), {"query": query})
        CNKI_DEBUG._wait_for_result_page(page)
    parsed = CNKI_DEBUG._parse_current_page(page)
    selected = _choose_result(list(parsed.get("results") or []), config)
    page.goto(str(selected.get("href") or ""), wait_until="domcontentloaded")
    CNKI_DEBUG._human_pause(page)
    manual_events.extend(CNKI_DEBUG._wait_for_human_if_needed(page, "", True))
    detail = page.evaluate(CNKI_DEBUG._build_paper_detail_script())
    return {
        "search_page": parsed,
        "selected_result": selected,
        "detail": detail,
        "manual_events": manual_events,
    }


def _extract_reader_candidates(page: Page) -> list[dict[str, Any]]:
    return list(
        page.evaluate(
            r"""() => {
                const tokens = ['在线阅读', '整本阅读', '阅读全文', 'HTML', 'html', 'CAJ', 'PDF', '全文', '阅读'];
                const nodes = Array.from(document.querySelectorAll('a,button,[role="button"]'));
                return nodes.map((node, index) => {
                    const text = (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
                    const href = node.getAttribute('href') || '';
                    const onclick = node.getAttribute('onclick') || '';
                    const className = String(node.className || '');
                    const id = node.id || '';
                    const parent = node.parentElement;
                    const parentClass = parent ? String(parent.className || '') : '';
                    const parentId = parent ? (parent.id || '') : '';
                    const haystack = `${text} ${href} ${onclick} ${className} ${id}`;
                    const style = window.getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    let priority = 0;
                    if (text === 'HTML阅读') priority += 1200;
                    else if (text.includes('HTML阅读')) priority += 1000;
                    if (text === '原版阅读') priority += 950;
                    else if (text.includes('原版阅读')) priority += 850;
                    if (text === 'CNKI AI阅读') priority += 820;
                    else if (text.includes('CNKI AI阅读')) priority += 760;
                    if (text.includes('在线阅读') || text.includes('阅读全文')) priority += 700;
                    if (text.includes('CAJ阅读')) priority += 620;
                    if (text.includes('PDF下载')) priority += 260;
                    if (text.includes('CAJ下载')) priority += 240;
                    if (/btn-html|btn-yb-reader|btn-dlcaj|btn-dlpdf|btn-cnki-ai|btn-ai-reader/i.test(`${className} ${parentClass}`)) priority += 180;
                    if (/cnkiAiReader|cajDown|pdfDown/i.test(`${id} ${parentId}`)) priority += 180;
                    if (/bar\.cnki\.net\/bar\/download\/order/i.test(href)) priority += 200;
                    if (/btn-dlcaj|btn-dlpdf/i.test(`${className} ${parentClass}`)) priority -= 120;
                    if (/manual\.html|service\.cnki|kefu\.cnki|agreement|privacy|feedback/i.test(href)) priority -= 400;
                    if (/ErrorMsg\.html/i.test(href)) priority -= 600;
                    if (/快速上手|页头|检索|个性化首页|出版来源导航|我的CNKI|查看全部更新信息|用户反馈|使用协议|隐私政策/.test(text)) priority -= 400;
                    return {
                        dom_index: index,
                        text,
                        href,
                        onclick,
                        class_name: className,
                        id,
                        parent_class_name: parentClass,
                        parent_id: parentId,
                        dataset: {...node.dataset},
                        is_visible: style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0,
                        display: style.display,
                        target: node.getAttribute('target') || '',
                        outer_html: (node.outerHTML || '').slice(0, 600),
                        matched: tokens.some((token) => haystack.includes(token)),
                        priority,
                    };
                }).filter((item) => item.matched && item.priority > 0).sort((a, b) => b.priority - a.priority);
            }"""
        )
        or []
    )


def _extract_page_context(page: Page) -> dict[str, Any]:
    return dict(
        page.evaluate(
            r"""() => {
                const hiddenInputs = Array.from(document.querySelectorAll('input[type="hidden"], input[id^="param"], input[name^="param"]'))
                    .map((node) => ({ id: node.id || '', name: node.name || '', value: node.value || '' }))
                    .filter((item) => item.id || item.name || item.value);

                const inlineScripts = Array.from(document.scripts)
                    .map((script, index) => ({ index, src: script.src || '', text: script.textContent || '' }))
                    .filter((item) => !item.src && /(caj|read|reader|download|fulltext|html)/i.test(item.text))
                    .slice(0, 10)
                    .map((item) => ({ index: item.index, snippet: item.text.slice(0, 2000) }));

                const meta = Array.from(document.querySelectorAll('meta')).map((node) => ({
                    name: node.getAttribute('name') || node.getAttribute('property') || '',
                    content: node.getAttribute('content') || ''
                })).filter((item) => item.name || item.content);

                return {
                    url: location.href,
                    title: document.title,
                    hidden_inputs: hiddenInputs,
                    inline_scripts: inlineScripts,
                    meta,
                    body_text_sample: (document.body?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 3000),
                };
            }"""
        )
        or {}
    )


def _extract_page_structure(page: Page) -> dict[str, Any]:
    return dict(
        page.evaluate(
            r"""() => {
                const cssPath = (node) => {
                    if (!node || !node.tagName) return '';
                    const parts = [];
                    let current = node;
                    let depth = 0;
                    while (current && current.nodeType === Node.ELEMENT_NODE && depth < 6) {
                        let part = current.tagName.toLowerCase();
                        if (current.id) {
                            part += `#${current.id}`;
                            parts.unshift(part);
                            break;
                        }
                        const className = String(current.className || '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
                        if (className.length) part += '.' + className.join('.');
                        const siblings = current.parentElement ? Array.from(current.parentElement.children).filter((item) => item.tagName === current.tagName) : [];
                        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
                        parts.unshift(part);
                        current = current.parentElement;
                        depth += 1;
                    }
                    return parts.join(' > ');
                };

                const visible = (node) => {
                    if (!node || !(node instanceof Element)) return false;
                    const style = window.getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width >= 0 && rect.height >= 0;
                };

                const container = document.querySelector('article, main, .article, .article-main, .detail-main, .detail_box, .doc-main, .main-content, body') || document.body;
                const toc = Array.from(document.querySelectorAll('nav a[href], .catalog a[href], .toc a[href], [class*="catalog"] a[href], [class*="toc"] a[href]'))
                    .map((node, index) => ({
                        index,
                        text: (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim(),
                        href: node.getAttribute('href') || '',
                    }))
                    .filter((item) => item.text)
                    .slice(0, 200);

                const blocks = [];
                const nodes = Array.from(container.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,blockquote,pre,figure,figcaption,img,table'));
                nodes.slice(0, 1500).forEach((node, index) => {
                    if (!visible(node)) return;
                    const tag = node.tagName.toLowerCase();
                    const text = (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
                    if (!text && !['img', 'table', 'figure'].includes(tag)) return;

                    const base = {
                        block_index: index,
                        tag,
                        css_path: cssPath(node),
                    };

                    if (/^h[1-6]$/.test(tag)) {
                        blocks.push({
                            ...base,
                            node_type: 'heading',
                            heading_level: Number(tag.slice(1)),
                            text,
                        });
                        return;
                    }

                    if (tag === 'img') {
                        blocks.push({
                            ...base,
                            node_type: 'image',
                            src: node.getAttribute('src') || '',
                            alt: node.getAttribute('alt') || '',
                            title: node.getAttribute('title') || '',
                            width: node.getAttribute('width') || '',
                            height: node.getAttribute('height') || '',
                        });
                        return;
                    }

                    if (tag === 'table') {
                        const rows = Array.from(node.querySelectorAll('tr')).slice(0, 20).map((row) =>
                            Array.from(row.querySelectorAll('th,td')).slice(0, 12).map((cell) => (cell.innerText || cell.textContent || '').replace(/\s+/g, ' ').trim())
                        );
                        const captionNode = node.querySelector('caption');
                        blocks.push({
                            ...base,
                            node_type: 'table',
                            caption: captionNode ? (captionNode.innerText || captionNode.textContent || '').replace(/\s+/g, ' ').trim() : '',
                            row_count: rows.length,
                            rows,
                        });
                        return;
                    }

                    if (tag === 'figure') {
                        const imageNode = node.querySelector('img');
                        const captionNode = node.querySelector('figcaption');
                        blocks.push({
                            ...base,
                            node_type: 'figure',
                            text,
                            image_src: imageNode ? imageNode.getAttribute('src') || '' : '',
                            caption: captionNode ? (captionNode.innerText || captionNode.textContent || '').replace(/\s+/g, ' ').trim() : '',
                        });
                        return;
                    }

                    blocks.push({
                        ...base,
                        node_type: tag === 'figcaption' ? 'figure_caption' : 'text',
                        text,
                    });
                });

                return {
                    url: location.href,
                    title: document.title,
                    toc,
                    blocks,
                    stats: {
                        toc_count: toc.length,
                        block_count: blocks.length,
                        heading_count: blocks.filter((item) => item.node_type === 'heading').length,
                        image_count: blocks.filter((item) => item.node_type === 'image').length,
                        table_count: blocks.filter((item) => item.node_type === 'table').length,
                    },
                };
            }"""
        )
        or {}
    )


def _build_structure_tree(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    root: dict[str, Any] = {
        "node_id": "root",
        "node_type": "document",
        "title": "document",
        "children": [],
    }
    section_stack: list[tuple[int, dict[str, Any]]] = [(0, root)]
    block_counter = 0

    for block in blocks:
        block_type = str(block.get("node_type") or "")
        if block_type == "heading":
            level = int(block.get("heading_level") or 1)
            section_node = {
                "node_id": f"section_{len(section_stack)}_{block.get('block_index', 0)}",
                "node_type": "section",
                "heading_level": level,
                "title": str(block.get("text") or ""),
                "source_block_index": block.get("block_index"),
                "children": [],
            }
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            parent = section_stack[-1][1] if section_stack else root
            parent.setdefault("children", []).append(section_node)
            section_stack.append((level, section_node))
            continue

        parent = section_stack[-1][1] if section_stack else root
        block_counter += 1
        parent.setdefault("children", []).append(
            {
                "node_id": f"block_{block_counter}",
                "node_type": block_type or "text",
                "title": str(block.get("text") or block.get("caption") or block.get("src") or ""),
                "source_block_index": block.get("block_index"),
                "payload": block,
            }
        )

    return root


def _try_open_reader(page: Page, context: BrowserContext, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []

    def _looks_like_reader_entry(url: str) -> bool:
        lowered = str(url or "").lower()
        if not lowered or lowered == "about:blank":
            return False
        if any(token in lowered for token in ["manual.html", "service.cnki", "kefu.cnki", "agreement", "privacy", "errormsg.html"]):
            return False
        return any(token in lowered for token in ["bar.cnki.net", "ai.cnki.net", "m.cnki.net", "kns.cnki.net", "cajviewer", "estudy"])

    def _classify_page(candidate: dict[str, Any], reader_page: Page | None) -> dict[str, Any]:
        if reader_page is None:
            return {"status": "missing"}
        try:
            url = str(reader_page.url or "")
        except Exception:
            url = ""
        try:
            title = str(reader_page.title() or "")
        except Exception:
            title = ""
        try:
            body_text = str(reader_page.locator("body").inner_text(timeout=3000) or "")[:2000]
        except Exception:
            body_text = ""

        lowered_url = url.lower()
        lowered_title = title.lower()
        lowered_text = body_text.lower()
        if any(token in lowered_url for token in ["errormsg.html", "manual.html"]):
            return {"status": "error", "reason": "error_page", "url": url, "title": title, "body_text": body_text}
        if "来源应用不正确" in body_text or "未知错误" in body_text:
            return {"status": "error", "reason": "source_invalid", "url": url, "title": title, "body_text": body_text}
        if any(token in lowered_text for token in ["html阅读", "原版阅读", "目录", "章节", "全文", "手机扫码阅读", "上一篇", "下一篇"]):
            return {"status": "reader", "reason": "reader_text_detected", "url": url, "title": title, "body_text": body_text}
        if "cnki ai阅读" in lowered_text or "aiplus.cnki.net" in lowered_url:
            return {"status": "reader", "reason": "ai_reader_detected", "url": url, "title": title, "body_text": body_text}
        if _looks_like_reader_entry(url):
            candidate_text = str(candidate.get("text") or "")
            if "下载" in candidate_text and not any(token in lowered_text for token in ["目录", "章节", "全文"]):
                return {"status": "intermediate", "reason": "download_entry_only", "url": url, "title": title, "body_text": body_text}
            return {"status": "reader", "reason": "reader_entry_url", "url": url, "title": title, "body_text": body_text}
        return {"status": "unknown", "reason": "unclassified", "url": url, "title": title, "body_text": body_text}

    def _request_handler(req: Any) -> None:
        url = str(req.url)
        lowered = url.lower()
        if any(token in lowered for token in ["read", "reader", "caj", "download", "fulltext", "html", "kcms"]):
            requests.append(
                {
                    "method": str(req.method),
                    "url": url,
                    "resource_type": str(req.resource_type),
                }
            )

    context.on("request", _request_handler)
    attempts: list[dict[str, Any]] = []
    try:
        for candidate in candidates[:8]:
            before_page_ids = {id(item) for item in context.pages}
            before_url = page.url
            href = str(candidate.get("href") or "").strip()
            click_result = page.evaluate(
                r"""(domIndex) => {
                    const nodes = Array.from(document.querySelectorAll('a,button,[role="button"]'));
                    const node = nodes[domIndex];
                    if (!node) return { status: 'missing', dom_index: domIndex };
                    node.setAttribute('target', '_blank');
                    if (node instanceof HTMLElement && node.style) {
                        node.style.display = 'block';
                        node.style.visibility = 'visible';
                    }
                    node.click();
                    return {
                        status: 'clicked',
                        dom_index: domIndex,
                        text: (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim(),
                        href: node.getAttribute('href') || '',
                        class_name: String(node.className || ''),
                    };
                }""",
                int(candidate.get("dom_index") or 0),
            )
            page.wait_for_timeout(4000)
            new_pages = [item for item in context.pages if id(item) not in before_page_ids]
            reader_page = new_pages[-1] if new_pages else None
            if reader_page is None and href and href.lower().startswith("http"):
                reader_page = context.new_page()
                reader_page.set_default_timeout(15000)
                reader_page.goto(href, wait_until="domcontentloaded")
                reader_page.wait_for_timeout(2000)
                click_result = {
                    "status": "goto_fallback",
                    "dom_index": candidate.get("dom_index"),
                    "text": candidate.get("text"),
                    "href": href,
                    "class_name": candidate.get("class_name"),
                }

            reader_url = ""
            page_state: dict[str, Any] = {"status": "missing"}
            if reader_page is not None:
                try:
                    reader_page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
                reader_page.wait_for_timeout(2000)
                try:
                    reader_url = reader_page.url
                except Exception:
                    reader_url = ""
                page_state = _classify_page(candidate, reader_page)
            attempts.append(
                {
                    "candidate": candidate,
                    "click_result": click_result,
                    "before_url": before_url,
                    "after_url": page.url,
                    "reader_url": reader_url,
                    "new_page_count": len([item for item in context.pages if id(item) not in before_page_ids]),
                    "page_state": page_state,
                }
            )
            if reader_page is not None and page_state.get("status") == "reader":
                return {
                    "status": "PASS",
                    "attempts": attempts,
                    "reader_page": reader_page,
                    "reader_url": reader_url,
                    "requests": requests[-80:],
                }
            if reader_page is not None:
                try:
                    reader_page.close()
                except Exception:
                    pass
    finally:
        try:
            context.remove_listener("request", _request_handler)
        except Exception:
            pass

    return {
        "status": "NO_READER_PAGE",
        "attempts": attempts,
        "reader_page": None,
        "reader_url": "",
        "requests": requests[-80:],
    }


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_response_payload(text: str) -> Any:
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.startswith("{") or raw.startswith("["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def _capture_reader_network_payloads(reader_page: Page) -> list[dict[str, Any]]:
    context = reader_page.context
    entries: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    def _should_capture(url: str, resource_type: str) -> bool:
        lowered = str(url or "").lower()
        if not lowered.startswith("https://kns.cnki.net"):
            return False
        if resource_type in {"xhr", "fetch"}:
            return True
        return any(token in lowered for token in ["/zkread/article/readonline", "/xmlread/xml.html"])

    def _response_handler(response: Any) -> None:
        request = response.request
        url = str(response.url or "")
        resource_type = str(request.resource_type or "")
        if not _should_capture(url, resource_type):
            return

        key = (str(request.method or "GET"), url)
        if key in seen_keys:
            return
        seen_keys.add(key)

        try:
            body_text = response.text()
        except Exception:
            body_text = ""
        parsed = _parse_response_payload(body_text)
        entries.append(
            {
                "method": str(request.method or "GET"),
                "url": url,
                "resource_type": resource_type,
                "status": int(response.status or 0),
                "content_type": str(response.headers.get("content-type") or ""),
                "body_preview": body_text[:5000],
                "json": parsed,
            }
        )

    context.on("response", _response_handler)
    try:
        reader_page.reload(wait_until="domcontentloaded")
        reader_page.wait_for_timeout(4000)

        try:
            tabs = reader_page.locator(".catalog-title .catalog-tab")
            if tabs.count() >= 2:
                tabs.nth(1).click()
                reader_page.wait_for_timeout(1500)
                tabs.nth(0).click()
                reader_page.wait_for_timeout(1000)
        except Exception:
            pass
    finally:
        try:
            context.remove_listener("response", _response_handler)
        except Exception:
            pass

    return entries


def _extract_reader_semantic_data(page: Page) -> dict[str, Any]:
    return dict(
        page.evaluate(
            r"""() => {
                const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();

                const catalogTree = Array.from(document.querySelectorAll('#js-catalog-tree li')).map((node, index) => {
                    const anchor = node.querySelector('a');
                    const titleNode = node.querySelector('.node_name');
                    return {
                        order: index + 1,
                        id: node.id || '',
                        title: clean((titleNode && titleNode.textContent) || (anchor && anchor.getAttribute('title')) || ''),
                    };
                }).filter((item) => item.title);

                const figureIndex = Array.from(document.querySelectorAll('.catalog-content-table li, .image-container .image-item')).map((node, index) => {
                    const text = clean(node.innerText || node.textContent || '');
                    const img = node.querySelector('img');
                    return {
                        order: index + 1,
                        text,
                        image_src: img ? (img.getAttribute('src') || '') : '',
                    };
                }).filter((item) => item.text || item.image_src);

                const articleRoot = document.querySelector('main .left-main, main .article-main, main .main-content, article, main') || document.body;
                const nodes = Array.from(articleRoot.querySelectorAll('h1,h2,h3,h4,h5,h6,p,img,table,figure,figcaption')).slice(0, 2500);
                const sections = [];
                let currentSection = {
                    title: '基本信息',
                    level: 0,
                    blocks: [],
                };
                const pushSection = () => {
                    if (currentSection.blocks.length || currentSection.title) {
                        sections.push(currentSection);
                    }
                };

                nodes.forEach((node) => {
                    const tag = node.tagName.toLowerCase();
                    const text = clean(node.innerText || node.textContent || '');
                    if (/^h[1-6]$/.test(tag) && text) {
                        pushSection();
                        currentSection = {
                            title: text,
                            level: Number(tag.slice(1)),
                            blocks: [],
                        };
                        return;
                    }
                    if (tag === 'img') {
                        currentSection.blocks.push({
                            type: 'image',
                            src: node.getAttribute('src') || '',
                            alt: node.getAttribute('alt') || '',
                            title: node.getAttribute('title') || '',
                        });
                        return;
                    }
                    if (tag === 'table') {
                        const rows = Array.from(node.querySelectorAll('tr')).slice(0, 30).map((row) =>
                            Array.from(row.querySelectorAll('th,td')).slice(0, 16).map((cell) => clean(cell.innerText || cell.textContent || ''))
                        );
                        currentSection.blocks.push({
                            type: 'table',
                            rows,
                        });
                        return;
                    }
                    if (tag === 'figure') {
                        const img = node.querySelector('img');
                        const caption = node.querySelector('figcaption');
                        currentSection.blocks.push({
                            type: 'figure',
                            image_src: img ? (img.getAttribute('src') || '') : '',
                            caption: clean(caption ? (caption.innerText || caption.textContent || '') : text),
                        });
                        return;
                    }
                    if (text) {
                        currentSection.blocks.push({
                            type: tag === 'figcaption' ? 'figure_caption' : 'text',
                            text,
                        });
                    }
                });
                pushSection();

                return {
                    catalog_tree: catalogTree,
                    figure_index: figureIndex,
                    sections,
                    stats: {
                        catalog_count: catalogTree.length,
                        figure_index_count: figureIndex.length,
                        section_count: sections.length,
                        text_block_count: sections.reduce((total, section) => total + section.blocks.filter((block) => block.type === 'text').length, 0),
                    },
                };
            }"""
        )
        or {}
    )


def _build_reader_api_summary(network_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "paper_info": None,
        "notes": None,
        "notes_count": None,
        "documents": [],
        "other_api_payloads": [],
    }
    for item in network_payloads:
        url = str(item.get("url") or "")
        payload = item.get("json")
        lowered = url.lower()
        if "getpaperinfo" in lowered:
            summary["paper_info"] = payload if payload is not None else item.get("body_preview")
        elif "getnotesbylid" in lowered:
            summary["notes"] = payload if payload is not None else item.get("body_preview")
        elif "getallnotescount" in lowered:
            summary["notes_count"] = payload if payload is not None else item.get("body_preview")
        elif any(token in lowered for token in ["/zkread/article/readonline", "/xmlread/xml.html"]):
            summary["documents"].append(
                {
                    "url": url,
                    "resource_type": item.get("resource_type"),
                    "status": item.get("status"),
                    "content_type": item.get("content_type"),
                }
            )
        else:
            summary["other_api_payloads"].append(
                {
                    "url": url,
                    "resource_type": item.get("resource_type"),
                    "status": item.get("status"),
                    "json": payload,
                    "body_preview": item.get("body_preview"),
                }
            )
    return summary


_PREFACE_TITLES = {
    "基本信息",
    "导言",
    "引言",
    "前言",
    "绪论",
    "摘要",
    "概述",
}


def _normalize_title_key(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _is_preface_like_title(value: str) -> bool:
    return _normalize_title_key(value) in {_normalize_title_key(item) for item in _PREFACE_TITLES}


def _enrich_catalog_tree(catalog_tree: list[dict[str, Any]], sections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_catalog_tree = [dict(item) for item in catalog_tree]
    enriched: list[dict[str, Any]] = []
    preface_title = str((sections[0] or {}).get("title") or "") if sections else ""
    preface_matched = False

    for index, node in enumerate(raw_catalog_tree, start=1):
        enriched_node = dict(node)
        raw_title = str(node.get("title") or "")
        aliases = [raw_title] if raw_title else []
        if index == 1 and preface_title and _is_preface_like_title(preface_title) and _is_preface_like_title(raw_title):
            aliases.append(preface_title)
            enriched_node["role"] = "preface"
            enriched_node["matched_section_title"] = preface_title
            preface_matched = True
        enriched_node["raw_title"] = raw_title
        enriched_node["aliases"] = list(dict.fromkeys(item for item in aliases if item))
        enriched_node["order"] = index
        enriched.append(enriched_node)

    if preface_title and _is_preface_like_title(preface_title) and not preface_matched:
        enriched.insert(
            0,
            {
                "order": 1,
                "id": "synthetic_preface",
                "title": preface_title,
                "raw_title": "",
                "aliases": [preface_title],
                "role": "preface",
                "synthetic": True,
                "matched_section_title": preface_title,
            },
        )

    for index, node in enumerate(enriched, start=1):
        node["order"] = index
    return enriched, raw_catalog_tree


def _match_catalog_node(section: dict[str, Any], catalog_tree: list[dict[str, Any]], section_index: int) -> tuple[dict[str, Any] | None, str]:
    title = str(section.get("title") or "")
    normalized_title = _normalize_title_key(title)
    if not normalized_title:
        return None, "missing_section_title"

    for node in catalog_tree:
        aliases = list(node.get("aliases") or [])
        if normalized_title in {_normalize_title_key(item) for item in aliases if item}:
            if section_index == 1 and str(node.get("role") or "") == "preface":
                return node, "preface_alias"
            return node, "exact_alias"

    for node in catalog_tree:
        raw_title = _normalize_title_key(str(node.get("title") or ""))
        if raw_title and (raw_title in normalized_title or normalized_title in raw_title):
            return node, "normalized_contains"

    if section_index == 1 and catalog_tree:
        first = catalog_tree[0]
        if str(first.get("role") or "") == "preface":
            return first, "preface_fallback"
    return None, "unmatched"


class _CnkiPaperHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sections: list[dict[str, Any]] = []
        self.current_section: dict[str, Any] = {"title": "导言", "blocks": [], "source_kind": "prefix"}
        self.current_tag: str | None = None
        self.current_attrs: dict[str, str] = {}
        self.buffer: list[str] = []
        self.pending_figure_title: str = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if tag in {"h1", "h4", "p"}:
            self.current_tag = tag
            self.current_attrs = attr_map
            self.buffer = []
            return
        if tag == "img":
            src = attr_map.get("data-src") or attr_map.get("src") or ""
            if src:
                self.current_section["blocks"].append(
                    {
                        "type": "figure" if self.pending_figure_title else "image",
                        "title": self.pending_figure_title,
                        "src": src,
                    }
                )
                self.pending_figure_title = ""

    def handle_data(self, data: str) -> None:
        if self.current_tag:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != self.current_tag:
            return
        text = " ".join(part.strip() for part in self.buffer if part.strip()).strip()
        if tag == "h1" and text:
            if self.current_section["blocks"] or self.current_section["title"]:
                self.sections.append(self.current_section)
            self.current_section = {"title": text, "blocks": [], "source_kind": "content"}
        elif tag == "h4" and text:
            role = self.current_attrs.get("role") or ""
            if role == "figure":
                self.pending_figure_title = text
            else:
                self.current_section["blocks"].append({"type": "heading", "text": text})
        elif tag == "p" and text:
            self.current_section["blocks"].append({"type": "paragraph", "text": text})
        self.current_tag = None
        self.current_attrs = {}
        self.buffer = []

    def finalize(self) -> list[dict[str, Any]]:
        if self.current_section["blocks"] or self.current_section["title"]:
            self.sections.append(self.current_section)
        return [section for section in self.sections if section.get("title") or section.get("blocks")]


def _build_reader_api_content(reader_api_summary: dict[str, Any]) -> dict[str, Any]:
    paper_info = dict(reader_api_summary.get("paper_info") or {})
    content = dict(paper_info.get("content") or {})
    paper = dict(content.get("paper") or {})
    prefix_html = str(paper.get("prefix") or "")
    content_html = str(paper.get("content") or "")
    parser = _CnkiPaperHtmlParser()
    parser.feed(prefix_html)
    parser.feed(content_html)
    sections = parser.finalize()

    figure_items = []
    for section in sections:
        for block in section.get("blocks") or []:
            if block.get("type") == "figure":
                figure_items.append(
                    {
                        "section": section.get("title"),
                        "title": block.get("title") or "",
                        "src": block.get("src") or "",
                    }
                )

    return {
        "title": paper.get("title") or "",
        "author_names": paper.get("authorNames") or "",
        "tilu_info": paper.get("tiluInfo") or {},
        "sections": sections,
        "figures": figure_items,
        "stats": {
            "section_count": len(sections),
            "figure_count": len(figure_items),
            "paragraph_count": sum(
                1
                for section in sections
                for block in (section.get("blocks") or [])
                if block.get("type") == "paragraph"
            ),
        },
    }


def _sanitize_filename(value: str, fallback: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip())
    text = text.strip("_")
    return text or fallback


def _resolve_reader_media(reader_page: Page) -> dict[str, Any]:
    reader_page.evaluate(
        """() => {
            const imgs = Array.from(document.querySelectorAll('img[data-src], img[src]'));
            imgs.forEach((img) => img.scrollIntoView({behavior: 'instant', block: 'center'}));
            window.scrollTo(0, document.body.scrollHeight);
        }"""
    )
    reader_page.wait_for_timeout(3000)
    return dict(
        reader_page.evaluate(
            r"""() => {
                const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();

                const images = Array.from(document.querySelectorAll('img[data-src], img[src]')).map((img, index) => {
                    const figure = img.closest('[role="section"], figure, .section.figure-center');
                    const heading = figure ? figure.querySelector('h4, figcaption, .figure') : null;
                    const currentSrc = img.currentSrc || '';
                    const dataSrc = img.getAttribute('data-src') || '';
                    const src = img.getAttribute('src') || '';
                    return {
                        index: index + 1,
                        title: clean(heading ? (heading.innerText || heading.textContent || '') : ''),
                        data_src: dataSrc,
                        src,
                        current_src: currentSrc,
                        width: img.naturalWidth || 0,
                        height: img.naturalHeight || 0,
                        section_id: figure ? (figure.getAttribute('data-id') || figure.id || '') : '',
                    };
                }).filter((item) => {
                    if (item.data_src) return true;
                    const lowered = String(item.current_src || item.src || '').toLowerCase();
                    return lowered.includes('/nzkhtml/resource/');
                });

                const tables = Array.from(document.querySelectorAll('table')).map((table, index) => {
                    const captionNode = table.querySelector('caption');
                    return {
                        index: index + 1,
                        caption: clean(captionNode ? (captionNode.innerText || captionNode.textContent || '') : ''),
                        rows: Array.from(table.querySelectorAll('tr')).slice(0, 30).map((row) =>
                            Array.from(row.querySelectorAll('th,td')).slice(0, 16).map((cell) => clean(cell.innerText || cell.textContent || ''))
                        ),
                    };
                });

                return {
                    images,
                    tables,
                };
            }"""
        )
        or {}
    )


def _build_cookie_header(context: BrowserContext, url: str) -> str:
    try:
        cookies = context.cookies([url])
    except Exception:
        cookies = []
    return "; ".join(f"{item.get('name', '')}={item.get('value', '')}" for item in cookies if item.get("name"))


def _download_binary(url: str, destination: Path, cookie_header: str) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": "Mozilla/5.0",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    try:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=30) as response:
            payload = response.read()
            destination.write_bytes(payload)
            return {
                "status": "downloaded",
                "bytes": len(payload),
                "content_type": str(response.headers.get("Content-Type") or ""),
            }
    except Exception as exc:
        return {
            "status": "failed",
            "error": str(exc),
        }


def _export_article_package(
    run_dir: Path,
    context: BrowserContext,
    reader_api_content: dict[str, Any],
    reader_semantic: dict[str, Any],
    reader_media: dict[str, Any],
) -> dict[str, Any]:
    package_root = run_dir / "article_package"
    structure_dir = package_root / "structure"
    chapters_dir = package_root / "chapters"
    paragraphs_dir = package_root / "paragraphs"
    images_dir = package_root / "media" / "images"
    tables_dir = package_root / "media" / "tables"
    for directory in [structure_dir, chapters_dir, paragraphs_dir, images_dir, tables_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    raw_catalog_tree = list(reader_semantic.get("catalog_tree") or [])
    sections = list(reader_api_content.get("sections") or [])
    catalog_tree, original_catalog_tree = _enrich_catalog_tree(raw_catalog_tree, sections)
    figures = list(reader_api_content.get("figures") or [])
    media_images = list(reader_media.get("images") or [])
    media_tables = list(reader_media.get("tables") or [])

    image_lookup: dict[str, dict[str, Any]] = {}
    image_index: list[dict[str, Any]] = []
    for image in media_images:
        resolved_url = str(image.get("current_src") or image.get("src") or "")
        data_src = str(image.get("data_src") or "")
        file_name = Path(urlparse(resolved_url).path).name if resolved_url else Path(data_src).name
        file_name = _sanitize_filename(file_name, f"image_{int(image.get('index') or 0):03d}.bin")
        local_path = images_dir / file_name
        download_result = {"status": "skipped"}
        if resolved_url:
            cookie_header = _build_cookie_header(context, resolved_url)
            download_result = _download_binary(resolved_url, local_path, cookie_header)
        record = {
            "index": image.get("index"),
            "title": image.get("title") or "",
            "data_src": data_src,
            "resolved_url": resolved_url,
            "width": image.get("width") or 0,
            "height": image.get("height") or 0,
            "local_path": str(local_path.relative_to(package_root)).replace("\\", "/") if local_path.exists() else "",
            "download": download_result,
        }
        image_index.append(record)
        if data_src:
            image_lookup[data_src] = record

    table_index: list[dict[str, Any]] = []
    for table in media_tables:
        table_file = tables_dir / f"table_{int(table.get('index') or 0):03d}.json"
        _write_json(table_file, table)
        table_index.append(
            {
                "index": table.get("index"),
                "caption": table.get("caption") or "",
                "row_count": len(list(table.get("rows") or [])),
                "path": str(table_file.relative_to(package_root)).replace("\\", "/"),
            }
        )

    paragraph_counter = 0
    chapter_records: list[dict[str, Any]] = []
    section_tree: list[dict[str, Any]] = []
    for section_index, section in enumerate(sections, start=1):
        chapter_slug = _sanitize_filename(str(section.get("title") or ""), f"section_{section_index:03d}")
        chapter_file = chapters_dir / f"{section_index:03d}_{chapter_slug}.json"
        paragraph_paths: list[str] = []
        figure_refs: list[dict[str, Any]] = []
        for block in list(section.get("blocks") or []):
            if block.get("type") == "paragraph":
                paragraph_counter += 1
                paragraph_file = paragraphs_dir / f"paragraph_{paragraph_counter:03d}.json"
                paragraph_payload = {
                    "order": paragraph_counter,
                    "section": section.get("title") or "",
                    "text": block.get("text") or "",
                }
                _write_json(paragraph_file, paragraph_payload)
                paragraph_paths.append(str(paragraph_file.relative_to(package_root)).replace("\\", "/"))
            elif block.get("type") == "figure":
                figure_refs.append(image_lookup.get(str(block.get("src") or ""), {
                    "title": block.get("title") or "",
                    "data_src": block.get("src") or "",
                    "resolved_url": "",
                    "local_path": "",
                }))

        chapter_payload = {
            "order": section_index,
            "title": section.get("title") or "",
            "blocks": section.get("blocks") or [],
            "paragraph_files": paragraph_paths,
            "figure_refs": figure_refs,
        }
        _write_json(chapter_file, chapter_payload)
        chapter_record = {
            "order": section_index,
            "title": section.get("title") or "",
            "chapter_file": str(chapter_file.relative_to(package_root)).replace("\\", "/"),
            "paragraph_files": paragraph_paths,
            "figure_refs": figure_refs,
        }
        chapter_records.append(chapter_record)
        matching_catalog, match_strategy = _match_catalog_node(section, catalog_tree, section_index)
        section_tree.append(
            {
                "order": section_index,
                "title": section.get("title") or "",
                "source_kind": section.get("source_kind") or "",
                "catalog_node": matching_catalog,
                "catalog_match_strategy": match_strategy,
                "chapter_file": chapter_record["chapter_file"],
                "paragraph_count": len(paragraph_paths),
                "figure_count": len(figure_refs),
            }
        )

    bundle = {
        "title": reader_api_content.get("title") or "",
        "author_names": reader_api_content.get("author_names") or "",
        "metadata": reader_api_content.get("tilu_info") or {},
        "raw_catalog_tree": original_catalog_tree,
        "catalog_tree": catalog_tree,
        "section_tree": section_tree,
        "chapters": chapter_records,
        "images": image_index,
        "tables": table_index,
    }

    _write_json(structure_dir / "raw_catalog_tree.json", original_catalog_tree)
    _write_json(structure_dir / "catalog_tree.json", catalog_tree)
    _write_json(structure_dir / "section_tree.json", section_tree)
    _write_json(structure_dir / "article_bundle.json", bundle)
    _write_json(images_dir / "index.json", image_index)
    _write_json(tables_dir / "index.json", table_index)

    return {
        "package_root": str(package_root),
        "structure_dir": str(structure_dir),
        "chapters_dir": str(chapters_dir),
        "paragraphs_dir": str(paragraphs_dir),
        "images_dir": str(images_dir),
        "tables_dir": str(tables_dir),
        "image_count": len(image_index),
        "table_count": len(table_index),
        "chapter_count": len(chapter_records),
        "paragraph_count": paragraph_counter,
        "bundle_path": str((structure_dir / "article_bundle.json").resolve()),
    }


def run_probe_in_context(context: BrowserContext, config: dict[str, Any], output_root: Path | None = None) -> dict[str, Any]:
    resolved_output_root = Path(output_root or config["output_root"]).resolve()
    resolved_output_root.mkdir(parents=True, exist_ok=True)

    page = _select_working_page(context, config)
    detail_bundle = _ensure_detail_page(page, config)
    selected_result = dict(detail_bundle.get("selected_result") or {})
    detail_record = CNKI_DEBUG._search_item_to_record(selected_result) if selected_result else {}
    if detail_bundle.get("detail"):
        detail_record.update({
            key: value for key, value in dict(detail_bundle.get("detail") or {}).items() if value not in (None, "", [])
        })
    record_bundle = CNKI_DEBUG._build_record_bundle(detail_record) if detail_record else {}

    detail_context = _extract_page_context(page)
    detail_candidates = _extract_reader_candidates(page)
    detail_structure = _extract_page_structure(page)
    detail_tree = _build_structure_tree(list(detail_structure.get("blocks") or []))

    reader_attempt = _try_open_reader(page, context, detail_candidates)
    reader_page = reader_attempt.pop("reader_page", None)
    reader_context: dict[str, Any] = {}
    reader_structure: dict[str, Any] = {}
    reader_tree: dict[str, Any] = {}
    reader_network_payloads: list[dict[str, Any]] = []
    reader_api_summary: dict[str, Any] = {}
    reader_api_content: dict[str, Any] = {}
    reader_semantic: dict[str, Any] = {}
    reader_media: dict[str, Any] = {}
    article_package: dict[str, Any] = {}
    reader_html_path = ""
    if reader_page is not None:
        reader_network_payloads = _capture_reader_network_payloads(reader_page)
        reader_context = _extract_page_context(reader_page)
        reader_structure = _extract_page_structure(reader_page)
        reader_tree = _build_structure_tree(list(reader_structure.get("blocks") or []))
        reader_semantic = _extract_reader_semantic_data(reader_page)
        reader_api_summary = _build_reader_api_summary(reader_network_payloads)
        reader_api_content = _build_reader_api_content(reader_api_summary)
        reader_media = _resolve_reader_media(reader_page)

    base_name = _slugify(detail_record.get("title") or selected_result.get("title") or config["query"] or "cnki_reader_probe")
    run_dir = (resolved_output_root / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{base_name}").resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    detail_html_path = run_dir / "detail_page.html"
    _write_text(detail_html_path, page.content())
    if reader_page is not None:
        reader_html_path = str((run_dir / "reader_page.html").resolve())
        _write_text(Path(reader_html_path), reader_page.content())

    _write_json(run_dir / "detail_page_context.json", detail_context)
    _write_json(run_dir / "detail_reader_candidates.json", detail_candidates)
    _write_json(run_dir / "detail_structure.json", detail_structure)
    _write_json(run_dir / "detail_structure_tree.json", detail_tree)
    if reader_context:
        _write_json(run_dir / "reader_page_context.json", reader_context)
    if reader_structure:
        _write_json(run_dir / "reader_structure.json", reader_structure)
    if reader_tree:
        _write_json(run_dir / "reader_structure_tree.json", reader_tree)
    if reader_network_payloads:
        _write_json(run_dir / "reader_network_payloads.json", reader_network_payloads)
    if reader_api_summary:
        _write_json(run_dir / "reader_api_summary.json", reader_api_summary)
    if reader_api_content:
        _write_json(run_dir / "reader_api_content.json", reader_api_content)
    if reader_media:
        _write_json(run_dir / "reader_media.json", reader_media)
    if reader_semantic:
        _write_json(run_dir / "reader_semantic.json", reader_semantic)
    if reader_api_content or reader_semantic or reader_media:
        article_package = _export_article_package(run_dir, context, reader_api_content, reader_semantic, reader_media)

    result = {
        "status": str(reader_attempt.get("status") or "PASS"),
        "query": config["query"],
        "selected_result": selected_result,
        "detail": detail_bundle.get("detail") or {},
        "detail_record_bundle": record_bundle,
        "manual_events": detail_bundle.get("manual_events") or [],
        "detail_context": detail_context,
        "detail_structure_stats": detail_structure.get("stats") or {},
        "reader_attempt": reader_attempt,
        "reader_context": reader_context,
        "reader_structure_stats": reader_structure.get("stats") or {},
        "reader_semantic_stats": reader_semantic.get("stats") or {},
        "reader_api_summary": reader_api_summary,
        "reader_api_content_stats": reader_api_content.get("stats") or {},
        "reader_media_stats": {
            "image_count": len(list(reader_media.get("images") or [])),
            "table_count": len(list(reader_media.get("tables") or [])),
        },
        "article_package": article_package,
        "artifacts": {
            "run_dir": str(run_dir),
            "detail_html_path": str(detail_html_path),
            "reader_html_path": reader_html_path,
            "detail_page_context_path": str((run_dir / "detail_page_context.json").resolve()),
            "detail_reader_candidates_path": str((run_dir / "detail_reader_candidates.json").resolve()),
            "detail_structure_path": str((run_dir / "detail_structure.json").resolve()),
            "detail_structure_tree_path": str((run_dir / "detail_structure_tree.json").resolve()),
            "reader_page_context_path": str((run_dir / "reader_page_context.json").resolve()) if reader_context else "",
            "reader_structure_path": str((run_dir / "reader_structure.json").resolve()) if reader_structure else "",
            "reader_structure_tree_path": str((run_dir / "reader_structure_tree.json").resolve()) if reader_tree else "",
            "reader_network_payloads_path": str((run_dir / "reader_network_payloads.json").resolve()) if reader_network_payloads else "",
            "reader_api_summary_path": str((run_dir / "reader_api_summary.json").resolve()) if reader_api_summary else "",
            "reader_api_content_path": str((run_dir / "reader_api_content.json").resolve()) if reader_api_content else "",
            "reader_media_path": str((run_dir / "reader_media.json").resolve()) if reader_media else "",
            "reader_semantic_path": str((run_dir / "reader_semantic.json").resolve()) if reader_semantic else "",
            "article_package_root": str(Path(article_package.get("package_root") or "").resolve()) if article_package else "",
        },
    }
    _write_json(run_dir / "probe_result.json", result)
    return result


def run_probe(config: dict[str, Any]) -> dict[str, Any]:
    output_root = Path(config["output_root"]).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    playwright: Playwright | None = None
    context: BrowserContext | None = None
    browser_proc = None
    try:
        playwright, context, browser_proc = _open_context(config)
        return run_probe_in_context(context, config, output_root)
    finally:
        if playwright is not None:
            playwright.stop()
        if browser_proc is not None and not config["keep_browser_open"]:
            try:
                if browser_proc.poll() is None:
                    browser_proc.terminate()
            except OSError:
                pass


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CNKI 在线阅读 HTML 探测与结构化抽取")
    parser.add_argument("--query", default="", help="当未直接提供 detail_url 时使用的检索词")
    parser.add_argument("--detail-url", default="", help="直接指定详情页 URL，跳过检索")
    parser.add_argument("--result-index", type=int, default=0, help="检索结果索引，从 0 开始")
    parser.add_argument("--prefer-database-tokens", default="学术期刊,中国学术期刊,学位论文", help="优先选择这些数据库标签的结果，逗号分隔")
    parser.add_argument("--output-dir", default="", help="输出根目录，默认写入 sandbox/online_retrieval_debug/outputs/cnki_reader_probe")
    parser.add_argument("--entry-url", default="", help="CNKI 检索入口 URL")
    parser.add_argument("--cdp-url", default="", help="已启动浏览器的 CDP URL")
    parser.add_argument("--cdp-port", type=int, default=0, help="远程调试端口")
    parser.add_argument("--timeout-ms", type=int, default=0, help="页面默认超时毫秒数")
    parser.add_argument("--skip-launch", action="store_true", help="只接管现有远程调试浏览器，不自动启动 Edge")
    parser.add_argument("--keep-browser-open", action="store_true", help="脚本结束后保留自动启动的浏览器")
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    result = run_probe(_build_probe_config(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()