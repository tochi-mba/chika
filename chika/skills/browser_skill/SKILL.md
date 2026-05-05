# Browser skill

Drives the user's actual Chrome via the Chika extension. The extension must be
connected (header shows the purple dot). All browser actions are **per-tab**.

## Read tools

| Tool                       | Purpose                                            |
|----------------------------|----------------------------------------------------|
| `browser_get_tabs`         | List all open tabs in this window.                 |
| `browser_get_active_tab`   | Get the active tab's URL + title + visible text.   |
| `browser_get_text`         | Extract main-text content from a tab.              |
| `browser_get_dom`          | DOM (truncated). Pass `selector` to scope.         |
| `browser_get_element`      | Single-element details for a CSS selector.         |
| `browser_get_page_var`     | Read a JS global variable from the page.           |
| `browser_screenshot`       | PNG screenshot of the active tab.                  |

## Write tools

| Tool                  | Purpose                                                |
|-----------------------|--------------------------------------------------------|
| `browser_navigate`    | Go to URL in the current tab.                          |
| `browser_open_tab`    | Open a new tab.                                        |
| `browser_close_tab`   | Close a specific tab id.                               |
| `browser_switch_tab`  | Bring a tab to focus.                                  |
| `browser_click`       | Click an element via CSS selector.                     |
| `browser_fill_input`  | Type into an input/textarea.                           |
| `browser_scroll`      | Scroll by px or to an element.                         |
| `browser_run_research`| Multi-step research: open URL, extract, summarise.    |
| `browser_watch_element`| Wait for an element to appear/change.                |
| `browser_unwatch`     | Cancel a previously registered watch.                  |
| `browser_list_watches`| List active watches.                                   |

## Patterns

### Read what's on the user's screen
```json
{"type": "sequential", "steps": [
  {"tool": "browser_get_active_tab", "store_result_as": "$tab"},
  {"tool": "browser_get_text", "args": {"tab_id": "$tab.id"}, "store_result_as": "$page"}
]}
```

### Form fill + submit
```json
{"type": "sequential", "steps": [
  {"tool": "browser_navigate",   "args": {"url": "https://example.com/login"}},
  {"tool": "browser_fill_input", "args": {"selector": "#email", "value": "..."}},
  {"tool": "browser_fill_input", "args": {"selector": "#password", "value": "..."}},
  {"tool": "browser_click",      "args": {"selector": "button[type=submit]"}}
]}
```

### Wait for an element
```json
{"tool": "browser_watch_element", "args": {"selector": ".result", "timeout_ms": 8000}}
```

## Anti-patterns

- Don't blindly `browser_get_dom` — it's huge. Always scope with a `selector`.
- Don't auto-fill credentials unless the user asked to.
- Don't run JS on banking / sensitive pages without explicit permission.

---

## Reference patterns (migrated from workflow_examples)

### Browser Workflows

## CORE RULES — apply to every site, not just YouTube

**Rule 0 — Never pre-emptively refuse. Always try.**
NEVER say "I can't access your browser data / history / tabs". You have full browser
control. If the user asks about something in their browser, JUST DO IT:
- Navigate to the right URL and read the page.
- "What was my last YouTube video?" → navigate to youtube.com/feed/history → read it → answer.
- "What's open in my browser?" → browser_get_tabs → answer.
Saying "I can't access that" without even trying is a failure. Always attempt the task first.

**Rule 1 — Use the open tab, not web_search.**
If the user has any site open, interact with it directly using browser tools.
`web_search` is only for when there is no relevant tab open at all.

**Rule 2 — Construct the URL directly when possible.**
Most sites expose sorting/filtering in the URL. Navigating straight to the
right URL is always faster than clicking through dropdowns and menus.
Common patterns that work on almost every site:
- Latest/newest: append `?sort=new`, `?sort=date`, `?order=newest`, `?sort=dd`
- Search: append `?q=query`, `?search=query`, `/search?q=query`
- Page: append `?page=2`, `?p=2`, `&offset=20`
Examples:
  Reddit newest posts:  `https://reddit.com/r/programming/new`
  GitHub newest issues: `https://github.com/org/repo/issues?q=is:open&sort=updated`
  YouTube channel vids: `https://youtube.com/@handle/videos?view=0&sort=dd`
  Google search:        `https://google.com/search?q=query`
  Hacker News newest:   `https://news.ycombinator.com/newest`
Apply this pattern to whatever site the user is on. Infer the URL pattern
from the current tab's URL structure.

**Rule 3 — Use targeted selectors, not full-page text dumps.**
`browser_get_text(selector=...)` scoped to the content container is fast.
Full-page dumps are slow and full of nav/footer noise.
Selector priority order (try each until one works):
  1. Semantic: `main`, `article`, `[role=main]`
  2. Content IDs: `#content`, `#results`, `#main`
  3. Content classes: `.results`, `.feed`, `.posts`, `.items`, `.listings`
  4. Data attributes: `[data-testid*=result]`, `[data-testid*=item]`
  5. List containers: `ul li`, `ol li` (if content is a list)
  6. Full page (no selector) — last resort only

**Rule 4 — Navigate → Read → Answer. Never open and abandon.**
After navigating or opening a tab to answer a question, you MUST read the page
and extract the actual answer before responding to the user.
Opening a page and telling the user "it's open — go look" is NOT completing the task.
The complete sequence is always: navigate → read content → extract answer → respond.
Example: user asks "what was my last YouTube video?" → you navigate to
youtube.com/feed/history → you read the page → you tell them the title and URL.
Stopping after the navigate step is a failure to complete the task.

After reading a new page, use `browser_get_text` or `browser_get_page_var` to
understand what's there. Extract links/titles with `llm_transform`, then navigate
or click. Never guess a URL or selector without reading the page.

**Rule 5 — Use `find` to zoom into large pages without bloating context.**
`browser_get_text(find="history")` returns only the lines that contain
"history" plus 4 lines of context around each match, separated by "...".
This is much cheaper than dumping the whole page. Use it when:
- You don't know the right CSS selector yet (use find to discover structure)
- The page is large and you only need one section
- A full-page dump would be too noisy for llm_transform to work well
Example: on a YouTube page, `find="History"` quickly surfaces the history
section and its links without reading the entire nav/feed/footer.

**Rule 6 — On any SPA or data-heavy site, try `browser_get_page_var` before the DOM.**
Most modern sites (YouTube, Twitter, Reddit, Instagram, Next.js apps, Nuxt apps, etc.)
embed ALL their page data as a JS global synchronously — before any component renders.
Reading that variable is instant, structured, and never fails due to render timing.

Common globals (applicable across thousands of sites):
- `ytInitialData`           — YouTube (any page: feed, history, channel, video)
- `__NEXT_DATA__`           — any Next.js site (Vercel, Notion, etc.)
- `__NUXT__`                — any Nuxt site
- `window.__INITIAL_STATE__`— Twitter/X, many React apps
- `window._sharedData`      — Instagram
- `window.__r`              — Reddit old/new
- `digitalData`             — Adobe Analytics-backed sites
- `window.__APP_STATE__`    — generic; worth trying on any SPA

**Workflow — three outcomes, three responses:**

**`too_large`** → the variable exists but is too big to return whole. The result
includes `keys_preview` (top-level key names) and `size_bytes`.

CRITICAL RULES FOR too_large (violating these produces wrong answers):
1. **DO NOT call `llm_transform` on a too_large result.** `keys_preview` is only a list of key
   names — not values. `llm_transform` has nothing real to work with and will hallucinate data.
   Wait until you have an actual `value` before transforming.
2. **Drill-or-DOM decision — applies to ANY site:**
   - Look at the URL to judge data density. Search results pages (any site with `?q=`, `/results`,
     `/search`) tend to have enormous JS globals. If after 2 drills it's still too_large, switch
     to DOM immediately — don't keep drilling.
   - Feeds and list pages (history, channel, timeline, front page): try 2-3 drills first,
     then fall back to DOM if still too_large.
3. **Narrowing path:** Pick the most data-sounding key from `keys_preview`:
   - Prefer: `contents`, `data`, `items`, `results`, `feed`, `entries`, `rows`, `posts`
   - Avoid: `header`, `config`, `footer`, `meta`, `analytics`, `tracking`, `responseContext`
   - Known globals: Next.js → `__NEXT_DATA__.props.pageProps`; Nuxt → `__NUXT__.data`;
     Reddit → `window.__r.data`; Twitter/X → `window.__INITIAL_STATE__.entities`
4. If that subtree is ALSO too_large, repeat once more, then switch to DOM.
5. **DOM fallback (works on any site):** Use content-first selectors in priority order:
   - For item/card lists: `article`, `[role=listitem]`, `[role=article]`, `li`, `.card`, `.item`
   - For feeds: `[role=feed] > *`, `main > ul > li`, `.feed > div`
   - For video grids (YouTube): `ytd-video-renderer`, `ytd-rich-item-renderer`
   - For search results (Google, DuckDuckGo, Bing): `[data-testid=result]`, `.result`, `#search div.g`
   - For news/blog lists: `article h2 a`, `.post-title a`, `.story a`
   Always pair with `wait_for` set to the same selector.
6. **After DOM fallback, use `llm_transform` to extract `[{title, url}]` from the HTML.** The href
   attributes will be preserved in the DOM output — this is the only reliable way to get URLs.

**When a completed workflow result contains too_large:**
You are now in a synthesis turn (the workflow finished and you're about to respond).
DO NOT write a text response to the user saying "I need to drill deeper" or "the data was too large".
Instead: immediately call `workflow_orchestrator` again with the narrowed path you identified.
The user is waiting for the answer — keep going until you have it.

**`var_not_found / handler_exception / error / empty/null`** → variable doesn't
exist on this page. CRITICAL: do NOT tell the user. Do NOT say anything was
"blocked". Follow this decision tree for your fallback:

1. **Were you trying to get a list of items with links?** (YouTube history/search/trending,
   Reddit feed, Twitter/X timeline, HN front page, any feed or list page)
   → use `browser_get_dom(selector=<content-container>, wait_for=<content-element>)`
   → then `llm_transform` to extract `[{title, url}]` from the HTML
   → NEVER use `browser_get_text` here — text strips hrefs, you will get timestamps
     and numbers in place of video IDs, post IDs, or article paths.

2. **Are you summarising text content with no need for URLs?** (article body, wiki page,
   doc page, support page)
   → use `browser_get_text(selector=<main-content>, wait_for=<content-element>)` with
     a `find=` keyword if relevant, then proceed.

Rule of thumb: if you were about to navigate to the result you're reading (e.g. "open the
video", "open the post", "open the article"), you NEED a URL → use browser_get_dom.

**`value returned`** → use it directly. Extract what you need with `llm_transform`.

**Rule 7 — ALWAYS use `wait_for` when reading a page after navigation.**
`browser_navigate` waits for the HTML to load, but SPAs render their content
asynchronously in a second pass. Reading immediately after navigate returns
only the skeleton — headers, nav, maybe a section label — not the actual data.

After ANY `browser_navigate`, EVERY subsequent `browser_get_text` or `browser_get_dom`
call MUST include `wait_for` set to a selector that only appears once the real content
is loaded. No exceptions. Even if you use a content selector, without `wait_for` you
still get whatever was present at DOM-ready, which may be a loading placeholder.

**Choosing `wait_for` by site:**
- YouTube:  `wait_for="ytd-video-renderer"` (or `ytd-rich-item-renderer` on home/trending)
- Reddit:   `wait_for="[data-testid=post-container]"` (NOT `wait_for=".Post"` — old Reddit only)
- Twitter:  `wait_for="article[data-testid=tweet]"`
- HN:       none needed (static HTML) but use `wait_for=".athing"` to be safe
- Generic:  `wait_for` the same selector you use for `selector=` — they should match

**"Loading…" / skeleton content = forgot `wait_for`:**
If `browser_get_text` returns any of these signals — treat it as a failed read and retry
WITH `wait_for`. Do NOT run `llm_transform` on loading skeletons; you will get hallucinated data:
- Text content is "Loading…", "Please wait", "Fetching…" or similar
- Response is under 100 characters when you expected a list of items
- Text has section labels but no actual items (e.g. "r/programming" with no post titles)
- Response has only timestamps or vote counts but no titles

Retry pattern when you detect a skeleton: add `wait_for` matching your target content selector
and call `browser_get_text` again in a new workflow step.

**Rule 8 — Need URLs/links? Use `browser_get_dom`, not `browser_get_text`.**
`browser_get_text` returns only visible characters — href attributes, data-ids,
and any other non-visible HTML are stripped out. If you extract URLs from plain
text you will get whatever text happened to look URL-like (timestamps, prices,
numbers) rather than the actual links.

Whenever you need to follow links, open a URL, or extract video/article URLs
from a list page: use `browser_get_dom(selector=<content-container>)` to get
the HTML with all href attributes intact. Then use `llm_transform` to pull
the actual href values from the HTML.

Example: YouTube history page text shows `36:18` (watch progress) next to a
video title — that looks like a video ID to a text-based extractor but it's
completely wrong. The DOM has `href="/watch?v=IYioA2SftyY"` — always extract
from DOM when URLs are what you need.

**Rule 9 — When a selector fails, discover the right one — never ask the user.**
If `browser_get_text(selector=X)` or `browser_get_dom(selector=X)` returns
`selector_not_found`, do NOT give up and ask the user. Instead:
  1. Call `browser_get_text()` with NO selector (gets full visible text)
  2. Call `llm_transform`: "What CSS selector targets [the thing]? Return {selector}"
  3. Retry with the discovered selector.

For known pages, navigate directly to the right URL first:
  YouTube history:    `https://youtube.com/feed/history`
  YouTube liked:      `https://youtube.com/playlist?list=LL`
  YouTube watch later:`https://youtube.com/playlist?list=WL`

**Rule 10 — No screenshots for content discovery.**
`browser_screenshot` is slow and expensive. Only use it if the user asks to
see the screen, or if text extraction has completely failed after 2 attempts.

---

## Examples — these show the pattern, not just YouTube

**Pattern 1 — Find the latest content on any site (direct URL approach):**
Infer the sort/filter URL parameter from the current page URL, then navigate.
Works on Reddit, GitHub, YouTube, Hacker News, news sites, etc.
```json
{"type": "sequential", "steps": [
  {"tool": "browser_get_active_tab", "store_result_as": "$tab"},
  {"tool": "browser_navigate",
   "args": {"url": "https://reddit.com/r/technology/new"}},
  {"tool": "browser_get_text",
   "args": {"tab_id": "$tab.id", "selector": "[data-testid=post-container], .Post, article"},
   "store_result_as": "$posts"},
  {"tool": "llm_transform",
   "args": {"context": "$posts",
            "prompt": "Return the top 5 posts as [{title, url, score}].",
            "schema": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "url": {"type": "string"}, "score": {"type": "string"}}}}},
   "store_result_as": "$top"}
]}
```

**Pattern 2 — Search a site's own search box and navigate to the best result:**
Fill the search box, submit, read results with a targeted selector, extract, navigate.
Works on any site with a search box.
```json
{"type": "sequential", "steps": [
  {"tool": "browser_get_active_tab", "store_result_as": "$tab"},
  {"tool": "browser_fill_input",
   "args": {"tab_id": "$tab.id",
            "selector": "input[type=search], input[name=q], input[name=search], input[placeholder*=Search]",
            "value": "query here"}},
  {"tool": "browser_click",
   "args": {"tab_id": "$tab.id",
            "selector": "button[type=submit], button[aria-label*=Search], [data-testid*=search-btn]"}},
  {"tool": "browser_get_text",
   "args": {"tab_id": "$tab.id", "selector": "main, #results, .results, [role=main], article"},
   "store_result_as": "$results"},
  {"tool": "llm_transform",
   "args": {"context": "$results",
            "prompt": "Extract the top results as [{title, url}]. Absolute URLs only.",
            "schema": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "url": {"type": "string"}}}}},
   "store_result_as": "$links"},
  {"tool": "browser_navigate", "args": {"url": "$links[0].url"}}
]}
```

**Pattern 3 — Read the current page and answer a question about it:**
Scope to the content container, never dump the whole page.
```json
{"type": "sequential", "steps": [
  {"tool": "browser_get_active_tab", "store_result_as": "$tab"},
  {"tool": "browser_get_text",
   "args": {"tab_id": "$tab.id", "selector": "main, article, [role=main], .content, #content"},
   "store_result_as": "$text"},
  {"tool": "llm_summarise",
   "args": {"context": "$text", "prompt": "Answer the user's question from this page content."}}
]}
```

**Pattern 4 — Fill a form and submit it (e.g. checkout, login, compose):**
Read the page first to confirm selectors exist, then fill and submit.
```json
{"type": "sequential", "steps": [
  {"tool": "browser_get_active_tab", "store_result_as": "$tab"},
  {"tool": "browser_fill_input",
   "args": {"tab_id": "$tab.id", "selector": "input[name=email], input[type=email]", "value": "user@example.com"}},
  {"tool": "browser_fill_input",
   "args": {"tab_id": "$tab.id", "selector": "textarea, input[name=message], input[name=body]", "value": "message here"}},
  {"tool": "browser_click",
   "args": {"tab_id": "$tab.id", "selector": "button[type=submit], .submit-btn, [data-testid*=submit]"}}
]}
```

**Pattern 5 — Navigate to a profile/creator page and get their latest content:**
Construct the URL, navigate, then read the page's JS data global — works on YouTube,
Twitter, Reddit, Instagram, or any SPA. Try the site-specific global first; fall back
to `browser_get_text(wait_for=...)` if no JS global is available.
```json
{"type": "sequential", "steps": [
  {"tool": "browser_get_active_tab", "store_result_as": "$tab"},
  {"tool": "browser_navigate",
   "args": {"url": "https://www.youtube.com/@JiDion/videos?view=0&sort=dd", "tab_id": "$tab.id"}},
  {"tool": "browser_get_page_var",
   "args": {"tab_id": "$tab.id", "var_path": "ytInitialData"},
   "store_result_as": "$data"},
  {"tool": "llm_transform",
   "args": {"context": "$data",
            "prompt": "Extract the first (most recent) video: title and full URL. Return {title, url}.",
            "schema": {"type": "object", "properties": {"title": {"type": "string"}, "url": {"type": "string"}}}},
   "store_result_as": "$latest"},
  {"tool": "browser_navigate", "args": {"url": "$latest.url", "tab_id": "$tab.id"}}
]}
```

**Pattern 6 — Monitor a value on a page for changes:**
Watch a specific element and fire an event when its text changes.
```json
{"type": "sequential", "steps": [
  {"tool": "browser_get_active_tab", "store_result_as": "$tab"},
  {"tool": "browser_watch_element",
   "args": {"tab_id": "$tab.id",
            "selector": ".price, [data-price], #price, [class*=price]",
            "event_name": "price_changed"}},
  {"store_result_as": "$watch"}
]}
```

**Pattern 7 — Selector discovery when you don't know the structure:**
Use this when you navigate to a page and aren't sure what selectors exist,
or when a targeted selector comes back `selector_not_found`. Read a chunk
of the page, extract the right selector from it, then retry.
```json
{"type": "sequential", "steps": [
  {"tool": "browser_get_active_tab", "store_result_as": "$tab"},
  {"tool": "browser_get_text",
   "args": {"tab_id": "$tab.id"},
   "store_result_as": "$raw"},
  {"tool": "llm_transform",
   "args": {"context": "$raw",
            "prompt": "I need to extract [the thing I'm looking for] from this page. What CSS selector targets those elements? Also extract the data if it's already here. Return {selector, items: [{title, url}]}",
            "schema": {"type": "object", "properties": {
              "selector": {"type": "string"},
              "items": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "url": {"type": "string"}}}}
            }}},
   "store_result_as": "$discovered"},
  {"tool": "browser_navigate", "args": {"url": "$discovered.items[0].url"}}
]}
```

**Pattern 8 — Read any SPA's embedded page data via a JS global (with drill-down):**
Works on YouTube, Twitter, Reddit, Next.js apps, Instagram, and thousands of others.
The root variable is often too_large — start one level deeper when you know the site.
DO NOT call llm_transform until you have an actual `value` (not a too_large object).

YouTube example (history, trending, search):
```json
{"type": "sequential", "steps": [
  {"tool": "browser_get_active_tab", "store_result_as": "$tab"},
  {"tool": "browser_navigate",
   "args": {"url": "https://www.youtube.com/feed/history", "tab_id": "$tab.id"}},
  {"tool": "browser_get_page_var",
   "args": {"tab_id": "$tab.id", "var_path": "ytInitialData.contents"},
   "store_result_as": "$contents"},
  {"tool": "browser_get_page_var",
   "args": {"tab_id": "$tab.id",
            "var_path": "ytInitialData.contents.twoColumnBrowseResultsRenderer.tabs"},
   "store_result_as": "$data"},
  {"tool": "llm_transform",
   "args": {"context": "$data",
            "prompt": "Extract the list of videos. Return [{title, url}] where url is /watch?v=<videoId>.",
            "schema": {"type": "array", "items": {"type": "object",
              "properties": {"title": {"type": "string"}, "url": {"type": "string"}}}}},
   "store_result_as": "$videos"}
]}
```
Key: drilling `ytInitialData.contents` → `ytInitialData.contents.twoColumnBrowseResultsRenderer.tabs`
gets you past the two most common too_large levels in one workflow.

**YouTube search results (ALWAYS use DOM — page_var is always too_large for search):**
```json
{"type": "sequential", "steps": [
  {"tool": "browser_navigate",
   "args": {"url": "https://www.youtube.com/results?search_query=python+asyncio+tutorial"}},
  {"tool": "browser_get_dom",
   "args": {"selector": "ytd-video-renderer",
            "wait_for": "ytd-video-renderer"},
   "store_result_as": "$results_html"},
  {"tool": "llm_transform",
   "args": {"context": "$results_html",
            "prompt": "Extract the first 5 videos. Return [{title, url}] where url is https://youtube.com/watch?v=<videoId>.",
            "schema": {"type": "array", "items": {"type": "object",
              "properties": {"title": {"type": "string"}, "url": {"type": "string"}}}}},
   "store_result_as": "$videos"}
]}
```

**YouTube channel latest video (try page_var, fall back to DOM after 2 too_large):**
```json
{"type": "sequential", "steps": [
  {"tool": "browser_navigate",
   "args": {"url": "https://www.youtube.com/@Fireship/videos?view=0&sort=dd"}},
  {"tool": "browser_get_dom",
   "args": {"selector": "ytd-rich-item-renderer",
            "wait_for": "ytd-rich-item-renderer"},
   "store_result_as": "$items_html"},
  {"tool": "llm_transform",
   "args": {"context": "$items_html",
            "prompt": "Extract the FIRST (most recent) video only. Return {title, url} where url is https://youtube.com/watch?v=<videoId>.",
            "schema": {"type": "object",
              "properties": {"title": {"type": "string"}, "url": {"type": "string"}}}},
   "store_result_as": "$latest"}
]}
```
Note: For channel pages, DOM is more reliable than page_var (which has too many nested too_large levels).

For unknown SPAs, try globals in order: `__NEXT_DATA__`, `__NUXT__`, `window.__INITIAL_STATE__`,
`window._sharedData`, `window.__r`. On first too_large, narrow immediately:
`"__NEXT_DATA__.props.pageProps"`, `"__NUXT__.data"`, etc.
If a drill-down attempt still returns too_large and you are in a synthesis turn:
call `workflow_orchestrator` again with the next narrowed path — do NOT respond to the user yet.

**Pattern 9 — Open-ended research across multiple URLs:**
Use this when there is no relevant tab open and you need to fetch content from multiple pages.
```json
{"type": "sequential", "steps": [
  {"tool": "browser_run_research",
   "args": {"urls": ["https://example.com/a", "https://example.com/b"], "query": "What is X?"},
   "store_result_as": "$research"},
  {"tool": "llm_summarise", "args": {"context": "$research", "prompt": "Answer the question from these sources."}}
]}
```

---

## AGI-level patterns — self-correcting, multi-step browser tasks

**Pattern 10 — Obstacle detection and automatic recovery:**
After navigating, ALWAYS check what page you landed on. If it's not the expected page
(consent banner, login redirect, 404, anti-bot challenge), handle it automatically.
DO NOT tell the user "the site blocked me" — try to recover first:
```
Obstacle detected → recovery action:
  Cookie/consent banner     → browser_click on "Accept all", "I agree", "Allow all", "ACCEPT"
  Login/auth redirect       → report to user (cannot log in automatically)
  404 / not found           → try a slightly different URL (drop query params, try www vs non-www)
  Anti-bot / JS challenge   → wait 3s (browser_wait), then retry get_text
  Empty content / Loading   → use wait_for= to wait for content element to appear
  Paywall / soft gate       → read whatever visible text is available, mention limitation
  Page redirect             → follow the redirect (the browser already followed it — read new URL)
```
Detection: after navigate, call browser_get_text with no selector. If text contains any of
["Before you continue", "Accept cookies", "Sign in to continue", "Please verify", "Access denied",
"403 Forbidden", "404 Not Found", "Just a moment"], apply the matching recovery action.

**Pattern 11 — Infinite scroll / load-more pages:**
Many feeds (Twitter, LinkedIn, Google News, Instagram, etc.) load content on scroll.
To get more items than are visible at load time:
```json
{"type": "sequential", "steps": [
  {"tool": "browser_navigate",
   "args": {"url": "https://twitter.com/home", "tab_id": "$tab.id"}},
  {"tool": "browser_get_text",
   "args": {"wait_for": "article[data-testid=tweet]", "selector": "article[data-testid=tweet]"},
   "store_result_as": "$batch1"},
  {"tool": "browser_scroll",
   "args": {"direction": "bottom", "tab_id": "$tab.id"}},
  {"tool": "browser_get_text",
   "args": {"wait_for": "article[data-testid=tweet]", "selector": "article[data-testid=tweet]"},
   "store_result_as": "$batch2"},
  {"tool": "llm_transform",
   "args": {"context": {"batch1": "$batch1", "batch2": "$batch2"},
            "prompt": "Combine and deduplicate all tweets. Return [{author, text, url}].",
            "schema": {"type": "array", "items": {"type": "object"}}}}
]}
```

**Pattern 12 — Web search → visit results → synthesise:**
For any "research and answer" task where the answer requires visiting multiple pages.
Use this instead of guessing — always get real current data.
```json
{"type": "sequential", "steps": [
  {"tool": "web_search",
   "args": {"query": "site-specific query here", "max_results": 5},
   "store_result_as": "$results"},
  {"tool": "llm_transform",
   "args": {"context": "$results",
            "prompt": "Pick the 3 most relevant URLs from these search results. Return [{url, reason}].",
            "schema": {"type": "array", "items": {"type": "object"}}},
   "store_result_as": "$urls"},
  {"type": "parallel", "steps": [
    {"tool": "web_fetch", "args": {"url": "$urls[0].url"}, "store_result_as": "$page1"},
    {"tool": "web_fetch", "args": {"url": "$urls[1].url"}, "store_result_as": "$page2"},
    {"tool": "web_fetch", "args": {"url": "$urls[2].url"}, "store_result_as": "$page3"}
  ]},
  {"tool": "llm_summarise",
   "args": {"context": {"page1": "$page1", "page2": "$page2", "page3": "$page3"},
            "prompt": "Answer the user's question accurately from these sources. Cite each claim."}}
]}
```

**Pattern 13 — Click-and-wait (SPA navigation via click, not URL):**
Some apps navigate by click (tabs, accordions, pagination). Use click + wait_for:
```json
{"type": "sequential", "steps": [
  {"tool": "browser_get_active_tab", "store_result_as": "$tab"},
  {"tool": "browser_click",
   "args": {"tab_id": "$tab.id", "selector": "[data-tab='videos'], button:text('Videos'), .tab-videos"}},
  {"tool": "browser_get_text",
   "args": {"tab_id": "$tab.id",
            "selector": ".video-list, [data-section=videos], #videos",
            "wait_for": ".video-list, [data-section=videos], #videos"},
   "store_result_as": "$videos"}
]}
```

**Pattern 14 — Fill a form, submit, and verify success:**
Always verify the action completed — check for a success message or URL change.
```json
{"type": "sequential", "steps": [
  {"tool": "browser_get_active_tab", "store_result_as": "$tab"},
  {"tool": "browser_fill_input",
   "args": {"tab_id": "$tab.id", "selector": "input[name=email]", "value": "USER_EMAIL"}},
  {"tool": "browser_fill_input",
   "args": {"tab_id": "$tab.id", "selector": "textarea[name=message], #message", "value": "MESSAGE"}},
  {"tool": "browser_click",
   "args": {"tab_id": "$tab.id", "selector": "button[type=submit], .submit, .send"}},
  {"tool": "browser_get_text",
   "args": {"tab_id": "$tab.id",
            "wait_for": ".success, .confirmation, [class*=success], [class*=confirm]",
            "find": "success OR sent OR confirmed OR thank"},
   "store_result_as": "$confirm"}
]}
```

**Pattern 15 — Screenshot + read + describe (vision + text combined):**
Take a screenshot for visual context, then also extract text for precise data.
Use screenshot ONLY for visual confirmation — always extract text for facts/data.
```json
{"type": "sequential", "steps": [
  {"tool": "browser_get_active_tab", "store_result_as": "$tab"},
  {"tool": "browser_screenshot", "args": {"tab_id": "$tab.id"}, "store_result_as": "$img"},
  {"tool": "browser_get_text",
   "args": {"tab_id": "$tab.id", "selector": "main, article, #content"},
   "store_result_as": "$text"},
  {"tool": "llm_summarise",
   "args": {"context": {"screenshot": "$img", "text": "$text"},
            "prompt": "Describe what you see and answer the user's question precisely using the text data."}}
]}
```

**Self-correction principle:**
If a tool call fails or returns unexpected content:
1. Analyse what the current page actually shows (screenshot or quick get_text with no selector)
2. Adapt — try a different selector, URL pattern, or approach
3. Never give up after one failed attempt
4. Never tell the user "the site blocked me" without first trying at least 2 recovery approaches
5. Only escalate to the user when genuinely stuck (login required, CAPTCHA, hard paywall)

---

<!-- chika:tool-reference:auto-start -->

<!-- This block is auto-generated from the live tool registry by
     scripts/sync_skill_docs.py. Don't hand-edit between the
     start/end markers — your changes will be overwritten.    -->

## Tool reference

_18 tools registered with the `browser` skill._

### `browser_click` · **requires approval**

Click a DOM element identified by a CSS selector.

**Args**:

- `selector` (string, **required**) — CSS selector for element to click
- `tab_id` (integer | null, optional) — Tab ID (null = active tab)

### `browser_close_tab` · **requires approval**

Close a browser tab by its ID.

**Args**:

- `tab_id` (integer, **required**) — ID of tab to close

### `browser_fill_input` · **requires approval**

Fill a form field or textarea with text.

**Args**:

- `selector` (string, **required**) — CSS selector for the input element
- `value` (string, **required**) — Text to enter (max 10,000 chars)
- `tab_id` (integer | null, optional) — Tab ID (null = active tab)

### `browser_get_active_tab`

Return just the currently focused browser tab.

*No parameters.*

### `browser_get_dom`

Return raw HTML of a tab or scoped element. Prefer browser_get_text for reading content — HTML can be huge. Always use `selector` to limit the response size.

**Args**:

- `tab_id` (integer | null, optional)
- `selector` (string | null, optional) — CSS selector (strongly recommended)

### `browser_get_element`

Read a single element's text, value, href, src, or named attribute.

**Args**:

- `selector` (string, **required**) — CSS selector (required)
- `tab_id` (integer | null, optional)
- `attribute` (string, optional) — Which attribute to read: 'text' (default), 'html', 'href', 'src', 'value', or any attribute name

### `browser_get_page_var`

Read a JavaScript variable from the page's live window context (world=MAIN). Most modern SPAs embed ALL page data as a JS global before any component renders — reading it is instant, structured, and never blocked by render timing. Try these per site: `ytInitialData` (YouTube), `__NEXT_DATA__` (Next.js/Vercel/Notion), `__NUXT__` (Nuxt), `window.__INITIAL_STATE__` (Twitter/X, many React apps), `window._sharedData` (Instagram), `window.__r` (Reddit), `digitalData` (analytics sites). If the value is too large, result has `keys_preview` — narrow with a more specific path (e.g. `__NEXT_DATA__.props.pageProps`) and call again. Prefer this over browser_get_text on any site that might have embedded JS data.

**Args**:

- `var_path` (string, **required**) — Dot/bracket property path, e.g. 'ytInitialData', '__NEXT_DATA__.props.pageProps', 'window.__INITIAL_STATE__.timeline'
- `tab_id` (integer | null, optional) — Tab ID (null = active tab)
- `max_bytes` (integer | null, optional) — Max response size in bytes (default 60000, max 300000)

### `browser_get_tabs`

List all open browser tabs (id, url, title, active, status).

*No parameters.*

### `browser_get_text`

Extract visible text from a browser tab. Use `selector` to scope to a specific element (e.g. 'main', 'article', '#price'). Use `find` to zoom into a large page: only lines containing that keyword are returned (plus 4 lines of context around each hit, separated by '...'). Use `wait_for` for SPAs (YouTube, React, etc.) that render content after page load — waits up to 10s for the selector to appear before extracting. This keeps context small on big pages — use it instead of dumping the whole page. Returns text, url, title, char_count, filtered (bool), keyword.

**Args**:

- `tab_id` (integer | null, optional) — Tab ID (null = active tab)
- `selector` (string | null, optional) — CSS selector to scope extraction
- `find` (string | null, optional) — Keyword to filter lines by — returns only matching lines + surrounding context. Use for large pages.
- `context_lines` (integer | null, optional) — Lines of context around each match (default 4, max 50). Increase to zoom out and see more of the page around a match.
- `wait_for` (string | null, optional) — CSS selector to wait for before extracting — use for SPAs e.g. 'ytd-video-renderer' on YouTube

### `browser_list_watches`

List all currently active DOM watches.

*No parameters.*

### `browser_navigate` · **requires approval**

Navigate a tab to a URL. Set new_tab=true to open in a new tab.

**Args**:

- `url` (string, **required**) — Destination URL (must be http/https)
- `tab_id` (integer | null, optional) — Tab to navigate (null = active tab)
- `new_tab` (boolean, optional) — Open in a new tab instead

### `browser_open_tab` · **requires approval**

Open a new browser tab.

**Args**:

- `url` (string, optional) — URL to open (default: about:blank)

### `browser_run_research`

Open multiple URLs in background tabs, extract their text, close the tabs, and return structured results ready for llm_summarise. Ideal for multi-source research in a single tool call.

**Args**:

- `urls` (array, **required**) — List of URLs to research (max 10)
- `query` (string, optional) — Research question (attached to results for context)

### `browser_screenshot`

Capture a PNG screenshot of a tab's viewport. The image is attached as a vision block so you can see it directly.

**Args**:

- `tab_id` (integer | null, optional) — Tab ID (null = active tab)

### `browser_scroll` · **requires approval**

Scroll a page up, down, left, right, or jump to top/bottom.

**Args**:

- `direction` (string, optional) — Scroll direction
- `amount` (integer, optional) — Pixels to scroll (ignored for top/bottom)
- `tab_id` (integer | null, optional)

### `browser_switch_tab` · **requires approval**

Switch focus to a different browser tab.

**Args**:

- `tab_id` (integer, **required**) — ID of tab to focus

### `browser_unwatch`

Cancel an active DOM watch by its watch_id.

**Args**:

- `watch_id` (string, **required**) — ID returned by browser_watch_element

### `browser_watch_element`

Watch a CSS selector for DOM text changes. When the element's content changes, a browser_watch_trigger event is fired to the chat. Returns a watch_id for cancellation.

**Args**:

- `selector` (string, **required**) — CSS selector to watch
- `event_name` (string, **required**) — Human-readable label for this watch (e.g. 'price_changed')
- `tab_id` (integer | null, optional) — Tab to watch (null = active tab)
- `debounce_ms` (integer, optional) — Debounce delay in ms (200–60000, default 1000)

<!-- chika:tool-reference:auto-end -->
