# Web skill

For research and live-fact lookups. All results are auto-appended to the
`$facts` ledger so later turns can validate claims.

## Tools

| Tool          | Owner skill | Purpose                                                       |
|---------------|-------------|---------------------------------------------------------------|
| `web_search`  | **web**     | DuckDuckGo search. Pass `query`. Returns `{results: [...]}`.  |
| `web_fetch`   | verify      | GET a URL, return text + final URL + status.                  |
| `verify_url`  | verify      | HEAD/GET probe — checks reachability + content type.          |

> Note: `web_fetch` and `verify_url` are owned by the **verify** skill,
> not the web skill — call `skill_load(skill="verify")` if you also need
> their full reference. They're listed here because URL hygiene
> patterns naturally chain through both skills.

## When to use which

- **Live facts** (prices, news, today's date-sensitive info): always
  `web_search` first to find a source, then `web_fetch` to read it.
- **Validating a known URL** the user mentioned: `web_fetch`.
- **Probe before linking** the user to something: `web_head`.

## Pattern: search → read → cite
```json
{"type": "sequential", "steps": [
  {"tool": "web_search", "args": {"query": "Anthropic Claude 4.7 release notes"}, "store_result_as": "$hits"},
  {"tool": "web_fetch",  "args": {"url": "$hits.results[0].url"}, "store_result_as": "$page"}
]}
```

After this, every claim in your reply should reference the URL or a
`$facts` entry. Unsourced facts trigger the grounding validator.

## URL hygiene

- **Never construct URLs from memory.** Search → extract → `web_head` /
  `web_fetch` → use. Fabricated URLs trip the grounding validator and the
  user's "this is a real link?" detector.
- **Bare root domains** (`google.com`, `github.com`, `wikipedia.org`)
  don't need pre-verification. **Specific pages do** — always verify
  before citing a deep link.
- For structured extraction from a fetched page, pair `web_fetch` with
  `llm_transform` and a `schema` so the inner LLM returns predictable
  shape instead of free text.

## More patterns

### Search and summarise
```json
{"type": "sequential", "steps": [
  {"tool": "web_search", "args": {"query": "$search_query"},
   "store_result_as": "$results"},
  {"tool": "llm_summarise",
   "args": {"prompt": "Summarise key findings.",
            "context": {"results": "$results"}},
   "store_result_as": "$summary"}
]}
```

### Fetch a long page → locate the relevant section → read just that
For pages too long to fit in context, save to a temp file and binary-search
with `llm_transform`:
```json
{"type": "sequential", "steps": [
  {"tool": "web_fetch",
   "args": {"url": "$url", "save_path": "$chika.tmp/chika_page.html"},
   "store_result_as": "$fetch"},
  {"tool": "file_read",
   "args": {"path": "$chika.tmp/chika_page.html", "start_line": 1, "end_line": 80},
   "store_result_as": "$top"},
  {"tool": "llm_transform",
   "args": {"prompt": "What line range contains the answer? total_lines is in the result.",
            "context": "$top",
            "schema": {"start": "integer", "end": "integer"}},
   "store_result_as": "$range"},
  {"tool": "file_read",
   "args": {"path": "$chika.tmp/chika_page.html",
            "start_line": "$range.start", "end_line": "$range.end"},
   "store_result_as": "$section"}
]}
```

### Search → pick best URL → fetch → preview
```json
{"type": "sequential", "steps": [
  {"tool": "web_search", "args": {"query": "site query here"},
   "store_result_as": "$results"},
  {"tool": "llm_transform",
   "args": {"prompt": "Extract the best URL.", "context": "$results",
            "schema": {"url": "string"}},
   "store_result_as": "$page"},
  {"tool": "web_fetch",
   "args": {"url": "$page.url", "save_path": "$chika.tmp/chika_page.html"},
   "store_result_as": "$fetch"},
  {"tool": "file_read",
   "args": {"path": "$chika.tmp/chika_page.html",
            "start_line": 1, "end_line": 80},
   "store_result_as": "$preview"}
]}
```

### Probe a link before showing it to the user
The probe tool is `verify_url` (in the verify skill, not web):
```json
{"tool": "verify_url", "args": {"url": "$some_url"}, "store_result_as": "$check"}
```
Then check `$check.reachable` and `$check.status`.

---

<!-- chika:tool-reference:auto-start -->

<!-- This block is auto-generated from the live tool registry by
     scripts/sync_skill_docs.py. Don't hand-edit between the
     start/end markers — your changes will be overwritten.    -->

## Tool reference

_1 tool registered with the `web` skill._

### `web_search`

Search the web via DuckDuckGo. Returns title, url, snippet for each result.

**Args**:

- `query` (string, **required**) — Search query
- `max_results` (integer, optional) — Max results (default 8)

<!-- chika:tool-reference:auto-end -->
