"""CNKI 搜索结果页面自动化收藏脚本（基于 Playwright，针对 Edge）。

# #DEBUG 暂时还未调试，不可以直接投入运行。
# #HACK 警告： 危险！该程序会自动在你的 CNKI 账号里批量执行收藏操作！请务必先仔细阅读以下说明，理解脚本行为，并做好充分准备（例如先在测试账号或小范围内验证）。错误的使用可能导致大量不必要的收藏或者丢失有用数据、甚至账号问题。

目的
- 在 CNKI 搜索结果页上循环执行：全选 -> 收藏到专题 -> 翻页（按 ArrowRight），直到最后一页或遇到人工中断（例如验证码）。

重要说明（你需要手动执行的部分，以及脚本与人的交互）

1) 初始准备（在你运行脚本前请执行）
   - 在本地确保已安装 Playwright：

     ```powershell
     python -m pip install playwright
     python -m playwright install
     ```

   - 启动脚本后脚本会以一个独立的 Edge profile（位于脚本同目录的 `cnki_user_data`）打开一个 Edge 窗口。这个配置默认不会改动你系统 Edge 的默认 profile。但请注意：切勿把 `USER_DATA_DIR` 指向系统 Edge 的主 profile，避免覆盖/损坏已有收藏。

   - 在脚本打开的新 Edge 窗口中，请手动完成以下操作（仅需在最初页做一次）:
     1. 登录 CNKI（若尚未登录）；
     2. 在搜索结果页设置排序为“相关度”（你之前已设置，这里再次确认）；
     3. 设置每页显示 50 条；
     4. 选择并确认要收藏到的目标“专题”（脚本可尝试选择专题，但最好先在页面中手动选好以降低复杂性）。

   - 上述准备完成并确认页面处于搜索结果列表时，回到终端并按回车继续（脚本在此处会等待）。

2) 运行时的自动化与人工交互（脚本行为）
   - 每页的操作顺序：
     1) 点击“全选”；等待约 ACTION_DELAY（默认 1.5s）；
     2) 点击“收藏到专题”；等待约 ACTION_DELAY（默认 1.5s）；
     3) 模拟按下键盘 ArrowRight 翻页；按键后至少等待 PAGE_NAV_DELAY（默认 4.0s）；
     4) 重复直到到达最后一页或达到 `max_pages`。

   - 当脚本检测到疑似人机验证（验证码）时，会：
     1) 在终端打印提示并暂停执行，等待你在浏览器中完成验证（脚本不会自动跳过验证码）；
     2) 验证完成后，回到终端按回车，脚本会继续执行后续循环。

   - 验证检测策略包括但不限于：页面文本关键词（如“验证码”、“请验证”）、可见的模态对话（role=dialog）、可疑 iframe（autodokit/title 包含 captcha/geetest/verify）或常见类名（.captcha、.geetest 等）。检测到任一策略即触发暂停。

3) 如何在不影响现有收藏的前提下测试脚本（建议的安全步骤）
   - 推荐先做 Dry Run：临时注释掉脚本中真正执行收藏的行（`collect_to_topic(page, topic_name)`），只测试“全选”和翻页逻辑；确认行为正确后再恢复收藏操作。
   - 或者把 `max_pages` 设置为 1 或 2 来做小范围验证；确认正确后再放开。
   - 如果你希望脚本永远不改动你的真是收藏，可在脚本中添加或使用 `DRY_RUN=True` 变体（此脚本默认没有 DRY_RUN，但你可手动注释收藏调用）。

4) 在运行中遇到验证码时的建议操作流程（快速参考）
   1. 脚本在终端提示出现验证码并暂停；
   2. 切到 Edge 浏览器窗口，按要求完成滑块/图形/短信等验证；
   3. 验证通过且页面恢复正常后，回终端按回车让脚本继续循环；
   4. 若验证未能生效或页面仍提示验证，脚本会再次检测并继续等待（可重复按回车尝试或手动刷新页面）。

5) 取消/中断
   - 如需立即停止脚本，按终端中的 Ctrl+C。再次运行脚本会从起始 URL 重新开始（当前脚本不保存进度）。

6) 日志与调试
   - 脚本会把运行日志写入与脚本同目录下的 `cnki_auto_favorite.log`；遇到问题先查看日志。
   - 若需要更进一步调试（例如确认定位器），可以在脚本中临时加入 `page.pause()` 或 `page.screenshot()` 来辅助定位。

7) 其他说明
   - 本脚本采用多候选定位器策略（文本、role、常见 class/id），但网站前端随时可能变化，调试时可能需要根据页面 DOM 微调定位器。
   - 如果你希望我把 `DRY_RUN` 或进度保存功能加入脚本，请告诉我，我可以在不运行任何操作的前提下更新代码并交付给你。

使用示例（在 PowerShell 中）

```powershell
# 安装 Playwright（若尚未安装）
python -m pip install playwright
python -m playwright install

# 运行脚本（会打开一个新的 Edge 窗口）
python .\autodo-kit\affairs\自动化导入知网研学专题.py
```

模块其余部分实现自动化逻辑：定位器、验证码检测、点击重试与循环控制（见下文代码）。
"""

from __future__ import annotations

from pathlib import Path
import time
import logging
import json
from typing import Optional, Any, List
import os


# -------------------- 配置 --------------------
# 目标起始 URL（搜索结果页面，示例）
START_URL = "https://x.cnki.net/kns8/DefaultResult/Index?dbcode=CJFQ"
# 默认专题名称（可在运行时覆盖，若页面已手动选好专题，可不依赖此字段）
TOPIC_NAME: Optional[str] = None
# 操作间隔（秒）：点击类操作默认等待
ACTION_DELAY = 1.5
# 翻页后等待（秒）：按 ArrowRight 后至少等待
PAGE_NAV_DELAY = 4.0
# 单次查找元素超时（毫秒）
DEFAULT_TIMEOUT_MS = 10000
# 点击重试次数
CLICK_RETRIES = 3
# 最大处理页数，防止意外无限循环
MAX_PAGES = 500
# 日志输出文件（必须由外部提供绝对路径；本脚本不在内部推断路径）
_log_path_raw = os.environ.get("CNKI_LOG_PATH")
if not _log_path_raw:
    _log_path_raw = str((Path.cwd() / "cnki_auto_favorite.log").resolve())
LOG_PATH = Path(_log_path_raw).resolve()

# 用户数据目录用于持久化登录（必须由外部提供绝对路径）
_user_data_dir_raw = os.environ.get("CNKI_USER_DATA_DIR")
if not _user_data_dir_raw:
    _user_data_dir_raw = str((Path.cwd() / "cnki_user_data").resolve())
USER_DATA_DIR = Path(_user_data_dir_raw).resolve()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# -------------------- 工具函数 --------------------
def wait_for_user_login() -> None:
    """等待用户在浏览器里完成登录/验证码。

    Args:
        无

    Returns:
        None

    Examples:
        >>> wait_for_user_login()
    """
    print("请在打开的 Edge 浏览器中完成登录（若尚未登录）并在完成后回到终端按回车继续...")
    input()


def click_first_visible(page, locators, action_name: str) -> bool:
    """尝试按顺序点击第一个可见的定位器。

    Args:
        page: Playwright 页面对象
        locators: 可调用产生定位器的可迭代对象（每项为 page.locator / page.get_by_text 等）
        action_name: 动作名称，用于日志

    Returns:
        bool: 是否成功点击
    """
    for attempt in range(1, CLICK_RETRIES + 1):
        for locator in locators:
            try:
                loc = locator
                count = loc.count()
                if count == 0:
                    continue
                elem = loc.first
                if not elem.is_visible():
                    continue
                elem.click(timeout=DEFAULT_TIMEOUT_MS)
                logger.info(f"动作:{action_name} -> 点击成功")
                return True
            except Exception as exc:
                logger.debug(f"尝试点击 {action_name} 时发生异常（尝试 {attempt}）: {exc}")
                time.sleep(0.5 * attempt)
        # 重试间隔
        time.sleep(0.5 * attempt)
    logger.warning(f"未能完成动作：{action_name}")
    return False


def detect_human_verification(page) -> bool:
    """多策略检测页面上是否存在人机验证/验证码。

    检查策略：
    - 页面文本包含关键词（验证码、请验证、请完成验证、人机）
    - 可见的对话/模态框（role=dialog/alertdialog）包含关键词
    - 页面内存在 iframe，且 iframe.autodokit 或 title 包含 captcha/geetest/verify
    - 常见类名/id 包含 captcha/verify/geetest

    Args:
        page: Playwright 页面对象

    Returns:
        bool: 若检测到疑似验证码元素或弹窗则返回 True
    """
    try:
        page_text = page.inner_text("body", timeout=2000)
        small_text = page_text[:500]
        keywords = ["验证码", "请验证", "请完成验证", "人机", "滑动验证", "verify", "captcha", "geetest"]
        for kw in keywords:
            if kw in page_text:
                logger.info(f"检测到验证码关键词: {kw}")
                return True
    except Exception:
        # 忽略读取全文本可能失败的情况
        pass

    # 检查模态对话
    try:
        dialogs = page.locator("role=dialog, role=alertdialog")
        if dialogs.count() > 0:
            for i in range(dialogs.count()):
                d = dialogs.nth(i)
                try:
                    if d.is_visible() and any(kw in d.inner_text() for kw in ["验证码", "请验证", "滑动验证"]):
                        logger.info("检测到对话框型验证")
                        return True
                except Exception:
                    continue
    except Exception:
        pass

    # 检查 iframe
    try:
        iframes = page.query_selector_all("iframe")
        for ifr in iframes:
            try:
                autodokit = ifr.get_attribute("autodokit") or ""
                title = ifr.get_attribute("title") or ""
                attrs = (autodokit + " " + title).lower()
                if any(token in attrs for token in ["captcha", "geetest", "verify"]) and ifr.is_visible():
                    logger.info(f"检测到可疑 iframe：{autodokit}")
                    return True
            except Exception:
                continue
    except Exception:
        pass

    # 检查常见类名/选择器
    suspect_selectors = [".captcha", "#captcha", ".geetest", ".verify-box", ".verify"]
    for sel in suspect_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                logger.info(f"检测到可疑选择器：{sel}")
                return True
        except Exception:
            continue

    return False


# -------------------- 页面操作封装 --------------------
def select_all_on_page(page) -> bool:
    """在当前页面尝试执行「全选」动作。

    Args:
        page: Playwright 页面对象

    Returns:
        bool: 是否尝试点击成功（不保证后续是否有选中项）
    """
    locators = [
        page.get_by_role("checkbox", name="全选"),
        page.get_by_role("button", name="全选"),
        page.get_by_text("全选", exact=True),
        page.locator("text=全选"),
        page.locator("input[type=checkbox][name*=select]"),
        page.locator("thead input[type=checkbox]"),
    ]
    return click_first_visible(page, locators, "全选")


def collect_to_topic(page, topic_name: Optional[str] = None) -> bool:
    """点击「收藏到专题」，并尝试在弹窗中选择指定专题（若提供）。

    Args:
        page: Playwright 页面对象
        topic_name: 专题名称（可选）

    Returns:
        bool: 是否触发收藏动作（不保证最终收藏成功）
    """
    locators = [
        page.get_by_role("button", name="收藏到专题"),
        page.get_by_text("收藏到专题", exact=True),
        page.locator("text=收藏到专题"),
        page.locator("[data-action*=collect]"),
        page.locator(".collect-to-topic, .btn-collect, .favorite-btn"),
    ]
    ok = click_first_visible(page, locators, "收藏到专题")
    time.sleep(ACTION_DELAY)
    if not ok:
        return False

    # 如果提供了专题名，尝试在弹窗中选择
    if topic_name:
        try:
            # 弹窗内的专题项候选
            topic_locators = [
                page.get_by_text(topic_name, exact=True),
                page.locator(f"text={topic_name}"),
                page.locator(".topic-item", has_text=topic_name),
            ]
            clicked = click_first_visible(page, topic_locators, f"选择专题: {topic_name}")
            time.sleep(ACTION_DELAY)
            # 点击确定
            confirm_locators = [
                page.get_by_role("button", name="确定"),
                page.get_by_text("确定", exact=True),
                page.locator("text=确定"),
            ]
            click_first_visible(page, confirm_locators, "确定")
            return clicked
        except Exception as exc:
            logger.warning(f"在选择专题时发生异常: {exc}")
            return True
    return True


def press_right_arrow(page) -> bool:
    """模拟按下右箭头（ArrowRight）以触发下一页；如果按键不可用，则尝试点击“下一页”按钮。

    Args:
        page: Playwright 页面对象

    Returns:
        bool: 是否触发了翻页动作（不能百分百保证页面已加载）
    """
    try:
        # 优先通过键盘导航
        page.keyboard.press("ArrowRight")
        logger.info("发送按键 ArrowRight")
        return True
    except Exception:
        # 退回到点击下一页按钮
        next_locators = [
            page.get_by_role("button", name="下一页"),
            page.get_by_text("下一页", exact=True),
            page.locator(".page-next, .pagination .next, a.page-next"),
        ]
        return click_first_visible(page, next_locators, "下一页")


def is_next_disabled(page) -> bool:
    """判断分页器的下一页是否被禁用（用于提前结束循环）。

    Args:
        page: Playwright 页面对象

    Returns:
        bool: 如果当前已经没有下一页返回 True
    """
    try:
        # 常见 aria-disabled 或按钮不可用判断
        next_btn = page.locator("button[aria-label*=\"下一页\"], button[aria-label*=\"next\"], .page-next, .pagination .next").first
        if next_btn and next_btn.count() > 0:
            try:
                return not next_btn.is_enabled()
            except Exception:
                return False
    except Exception:
        pass
    return False


# -------------------- 主流程 --------------------

def main(start_url: str = START_URL, topic_name: Optional[str] = TOPIC_NAME, max_pages: int = MAX_PAGES) -> None:
    """运行主自动化循环：在页面上重复执行全选 -> 收藏 -> 翻页，遇到验证码暂停。

    Args:
        start_url: 起始搜索结果页 URL
        topic_name: 可选专题名称，若为空则假定用户已在页面选择好目标专题
        max_pages: 最大处理页数，防止无限循环

    Returns:
        None
    """
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except Exception as exc:
        raise RuntimeError("未安装 playwright，请先安装后再运行该事务") from exc

    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            channel="msedge",
        )
        page = browser.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        logger.info(f"打开起始页: {start_url}")
        page.goto(start_url, wait_until="domcontentloaded")

        # 等待用户登录或完成可能的初始验证
        print("如果尚未登录，请在打开的浏览器中登录 CNKI，登录完成后按回车继续...")
        input()

        page_index = 1
        while page_index <= max_pages:
            logger.info(f"开始处理第 {page_index} 页，URL={page.url}")

            # 检测验证码
            if detect_human_verification(page):
                print("检测到人机验证，请在浏览器中完成验证，完成后按回车继续脚本...")
                input()
                # 等待短暂时间以便页面稳定
                time.sleep(2)
                if detect_human_verification(page):
                    logger.warning("继续检测到验证码，建议手动确认已完成验证。")
                    input("如已完成验证，请按回车继续...")

            try:
                # 全选
                select_all_on_page(page)
                time.sleep(ACTION_DELAY)

                # 收藏
                collect_to_topic(page, topic_name)
                time.sleep(ACTION_DELAY)

                # 翻页
                pressed = press_right_arrow(page)
                # 按题主要求，按键后至少等待 4 秒
                time.sleep(PAGE_NAV_DELAY)

                # 检查是否确认为最后一页（若下一页按钮被禁用）
                if is_next_disabled(page):
                    logger.info("已检测到无下一页，流程结束。")
                    break

                # 若按键/点击未成功，尝试通过判断页面中是否存在“下一页”来决定是否继续
                if not pressed:
                    logger.warning("未能触发翻页动作，尝试再次点击下一页")
                    if not press_right_arrow(page):
                        logger.warning("再次尝试翻页失败，结束循环")
                        break

                page_index += 1

            except PlaywrightTimeoutError:
                logger.warning("页面响应超时，尝试继续下一页")
                time.sleep(PAGE_NAV_DELAY)
                continue
            except Exception as exc:
                logger.exception(f"在处理第 {page_index} 页时发生异常: {exc}")
                # 记录并继续
                time.sleep(PAGE_NAV_DELAY)
                page_index += 1
                continue

        logger.info("处理完成，关闭上下文")
        browser.close()


if __name__ == "__main__":
    main()


def execute(config_path: Path, workspace_root: Path | None = None, **_: Any) -> List[Path]:
    """事务标准执行入口。

    Args:
        config_path: 配置文件路径。
        workspace_root: 工作区根目录（兼容参数，当前不直接使用）。
        **_: 兼容额外关键字参数。

    Returns:
        产物文件路径列表（默认返回日志路径）。
    """

    _ = workspace_root
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))

    start_url = str(cfg.get("start_url") or START_URL)
    topic_name = cfg.get("topic_name")
    max_pages = int(cfg.get("max_pages") or MAX_PAGES)

    global LOG_PATH, USER_DATA_DIR
    raw_log_path = str(cfg.get("log_path") or LOG_PATH)
    raw_user_data_dir = str(cfg.get("user_data_dir") or USER_DATA_DIR)
    LOG_PATH = Path(raw_log_path).resolve()
    USER_DATA_DIR = Path(raw_user_data_dir).resolve()

    main(start_url=start_url, topic_name=topic_name, max_pages=max_pages)
    return [LOG_PATH]
