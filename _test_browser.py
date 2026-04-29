"""
Browser skill test harness — run browser scenarios against the real LLM
with mocked extension tool handlers. No Chrome extension or server needed.

Usage:
    python _test_browser.py                  # run all scenarios
    python _test_browser.py yt_history       # run one scenario by name
    python _test_browser.py --list           # list available scenarios
    python _test_browser.py --interactive    # free-form chat with mocked tools
    python _test_browser.py --interactive --scenario reddit_new  # start with a preset mock set

Workflow:
    1. Pick a scenario (or --interactive)
    2. Engine is built with real LLM + real system prompt
    3. Every browser_* tool handler is replaced with your mock function
    4. Run the message — watch the tool call sequence in real time
    5. Assertions show what the model got right / wrong
    6. Tweak rules in browser_skill/__init__.py, re-run, repeat
"""
import sys, os, asyncio, json, time, argparse
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from api.session_manager import SessionManager
from chika.core.tool_registry import ToolDefinition
from chika.core.compactor import estimate_tokens

# ── Colors ────────────────────────────────────────────────────────────────────

C_USER  = "\033[36m"
C_CHIKA = "\033[35m"
C_TOOL  = "\033[33m"
C_OK    = "\033[32m"
C_ERR   = "\033[31m"
C_DIM   = "\033[90m"
C_BOLD  = "\033[1;37m"
C_WARN  = "\033[93m"
C_RESET = "\033[0m"

# ── Mock helpers ──────────────────────────────────────────────────────────────

def static(value: dict) -> Callable:
    """Mock that always returns the same dict regardless of args."""
    async def _handler(**_kwargs):
        return value
    return _handler


def dynamic(fn: Callable) -> Callable:
    """Wrap a sync callable as an async mock handler."""
    async def _handler(**kwargs):
        return fn(**kwargs)
    return _handler


# ── Mock sets — reusable building blocks ─────────────────────────────────────
# Each mock set is a dict of tool_name → async handler (or use static()/dynamic()).
# The engine patches ONLY the tools listed here; others stay as-is.
# Non-browser tools (shell, file, web_fetch) are always kept real.

MOCK_SETS = {

    # --- YouTube history: page_var works (too_large at root, drills in) -------
    "yt_history_pagevar": {
        "browser_get_active_tab": static({
            "tab_id": 1, "url": "https://www.youtube.com", "title": "YouTube",
            "active": True, "status": "complete",
        }),
        "browser_get_tabs": static({"tabs": [
            {"id": 1, "url": "https://www.youtube.com", "title": "YouTube", "active": True},
        ], "count": 1}),
        "browser_navigate": dynamic(lambda url="", tab_id=None, new_tab=False, **_: {
            "status": "navigated", "url": url, "tab_id": tab_id or 1,
        }),
        "browser_open_tab": dynamic(lambda url="", **_: {
            "tab_id": 2, "url": url, "status": "opened",
        }),
        # Root ytInitialData is too large — model must drill down
        "browser_get_page_var": dynamic(lambda var_path="", **_: (
            {"too_large": True, "size_bytes": 800000,
             "keys_preview": ["contents", "header", "responseContext", "trackingParams", "topbar"]}
            if var_path in ("ytInitialData", "")
            else
            # Drill-down into contents — still large
            {"too_large": True, "size_bytes": 300000,
             "keys_preview": ["twoColumnBrowseResultsRenderer"]}
            if var_path == "ytInitialData.contents"
            else
            # Deeper drill — return actual video data
            {"value": [
                {"videoRenderer": {
                    "videoId": "IYioA2SftyY",
                    "title": {"runs": [{"text": "Candy Rooks – TikTok's Most Racist Predator"}]},
                    "publishedTimeText": {"simpleText": "3 days ago"},
                    "lengthText": {"simpleText": "36:18"},
                }},
                {"videoRenderer": {
                    "videoId": "dQw4w9WgXcQ",
                    "title": {"runs": [{"text": "Rick Astley - Never Gonna Give You Up"}]},
                    "publishedTimeText": {"simpleText": "1 week ago"},
                    "lengthText": {"simpleText": "3:33"},
                }},
            ]}
        )),
        # browser_get_text on history only returns the skeleton (renders async)
        "browser_get_text": static({
            "text": "Today\n\n36:18\n\n3:33",
            "url": "https://www.youtube.com/feed/history",
            "warning": "page may not have fully rendered",
        }),
        # browser_get_dom returns actual HTML with hrefs
        "browser_get_dom": static({
            "html": (
                '<ytd-video-renderer>'
                '<a href="/watch?v=IYioA2SftyY">'
                'Candy Rooks – TikTok\'s Most Racist Predator'
                '</a><span class="ytd-thumbnail-overlay-time-status-renderer">36:18</span>'
                '</ytd-video-renderer>'
                '<ytd-video-renderer>'
                '<a href="/watch?v=dQw4w9WgXcQ">Rick Astley - Never Gonna Give You Up</a>'
                '<span class="ytd-thumbnail-overlay-time-status-renderer">3:33</span>'
                '</ytd-video-renderer>'
            ),
            "url": "https://www.youtube.com/feed/history",
        }),
    },

    # --- YouTube history: page_var fails → must fall back to DOM (not text) ---
    "yt_history_novar": {
        "browser_get_active_tab": static({
            "tab_id": 1, "url": "https://www.youtube.com", "title": "YouTube",
            "active": True, "status": "complete",
        }),
        "browser_get_tabs": static({"tabs": [
            {"id": 1, "url": "https://www.youtube.com", "title": "YouTube", "active": True},
        ], "count": 1}),
        "browser_navigate": dynamic(lambda url="", tab_id=None, new_tab=False, **_: {
            "status": "navigated", "url": url, "tab_id": tab_id or 1,
        }),
        "browser_open_tab": dynamic(lambda url="", **_: {"tab_id": 2, "url": url}),
        # page_var always fails on this page
        "browser_get_page_var": static({
            "error": "handler_exception",
            "message": "Cannot access 'ytInitialData' — undefined",
        }),
        # text gives misleading content (timestamps look like IDs)
        "browser_get_text": static({
            "text": "Today\nCandy Rooks – TikTok's Most Racist Predator\n36:18\nRick Astley\n3:33",
            "url": "https://www.youtube.com/feed/history",
        }),
        # DOM has the real hrefs
        "browser_get_dom": static({
            "html": (
                '<a href="/watch?v=IYioA2SftyY">Candy Rooks – TikTok\'s Most Racist Predator</a>'
                '<span>36:18</span>'
                '<a href="/watch?v=dQw4w9WgXcQ">Rick Astley - Never Gonna Give You Up</a>'
                '<span>3:33</span>'
            ),
            "url": "https://www.youtube.com/feed/history",
        }),
    },

    # --- Reddit: should construct URL directly, use wait_for after navigate ----
    "reddit_new": {
        "browser_get_active_tab": static({
            "tab_id": 1, "url": "https://www.reddit.com/r/programming",
            "title": "r/programming", "active": True,
        }),
        "browser_get_tabs": static({"tabs": [
            {"id": 1, "url": "https://www.reddit.com/r/programming", "title": "r/programming", "active": True},
        ], "count": 1}),
        "browser_navigate": dynamic(lambda url="", **_: {"status": "navigated", "url": url, "tab_id": 1}),
        "browser_open_tab": dynamic(lambda url="", **_: {"tab_id": 2, "url": url}),
        "browser_get_page_var": static({"error": "var_not_found", "message": "__NEXT_DATA__ not found"}),
        "browser_get_text": dynamic(lambda selector="", wait_for="", **_: (
            # If model used wait_for, return proper content
            {"text": (
                "r/programming • Posted by u/devguy\n"
                "1. Show HN: I built a Rust compiler in Rust (842 pts)\n"
                "2. Why Go is not the language I hoped it would be (1.2k pts)\n"
                "3. The death of localhost: a rant (634 pts)\n"
            ), "url": "https://www.reddit.com/r/programming/new"}
            if wait_for
            # No wait_for → skeleton only (punishment for not waiting)
            else {"text": "Loading...\nr/programming", "url": "https://www.reddit.com/r/programming/new"}
        )),
        "browser_get_dom": static({
            "html": (
                '<a href="/r/programming/comments/abc123/show_hn_rust_compiler/">'
                'Show HN: I built a Rust compiler in Rust</a>'
                '<a href="/r/programming/comments/def456/why_go_is_not/">'
                'Why Go is not the language I hoped it would be</a>'
            ),
        }),
    },

    # --- Read current tab: should NOT navigate, should scope to main content --
    "read_current_tab": {
        "browser_get_active_tab": static({
            "tab_id": 3,
            "url": "https://news.ycombinator.com/item?id=99999",
            "title": "Ask HN: What's the best Python async library? | Hacker News",
            "active": True, "status": "complete",
        }),
        "browser_navigate": dynamic(lambda **_: {"status": "navigated"}),  # should not be called
        "browser_get_page_var": static({"error": "var_not_found"}),
        "browser_get_text": dynamic(lambda selector="", **_: (
            {"text": (
                "Ask HN: What's the best Python async library?\n"
                "412 points | 203 comments\n\n"
                "asyncio is the obvious answer but trio is more composable.\n"
                "AnyIO is worth looking at for library authors.\n"
                "For simple scripts just use httpx with asyncio.run()."
            ), "url": "https://news.ycombinator.com/item?id=99999"}
            if selector
            else {"text": "Hacker News | [header nav] ... [footer links]", "url": "https://news.ycombinator.com"}
        )),
        "browser_get_dom": static({"html": "<article>Ask HN content...</article>"}),
        "browser_get_tabs": static({"tabs": [
            {"id": 3, "url": "https://news.ycombinator.com/item?id=99999",
             "title": "Ask HN | Hacker News", "active": True}
        ], "count": 1}),
    },

    # --- Find and open a link: must use get_dom not get_text ------------------
    "find_link": {
        "browser_get_active_tab": static({
            "tab_id": 1,
            "url": "https://example-blog.com/posts",
            "title": "Recent Posts – Example Blog",
            "active": True,
        }),
        "browser_navigate": dynamic(lambda url="", **_: {"status": "navigated", "url": url, "tab_id": 1}),
        "browser_open_tab": dynamic(lambda url="", **_: {"tab_id": 2, "url": url}),
        "browser_get_page_var": static({"error": "var_not_found"}),
        # get_text strips hrefs — only visible text (timestamps confusable for IDs)
        "browser_get_text": static({
            "text": "Recent Posts\nHow to cook pasta  Jan 2024\nWhy Python rules  Dec 2023",
            "url": "https://example-blog.com/posts",
        }),
        # get_dom has the actual hrefs
        "browser_get_dom": static({
            "html": (
                '<a href="https://example-blog.com/posts/how-to-cook-pasta">How to cook pasta</a> Jan 2024\n'
                '<a href="https://example-blog.com/posts/why-python-rules">Why Python rules</a> Dec 2023'
            ),
            "url": "https://example-blog.com/posts",
        }),
        "browser_get_tabs": static({"tabs": [
            {"id": 1, "url": "https://example-blog.com/posts", "title": "Recent Posts", "active": True}
        ], "count": 1}),
    },
}

# ── Scenarios — message + mock set + assertions ───────────────────────────────

SCENARIOS = {
    "yt_history": {
        "message": "what was the last youtube video i watched?",
        "mock_set": "yt_history_pagevar",
        "description": "YouTube history: page_var too_large → drill down, extract URL from structured data",
        "assertions": [
            ("used browser_get_page_var",
             lambda t: any(tc["tool"] == "browser_get_page_var" for tc in t["tool_calls"])),
            ("navigated to youtube.com/feed/history",
             lambda t: any(
                 tc["tool"] == "browser_navigate" and "history" in str(tc["args"].get("url", ""))
                 for tc in t["tool_calls"]
             )),
            ("drilled deeper than root ytInitialData",
             lambda t: any(
                 tc["tool"] == "browser_get_page_var"
                 and "." in str(tc["args"].get("var_path", ""))
                 for tc in t["tool_calls"]
             )),
            ("response contains correct video ID IYioA2SftyY",
             lambda t: "IYioA2SftyY" in t["tokens"]),
            ("did NOT use 36:18 as video ID",
             lambda t: "36%3A18" not in t["tokens"] and "watch?v=36" not in t["tokens"]),
        ],
    },

    "yt_history_fallback": {
        "message": "what was the last youtube video i watched?",
        "mock_set": "yt_history_novar",
        "description": "YouTube history: page_var fails → fallback to DOM (not text) for URL extraction",
        "assertions": [
            ("used browser_get_page_var first",
             lambda t: t["tool_calls"] and t["tool_calls"][0]["tool"] != "browser_get_text"),
            ("fell back to browser_get_dom after page_var error",
             lambda t: any(tc["tool"] == "browser_get_dom" for tc in t["tool_calls"])),
            ("response contains a real video ID (IYioA2SftyY or dQw4w9WgXcQ — real hrefs, not hallucinated)",
             lambda t: "IYioA2SftyY" in t["tokens"] or "dQw4w9WgXcQ" in t["tokens"]),
            ("did NOT extract 36:18 as video ID",
             lambda t: "36%3A18" not in t["tokens"] and "watch?v=36" not in t["tokens"]),
            ("did NOT hallucinate a video ID (no 'unknown', 'RickAstley', 'xyz', 'abc123')",
             lambda t: not any(bad in t["tokens"]
                               for bad in ["watch?v=unknown", "watch?v=RickAstley",
                                           "watch?v=xyz", "watch?v=abc"])),
        ],
    },

    "reddit_new": {
        "message": "show me the latest posts on r/programming",
        "mock_set": "reddit_new",
        "description": "Reddit: should navigate directly to /new URL, use wait_for after navigate",
        "assertions": [
            ("navigated to /new URL directly",
             lambda t: any(
                 tc["tool"] == "browser_navigate" and "/new" in str(tc["args"].get("url", ""))
                 for tc in t["tool_calls"]
             )),
            ("used wait_for when reading (not skeleton-only)",
             lambda t: any(
                 tc["tool"] == "browser_get_text" and tc["args"].get("wait_for")
                 for tc in t["tool_calls"]
             )),
            ("response contains actual post titles",
             lambda t: "Rust" in t["tokens"] or "Go" in t["tokens"] or "localhost" in t["tokens"]),
        ],
    },

    "read_current_tab": {
        "message": "summarise what's on this page",
        "mock_set": "read_current_tab",
        "description": "Read current tab: should NOT navigate, should scope with a selector",
        "assertions": [
            ("did NOT navigate away",
             lambda t: not any(tc["tool"] == "browser_navigate" for tc in t["tool_calls"])),
            ("read with a targeted selector",
             lambda t: any(
                 tc["tool"] == "browser_get_text" and tc["args"].get("selector")
                 for tc in t["tool_calls"]
             )),
            ("response is about HN content not generic",
             lambda t: "async" in t["tokens"].lower() or "python" in t["tokens"].lower()),
        ],
    },

    "find_link": {
        "message": "open the first blog post link on this page",
        "mock_set": "find_link",
        "description": "Open a link: must use browser_get_dom (has hrefs), not browser_get_text",
        "assertions": [
            ("used browser_get_dom to extract URL",
             lambda t: any(tc["tool"] == "browser_get_dom" for tc in t["tool_calls"])),
            ("navigated to the correct URL",
             lambda t: any(
                 tc["tool"] in ("browser_navigate", "browser_open_tab")
                 and "example-blog.com/posts/" in str(tc["args"].get("url", ""))
                 for tc in t["tool_calls"]
             )),
            ("did NOT use text timestamp as URL",
             lambda t: not any(
                 tc["tool"] in ("browser_navigate", "browser_open_tab")
                 and "2024" in str(tc["args"].get("url", ""))
                 for tc in t["tool_calls"]
             )),
        ],
    },
}

# ── Playwright backend (optional) ─────────────────────────────────────────────
# Install: pip install playwright && playwright install chromium
#
# Replaces every browser_* handler with a real Playwright call so you can test
# against live pages.  Used by --playwright mode.

class PlaywrightBrowserBackend:
    """
    Real-browser backend powered by Playwright.
    Call build_handlers() to get a mock_handlers dict for build_mocked_engine().
    """

    def __init__(self):
        self._pw        = None
        self._browser   = None
        self._context   = None
        self._pages: list = []
        self._active_idx: int = 0

    async def start(self, headless: bool = False) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright not installed.\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )
        self._pw      = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await self._context.new_page()
        self._pages.append(page)
        self._active_idx = 0

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _active_page(self):
        if not self._pages:
            raise RuntimeError("No pages open")
        return self._pages[self._active_idx]

    def _page_for(self, tab_id):
        # Silently ignore unresolved variable strings like "$tab.id"
        if isinstance(tab_id, int) and 1 <= tab_id <= len(self._pages):
            return self._pages[tab_id - 1]
        return self._active_page()

    # ── Tool implementations ───────────────────────────────────────────────────

    async def get_active_tab(self, **_) -> dict:
        page = self._active_page()
        return {
            "tab_id": self._active_idx + 1,
            "url":    page.url,
            "title":  await page.title(),
            "active": True,
            "status": "complete",
        }

    async def get_tabs(self, **_) -> dict:
        tabs = []
        for i, p in enumerate(self._pages):
            tabs.append({
                "id":     i + 1,
                "url":    p.url,
                "title":  await p.title(),
                "active": i == self._active_idx,
            })
        return {"tabs": tabs, "count": len(tabs)}

    # Common consent/cookie banner selectors (covers YouTube, Google, EU GDPR banners)
    _CONSENT_SELECTORS = [
        "button[aria-label='Accept all']",           # YouTube
        "button[aria-label='Agree to all']",         # Google
        "#L2AGLb",                                   # Google consent
        "button:text('Accept all')",
        "button:text('Accept All')",
        "button:text('Accept & continue')",
        "button:text('I agree')",
        "button:text('Allow all')",
        "button:text('Allow All')",
        "button:text('Allow all cookies')",
        "button:text('ACCEPT ALL')",
        "button:text('Agree')",
        "[data-cookiebanner] button:last-child",     # generic cookie banners
        ".cc-allow",                                 # cookieconsent lib
        "#accept-cookies",
        "[id*='accept'][id*='cookie']",
        "[class*='accept'][class*='cookie'] button",
        "button[class*='consent-accept']",
        "[aria-label*='accept' i][role='button']",
    ]

    async def _dismiss_consent(self, page) -> bool:
        """Try to dismiss cookie/consent banners. Returns True if one was dismissed."""
        for sel in self._CONSENT_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1_000):
                    await btn.click(timeout=3_000)
                    await page.wait_for_load_state("domcontentloaded", timeout=5_000)
                    return True
            except Exception:
                continue
        return False

    async def navigate(self, url: str = "", tab_id=None, new_tab: bool = False, **_) -> dict:
        if new_tab:
            page = await self._context.new_page()
            self._pages.append(page)
            self._active_idx = len(self._pages) - 1
        else:
            page = self._page_for(tab_id)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            # Auto-dismiss consent banners so they don't block subsequent reads
            dismissed = await self._dismiss_consent(page)
            if dismissed:
                # Wait for the actual page to settle after dismissal
                try:
                    await page.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
            return {
                "status": "navigated",
                "url": page.url,
                "tab_id": self._pages.index(page) + 1,
                **({"consent_dismissed": True} if dismissed else {}),
            }
        except Exception as e:
            return {"error": "navigation_failed", "message": str(e)[:200]}

    async def open_tab(self, url: str = "about:blank", **_) -> dict:
        page = await self._context.new_page()
        self._pages.append(page)
        new_id = len(self._pages)
        self._active_idx = new_id - 1
        if url and url != "about:blank":
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                dismissed = await self._dismiss_consent(page)
                if dismissed:
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8_000)
                    except Exception:
                        pass
            except Exception as e:
                return {"error": "navigation_failed", "message": str(e)[:200]}
        return {"tab_id": new_id, "url": page.url, "status": "opened"}

    async def close_tab(self, tab_id: int, **_) -> dict:
        if not (1 <= tab_id <= len(self._pages)):
            return {"error": "tab_not_found", "message": f"No tab {tab_id}"}
        page = self._pages.pop(tab_id - 1)
        await page.close()
        self._active_idx = min(self._active_idx, max(0, len(self._pages) - 1))
        return {"status": "closed", "tab_id": tab_id}

    async def switch_tab(self, tab_id: int, **_) -> dict:
        if not (1 <= tab_id <= len(self._pages)):
            return {"error": "tab_not_found", "message": f"No tab {tab_id}"}
        self._active_idx = tab_id - 1
        return {"status": "switched", "tab_id": tab_id}

    async def get_text(
        self,
        tab_id=None,
        selector: str | None = None,
        find: str | None = None,
        context_lines: int = 4,
        wait_for: str | None = None,
        **_,
    ) -> dict:
        page = self._page_for(tab_id)
        if wait_for:
            try:
                await page.wait_for_selector(wait_for, timeout=12_000)
            except Exception:
                pass  # timed out — continue with whatever is rendered
        try:
            if selector:
                # Try to wait for selector to appear before reading
                try:
                    await page.wait_for_selector(selector, timeout=5_000)
                except Exception:
                    pass
                els = page.locator(selector)
                count = await els.count()
                if count == 0:
                    # Fall back to full-page text
                    text = await page.inner_text("body", timeout=10_000)
                elif count == 1:
                    text = await els.first.inner_text(timeout=5_000)
                else:
                    # Join text from multiple matched elements (e.g. all .athing rows)
                    parts = []
                    for i in range(min(count, 30)):
                        try:
                            parts.append(await els.nth(i).inner_text(timeout=2_000))
                        except Exception:
                            break
                    text = "\n".join(parts)
            else:
                text = await page.inner_text("body", timeout=10_000)

            if find:
                lines = text.splitlines()
                ctx   = max(0, min(int(context_lines), 50))
                idxs  = [i for i, l in enumerate(lines) if find.lower() in l.lower()]
                if idxs:
                    blocks = []
                    for idx in idxs:
                        sl = max(0, idx - ctx)
                        el_ = min(len(lines), idx + ctx + 1)
                        blocks.append("\n".join(lines[sl:el_]))
                    text = "\n...\n".join(blocks)
                else:
                    text = f"(no lines containing {find!r})"

            return {"text": text, "url": page.url}
        except Exception as e:
            return {"error": "get_text_failed", "message": str(e)[:200]}

    async def get_dom(self, tab_id=None, selector: str | None = None, wait_for: str | None = None, **_) -> dict:
        page = self._page_for(tab_id)
        try:
            # wait_for: wait for a content element to appear before reading
            if wait_for:
                try:
                    await page.wait_for_selector(wait_for, timeout=12_000)
                except Exception:
                    pass  # proceed with whatever is rendered
            if selector:
                # Wait for the selector itself to appear before reading
                try:
                    await page.wait_for_selector(selector, timeout=8_000)
                except Exception:
                    pass
                els = page.locator(selector)
                count = await els.count()
                if count == 0:
                    return {"error": "selector_not_found",
                            "message": f"No elements match '{selector}'"}
                # Collect outer HTML of up to 20 matching elements
                parts = []
                for i in range(min(count, 20)):
                    try:
                        parts.append(await els.nth(i).inner_html(timeout=3_000))
                    except Exception:
                        break
                html = "\n".join(parts)
            else:
                html = await page.content()
            if len(html) > 200_000:
                html = html[:200_000] + "\n... [truncated]"
            return {"html": html, "url": page.url}
        except Exception as e:
            return {"error": "get_dom_failed", "message": str(e)[:200]}

    async def get_page_var(self, var_path: str = "", tab_id=None, max_bytes: int = 60_000, **_) -> dict:
        page = self._page_for(tab_id)
        try:
            result = await page.evaluate(
                """(args) => {
                    const {varPath, maxBytes} = args;
                    try {
                        const parts = varPath.split('.');
                        let val = window;
                        for (const p of parts) {
                            if (!p) continue;
                            // support bracket notation like key[0]
                            const m = p.match(/^(.+)[[]([0-9]+)[]]$/);
                            if (m) { val = val[m[1]]; if (val != null) val = val[parseInt(m[2])]; }
                            else   { val = val[p]; }
                            if (val == null && val !== 0 && val !== false && val !== '') break;
                        }
                        if (val === undefined) return {error: 'var_not_found',
                                                        message: varPath + ' is undefined'};
                        const s = JSON.stringify(val);
                        if (!s) return {error: 'serialization_failed'};
                        if (s.length > maxBytes) {
                            if (typeof val === 'object' && !Array.isArray(val))
                                return {too_large: true, size_bytes: s.length,
                                        keys_preview: Object.keys(val).slice(0, 20)};
                            if (Array.isArray(val))
                                return {too_large: true, size_bytes: s.length, length: val.length,
                                        first_item_keys: val[0] && typeof val[0]==='object'
                                                         ? Object.keys(val[0]).slice(0,20) : []};
                            return {too_large: true, size_bytes: s.length};
                        }
                        return {ok: true, json_str: s};
                    } catch(e) {
                        return {error: 'handler_exception', message: e.message};
                    }
                }""",
                {"varPath": var_path, "maxBytes": max_bytes},
            )
            if result.get("error"):
                return {"error": result["error"], "message": result.get("message", "")}
            if result.get("too_large"):
                return {k: v for k, v in result.items()}
            return {"value": json.loads(result["json_str"])}
        except Exception as e:
            return {"error": "handler_exception", "message": str(e)[:200]}

    async def get_element(self, selector: str, tab_id=None, attribute: str = "text", **_) -> dict:
        page = self._page_for(tab_id)
        try:
            el = page.locator(selector).first
            if attribute == "text":
                val = await el.inner_text(timeout=5_000)
            elif attribute == "value":
                val = await el.input_value(timeout=5_000)
            else:
                val = await el.get_attribute(attribute, timeout=5_000)
            return {"attribute": attribute, "value": val, "selector": selector}
        except Exception as e:
            return {"error": "get_element_failed", "message": str(e)[:200]}

    async def screenshot(self, tab_id=None, **_) -> dict:
        import base64
        page = self._page_for(tab_id)
        try:
            png = await page.screenshot(type="png")
            b64 = base64.b64encode(png).decode()
            return {"image": b64, "_vision_image": b64, "_vision_media_type": "image/png"}
        except Exception as e:
            return {"error": "screenshot_failed", "message": str(e)[:200]}

    async def click(self, selector: str, tab_id=None, **_) -> dict:
        page = self._page_for(tab_id)
        try:
            await page.click(selector, timeout=10_000)
            return {"status": "clicked", "selector": selector}
        except Exception as e:
            return {"error": "click_failed", "message": str(e)[:200]}

    async def fill_input(self, selector: str, value: str = "", tab_id=None, **_) -> dict:
        page = self._page_for(tab_id)
        try:
            await page.fill(selector, value, timeout=10_000)
            return {"status": "filled", "selector": selector}
        except Exception as e:
            return {"error": "fill_failed", "message": str(e)[:200]}

    async def scroll(self, direction: str = "down", amount: int = 500, tab_id=None, **_) -> dict:
        page = self._page_for(tab_id)
        try:
            js_map = {
                "down":   f"window.scrollBy(0, {amount})",
                "up":     f"window.scrollBy(0, -{amount})",
                "right":  f"window.scrollBy({amount}, 0)",
                "left":   f"window.scrollBy(-{amount}, 0)",
                "bottom": "window.scrollTo(0, document.body.scrollHeight)",
                "top":    "window.scrollTo(0, 0)",
            }
            await page.evaluate(js_map.get(direction, f"window.scrollBy(0, {amount})"))
            return {"status": "scrolled", "direction": direction, "amount": amount}
        except Exception as e:
            return {"error": "scroll_failed", "message": str(e)[:200]}

    def build_handlers(self) -> dict:
        """Return a mock_handlers dict for build_mocked_engine()."""
        return {
            "browser_get_active_tab": self.get_active_tab,
            "browser_get_tabs":       self.get_tabs,
            "browser_navigate":       self.navigate,
            "browser_open_tab":       self.open_tab,
            "browser_close_tab":      self.close_tab,
            "browser_switch_tab":     self.switch_tab,
            "browser_get_text":       self.get_text,
            "browser_get_dom":        self.get_dom,
            "browser_get_page_var":   self.get_page_var,
            "browser_get_element":    self.get_element,
            "browser_screenshot":     self.screenshot,
            "browser_click":          self.click,
            "browser_fill_input":     self.fill_input,
            "browser_scroll":         self.scroll,
        }


# ── Engine builder ─────────────────────────────────────────────────────────────

def build_mocked_engine(mock_handlers: dict[str, Callable]):
    """
    Create a fresh Chika engine with real LLM + real system prompt,
    but with browser_* tool handlers replaced by the provided mocks.
    """
    sm = SessionManager()
    session_id = f"browser_test_{int(time.time())}"
    engine = sm.get_or_create(session_id)
    engine._history = []

    patched = 0
    not_found = []
    for tool_name, handler in mock_handlers.items():
        tool_def = engine._tools.get(tool_name)
        if tool_def is None:
            not_found.append(tool_name)
            continue
        # Replace the handler on the existing ToolDefinition in-place
        tool_def.handler = handler
        patched += 1

    if not_found:
        print(f"{C_WARN}  [warn] mock tools not found in registry: {not_found}{C_RESET}")

    print(f"{C_DIM}  [patched {patched} browser tool handlers]{C_RESET}")
    return engine


# ── Trace collector ───────────────────────────────────────────────────────────

async def run_turn(engine, user_text: str) -> dict:
    """Send one message, stream events to terminal, collect trace."""
    print(f"\n{C_USER}━━━ YOU ━━━{C_RESET}  {user_text}\n")

    trace = {
        "user": user_text,
        "tokens": "",
        "tool_calls": [],   # [{tool, args}]
        "tool_results": [], # [{tool, error, result}]
        "errors": [],
        "duration_sec": 0.0,
    }
    t0 = time.time()

    async for event in engine.chat(user_text):
        etype = event.get("type", "")

        if etype == "token":
            txt = event.get("text", "")
            trace["tokens"] += txt
            print(txt, end="", flush=True)

        elif etype == "tool_call":
            tool = event.get("tool", "?")
            args = event.get("args", {})
            trace["tool_calls"].append({"tool": tool, "args": args})
            args_short = json.dumps(args, default=str)
            if len(args_short) > 120:
                args_short = args_short[:117] + "..."
            print(f"\n  {C_TOOL}-> {tool}{C_RESET}  {C_DIM}{args_short}{C_RESET}")

        elif etype == "tool_result":
            tool  = event.get("tool", "?")
            error = event.get("error")
            result = event.get("result")
            trace["tool_results"].append({"tool": tool, "error": error, "result": result})
            if error:
                mark = f"{C_ERR}✗{C_RESET}"
                detail = str(error)[:100]
            else:
                mark = f"{C_OK}✓{C_RESET}"
                detail = json.dumps(result, default=str)[:120] if result is not None else ""
            print(f"  {mark} {tool}  {C_DIM}{detail}{C_RESET}")

        elif etype == "error":
            msg = event.get("message", "")
            trace["errors"].append(msg)
            print(f"\n  {C_ERR}ERROR: {msg}{C_RESET}")

        elif etype == "done":
            break

    trace["duration_sec"] = round(time.time() - t0, 2)
    if trace["tokens"] and not trace["tokens"].endswith("\n"):
        print()

    post_tok = estimate_tokens(engine._history)
    print(f"\n{C_DIM}[{trace['duration_sec']}s | {len(trace['tool_calls'])} tools | history ~{post_tok} tokens]{C_RESET}")
    return trace


# ── Assertion runner ──────────────────────────────────────────────────────────

def run_assertions(trace: dict, assertions: list[tuple]) -> tuple[int, int]:
    """Print assertion results. Returns (passed, total)."""
    if not assertions:
        return 0, 0
    print(f"\n{C_BOLD}━━━ ASSERTIONS ━━━{C_RESET}")
    passed = 0
    for label, check_fn in assertions:
        try:
            ok = check_fn(trace)
        except Exception as e:
            ok = False
            label = f"{label}  [check error: {e}]"
        if ok:
            print(f"  {C_OK}✓{C_RESET}  {label}")
            passed += 1
        else:
            print(f"  {C_ERR}✗{C_RESET}  {label}")
    print(f"\n  {passed}/{len(assertions)} passed")
    return passed, len(assertions)


# ── Scenario runner ───────────────────────────────────────────────────────────

async def run_scenario(name: str) -> bool:
    scenario = SCENARIOS.get(name)
    if scenario is None:
        print(f"{C_ERR}Unknown scenario: {name!r}{C_RESET}")
        print(f"Available: {', '.join(SCENARIOS)}")
        return False

    mock_set_name = scenario["mock_set"]
    mock_set = MOCK_SETS.get(mock_set_name, {})

    print(f"\n{C_BOLD}{'='*60}{C_RESET}")
    print(f"{C_BOLD}SCENARIO: {name}{C_RESET}")
    print(f"{C_DIM}{scenario['description']}{C_RESET}")
    print(f"{C_BOLD}{'='*60}{C_RESET}")

    engine = build_mocked_engine(mock_set)
    trace  = await run_turn(engine, scenario["message"])
    passed, total = run_assertions(trace, scenario.get("assertions", []))
    return passed == total


# ── Interactive mode ──────────────────────────────────────────────────────────

async def interactive_mode(mock_set_name: str | None):
    # Pick mock set
    if mock_set_name and mock_set_name in MOCK_SETS:
        mock_set = MOCK_SETS[mock_set_name]
        print(f"\n{C_BOLD}Interactive mode — mock set: {mock_set_name}{C_RESET}")
    else:
        # Default: YouTube history mocks (most common debug scenario)
        mock_set = MOCK_SETS["yt_history_pagevar"]
        print(f"\n{C_BOLD}Interactive mode — mock set: yt_history_pagevar (default){C_RESET}")
        print(f"{C_DIM}Use --scenario <name> to switch mock sets. Available: {', '.join(MOCK_SETS)}{C_RESET}")

    engine = build_mocked_engine(mock_set)
    print(f"{C_DIM}Type your message. 'reset' to clear history. 'quit' to exit.{C_RESET}\n")

    while True:
        try:
            user_input = input(f"{C_USER}> {C_RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            break
        if user_input.lower() == "reset":
            engine._history.clear()
            print(f"{C_DIM}[history cleared]{C_RESET}")
            continue
        if user_input.lower() == "mocks":
            print(f"{C_DIM}Active mocks: {list(mock_set.keys())}{C_RESET}")
            continue

        await run_turn(engine, user_input)


# ── Playwright interactive mode ────────────────────────────────────────────────

async def playwright_mode(headless: bool = False) -> None:
    """Interactive chat backed by a real Playwright browser (headed by default)."""
    print(f"\n{C_BOLD}Playwright mode — launching {'headless' if headless else 'headed'} browser...{C_RESET}")
    backend = PlaywrightBrowserBackend()
    try:
        await backend.start(headless=headless)
    except RuntimeError as e:
        print(f"{C_ERR}{e}{C_RESET}")
        return

    mode_label = "headless" if headless else "headed (you can see the browser)"
    print(f"{C_OK}Browser launched — {mode_label}.{C_RESET}")

    engine = build_mocked_engine(backend.build_handlers())
    print(
        f"{C_DIM}Commands: 'tabs' list tabs | 'reset' clear history | 'quit' exit.{C_RESET}\n"
    )

    try:
        while True:
            try:
                user_input = input(f"{C_USER}> {C_RESET}").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input:
                continue
            cmd = user_input.lower()
            if cmd in ("quit", "exit"):
                break
            if cmd == "reset":
                engine._history.clear()
                print(f"{C_DIM}[history cleared]{C_RESET}")
                continue
            if cmd == "tabs":
                result = await backend.get_tabs()
                for t in result.get("tabs", []):
                    active_marker = f"  {C_OK}<active>{C_RESET}" if t.get("active") else ""
                    print(f"  [{t['id']}] {t['url']}{active_marker}")
                continue

            await run_turn(engine, user_input)
    finally:
        await backend.stop()
        print(f"\n{C_DIM}[browser closed]{C_RESET}")


# ── Auto-progression Playwright tests ─────────────────────────────────────────
# Run with:  python _test_browser.py --auto
# Opens a headed browser, runs each test in sequence (hardest at the end),
# prints a pass/fail summary.  Fix issues in rules/code, re-run to verify.

AUTO_TESTS = [
    # ── Level 1: basic navigation + text read ─────────────────────────────────
    {
        "name":        "static_page",
        "message":     "go to example.com and tell me what's on the page",
        "description": "Static page — navigate + get_text, simplest possible case",
        "checks": [
            ("opened or navigated to example.com",
             lambda t: any("example.com" in str(tc["args"].get("url","")).lower()
                           for tc in t["tool_calls"]
                           if tc["tool"] in ("browser_navigate","browser_open_tab"))),
            ("got text or DOM from the page",
             lambda t: any(tc["tool"] in ("browser_get_text","browser_get_dom","web_fetch")
                           for tc in t["tool_calls"])),
            ("response mentions the page content",
             lambda t: any(w in t["tokens"].lower()
                           for w in ("example","domain","illustrative","sample","documentation"))),
        ],
    },
    # ── Level 2: structured content ───────────────────────────────────────────
    {
        "name":        "hacker_news_top",
        "message":     "go to news.ycombinator.com and list the top 5 story titles",
        "description": "Hacker News — mostly-static HTML, numbered list expected",
        "checks": [
            ("opened or navigated to HN",
             lambda t: any("ycombinator" in str(tc["args"].get("url","")).lower()
                           for tc in t["tool_calls"]
                           if tc["tool"] in ("browser_navigate","browser_open_tab"))),
            ("read the page with browser tool or web_fetch",
             lambda t: any(tc["tool"] in ("browser_get_text","browser_get_dom","web_fetch")
                           for tc in t["tool_calls"])),
            ("response contains at least 2 story items",
             lambda t: sum(1 for n in ["1.","2.","3.","**1","**2","**3","1 ","2 ","3 "]
                           if n in t["tokens"]) >= 2 or
                       t["tokens"].count("\n") >= 3),
        ],
    },
    # ── Level 3: Wikipedia targeted selector ──────────────────────────────────
    {
        "name":        "wikipedia_summary",
        "message":     "go to en.wikipedia.org/wiki/Python_(programming_language) and summarise what Python is in 2 sentences",
        "description": "Wikipedia — browser or web_fetch acceptable, concise 2-sentence summary expected",
        "checks": [
            ("accessed wikipedia (browser or web_fetch)",
             lambda t: any("wikipedia" in str(tc["args"].get("url","")).lower() or
                           "python" in str(tc["args"].get("url","")).lower()
                           for tc in t["tool_calls"]
                           if tc["tool"] in ("browser_navigate","browser_open_tab","web_fetch","verify_url"))),
            ("got content from the page",
             lambda t: any(tc["tool"] in ("browser_get_text","browser_get_dom","web_fetch","llm_summarise")
                           for tc in t["tool_calls"])),
            ("response mentions programming language",
             lambda t: "programming" in t["tokens"].lower() or "language" in t["tokens"].lower()),
        ],
    },
    # ── Level 4: SPA with wait_for — lobste.rs (no anti-bot) ──────────────────
    {
        "name":        "lobsters_new",
        "message":     "go to lobste.rs and list the top 3 story titles from the front page",
        "description": "lobste.rs — clean static/minimal-JS site, link list test",
        "checks": [
            ("opened or navigated to lobste.rs",
             lambda t: any("lobste" in str(tc["args"].get("url","")).lower()
                           for tc in t["tool_calls"]
                           if tc["tool"] in ("browser_navigate","browser_open_tab","web_fetch"))),
            ("read the page",
             lambda t: any(tc["tool"] in ("browser_get_text","browser_get_dom","web_fetch")
                           for tc in t["tool_calls"])),
            ("response has actual story titles (not empty)",
             lambda t: len(t["tokens"]) > 80 and "loading" not in t["tokens"].lower()),
        ],
    },
    # ── Level 5: page_var drill-down ──────────────────────────────────────────
    {
        "name":        "youtube_trending",
        "message":     "go to youtube.com/feed/trending and tell me the first 3 trending video titles",
        "description": "YouTube — try page_var first, fall back to DOM, never use text for URLs",
        "checks": [
            ("navigated to youtube trending",
             lambda t: any("youtube" in str(tc["args"].get("url","")).lower()
                           for tc in t["tool_calls"] if tc["tool"]=="browser_navigate")),
            ("tried page_var OR used DOM",
             lambda t: any(tc["tool"] in ("browser_get_page_var","browser_get_dom")
                           for tc in t["tool_calls"])),
            ("gave a substantive response — titles OR honest empty explanation (no raw skeleton)",
             lambda t: len(t["tokens"]) > 60
             and "loading" not in t["tokens"].lower()
             and "skeleton" not in t["tokens"].lower()
             and not (len(t["tokens"].strip()) < 80 and "youtube" not in t["tokens"].lower())),
        ],
    },
    # ── Level 6: multi-tab — open in new tab ──────────────────────────────────
    {
        "name":        "open_new_tab",
        "message":     "open github.com/trending in a new tab and tell me the top 3 trending repos",
        "description": "GitHub trending — open_tab + page read",
        "checks": [
            ("opened a new tab for github",
             lambda t: any("github" in str(tc["args"].get("url","")).lower()
                           for tc in t["tool_calls"]
                           if tc["tool"] in ("browser_open_tab","browser_navigate"))),
            ("read the page",
             lambda t: any(tc["tool"] in ("browser_get_text","browser_get_dom","browser_get_page_var")
                           for tc in t["tool_calls"])),
            ("response mentions repos",
             lambda t: any(w in t["tokens"].lower()
                           for w in ("repo","repository","star","trending","/"))),
        ],
    },
    # ── Level 7: link extraction — DOM not text ────────────────────────────────
    {
        "name":        "extract_link",
        "message":     "go to news.ycombinator.com and open the first story link in a new tab",
        "description": "Link extraction — must use DOM to get href, NOT text (which strips hrefs)",
        "checks": [
            ("used browser_get_dom to find links",
             lambda t: any(tc["tool"]=="browser_get_dom" for tc in t["tool_calls"])),
            ("opened or navigated to a non-HN URL",
             lambda t: any(
                 tc["tool"] in ("browser_open_tab","browser_navigate") and
                 "ycombinator" not in str(tc["args"].get("url","")).lower() and
                 "http" in str(tc["args"].get("url","")).lower()
                 for tc in t["tool_calls"]
             )),
            ("did NOT extract a date/number as a URL",
             lambda t: not any(
                 tc["tool"] in ("browser_open_tab","browser_navigate") and
                 any(bad in str(tc["args"].get("url",""))
                     for bad in ["pts", "minutes", "hours", "ago", "points"])
                 for tc in t["tool_calls"]
             )),
        ],
    },
    # ── Level 8: screenshot ────────────────────────────────────────────────────
    {
        "name":        "screenshot_page",
        "message":     "take a screenshot of the current page and describe what you see",
        "description": "Screenshot — uses browser_screenshot, describes visual content",
        "checks": [
            ("took a screenshot",
             lambda t: any(tc["tool"]=="browser_screenshot" for tc in t["tool_calls"])),
            ("described what was seen",
             lambda t: len(t["tokens"]) > 60),
        ],
    },
    # ── Level 9: YouTube consent auto-recovery ─────────────────────────────────
    {
        "name":        "youtube_consent_recovery",
        "message":     "go to youtube.com and tell me what videos are on the homepage",
        "description": "YouTube — consent banner auto-dismissed, content readable via DOM or page_var",
        "checks": [
            ("opened or navigated to youtube (navigate or open_tab)",
             lambda t: any(
                 "youtube.com" in str(tc["args"].get("url", ""))
                 for tc in t["tool_calls"]
                 if tc["tool"] in ("browser_navigate", "browser_open_tab")
             )),
            ("read page content (dom or page_var or text or screenshot)",
             lambda t: any(
                 tc["tool"] in ("browser_get_dom", "browser_get_page_var", "browser_get_text",
                                "browser_screenshot")
                 for tc in t["tool_calls"]
             )),
            ("produced a response mentioning youtube or video",
             lambda t: any(
                 kw in t["tokens"].lower()
                 for kw in ["video", "youtube", "watch", "channel", "trending",
                             "recommend", "homepage", "signed", "logged", "fresh"]
             )),
        ],
    },
    # ── Level 10: multi-page research synthesis ────────────────────────────────
    {
        "name":        "research_synthesis",
        "message":     (
            "research 'Python async await best practices' — visit at least 2 different pages "
            "and give me a concise summary with the most important patterns"
        ),
        "description": "Research synthesis — multi-page visit, combines sources, substantive answer",
        "checks": [
            ("fetched or navigated to pages (web_fetch x2, browser_run_research, or navigate+read)",
             lambda t: (
                 sum(1 for tc in t["tool_calls"] if tc["tool"] == "web_fetch") >= 2
                 or any(tc["tool"] == "browser_run_research" for tc in t["tool_calls"])
                 or sum(
                     1 for tc in t["tool_calls"]
                     if tc["tool"] in ("web_fetch", "browser_navigate", "browser_open_tab",
                                       "browser_get_text", "browser_get_dom")
                 ) >= 2
             )),
            ("synthesised a substantive answer (>300 chars)",
             lambda t: len(t["tokens"]) > 300),
            ("response mentions async/await concepts",
             lambda t: any(
                 kw in t["tokens"].lower()
                 for kw in ["async", "await", "coroutine", "event loop", "asyncio",
                             "gather", "task", "concurrent", "non-blocking"]
             )),
        ],
    },
    # ── Level 11: search form interaction ──────────────────────────────────────
    {
        "name":        "search_form_interaction",
        "message":     "search hacker news for 'rust language' and list the top 5 results",
        "description": "HN search — via Algolia URL or web_search, reads and lists results",
        "checks": [
            ("found HN results (browser navigate to algolia OR web_search with HN context)",
             lambda t: any(
                 "hn.algolia.com" in str(tc["args"].get("url", ""))
                 or "news.ycombinator.com" in str(tc["args"].get("url", ""))
                 for tc in t["tool_calls"]
                 if tc["tool"] in ("browser_navigate", "browser_open_tab", "web_fetch")
             ) or any(
                 "hacker" in str(tc["args"]).lower() or "ycombinator" in str(tc["args"]).lower()
                 or "hn" in str(tc["args"]).lower()
                 for tc in t["tool_calls"]
                 if tc["tool"] == "web_search"
             )),
            ("got results somehow (browser tool or web_search or web_fetch)",
             lambda t: any(
                 tc["tool"] in ("browser_get_text", "browser_get_dom", "web_fetch", "web_search")
                 for tc in t["tool_calls"]
             )),
            ("listed at least 3 results",
             lambda t: sum(
                 1 for line in t["tokens"].split("\n")
                 if line.strip() and (
                     line.strip()[0].isdigit() or line.strip().startswith("-")
                     or line.strip().startswith("*") or line.strip().startswith("•")
                     or "**" in line
                 )
             ) >= 3),
        ],
    },
    # ── Level 12: YouTube channel latest video ─────────────────────────────────
    {
        "name":        "yt_channel_latest",
        "message":     "what's the latest video on the Fireship channel on YouTube?",
        "description": "YouTube channel latest — navigates to @Fireship/videos, reads page_var, returns title+URL",
        "checks": [
            ("navigated to Fireship channel or searched for it",
             lambda t: any(
                 "fireship" in str(tc["args"].get("url", "")).lower()
                 or "fireship" in str(tc["args"].get("query", "")).lower()
                 for tc in t["tool_calls"]
                 if tc["tool"] in ("browser_navigate", "browser_open_tab", "web_search", "web_fetch")
             )),
            ("read page content (page_var or dom or text)",
             lambda t: any(
                 tc["tool"] in ("browser_get_page_var", "browser_get_dom",
                                "browser_get_text", "web_fetch")
                 for tc in t["tool_calls"]
             )),
            ("responded with an actual video title (not just a URL)",
             lambda t: len(t["tokens"]) > 60 and not t["tokens"].strip().startswith("http")),
            ("response mentions a URL or video link",
             lambda t: "youtube.com" in t["tokens"].lower()
             or "/watch" in t["tokens"].lower()
             or "youtu.be" in t["tokens"].lower()
             or "fireship" in t["tokens"].lower()),
        ],
    },
    # ── Level 13: YouTube video search ─────────────────────────────────────────
    {
        "name":        "yt_video_search",
        "message":     "search YouTube for 'Python asyncio tutorial' and tell me the first result",
        "description": "YouTube search — constructs search URL or uses page_var, extracts first result title+URL",
        "checks": [
            ("searched YouTube (via URL or page_var or web_search)",
             lambda t: any(
                 ("youtube.com/results" in str(tc["args"].get("url", ""))
                  or "youtube.com/search" in str(tc["args"].get("url", ""))
                  or ("youtube" in str(tc["args"].get("query", "")).lower()
                      and "asyncio" in str(tc["args"]).lower()))
                 or ("youtube" in str(tc["args"].get("url", "")).lower()
                     and "search" in str(tc["args"].get("url", "")).lower())
                 or ("asyncio" in str(tc["args"]).lower()
                     and tc["tool"] in ("web_search", "web_fetch"))
                 for tc in t["tool_calls"]
                 if tc["tool"] in ("browser_navigate", "browser_open_tab",
                                   "web_search", "web_fetch", "browser_get_page_var")
             )),
            ("read the search results page",
             lambda t: any(
                 tc["tool"] in ("browser_get_page_var", "browser_get_dom",
                                "browser_get_text", "web_fetch", "llm_transform")
                 for tc in t["tool_calls"]
             )),
            ("returned a real video title for the first result",
             lambda t: len(t["tokens"]) > 60
             and any(
                 kw in t["tokens"].lower()
                 for kw in ["asyncio", "async", "python", "tutorial", "video", "watch"]
             )),
            ("included a URL for the video (not just said go look)",
             lambda t: "youtube.com" in t["tokens"].lower()
             or "/watch?v=" in t["tokens"].lower()
             or "youtu.be" in t["tokens"].lower()),
        ],
    },
    # ── Level 14: cross-site feed comparison (AGI) ─────────────────────────────
    {
        "name":        "cross_site_comparison",
        "message":     "what's trending on both Hacker News and lobste.rs right now? list top 3 from each and note any overlap",
        "description": "AGI: multi-site synthesis — reads 2 different feeds, compares them",
        "checks": [
            ("visited both HN and lobste.rs",
             lambda t: (
                 any("ycombinator" in str(tc["args"]).lower() or "hackernews" in str(tc["args"]).lower()
                     for tc in t["tool_calls"])
                 and any("lobste" in str(tc["args"]).lower()
                         for tc in t["tool_calls"])
             )),
            ("read content from both sites",
             lambda t: sum(
                 1 for tc in t["tool_calls"]
                 if tc["tool"] in ("browser_get_text", "browser_get_dom",
                                   "web_fetch", "browser_get_page_var")
             ) >= 2),
            ("response lists titles from both (at least 4 total)",
             lambda t: sum(
                 1 for line in t["tokens"].split("\n")
                 if line.strip() and (
                     line.strip()[0].isdigit() or line.strip().startswith("-")
                     or line.strip().startswith("*") or line.strip().startswith("•")
                     or "**" in line
                 )
             ) >= 4),
            ("mentions whether there's overlap or not",
             lambda t: any(
                 kw in t["tokens"].lower()
                 for kw in ["overlap", "appear", "both", "same", "shared",
                             "no overlap", "different", "common"]
             )),
        ],
    },
    # ── Level 15: npm package info (structured data from any registry) ─────────
    {
        "name":        "npm_package_info",
        "message":     "what's the current version of the 'zod' npm package and how many weekly downloads does it get?",
        "description": "AGI: structured data from a registry page — version + download stats from npmjs.com",
        "checks": [
            ("navigated to npmjs.com or fetched package info",
             lambda t: any(
                 "npmjs" in str(tc["args"]).lower()
                 or "npm" in str(tc["args"]).lower()
                 or "zod" in str(tc["args"]).lower()
                 for tc in t["tool_calls"]
                 if tc["tool"] in ("browser_navigate", "browser_open_tab",
                                   "web_fetch", "web_search")
             )),
            ("read the package page",
             lambda t: any(
                 tc["tool"] in ("browser_get_text", "browser_get_dom",
                                "web_fetch", "browser_get_page_var")
                 for tc in t["tool_calls"]
             )),
            ("response includes a version number",
             lambda t: any(
                 char.isdigit() and "." in t["tokens"]
                 for char in t["tokens"]
             ) and any(
                 kw in t["tokens"].lower()
                 for kw in ["version", "v3", "v2", "v1", "3.", "2.", "latest"]
             )),
            ("response mentions downloads or weekly stats",
             lambda t: any(
                 kw in t["tokens"].lower()
                 for kw in ["download", "weekly", "million", "thousand", "installs", "npm"]
             )),
        ],
    },
    # ── Level 16: SPA internal navigation (click-based, no URL change) ─────────
    {
        "name":        "spa_click_navigation",
        "message":     "go to the MDN docs for the JavaScript Promise API and summarise what Promise.all() does",
        "description": "AGI: docs navigation — finds the right anchor or sub-page, reads targeted content",
        "checks": [
            ("navigated to MDN",
             lambda t: any(
                 "developer.mozilla" in str(tc["args"]).lower()
                 or "mdn" in str(tc["args"]).lower()
                 for tc in t["tool_calls"]
                 if tc["tool"] in ("browser_navigate", "browser_open_tab",
                                   "web_fetch", "web_search")
             )),
            ("read actual MDN content",
             lambda t: any(
                 tc["tool"] in ("browser_get_text", "browser_get_dom", "web_fetch")
                 for tc in t["tool_calls"]
             )),
            ("response explains Promise.all correctly",
             lambda t: all(
                 kw in t["tokens"].lower()
                 for kw in ["promise", "all"]
             ) and any(
                 kw in t["tokens"].lower()
                 for kw in ["parallel", "concurrent", "iterable", "array",
                             "resolves", "rejects", "fulfills", "settle"]
             )),
        ],
    },
    # ── Level 17: GitHub repo analysis (multi-section read) ────────────────────
    {
        "name":        "github_repo_analysis",
        "message":     "go to github.com/sindresorhus/got and tell me: what is it, what's the latest release, and how many stars does it have?",
        "description": "AGI: multi-section GitHub page — description + release + stars in one pass",
        "checks": [
            ("navigated to GitHub repo",
             lambda t: any(
                 "github.com" in str(tc["args"]).lower()
                 and "got" in str(tc["args"]).lower()
                 for tc in t["tool_calls"]
                 if tc["tool"] in ("browser_navigate", "browser_open_tab",
                                   "web_fetch", "web_search")
             )),
            ("read the repo page",
             lambda t: any(
                 tc["tool"] in ("browser_get_text", "browser_get_dom", "web_fetch")
                 for tc in t["tool_calls"]
             )),
            ("response describes what the package does",
             lambda t: any(
                 kw in t["tokens"].lower()
                 for kw in ["http", "request", "fetch", "node", "javascript",
                             "got", "library", "client"]
             )),
            ("mentions stars or release",
             lambda t: any(
                 kw in t["tokens"].lower()
                 for kw in ["star", "release", "version", "k", "thousand"]
             )),
        ],
    },
    # ── Level 18: error recovery — 404 fallback (AGI resilience) ──────────────
    {
        "name":        "error_recovery_404",
        # Plausible-looking story URL that won't exist — model navigates, gets 404,
        # then self-corrects to the lobste.rs front page.
        "message":     "go to https://lobste.rs/s/xk9mq2/ghostty-leaving-github and summarise what the article says",
        "description": "AGI resilience: plausible 404 URL, model navigates it, gets error, recovers to find real content",
        "checks": [
            ("attempted the given URL (even though it 404s)",
             lambda t: any(
                 "lobste.rs" in str(tc["args"]).lower()
                 and ("xk9mq2" in str(tc["args"]).lower()
                      or "ghostty" in str(tc["args"]).lower())
                 for tc in t["tool_calls"]
             )),
            ("recovered — navigated to a working page or searched for content",
             lambda t: any(
                 (
                     tc["tool"] in ("browser_navigate", "browser_open_tab",
                                    "web_fetch", "web_search")
                     and isinstance(tc["args"], dict)
                     and (
                         ("lobste.rs" in tc["args"].get("url", "")
                          and "xk9mq2" not in tc["args"].get("url", ""))
                         or "ghostty" in str(tc["args"]).lower()
                         or "mitchellh" in str(tc["args"]).lower()
                     )
                 )
                 for tc in t["tool_calls"]
             )),
            ("produced a substantive response (not just 'page not found')",
             lambda t: len(t["tokens"]) > 80 and any(
                 kw in t["tokens"].lower()
                 for kw in ["ghostty", "github", "lobste", "story", "article",
                             "found", "404", "not found", "unavailable"]
             )),
        ],
    },
    # ── Level 19: DuckDuckGo search results (non-YouTube large SPA) ────────────
    {
        "name":        "ddg_search_dom_fallback",
        "message":     "search DuckDuckGo for 'effect of caffeine on sleep' and summarise the top 3 results",
        "description": "AGI: large non-YouTube SPA — DDG search results via DOM, no page_var",
        "checks": [
            ("searched DuckDuckGo",
             lambda t: any(
                 "duckduckgo" in str(tc["args"]).lower()
                 or "ddg" in str(tc["args"]).lower()
                 or "caffeine" in str(tc["args"]).lower()
                 for tc in t["tool_calls"]
                 if tc["tool"] in ("browser_navigate", "browser_open_tab",
                                   "web_search", "web_fetch")
             )),
            ("read search results",
             lambda t: any(
                 tc["tool"] in ("browser_get_text", "browser_get_dom",
                                "web_fetch", "web_search")
                 for tc in t["tool_calls"]
             )),
            ("summarised actual results (not just listed URLs)",
             lambda t: len(t["tokens"]) > 150 and any(
                 kw in t["tokens"].lower()
                 for kw in ["caffeine", "sleep", "effect", "coffee", "adenosine",
                             "quality", "disrupt", "hours", "research", "study"]
             )),
        ],
    },
]


async def auto_playwright_mode(headless: bool = False) -> None:
    """
    Run AUTO_TESTS sequentially against a real Playwright browser.
    Progressively harder — starts with static pages, ends with multi-tab + screenshot.
    Prints a summary at the end.  Fix issues in browser_skill/__init__.py and re-run.
    """
    print(f"\n{C_BOLD}Auto-progression Playwright test — {len(AUTO_TESTS)} levels{C_RESET}")
    print(f"{'headless' if headless else 'Headed — browser window will open'}\n")

    backend = PlaywrightBrowserBackend()
    try:
        await backend.start(headless=headless)
    except RuntimeError as e:
        print(f"{C_ERR}{e}{C_RESET}")
        return

    print(f"{C_OK}Browser ready.{C_RESET}\n")

    results: list[dict] = []

    for i, test in enumerate(AUTO_TESTS, 1):
        print(f"\n{C_BOLD}{'='*64}{C_RESET}")
        print(f"{C_BOLD}Level {i}/{len(AUTO_TESTS)}: {test['name']}{C_RESET}")
        print(f"{C_DIM}{test['description']}{C_RESET}")
        print(f"{C_BOLD}{'='*64}{C_RESET}")

        # Fresh engine + fresh history for each test so they're independent
        engine = build_mocked_engine(backend.build_handlers())

        try:
            trace = await run_turn(engine, test["message"])
            passed, total = run_assertions(trace, test.get("checks", []))
            results.append({
                "name":   test["name"],
                "level":  i,
                "passed": passed,
                "total":  total,
                "errors": trace["errors"],
            })
        except Exception as exc:
            print(f"\n{C_ERR}CRASH during {test['name']}: {exc}{C_RESET}")
            import traceback; traceback.print_exc()
            results.append({
                "name":   test["name"],
                "level":  i,
                "passed": 0,
                "total":  len(test.get("checks", [])),
                "errors": [str(exc)],
            })

    await backend.stop()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{C_BOLD}{'='*64}")
    print(f"AUTO-PROGRESSION SUMMARY{C_RESET}")
    print(f"{'Level':<8} {'Name':<25} {'Score':<10} Status")
    print(f"{'-'*64}")
    for r in results:
        score  = f"{r['passed']}/{r['total']}"
        ok     = r["passed"] == r["total"]
        status = f"{C_OK}PASS{C_RESET}" if ok else f"{C_ERR}FAIL{C_RESET}"
        err    = f"  {C_WARN}{r['errors'][0][:60]}{C_RESET}" if r["errors"] else ""
        print(f"  {r['level']:<6} {r['name']:<25} {score:<10} {status}{err}")

    total_pass = sum(1 for r in results if r["passed"] == r["total"])
    print(f"\n{total_pass}/{len(results)} levels fully passed")


# ── CLI ───────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Browser skill test harness — mocked or real-browser tools, real LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python _test_browser.py                   run all mock scenarios\n"
            "  python _test_browser.py yt_history        run one scenario\n"
            "  python _test_browser.py -i                interactive with mocks\n"
            "  python _test_browser.py --playwright      interactive with REAL browser\n"
            "  python _test_browser.py --playwright --headless  same but no window\n"
        ),
    )
    parser.add_argument(
        "scenario", nargs="?", default=None,
        help="Scenario name to run (omit to run all)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List available scenarios and mock sets",
    )
    parser.add_argument(
        "--interactive", "-i", action="store_true",
        help="Interactive mode: free-form chat with mocked tools",
    )
    parser.add_argument(
        "--mock-set", "--scenario-mocks", default=None,
        dest="mock_set",
        help="Mock set to use in --interactive mode",
    )
    parser.add_argument(
        "--playwright", "-p", action="store_true",
        help="Interactive mode using a REAL browser via Playwright",
    )
    parser.add_argument(
        "--auto", "-a", action="store_true",
        help="Auto-progression mode: run all 8 Playwright levels unattended",
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Run Playwright browser in headless mode (no visible window)",
    )
    args = parser.parse_args()

    if args.list:
        print(f"\n{C_BOLD}Scenarios:{C_RESET}")
        for name, sc in SCENARIOS.items():
            print(f"  {C_TOOL}{name:<22}{C_RESET}  {sc['description']}")
        print(f"\n{C_BOLD}Mock sets:{C_RESET}")
        for name, ms in MOCK_SETS.items():
            tools = ", ".join(ms.keys())
            print(f"  {C_TOOL}{name:<22}{C_RESET}  [{tools}]")
        return

    if args.auto:
        await auto_playwright_mode(headless=args.headless)
        return

    if args.playwright:
        await playwright_mode(headless=args.headless)
        return

    if args.interactive:
        await interactive_mode(args.mock_set)
        return

    if args.scenario:
        ok = await run_scenario(args.scenario)
        sys.exit(0 if ok else 1)

    # Run all scenarios
    results = {}
    for name in SCENARIOS:
        ok = await run_scenario(name)
        results[name] = ok

    print(f"\n{C_BOLD}{'='*60}")
    print(f"SUMMARY{C_RESET}")
    total_pass = sum(results.values())
    for name, ok in results.items():
        mark = f"{C_OK}PASS{C_RESET}" if ok else f"{C_ERR}FAIL{C_RESET}"
        print(f"  {mark}  {name}")
    print(f"\n{total_pass}/{len(results)} scenarios passed")


if __name__ == "__main__":
    asyncio.run(main())
