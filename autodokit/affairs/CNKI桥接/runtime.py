"""CNKI Playwright 真实执行器。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Error as PlaywrightError, Page, Playwright, sync_playwright

from .artifacts import (
    build_zotero_item,
    parse_cnkielearning,
    push_items_to_zotero,
    write_cnki_export_artifacts,
)


@dataclass(slots=True, frozen=True)
class CnkiBrowserConfig:
    """CNKI 浏览器执行配置。

    Args:
        user_data_dir: 持久化浏览器数据目录。
        headless: 是否无头模式。
        channel: 浏览器通道。
        executable_path: 浏览器可执行路径。
        timeout_ms: 页面超时时间。
        slow_mo_ms: 每步慢速执行毫秒数。
        cdp_url: 已启动浏览器的 CDP 地址。
    """

    user_data_dir: str
    headless: bool = False
    channel: str = "chrome"
    executable_path: str = ""
    timeout_ms: int = 15000
    slow_mo_ms: int = 0
    cdp_url: str = ""


class CnkiManualInterventionRequired(RuntimeError):
    """需要人工干预时抛出的异常。"""

    def __init__(self, reason: str, message: str):
        """初始化异常。

        Args:
            reason: 中断原因。
            message: 提示信息。
        """

        super().__init__(message)
        self.reason = reason
        self.message = message


class CnkiPlaywrightRuntime:
    """基于 Playwright 的 CNKI 真实执行器。"""

    def __init__(self, project_root: str | Path, config: CnkiBrowserConfig | None = None):
        """初始化执行器。

        Args:
            project_root: 项目根目录。
            config: 浏览器配置。
        """

        root = Path(project_root).resolve()
        default_dir = root / "sandbox" / "runtime" / "web_brower_profiles" / "cnki_main"
        self.project_root = root
        if config is None or not str(config.user_data_dir).strip():
            self.config = CnkiBrowserConfig(
                user_data_dir=str(default_dir),
                headless=False if config is None else config.headless,
                channel="chrome" if config is None else config.channel,
                executable_path="" if config is None else config.executable_path,
                timeout_ms=15000 if config is None else config.timeout_ms,
                slow_mo_ms=0 if config is None else config.slow_mo_ms,
                cdp_url="" if config is None else config.cdp_url,
            )
        else:
            self.config = config

    def search(self, query: str, page: int = 1, sort_by: str = "relevance") -> dict[str, Any]:
        """执行 CNKI 基础检索。

        Args:
            query: 检索关键词。
            page: 页码。
            sort_by: 排序方式。

        Returns:
            结构化检索结果。
        """

        def _worker(active_page: Page) -> dict[str, Any]:
            active_page.goto("https://kns.cnki.net/kns8s/search", wait_until="domcontentloaded")
            self._assert_not_verification_page(active_page)
            active_page.wait_for_selector("input.search-input", timeout=self.config.timeout_ms)
            result = active_page.evaluate(_build_search_script(), {"query": query})
            self._raise_if_manual(result)
            return {
                "query": query,
                "requested_page": page,
                "requested_sort_by": sort_by,
                "actual": result,
                "notes": [
                    "当前真实执行器已覆盖基础检索与结果抽取。",
                    "分页和排序的深度控制将在后续页面执行器增强时继续补强。",
                ],
            }

        return self._run(_worker)

    def paper_detail(self, detail_url: str) -> dict[str, Any]:
        """执行单篇详情抽取。

        Args:
            detail_url: 详情页 URL。

        Returns:
            结构化详情结果。
        """

        def _worker(active_page: Page) -> dict[str, Any]:
            active_page.goto(detail_url, wait_until="domcontentloaded")
            self._assert_not_verification_page(active_page)
            active_page.wait_for_timeout(1500)
            result = active_page.evaluate(_build_paper_detail_script())
            self._raise_if_manual(result)
            return result

        return self._run(_worker)

    def journal_index(self, journal_name: str, detail_url: str = "") -> dict[str, Any]:
        """执行期刊评价抽取。

        Args:
            journal_name: 期刊名称。
            detail_url: 详情页 URL。

        Returns:
            结构化期刊评价结果。
        """

        def _worker(active_page: Page) -> dict[str, Any]:
            if detail_url:
                active_page.goto(detail_url, wait_until="domcontentloaded")
                self._assert_not_verification_page(active_page)
            else:
                active_page.goto("https://navi.cnki.net/knavi", wait_until="domcontentloaded")
                self._assert_not_verification_page(active_page)
                active_page.wait_for_timeout(1500)
                active_page.fill("input.search-input, input#txt_search", journal_name)
                active_page.keyboard.press("Enter")
                active_page.wait_for_timeout(3000)
                href = active_page.evaluate(_build_first_journal_link_script())
                if not href:
                    raise RuntimeError(f"未找到期刊：{journal_name}")
                active_page.goto(href, wait_until="domcontentloaded")
            active_page.wait_for_timeout(2000)
            result = active_page.evaluate(_build_journal_index_script())
            self._raise_if_manual(result)
            return result

        return self._run(_worker)

    def journal_toc(self, journal_name: str, year: str, issue: str, detail_url: str = "") -> dict[str, Any]:
        """执行刊期目录抽取。

        Args:
            journal_name: 期刊名称。
            year: 年份。
            issue: 期号。
            detail_url: 详情页 URL。

        Returns:
            刊期目录结果。
        """

        def _worker(active_page: Page) -> dict[str, Any]:
            if detail_url:
                active_page.goto(detail_url, wait_until="domcontentloaded")
                self._assert_not_verification_page(active_page)
            else:
                index_result = self.journal_index(journal_name=journal_name)
                target_url = str(index_result.get("detail_url") or "")
                if not target_url:
                    raise RuntimeError(f"未获取到期刊详情页：{journal_name}")
                active_page.goto(target_url, wait_until="domcontentloaded")
            active_page.wait_for_timeout(2000)
            result = active_page.evaluate(_build_journal_toc_script(), {"year": year, "issue": issue})
            self._raise_if_manual(result)
            result["journal_name"] = journal_name
            return result

        return self._run(_worker)

    def export(
        self,
        detail_url: str,
        mode: str,
        export_id: str = "",
        push_to_zotero: bool = False,
        save_artifacts: bool = True,
    ) -> dict[str, Any]:
        """执行详情页导出。

        Args:
            detail_url: 详情页 URL。
            mode: 导出模式。
            export_id: 导出标识。
            push_to_zotero: 是否推送到 Zotero。
            save_artifacts: 是否写出本地产物。

        Returns:
            导出结果。
        """

        def _worker(active_page: Page) -> dict[str, Any]:
            active_page.goto(detail_url, wait_until="domcontentloaded")
            self._assert_not_verification_page(active_page)
            active_page.wait_for_timeout(1500)
            result = active_page.evaluate(_build_export_script(), {"exportId": export_id})
            self._raise_if_manual(result)
            elearning = str(result.get("ELEARNING") or "")
            record = parse_cnkielearning(elearning)
            record["detail_url"] = detail_url
            raw_payload = {
                "mode": mode,
                "detail_url": detail_url,
                "raw_export": result,
                "parsed_record": record,
            }
            artifacts = None
            if save_artifacts:
                artifacts = write_cnki_export_artifacts(
                    project_root=self.project_root,
                    export_record=record,
                    raw_export_payload=raw_payload,
                )
            zotero_result = {"status": "skipped", "message": "未请求 Zotero 推送"}
            if push_to_zotero or mode == "zotero":
                code, message = push_items_to_zotero([build_zotero_item(record)])
                zotero_result = {"status": code, "message": message}
            return {
                "mode": mode,
                "detail_url": detail_url,
                "export_record": record,
                "raw_export": result,
                "artifacts": artifacts.to_dict() if artifacts else {},
                "zotero_result": zotero_result,
            }

        return self._run(_worker)

    def _run(self, worker: Any) -> dict[str, Any]:
        """执行带浏览器上下文的工作函数。

        Args:
            worker: 工作函数。

        Returns:
            工作函数结果。
        """

        playwright, context, needs_close = self._open_context()
        try:
            page = self._select_page(context)
            page.set_default_timeout(self.config.timeout_ms)
            try:
                return worker(page)
            except CnkiManualInterventionRequired:
                raise
            except PlaywrightError as error:
                self._raise_if_playwright_blocked(page=page, error=error)
                raise
        finally:
            if needs_close:
                context.close()
            playwright.stop()

    def _open_context(self) -> tuple[Playwright, BrowserContext, bool]:
        """打开浏览器上下文。

        Returns:
            Playwright 实例、上下文与是否需要关闭标记。
        """

        playwright = sync_playwright().start()
        if self.config.cdp_url:
            browser = playwright.chromium.connect_over_cdp(self.config.cdp_url)
            if browser.contexts:
                return playwright, browser.contexts[0], False
            return playwright, browser.new_context(), False
        user_data_dir = Path(self.config.user_data_dir)
        user_data_dir.mkdir(parents=True, exist_ok=True)
        launch_attempts = self._build_launch_attempts()
        last_error = ""
        context: BrowserContext | None = None
        for attempt in launch_attempts:
            try:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(user_data_dir),
                    headless=self.config.headless,
                    channel=attempt.get("channel"),
                    executable_path=attempt.get("executable_path"),
                    slow_mo=self.config.slow_mo_ms,
                    accept_downloads=True,
                )
                break
            except Exception as error:  # noqa: BLE001
                last_error = str(error)
                continue
        if context is None:
            raise RuntimeError(
                "无法启动 CNKI 浏览器执行器。"
                f"已尝试的浏览器候选为: {json.dumps(launch_attempts, ensure_ascii=False)}。"
                f"最后错误: {last_error}"
            )
        return playwright, context, True

    def _build_launch_attempts(self) -> list[dict[str, str | None]]:
        """构造浏览器启动候选列表。

        Returns:
            启动候选列表。
        """

        attempts: list[dict[str, str | None]] = []
        if self.config.executable_path:
            attempts.append({"channel": None, "executable_path": self.config.executable_path})
        if self.config.channel:
            attempts.append({"channel": self.config.channel, "executable_path": None})
        edge_candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for candidate in edge_candidates:
            if Path(candidate).exists():
                attempts.append({"channel": None, "executable_path": candidate})
        attempts.append({"channel": None, "executable_path": None})
        unique_attempts: list[dict[str, str | None]] = []
        seen: set[tuple[str | None, str | None]] = set()
        for attempt in attempts:
            key = (attempt.get("channel"), attempt.get("executable_path"))
            if key in seen:
                continue
            seen.add(key)
            unique_attempts.append(attempt)
        return unique_attempts

    def _select_page(self, context: BrowserContext) -> Page:
        """选择活动页。

        Args:
            context: 浏览器上下文。

        Returns:
            页面对象。
        """

        if context.pages:
            return context.pages[0]
        return context.new_page()

    def _raise_if_manual(self, result: dict[str, Any]) -> None:
        """根据执行结果判断是否需要人工介入。

        Args:
            result: 脚本返回结果。

        Raises:
            CnkiManualInterventionRequired: 当需要人工处理时抛出。
        """

        if not isinstance(result, dict):
            return
        error = str(result.get("error") or "")
        if error == "captcha":
            raise CnkiManualInterventionRequired("captcha_required", "CNKI 当前显示滑块验证码，请人工完成验证后重试。")
        if error == "not_logged_in":
            raise CnkiManualInterventionRequired("login_required", "CNKI 当前未登录，无法继续执行该操作。")
        if error == "no_download":
            raise CnkiManualInterventionRequired("download_permission_required", "当前条目未提供可用下载链接。")

    def _assert_not_verification_page(self, page: Page) -> None:
        """检查是否进入安全验证页。

        Args:
            page: 页面对象。

        Raises:
            CnkiManualInterventionRequired: 当当前页面是安全验证页时抛出。
        """

        current_url = page.url
        current_title = page.title()
        if "verify/home" in current_url or "安全验证" in current_title:
            raise CnkiManualInterventionRequired(
                "captcha_required",
                "CNKI 当前跳转到安全验证页，请人工完成验证后重试。",
            )

    def _raise_if_playwright_blocked(self, page: Page, error: PlaywrightError) -> None:
        """将可识别的 Playwright 站点阻断转换为人工中断。

        Args:
            page: 页面对象。
            error: Playwright 异常。

        Raises:
            CnkiManualInterventionRequired: 当错误属于站点阻断时抛出。
        """

        current_url = self._safe_page_url(page)
        current_title = self._safe_page_title(page)
        message = str(error)
        if "verify/home" in current_url or "安全验证" in current_title:
            raise CnkiManualInterventionRequired(
                "captcha_required",
                "CNKI 当前跳转到安全验证页，请人工完成验证后重试。",
            )
        if "ERR_HTTP_RESPONSE_CODE_FAILURE" in message:
            raise CnkiManualInterventionRequired(
                "site_blocked",
                f"CNKI 当前返回 HTTP 错误页，无法继续访问：{current_url or '未知页面'}。",
            )
        if any(
            token in message
            for token in [
                "ERR_NAME_NOT_RESOLVED",
                "ERR_INTERNET_DISCONNECTED",
                "ERR_CONNECTION_TIMED_OUT",
                "ERR_CONNECTION_REFUSED",
                "ERR_CONNECTION_RESET",
            ]
        ):
            raise CnkiManualInterventionRequired(
                "site_unreachable",
                "CNKI 当前网络不可达，请检查网络、代理或校园网访问条件后重试。",
            )

    def _safe_page_url(self, page: Page) -> str:
        """安全读取页面 URL。

        Args:
            page: 页面对象。

        Returns:
            页面 URL；失败时返回空字符串。
        """

        try:
            return page.url
        except Exception:  # noqa: BLE001
            return ""

    def _safe_page_title(self, page: Page) -> str:
        """安全读取页面标题。

        Args:
            page: 页面对象。

        Returns:
            页面标题；失败时返回空字符串。
        """

        try:
            return page.title()
        except Exception:  # noqa: BLE001
            return ""


def _build_search_script() -> str:
    """构造基础检索脚本。

    Returns:
        JavaScript 源码。
    """

    return r"""
    async (params) => {
      const query = params.query;
      await new Promise((resolve, reject) => {
        let retry = 0;
        const check = () => {
          if (document.querySelector('input.search-input')) resolve();
          else if (retry++ > 30) reject(new Error('timeout'));
          else setTimeout(check, 500);
        };
        check();
      });
      const captcha = document.querySelector('#tcaptcha_transform_dy');
      if (captcha && captcha.getBoundingClientRect().top >= 0) return { error: 'captcha' };
      const input = document.querySelector('input.search-input');
      input.value = query;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      document.querySelector('input.search-btn')?.click();
      await new Promise((resolve, reject) => {
        let retry = 0;
        const check = () => {
          if (document.body.innerText.includes('条结果')) resolve();
          else if (retry++ > 50) reject(new Error('timeout'));
          else setTimeout(check, 500);
        };
        check();
      });
      const captcha2 = document.querySelector('#tcaptcha_transform_dy');
      if (captcha2 && captcha2.getBoundingClientRect().top >= 0) return { error: 'captcha' };
      const rows = document.querySelectorAll('.result-table-list tbody tr');
      const checkboxes = document.querySelectorAll('.result-table-list tbody input.cbItem');
      const results = Array.from(rows).map((row, index) => {
        const titleLink = row.querySelector('td.name a.fz14');
        const authors = Array.from(row.querySelectorAll('td.author a.KnowledgeNetLink') || []).map((item) => item.innerText?.trim()).filter(Boolean);
        return {
          n: index + 1,
          title: titleLink?.innerText?.trim() || '',
          href: titleLink?.href || '',
          exportId: checkboxes[index]?.value || '',
          authors,
          journal: row.querySelector('td.source a')?.innerText?.trim() || '',
          date: row.querySelector('td.date')?.innerText?.trim() || '',
          citations: row.querySelector('td.quote')?.innerText?.trim() || '',
          downloads: row.querySelector('td.download')?.innerText?.trim() || '',
        };
      });
      return {
        query,
        total: document.querySelector('.pagerTitleCell')?.innerText?.match(/([\d,]+)/)?.[1] || '0',
        page: document.querySelector('.countPageMark')?.innerText || '1/1',
        results,
        url: location.href,
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


def _build_first_journal_link_script() -> str:
    """构造第一条期刊链接抽取脚本。"""

    return r"""
    () => {
      const link = document.querySelector('a[href*="knavi/detail"]');
      return link?.href || '';
    }
    """


def _build_journal_index_script() -> str:
    """构造期刊评价抽取脚本。"""

    return r"""
    () => {
      const body = document.body.innerText;
      const titleText = document.querySelector('h3.titbox, h3.titbox1')?.innerText?.trim() || '';
      const parts = titleText.split('\n').map((item) => item.trim()).filter(Boolean);
      const knownTags = ['北大核心','CSSCI','CSCD','SCI','EI','CAS','JST','WJCI','AMI','Scopus','卓越期刊','网络首发'];
      return {
        journal_name_cn: parts[0] || '',
        journal_name_en: parts[1] || '',
        issn: body.match(/ISSN[：:]\s*(\S+)/)?.[1] || '',
        cn_number: body.match(/CN[：:]\s*(\S+)/)?.[1] || '',
        sponsor: body.match(/主办单位[：:]\s*(.+?)(?=\n)/)?.[1] || '',
        frequency: body.match(/出版周期[：:]\s*(\S+)/)?.[1] || '',
        indexed_in: knownTags.filter((tag) => body.includes(tag)),
        impact_composite: body.match(/复合影响因子[：:]\s*([\d.]+)/)?.[1] || '',
        impact_comprehensive: body.match(/综合影响因子[：:]\s*([\d.]+)/)?.[1] || '',
        detail_url: location.href,
        toc_url: location.href,
      };
    }
    """


def _build_journal_toc_script() -> str:
    """构造刊期目录抽取脚本。"""

    return r"""
    async (params) => {
      const captcha = document.querySelector('#tcaptcha_transform_dy');
      if (captcha && captcha.getBoundingClientRect().top >= 0) return { error: 'captcha' };
      const dls = document.querySelectorAll('#yearissue0 dl.s-dataList');
      let target = null;
      for (const dl of dls) {
        if (dl.querySelector('dt')?.innerText?.trim() === params.year) {
          target = Array.from(dl.querySelectorAll('dd a')).find((item) => item.innerText.trim() === params.issue || item.innerText.trim() === `No.${params.issue}`);
          break;
        }
      }
      if (!target) {
        return { error: 'issue_not_found', available_years: Array.from(dls).map((item) => item.querySelector('dt')?.innerText?.trim()).filter(Boolean) };
      }
      target.click();
      await new Promise((resolve, reject) => {
        let retry = 0;
        const check = () => {
          if (document.querySelectorAll('#CataLogContent dd.row').length > 0) resolve();
          else if (retry++ > 30) reject(new Error('timeout'));
          else setTimeout(check, 500);
        };
        setTimeout(check, 1000);
      });
      const rows = document.querySelectorAll('#CataLogContent dd.row');
      const papers = Array.from(rows).map((row, index) => ({
        no: index + 1,
        title: row.querySelector('span.name a')?.innerText?.trim() || '',
        authors: (row.querySelector('span.author')?.innerText?.trim() || '').replace(/;$/, '').split(';').map((item) => item.trim()).filter(Boolean),
        pages: row.querySelector('span.company')?.innerText?.trim() || '',
        detail_url: row.querySelector('span.name a')?.href || '',
      }));
      return {
        issue_label: document.querySelector('span.date-list')?.innerText?.trim() || '',
        toc_url: location.href,
        original_pdf_url: document.querySelector('a.btn-preview:not(.btn-back)')?.href || '',
        paper_count: papers.length,
        articles: papers,
      };
    }
    """
