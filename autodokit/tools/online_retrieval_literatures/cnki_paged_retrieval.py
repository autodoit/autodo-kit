"""CNKI 分页检索、Bib 导出与 PDF/CAJ 下载调试脚本。"""

from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright


def _discover_repo_root(start_path: Path) -> Path:
    """从当前脚本位置向上定位仓库根目录。"""

    for candidate in [start_path, *start_path.parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "autodokit").is_dir():
            return candidate
    raise RuntimeError("未找到 autodo-kit 仓库根目录。")


REPO_ROOT = _discover_repo_root(Path(__file__).resolve().parent)


def _load_repo_module(module_name: str, relative_path: str) -> Any:
    """从仓库源码文件直接加载模块，避免依赖预安装包。"""

    module_path = (REPO_ROOT / relative_path).resolve()
    if not module_path.exists():
        raise ImportError(f"未找到模块源码：{module_path}")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块源码：{module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(module_name, module)
    spec.loader.exec_module(module)
    return module


_OPEN_ACCESS_MODULE = _load_repo_module(
    "autodokit.tools.open_access_literature_retrieval",
    "autodokit/tools/online_retrieval_literatures/open_access_literature_retrieval.py",
)
_CNKI_ARTIFACTS_MODULE = _load_repo_module(
    "autodokit.affairs.CNKI桥接.artifacts",
    "autodokit/affairs/CNKI桥接/artifacts.py",
)

def _missing_stub(name: str):
    def _fn(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover - runtime stub
        raise RuntimeError(f"依赖模块 open_access_literature_retrieval 缺少 `{name}`，在运行时请确保该模块提供此函数。")

    return _fn

build_model_routing_decision = getattr(_OPEN_ACCESS_MODULE, "build_model_routing_decision", _missing_stub("build_model_routing_decision"))
invoke_with_fallback = getattr(_OPEN_ACCESS_MODULE, "invoke_with_fallback", _missing_stub("invoke_with_fallback"))
load_api_key_file = getattr(_OPEN_ACCESS_MODULE, "_load_api_key_file", _missing_stub("_load_api_key_file"))
build_ris_text = _CNKI_ARTIFACTS_MODULE.build_ris_text
parse_cnkielearning = _CNKI_ARTIFACTS_MODULE.parse_cnkielearning
slugify_filename = _CNKI_ARTIFACTS_MODULE.slugify_filename


REQUEST_TIMEOUT = 60
MANUAL_WAIT_TIMEOUT_SECONDS = 900
MANUAL_WAIT_POLL_SECONDS = 5
HUMAN_STEP_DELAY_MS = 1200


def _resolve_project_root(config: dict[str, Any]) -> Path:
    """解析当前调试配置对应的仓库根目录。"""

    raw_root = str(config.get("project_root") or "").strip()
    if raw_root:
        candidate = Path(raw_root).expanduser()
        if not candidate.is_absolute():
            candidate = (REPO_ROOT / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if (candidate / "pyproject.toml").exists() and (candidate / "autodokit").is_dir():
            return candidate
    return REPO_ROOT


def _resolve_repo_path(project_root: Path, raw_path: str | Path | None, default_relative: str) -> Path:
    """按当前仓库根目录解析配置路径。"""

    raw_text = str(raw_path or "").strip()
    if not raw_text:
        return (project_root / default_relative).resolve()
    candidate = Path(raw_text).expanduser()
    if candidate.is_absolute():
        if "AcademicResearch-auto-workflow" in raw_text and not candidate.exists():
            return (project_root / default_relative).resolve()
        return candidate.resolve()
    return (project_root / candidate).resolve()


def _find_edge_executable() -> str:
    """查找可用于 CDP 的 Chromium 内核浏览器可执行文件。

    Returns:
        浏览器可执行文件路径。

    Raises:
        RuntimeError: 当前系统未找到可用浏览器时抛出。
    """

    candidates = [
        shutil.which("msedge"),
        shutil.which("microsoft-edge"),
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("Google Chrome"),
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("未找到可用浏览器（Chrome/Edge），请先安装或在脚本中补充浏览器路径。")


def _launch_edge_with_cdp(profile_dir: Path, port: int, start_url: str) -> subprocess.Popen[str]:
    """以远程调试模式启动 Google Chrome。

    Args:
        profile_dir: 持久化 profile 目录。
        port: CDP 端口。

    Returns:
        浏览器进程对象。
    """

    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        _find_edge_executable(),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={str(profile_dir.resolve())}",
        start_url,
    ]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)


def _connect_context(cdp_url: str) -> tuple[Playwright, BrowserContext]:
    """连接 CDP 浏览器上下文。

    Args:
        cdp_url: CDP 地址。

    Returns:
        Playwright 实例与浏览器上下文。
    """

    playwright = sync_playwright().start()
    browser = playwright.chromium.connect_over_cdp(cdp_url)
    if browser.contexts:
        return playwright, browser.contexts[0]
    return playwright, browser.new_context()


def _connect_context_with_retry(cdp_url: str, retries: int = 12, delay_seconds: float = 1.0) -> tuple[Playwright, BrowserContext]:
    """重试连接 CDP 浏览器上下文。"""

    last_error: Exception | None = None
    for _ in range(max(retries, 1)):
        try:
            return _connect_context(cdp_url)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(max(delay_seconds, 0.1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("连接 CDP 失败，且未捕获到具体异常。")


def _select_existing_page(context: BrowserContext, preferred_url: str = "") -> Page:
    """从现有上下文中选择页面。

    Args:
        context: 浏览器上下文。
        preferred_url: 优先匹配的 URL 片段。

    Returns:
        页面对象。
    """

    pages = list(context.pages)
    if preferred_url:
        for page in pages:
            try:
                if preferred_url in page.url:
                    return page
            except Exception:  # noqa: BLE001
                continue
    if pages:
        return pages[0]
    raise RuntimeError("未发现可接管的现有浏览器页面。当前模式禁止自动新开页面。")


def _normalize_text(value: Any) -> str:
    """归一化文本。"""

    return " ".join(str(value or "").split()).strip()


def _page_inner_text(page: Page) -> str:
    """读取主文档正文文本，规避扩展注入的重复 body。"""

    return _normalize_text(page.locator("body").first.inner_text(timeout=2000))


def _read_page_state(page: Page) -> tuple[str, str, str]:
    """稳定读取页面状态，规避导航瞬间的执行上下文销毁。"""

    current_url = page.url
    for _ in range(3):
        try:
            current_url = page.url
            current_title = page.title()
            page_text = _page_inner_text(page)
            return current_url, current_title, page_text
        except Exception:  # noqa: BLE001
            try:
                page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:  # noqa: BLE001
                page.wait_for_timeout(1000)
    return current_url, "", ""


def _escape_bibtex(value: str) -> str:
    """转义 BibTeX 字段值。"""

    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _build_bibtex_key(record: dict[str, Any]) -> str:
    """构造 BibTeX 键。"""

    authors = list(record.get("authors") or [])
    lead_author = authors[0] if authors else "cnki"
    year = _normalize_text(record.get("year")) or "nd"
    title = _normalize_text(record.get("title")) or "paper"
    return slugify_filename(f"{lead_author}_{year}_{title}")[:80]


def _record_to_bibtex(record: dict[str, Any]) -> str:
    """将 CNKI 记录转换成 BibTeX。"""

    fields = {
        "title": _normalize_text(record.get("title")),
        "author": " and ".join([_normalize_text(item) for item in record.get("authors") or [] if _normalize_text(item)]),
        "journal": _normalize_text(record.get("journal")),
        "year": _normalize_text(record.get("year") or record.get("pub_time")),
        "keywords": "; ".join([_normalize_text(item) for item in record.get("keywords") or [] if _normalize_text(item)]),
        "abstract": _normalize_text(record.get("abstract")),
        "url": _normalize_text(record.get("detail_url") or record.get("link")),
    }
    lines = [f"@article{{{_build_bibtex_key(record)},"]
    for key, value in fields.items():
        if value:
            lines.append(f"  {key} = {{{_escape_bibtex(value)}}},")
    lines.append("}")
    return "\n".join(lines)


def _search_item_to_record(item: dict[str, Any]) -> dict[str, Any]:
    """将检索结果页条目转换为最小可用的题录记录。"""

    return {
        "title": _normalize_text(item.get("title")),
        "authors": [_normalize_text(author) for author in item.get("authors") or [] if _normalize_text(author)],
        "journal": _normalize_text(item.get("journal")),
        "year": _normalize_text(item.get("date"))[:4],
        "pub_time": _normalize_text(item.get("date")),
        "keywords": [],
        "abstract": "",
        "detail_url": _normalize_text(item.get("href")),
        "link": _normalize_text(item.get("href")),
        "citations": _normalize_text(item.get("citations")),
        "downloads": _normalize_text(item.get("downloads")),
    }


def _build_record_bundle(record: dict[str, Any]) -> dict[str, Any]:
    """为题录记录构造标准化导出字段。"""

    return {
        "record": record,
        "ris": build_ris_text(record),
        "bibtex": _record_to_bibtex(record),
    }


def _request_with_cookies(url: str, cookie_header: str) -> tuple[bytes, dict[str, str], str]:
    """带 Cookie 头下载资源。

    Args:
        url: 资源地址。
        cookie_header: Cookie 请求头。

    Returns:
        响应体、响应头和最终 URL。
    """

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AcademicResearchAutoWorkflow-CNKI/0.1",
            "Cookie": cookie_header,
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.read(), {key.lower(): value for key, value in response.headers.items()}, response.geturl()


def _get_cookie_header(context: BrowserContext, url: str) -> str:
    """提取当前上下文 Cookie 头。"""

    cookies = context.cookies([url])
    return "; ".join(f"{item['name']}={item['value']}" for item in cookies)


def _build_parse_results_script() -> str:
    """构造当前页结果解析脚本。"""

    return r"""
    () => {
      const captcha = document.querySelector('#tcaptcha_transform_dy');
      if (captcha && captcha.getBoundingClientRect().top >= 0)
      {
        return { error: 'captcha' };
      }
      const rows = Array.from(document.querySelectorAll('.result-table-list tbody tr'));
      const checkboxes = Array.from(document.querySelectorAll('.result-table-list tbody input.cbItem'));
      const pageMarkText = document.querySelector('.countPageMark')?.innerText?.trim() || '1/1';
      const pageParts = pageMarkText.split('/').map((item) => item.trim());
      const currentPage = Number(pageParts[0] || '1') || 1;
      const totalPages = Number(pageParts[1] || '1') || 1;
      const results = rows.map((row, index) => {
        const titleLink = row.querySelector('td.name a.fz14');
                const downloadLink = row.querySelector('a.downloadlink.icon-download');
                const cells = Array.from(row.querySelectorAll('td'));
        const authors = Array.from(row.querySelectorAll('td.author a.KnowledgeNetLink') || []).map((item) => item.innerText?.trim()).filter(Boolean);
        return {
          n: index + 1,
          title: titleLink?.innerText?.trim() || '',
          href: titleLink?.href || '',
                    downloadHref: downloadLink?.href || '',
          exportId: checkboxes[index]?.value || '',
          authors,
          journal: row.querySelector('td.source a')?.innerText?.trim() || '',
          date: row.querySelector('td.date')?.innerText?.trim() || '',
                    database: row.querySelector('td.data')?.innerText?.trim() || cells[4]?.innerText?.trim() || '',
          citations: row.querySelector('td.quote')?.innerText?.trim() || '',
          downloads: row.querySelector('td.download')?.innerText?.trim() || '',
        };
      });
      const totalText = document.querySelector('.pagerTitleCell')?.innerText || document.body.innerText;
      const totalMatch = totalText.match(/([\d,]+)\s*条结果/);
      const nextButton = Array.from(document.querySelectorAll('a,button,span')).find((item) => {
        const text = (item.innerText || '').trim();
        const cls = item.className || '';
        const aria = item.getAttribute('aria-disabled') || '';
        return /下一页|Next/i.test(text) && !/disabled|disable/.test(String(cls)) && aria !== 'true';
      });
      return {
        total: totalMatch ? totalMatch[1] : '0',
        current_page: currentPage,
        total_pages: totalPages,
        has_next: Boolean(nextButton && currentPage < totalPages),
        url: location.href,
        results,
      };
    }
    """


def _build_paper_detail_script() -> str:
        """构造论文详情抽取脚本。"""

        return r"""
        async () => {
            await new Promise((resolve, reject) => {
                let retry = 0;
                const check = () => {
                    if (document.querySelector('.brief h1')) resolve();
                    else if (retry++ > 30) reject(new Error('timeout'));
                    else setTimeout(check, 500);
                };
                check();
            });
            const captcha = document.querySelector('#tcaptcha_transform_dy');
            if (captcha && captcha.getBoundingClientRect().top >= 0) return { error: 'captcha' };
            const title = document.querySelector('.brief h1')?.innerText?.trim()?.replace(/\s*网络首发\s*$/, '') || '';
            const authors = Array.from(document.querySelectorAll('.author a, #authorpart a')).map((item) => item.innerText?.trim()).filter(Boolean);
            const authorOrganizations = Array.from(document.querySelectorAll('.orgn a, #authorpart+ p a')).map((item) => item.innerText?.trim()).filter(Boolean);
            const body = document.body.innerText;
            const abstract = document.querySelector('#ChDivSummary')?.innerText?.trim() || document.querySelector('.abstract-text')?.innerText?.trim() || '';
            const keywords = Array.from(document.querySelectorAll('.keywords a, #catalog_KEYWORD a')).map((item) => item.innerText?.trim()).filter(Boolean);
            return {
                title,
                authors,
                author_organizations: authorOrganizations,
                journal: document.querySelector('.top-tip span a, .source a')?.innerText?.trim() || '',
                date: body.match(/(\d{4}-\d{2}-\d{2})/)?.[1] || '',
                abstract,
                keywords,
                fund: body.match(/基金[：: ]\s*(.+?)(?=\n)/)?.[1] || '',
                classification: body.match(/分类号[：: ]\s*(.+?)(?=\n)/)?.[1] || '',
                doi: body.match(/DOI[：: ]\s*(.+?)(?=\n)/)?.[1] || '',
                detail_url: location.href,
                export_id: document.querySelector('#export-id')?.value || '',
            };
        }
        """


def _build_export_script() -> str:
        """构造导出脚本。"""

        return r"""
        async (params) => {
            const captcha = document.querySelector('#tcaptcha_transform_dy');
            if (captcha && captcha.getBoundingClientRect().top >= 0) return { error: 'captcha' };
            const url = document.querySelector('#export-url')?.value;
            const exportId = params.exportId || document.querySelector('#export-id')?.value;
            if (!url || !exportId) {
                return { error: 'not_exportable', message: '当前页面未提供导出参数' };
            }
            const uniplatform = new URLSearchParams(window.location.search).get('uniplatform') || 'NZKPT';
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams({ filename: exportId, displaymode: 'GBTREFER,elearning,EndNote', uniplatform }),
            });
            const data = await response.json();
            if (data.code !== 1) return { error: data.msg || 'export_failed' };
            const result = { export_id: exportId, detail_url: location.href };
            for (const item of data.data) {
                result[item.mode] = item.value[0];
            }
            return result;
        }
        """


def _is_result_page(page: Page) -> bool:
    """判断当前页是否已经进入 CNKI 结果列表页。"""

    try:
        if bool(
            page.locator(".result-table-list tbody tr").count()
            or page.locator("label.checkAll").count()
            or page.locator("#PageNext").count()
            or page.locator(".countPageMark").count()
        ):
            return True
        body_text = _page_inner_text(page)
        return "条结果" in body_text and ("导出与分析" in body_text or "批量操作" in body_text)
    except Exception:  # noqa: BLE001
        return False


def _wait_for_result_page(page: Page) -> None:
    """等待搜索后进入 CNKI 结果页。"""

    try:
        page.wait_for_function(
            r"""() => {
                const rowCount = document.querySelectorAll('.result-table-list tbody tr').length;
                const hasPager = Boolean(document.querySelector('.countPageMark, #PageNext, label.checkAll'));
                const bodyText = document.body?.innerText || '';
                return rowCount > 0 || hasPager || (/条结果/.test(bodyText) && (/导出与分析|批量操作/.test(bodyText)));
            }""",
            timeout=90000,
        )
        return
    except Exception:  # noqa: BLE001
        pass

    for _ in range(30):
        if _is_result_page(page):
            return
        try:
            page.wait_for_load_state("networkidle", timeout=2000)
        except Exception:  # noqa: BLE001
            page.wait_for_timeout(1000)
    if not _is_result_page(page):
        current_url, current_title, page_text = _read_page_state(page)
        raise RuntimeError(
            "搜索后未进入结果列表页。"
            f" 当前 URL: {current_url}；标题: {current_title}；页面片段: {page_text[:300]}"
        )


def _human_pause(page: Page, milliseconds: int = HUMAN_STEP_DELAY_MS) -> None:
    """模拟人工操作节奏。"""

    page.wait_for_timeout(milliseconds)


def _safe_evaluate(page: Page, script: str, arg: Any | None = None, *, retries: int = 2) -> Any:
    """执行 page.evaluate，并对导航竞态导致的上下文丢失做重试。"""

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if arg is None:
                return page.evaluate(script)
            return page.evaluate(script, arg)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            message = str(exc)
            if "Execution context was destroyed" not in message and "Cannot find context with specified id" not in message:
                raise
            if attempt >= retries:
                break
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:  # noqa: BLE001
                page.wait_for_timeout(800)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("evaluate 调用失败，且未捕获到具体异常")


def _build_submit_search_script() -> str:
    """构造搜索脚本。"""

    return r"""
    async (params) => {
      const waitFor = (predicate, limit = 50) => new Promise((resolve, reject) => {
        let retry = 0;
        const tick = () => {
          if (predicate())
          {
            resolve(true);
            return;
          }
          if (retry++ > limit)
          {
            reject(new Error('timeout'));
            return;
          }
          setTimeout(tick, 500);
        };
        tick();
      });

            const beforeUrl = location.href;
            await waitFor(() => document.querySelector('textarea.search-input, input.search-input, #txt_SearchText'));
            const input = document.querySelector('textarea.search-input, input.search-input, #txt_SearchText');
            if (!input)
            {
                throw new Error('search_input_not_found');
            }
            input.focus();
            input.value = params.query;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            const searchButton = document.querySelector('.search-btn, input.search-btn, button.search-btn, a.search-btn');
            if (searchButton)
            {
                searchButton.click();
            }
            else
            {
                input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
                input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));
            }
            return {
                status: 'SUBMITTED',
                before_url: beforeUrl,
            };
    }
    """


def _detect_blocking_state(page: Page) -> dict[str, Any]:
    """识别当前页面是否处于登录、验证码或统一认证错误页。"""

    current_url, current_title, page_text = _read_page_state(page)
    lowered = page_text.lower()

    if "login.hunnu.edu.cn/error" in current_url or "无效的Client ID" in page_text:
        return {
            "reason": "auth_client_invalid",
            "url": current_url,
            "title": current_title,
            "message": "检索请求被学校统一认证页拦截，并返回无效的 Client ID。",
        }
    if "verify/home" in current_url or "安全验证" in current_title or "captcha" in lowered:
        return {
            "reason": "captcha_required",
            "url": current_url,
            "title": current_title,
        }
    if "登录" in current_title or "log in" in lowered or "sign in" in lowered:
        return {
            "reason": "login_required",
            "url": current_url,
            "title": current_title,
        }
    return {}


def _build_next_page_script() -> str:
    """构造下一页脚本。"""

    return r"""
    async (params) => {
      const waitFor = (predicate, limit = 50) => new Promise((resolve, reject) => {
        let retry = 0;
        const tick = () => {
          if (predicate())
          {
            resolve(true);
            return;
          }
          if (retry++ > limit)
          {
            reject(new Error('timeout'));
            return;
          }
          setTimeout(tick, 500);
        };
        tick();
      });

      const before = params.beforePage;
            const nextButton = document.querySelector('#PageNext') || Array.from(document.querySelectorAll('a,button,span')).find((item) => {
        const text = (item.innerText || '').trim();
        const cls = item.className || '';
        const aria = item.getAttribute('aria-disabled') || '';
        return /下一页|Next/i.test(text) && !/disabled|disable/.test(String(cls)) && aria !== 'true';
      });
      if (!nextButton)
      {
        return { error: 'no_next' };
      }
      nextButton.click();
      await waitFor(() => {
        const text = document.querySelector('.countPageMark')?.innerText?.trim() || '';
        return text && text !== before;
      });
      return { status: 'PASS' };
    }
    """


def _build_download_candidates_script() -> str:
    """构造详情页下载候选抽取脚本。"""

    return r"""
    () => {
      const candidates = [];
      const nodes = Array.from(document.querySelectorAll('a,button'));
      for (const node of nodes)
      {
        const text = (node.innerText || node.textContent || '').trim();
        const href = node.getAttribute('href') || '';
        const onclick = node.getAttribute('onclick') || '';
        const normalized = `${text} ${href} ${onclick}`.toLowerCase();
        if (!normalized)
        {
          continue;
        }
        if (/pdf/.test(normalized) || /caj/.test(normalized) || /整本下载/.test(text) || /下载/.test(text))
        {
          candidates.push({
            text,
            href,
            onclick,
            tag: node.tagName.toLowerCase(),
          });
        }
      }
      return candidates;
    }
    """


def _maybe_analyze_with_bailian(page: Page, api_key_file: str) -> dict[str, Any]:
    """调用百炼分析当前页文本阻断类型。"""

    if not api_key_file:
        return {}
    page_text = _page_inner_text(page)
    if not page_text:
        return {}
    api_key = load_api_key_file(api_key_file)
    decision = build_model_routing_decision(
        task_type="general",
        quality_tier="balanced",
        budget_level="normal",
        latency_level="medium",
        risk_level="low",
        mainland_only=True,
    )
    prompt = (
        "请判断下面 CNKI 页面文本更像是登录页、验证码页、权限不足页还是正常文献页，"
        "并给出一句中文操作建议。\n\n"
        + page_text[:4000]
    )
    return invoke_with_fallback(
        api_key=api_key,
        candidate_models=[decision["primary_model"], *list(decision.get("fallback_models") or [])],
        prompt=prompt,
        timeout=60,
    )


def _wait_for_human_if_needed(page: Page, api_key_file: str, allow_manual_intervention: bool) -> list[dict[str, Any]]:
    """若遇到登录或验证码则暂停等待人工处理。"""

    manual_events: list[dict[str, Any]] = []
    wait_started_at = time.time()
    while True:
        try:
            blocked_state = _detect_blocking_state(page)
        except Exception as exc:  # noqa: BLE001
            manual_events.append(
                {
                    "status": "manual_interrupted",
                    "reason": "page_or_context_closed",
                    "detail": f"{exc.__class__.__name__}: {exc}",
                }
            )
            return manual_events
        if not blocked_state:
            return manual_events
        event: dict[str, Any] = dict(blocked_state)
        if api_key_file:
            try:
                event["bailian_analysis"] = _maybe_analyze_with_bailian(page, api_key_file)
            except Exception as exc:  # noqa: BLE001
                event["bailian_error"] = str(exc)
        manual_events.append(event)
        if event.get("reason") == "auth_client_invalid" or not allow_manual_intervention:
            return manual_events
        elapsed = int(time.time() - wait_started_at)
        if elapsed >= MANUAL_WAIT_TIMEOUT_SECONDS:
            event["timeout_seconds"] = elapsed
            event["status"] = "manual_timeout"
            return manual_events
        remaining = MANUAL_WAIT_TIMEOUT_SECONDS - elapsed
        print(
            "[人工接管] 当前页面需要登录或完成验证，浏览器窗口会保持打开。"
            f"已等待 {elapsed} 秒，剩余约 {remaining} 秒，将自动轮询页面状态。"
        )
        try:
            page.wait_for_timeout(MANUAL_WAIT_POLL_SECONDS * 1000)
        except Exception as exc:  # noqa: BLE001
            manual_events.append(
                {
                    "status": "manual_interrupted",
                    "reason": "page_or_context_closed",
                    "detail": f"{exc.__class__.__name__}: {exc}",
                }
            )
            return manual_events


def _parse_current_page(page: Page) -> dict[str, Any]:
    """解析当前搜索结果页。"""

    result = page.evaluate(_build_parse_results_script())
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(f"解析结果页失败: {result.get('error')}")
    return dict(result)


def _download_fulltext(context: BrowserContext, detail_page: Page, output_dir: Path, base_name: str) -> dict[str, Any]:
    """优先下载 PDF，若没有则下载 CAJ。"""

    candidates = detail_page.evaluate(_build_download_candidates_script())
    normalized: list[dict[str, Any]] = []
    for item in candidates or []:
        text = _normalize_text((item or {}).get("text"))
        href = _normalize_text((item or {}).get("href"))
        label = f"{text} {href}".lower()
        preferred_type = "pdf" if "pdf" in label else "caj" if "caj" in label else "download"
        normalized.append({"text": text, "href": href, "preferred_type": preferred_type})
    normalized.sort(key=lambda item: 0 if item["preferred_type"] == "pdf" else 1)

    cookie_header = _get_cookie_header(context, detail_page.url)
    attempts: list[dict[str, Any]] = []
    for item in normalized:
        href = item["href"]
        if not href or href.startswith("javascript"):
            attempts.append({"status": "SKIPPED", "message": f"候选链接不可直接下载: {item['text']}"})
            continue
        final_url = urllib.parse.urljoin(detail_page.url, href)
        suffix = ".pdf" if item["preferred_type"] == "pdf" else ".caj"
        try:
            body, headers, resolved_url = _request_with_cookies(final_url, cookie_header)
        except urllib.error.HTTPError as exc:
            attempts.append({"status": "ERROR", "url": final_url, "message": f"HTTP {exc.code}"})
            continue
        except Exception as exc:  # noqa: BLE001
            attempts.append({"status": "ERROR", "url": final_url, "message": str(exc)})
            continue
        content_type = str(headers.get("content-type") or "").lower()
        lowered_head = body[:256].lower()
        if lowered_head.startswith(b"\xef\xbb\xbf<!doctype html") or lowered_head.startswith(b"<!doctype html") or lowered_head.startswith(b"<html"):
            attempts.append({"status": "HTML", "url": resolved_url, "message": "下载链接返回 HTML，可能仍需人工处理"})
            continue
        if body[:4] == b"%PDF" or "application/pdf" in content_type:
            suffix = ".pdf"
        elif "caj" in content_type or final_url.lower().endswith(".caj") or resolved_url.lower().endswith(".caj"):
            suffix = ".caj"
        output_path = output_dir / f"{base_name}{suffix}"
        output_path.write_bytes(body)
        return {
            "status": "PASS",
            "preferred_type": item["preferred_type"],
            "saved_path": str(output_path),
            "final_url": resolved_url,
            "attempts": attempts,
        }
    return {
        "status": "NO_DOWNLOAD",
        "attempts": attempts,
    }


def _process_record(context: BrowserContext, page: Page, item: dict[str, Any], output_dir: Path, return_url: str) -> dict[str, Any]:
    """处理单条 CNKI 结果。"""

    detail_url = _normalize_text(item.get("href"))
    export_id = _normalize_text(item.get("exportId"))
    fallback_record = _search_item_to_record(item)
    fallback_bundle = _build_record_bundle(fallback_record)
    if not detail_url:
        return {
            "status": "METADATA_ONLY",
            "reason": "missing_detail_url",
            "search_item": item,
            **fallback_bundle,
        }

    try:
        try:
            _human_pause(page)
            page.goto(detail_url, wait_until="domcontentloaded")
            _human_pause(page)
            detail_result = page.evaluate(_build_paper_detail_script())
            export_result = page.evaluate(_build_export_script(), {"exportId": export_id})
            parsed_record = parse_cnkielearning(str((export_result or {}).get("ELEARNING") or ""))
            parsed_record["detail_url"] = detail_url
            parsed_record.setdefault("authors", list(item.get("authors") or []))
            if not parsed_record.get("title"):
                parsed_record["title"] = _normalize_text(item.get("title"))
            if not parsed_record.get("journal"):
                parsed_record["journal"] = _normalize_text(item.get("journal"))
            if not parsed_record.get("year"):
                parsed_record["year"] = _normalize_text(item.get("date"))[:4]

            base_name = slugify_filename(_build_bibtex_key(parsed_record))
            download_dir = output_dir / "downloads"
            download_dir.mkdir(parents=True, exist_ok=True)
            download_result = _download_fulltext(context, page, download_dir, base_name)

            return {
                "status": "PASS",
                "search_item": item,
                "detail": detail_result,
                "export": export_result,
                "record": parsed_record,
                "ris": build_ris_text(parsed_record),
                "bibtex": _record_to_bibtex(parsed_record),
                "download": download_result,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "METADATA_ONLY",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
                "search_item": item,
                **fallback_bundle,
            }
    finally:
        _human_pause(page)
        page.goto(return_url, wait_until="domcontentloaded")
        _human_pause(page, 1000)


def _write_outputs(records: list[dict[str, Any]], output_dir: Path) -> dict[str, str]:
    """写出 CNKI 元数据与下载 manifest。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_json = output_dir / "zh_cnki_metadata.json"
    metadata_csv = output_dir / "zh_cnki_metadata.csv"
    metadata_bib = output_dir / "zh_cnki_metadata.bib"
    download_json = output_dir / "zh_cnki_download_manifest.json"
    download_csv = output_dir / "zh_cnki_download_manifest.csv"

    metadata_payload = [item.get("record") for item in records if item.get("record")]
    metadata_json.write_text(json.dumps(metadata_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with metadata_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["title", "authors", "journal", "year", "keywords", "detail_url"],
        )
        writer.writeheader()
        for item in metadata_payload:
            writer.writerow(
                {
                    "title": item.get("title", ""),
                    "authors": "; ".join(item.get("authors") or []),
                    "journal": item.get("journal", ""),
                    "year": item.get("year", ""),
                    "keywords": "; ".join(item.get("keywords") or []),
                    "detail_url": item.get("detail_url", ""),
                }
            )

    metadata_bib.write_text("\n\n".join(item.get("bibtex", "") for item in records if item.get("bibtex")) + "\n", encoding="utf-8")

    manifest = []
    for item in records:
        download = dict(item.get("download") or {})
        record = dict(item.get("record") or {})
        manifest.append(
            {
                "status": download.get("status", item.get("status", "")),
                "title": record.get("title", _normalize_text((item.get("search_item") or {}).get("title"))),
                "journal": record.get("journal", ""),
                "year": record.get("year", ""),
                "saved_path": download.get("saved_path", ""),
                "final_url": download.get("final_url", ""),
                "detail_url": record.get("detail_url", _normalize_text((item.get("search_item") or {}).get("href"))),
                "preferred_type": download.get("preferred_type", ""),
            }
        )
    download_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with download_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["status", "title", "journal", "year", "preferred_type", "saved_path", "final_url", "detail_url"],
        )
        writer.writeheader()
        for item in manifest:
            writer.writerow(item)

    return {
        "metadata_json": str(metadata_json),
        "metadata_csv": str(metadata_csv),
        "metadata_bib": str(metadata_bib),
        "download_json": str(download_json),
        "download_csv": str(download_csv),
    }


def run_pipeline(config: dict[str, Any]) -> dict[str, Any]:
    """执行 CNKI 端到端调试流程。

    Args:
        config: 调试配置。

    Returns:
        结构化运行结果。
    """

    project_root = _resolve_project_root(config)
    output_dir = _resolve_repo_path(project_root, config.get("zh_output_dir"), "sandbox/online_retrieval_debug/outputs/zh_cnki")
    profile_dir = _resolve_repo_path(
        project_root,
        (config.get("cnki_browser_config") or {}).get("user_data_dir"),
        "sandbox/runtime/web_brower_profiles/cnki_debug",
    )
    port = int(config.get("cnki_cdp_port") or 9222)
    cdp_url = str(config.get("cnki_cdp_url") or f"http://127.0.0.1:{port}")
    entry_url = str(config.get("cnki_entry_url") or "https://kns.cnki.net/kns8s/search")
    browser_config = dict(config.get("cnki_browser_config") or {})
    skip_launch = bool(
        config.get("cnki_skip_launch", False)
        or browser_config.get("skip_launch", False)
        or browser_config.get("existing_browser_only", False)
        or browser_config.get("vscode_embedded_only", False)
    )
    keep_browser = bool(config.get("keep_browser_open", True))
    allow_manual = bool(config.get("allow_manual_intervention", True))
    bailian_api_key_file = str(
        _resolve_repo_path(project_root, config.get("bailian_api_key_file"), "configs/bailian-api-key.txt")
        if config.get("bailian_api_key_file")
        else ""
    )
    query = str(config.get("zh_query") or "").strip()
    max_pages = int(config.get("max_pages") or 1)

    output_dir.mkdir(parents=True, exist_ok=True)
    browser_proc: subprocess.Popen[str] | None = None
    playwright: Playwright | None = None
    context: BrowserContext | None = None
    manual_events: list[dict[str, Any]] = []
    page_summaries: list[dict[str, Any]] = []
    processed_records: list[dict[str, Any]] = []

    try:
        if not skip_launch:
            return {
                "status": "BLOCKED",
                "error_type": "BrowserPolicyViolation",
                "error": (
                    "当前策略禁止脚本自动启动第三方浏览器。"
                    "请改用已存在的受控会话，并设置 cnki_skip_launch=true 后重试。"
                ),
                "query": query,
                "record_count": 0,
                "download_count": 0,
                "manual_events": manual_events,
                "browser": {
                    "cdp_url": cdp_url,
                    "profile_dir": str(profile_dir),
                    "kept_open": keep_browser,
                    "launch_skipped": True,
                },
            }
        print(f"[CNKI] 连接 CDP: {cdp_url}")
        try:
            playwright, context = _connect_context_with_retry(cdp_url)
        except Exception as exc:
            if skip_launch:
                return {
                    "status": "BLOCKED",
                    "error_type": "BrowserAttachRequired",
                    "error": (
                        "当前配置为仅接管已有浏览器，但未连接到可用 CDP 会话。"
                        "请先在目标浏览器开启远程调试并提供 cnki_cdp_url/cnki_cdp_port。"
                    ),
                    "query": query,
                    "record_count": 0,
                    "download_count": 0,
                    "manual_events": manual_events,
                    "browser": {
                        "cdp_url": cdp_url,
                        "profile_dir": str(profile_dir),
                        "kept_open": keep_browser,
                        "launch_skipped": True,
                    },
                }
            raise exc
        page = _select_existing_page(context, preferred_url=entry_url)
        print(f"[CNKI] 已接管页面: {page.url}")
        page.set_default_timeout(int(browser_config.get("timeout_ms") or 15000))
        manual_events.extend(_wait_for_human_if_needed(page, bailian_api_key_file, allow_manual))

        if entry_url and entry_url not in page.url and not _is_result_page(page):
            print("[CNKI] 当前活动页不是目标知网页面，自动新开入口页继续执行。")
            page = context.new_page()
            page.set_default_timeout(int(browser_config.get("timeout_ms") or 15000))
            page.goto(entry_url, wait_until="domcontentloaded")
            _human_pause(page)
            manual_events.extend(_wait_for_human_if_needed(page, bailian_api_key_file, allow_manual))

        if _is_result_page(page):
            print("[CNKI] 当前已在结果页，直接从现有列表继续。")
        else:
            print(f"[CNKI] 提交检索词: {query}")
            _safe_evaluate(page, _build_submit_search_script(), {"query": query})
            _wait_for_result_page(page)
        manual_events.extend(_wait_for_human_if_needed(page, bailian_api_key_file, allow_manual))
        blocked_state = _detect_blocking_state(page)
        if blocked_state.get("reason") == "auth_client_invalid":
            output_paths = _write_outputs(processed_records, output_dir)
            return {
                "status": "BLOCKED",
                "query": query,
                "page_summaries": page_summaries,
                "records": processed_records,
                "record_count": 0,
                "download_count": 0,
                "manual_events": manual_events,
                "browser": {
                    "cdp_url": cdp_url,
                    "profile_dir": str(profile_dir),
                    "kept_open": keep_browser,
                },
                "output_paths": output_paths,
                "error_type": "AuthClientInvalid",
                "error": blocked_state.get("message", "无效的 Client ID"),
            }

        seen_urls: set[str] = set()
        for page_index in range(max_pages):
            parsed = _parse_current_page(page)
            print(
                f"[CNKI] 已解析第 {parsed.get('current_page')} / {parsed.get('total_pages')} 页，"
                f"当前页 {len(parsed.get('results') or [])} 条。"
            )
            page_summaries.append(parsed)
            result_page_url = str(parsed.get("url") or page.url)
            for item in list(parsed.get("results") or []):
                href = _normalize_text((item or {}).get("href"))
                database = _normalize_text((item or {}).get("database"))
                if "外文" in database:
                    print(f"[CNKI] 跳过外文条目: {_normalize_text((item or {}).get('title'))}")
                    continue
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)
                print(f"[CNKI] 处理详情: {_normalize_text((item or {}).get('title'))}")
                processed_records.append(_process_record(context, page, dict(item), output_dir, result_page_url))
            if page_index + 1 >= max_pages or not parsed.get("has_next"):
                break
            before_mark = f"{parsed.get('current_page', '')}/{parsed.get('total_pages', '')}"
            print(f"[CNKI] 准备翻页，当前页标记: {before_mark}")
            _human_pause(page)
            next_result = _safe_evaluate(page, _build_next_page_script(), {"beforePage": before_mark})
            if isinstance(next_result, dict) and next_result.get("error"):
                print(f"[CNKI] 翻页结束: {next_result.get('error')}")
                break
            _human_pause(page)
            manual_events.extend(_wait_for_human_if_needed(page, bailian_api_key_file, allow_manual))

        output_paths = _write_outputs(processed_records, output_dir)
        print(f"[CNKI] 产物已写出: {output_paths}")
        success_count = sum(1 for item in processed_records if item.get("record"))
        download_success_count = sum(1 for item in processed_records if (item.get("download") or {}).get("status") == "PASS")
        return {
            "status": "PASS" if success_count else "BLOCKED",
            "query": query,
            "page_summaries": page_summaries,
            "records": processed_records,
            "record_count": success_count,
            "download_count": download_success_count,
            "manual_events": manual_events,
            "browser": {
                "cdp_url": cdp_url,
                "profile_dir": str(profile_dir),
                "kept_open": keep_browser,
            },
            "output_paths": output_paths,
        }
    finally:
        if playwright is not None:
            playwright.stop()
        if browser_proc and not keep_browser:
            try:
                if browser_proc.poll() is None:
                    browser_proc.terminate()
                    time.sleep(1)
                    if browser_proc.poll() is None:
                        browser_proc.kill()
            except OSError:
                pass


def main() -> None:
    """读取顶层调试输入并执行中文链。"""

    script_dir = Path(__file__).resolve().parent
    config = json.loads((script_dir / "debug_inputs.json").read_text(encoding="utf-8"))
    result = run_pipeline(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()