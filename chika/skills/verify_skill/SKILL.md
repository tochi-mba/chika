# Verify skill

Anti-hallucination grounding tools. Every retrieval auto-appends to the
`$facts` ledger so the post-response validator can fail-fast on any
URL/claim that wasn't actually fetched this session.

## Tools

| Tool         | Purpose                                                       |
|--------------|---------------------------------------------------------------|
| `web_fetch`  | GET a URL, return body text + final URL + status. Auto-feeds `$facts`. Use this whenever you need to read the actual page content. |
| `verify_url` | HEAD/GET probe. Returns reachability, status, final URL, content-type. Auto-feeds `$facts`. Use before citing or `app_open`-ing a URL. |
| `fact_check` | Compare a claim string against the `$facts` ledger. Returns `supported: bool`, matches, and a confidence score.  |

## When to use

- **Before citing a URL**: run `verify_url` so the URL lands in `$facts`. The
  post-response validator only flags ungrounded URLs — anything in the
  ledger is considered grounded.
- **After making a strong factual claim**: run `fact_check` to confirm
  something earlier in the conversation supports it.

## Pattern

Probe a URL (cheap, just HEAD/GET status):
```json
{"tool": "verify_url", "args": {"url": "https://docs.python.org/3/library/asyncio.html"}}
```

Fetch and read body text:
```json
{"tool": "web_fetch", "args": {"url": "$candidate.url", "max_chars": 8000},
 "store_result_as": "$page"}
```

After both, the URL is in `$facts` — citing it in your reply will not
trip the grounding validator.

## Common kwarg slips

The agent occasionally writes `link=` or `target=` instead of `url=` for
both tools. Both `verify_url` and `web_fetch` strictly require `url`;
the dispatcher rejects unknown kwargs with a clear error rather than
silently absorbing them. **Always use `url`.**

---

## Reference patterns (migrated from workflow_examples)

### Grounding & Verification

**Verify a URL before opening or citing it:**
```json
{"type": "sequential", "steps": [
  {"tool": "verify_url", "args": {"url": "$candidate.url"}, "store_result_as": "$check"},
  {"type": "conditional",
   "condition": {"field": "$check.reachable", "operator": "equals", "value": true},
   "if_true": {"tool": "app_open", "args": {"target": "$candidate.url"}},
   "if_false": {"tool": "web_search", "args": {"query": "$retry_query"}}
  }
]}
```

**Fact-check a claim before stating it:**
```json
{"type": "sequential", "steps": [
  {"tool": "fact_check",
   "args": {"claim": "The most popular dessert at Legends is Loaded Waffles"},
   "store_result_as": "$check"},
  {"type": "conditional",
   "condition": {"field": "$check.supported", "operator": "equals", "value": true},
   "if_true": {"tool": "llm_summarise",
               "args": {"prompt": "Draft a reply citing these supporting facts.",
                        "context": "$check.matches"}},
   "if_false": {"tool": "web_search",
                "args": {"query": "Legends Dessert and Burger Bar popular dessert"},
                "store_result_as": "$results"}
  }
]}
```

---

<!-- chika:tool-reference:auto-start -->

<!-- This block is auto-generated from the live tool registry by
     scripts/sync_skill_docs.py. Don't hand-edit between the
     start/end markers — your changes will be overwritten.    -->

## Tool reference

_3 tools registered with the `verify` skill._

### `fact_check`

Look up whether a claim is supported by the $facts ledger (facts automatically accumulated from web_search, file_read, shell_exec, etc). Returns supported=True with matching fact sources, or supported=False with a directive to go retrieve evidence. Use this before asserting any factual claim to the user when you're not 100% sure you just saw the evidence in this turn.

**Args**:

- `claim` (string, **required**) — The factual claim to verify against retrieved evidence
- `min_overlap` (integer, optional) — Minimum token overlap to consider a fact a match (default 2)

### `verify_url`

HEAD an URL and report status, content_type, and whether it is reachable. ALWAYS use this before writing a URL into a file, citing it to the user, or opening it.

**Args**:

- `url` (string, **required**) — The URL to check
- `timeout` (number, optional) — Seconds (default 8)

### `web_fetch`

Fetch a URL and return its body as text. Handles redirects, caps size at max_chars (default 20000). Prefer this over `shell_exec` curl + `file_read` for reading web pages — it's one call, handles encoding, and tags the source so claims citing it can be grounded.

**Args**:

- `url` (string, **required**) — URL to fetch
- `max_chars` (integer, optional) — Truncate body at this many chars (default 20000)
- `timeout` (number, optional) — Seconds (default 15)

<!-- chika:tool-reference:auto-end -->
