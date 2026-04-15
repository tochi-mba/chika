from __future__ import annotations
from chika.core.skill_registry import Skill
from chika.core.tool_registry import ToolDefinition


import re as _re

def _simplify_query(query: str) -> str | None:
    """Strip site:, filetype:, inurl: etc. and return a simpler query. Returns None if nothing to strip."""
    simplified = _re.sub(r'\b\w+:[^\s]+', '', query).strip()
    # Also strip boolean operators that might restrict results
    simplified = _re.sub(r'\s+(OR|AND)\s+', ' ', simplified).strip()
    simplified = _re.sub(r'\s+', ' ', simplified).strip()
    return simplified if simplified and simplified != query else None


async def web_search(query: str, max_results: int = 8) -> dict:
    """
    Search the web. Every returned payload carries `_source: "web_search"` so
    the agent (and any downstream meta-tool) can verify the context came from
    an actual retrieval and not from training-data recall.

    On 0 results, returns `count: 0` explicitly so the caller sees the
    empty state and either retries with a simpler query or informs the user.
    """
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        if not results:
            # Auto-retry with a simplified query (strips site:, filetype:, etc.)
            fallback = _simplify_query(query)
            if fallback:
                with DDGS() as ddgs:
                    results = list(ddgs.text(fallback, max_results=max_results))
                if results:
                    return {
                        "_source": "web_search",
                        "query": fallback,
                        "original_query": query,
                        "retry_reason": "Original query returned 0 results — retried without filters",
                        "results": [
                            {"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")}
                            for r in results
                        ],
                        "count": len(results),
                    }

        return {
            "_source": "web_search",
            "query": query,
            "results": [
                {"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")}
                for r in results
            ],
            "count": len(results),
            # Explicit instruction the LLM can (and should) read before citing.
            "_grounding": (
                "These results are the ONLY grounded facts for this query. "
                "If count==0, do not synthesize — say 'no results found' and retry "
                "with a simpler query, or ask the user."
            ) if results else (
                "0 results. Do NOT call llm_transform on this payload — it will "
                "fabricate. Retry with a simpler query or tell the user nothing "
                "was found."
            ),
        }
    except Exception as exc:
        return {
            "_source": "web_search",
            "error": str(exc),
            "query": query,
            "results": [],
            "count": 0,
        }


WEB_SKILL = Skill(
    name="web",
    description="Web search (DuckDuckGo) and page fetching",
    tools=[
        ToolDefinition(
            name="web_search",
            description="Search the web via DuckDuckGo. Returns title, url, snippet for each result.",
            parameters={
                "type": "object",
                "properties": {
                    "query":       {"type": "string",  "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Max results (default 8)"},
                },
                "required": ["query"],
            },
            handler=web_search,
        ),
    ],
    workflow_examples="""
### Web Research Workflows

**Search and summarise:**
```json
{"type": "sequential", "steps": [
  {"tool": "web_search", "args": {"query": "$search_query"}, "store_result_as": "$results"},
  {"tool": "llm_summarise",
   "args": {"prompt": "Summarise key findings.", "context": {"results": "$results"}},
   "store_result_as": "$summary"}
]}
```

**Fetch a page with curl — save to temp file — read in sections:**
```json
{"type": "sequential", "steps": [
  {"tool": "shell_exec", "args": {"command": "curl -sL \"$url\" -o /tmp/chika_page.html"}, "store_result_as": "$fetch"},
  {"tool": "shell_exec", "args": {"command": "wc -l /tmp/chika_page.html"}, "store_result_as": "$wc"},
  {"tool": "file_read", "args": {"path": "/tmp/chika_page.html", "start_line": 1, "end_line": 80}, "store_result_as": "$top"},
  {"tool": "llm_transform", "args": {"prompt": "What line range contains the answer?", "context": "$top", "schema": {"start": "integer", "end": "integer"}}, "store_result_as": "$range"},
  {"tool": "file_read", "args": {"path": "/tmp/chika_page.html", "start_line": "$range.start", "end_line": "$range.end"}, "store_result_as": "$section"}
]}
```

**Search → get URL → fetch → read:**
```json
{"type": "sequential", "steps": [
  {"tool": "web_search", "args": {"query": "site query here"}, "store_result_as": "$results"},
  {"tool": "llm_transform", "args": {"prompt": "Extract the best URL.", "context": "$results", "schema": {"url": "string"}}, "store_result_as": "$page"},
  {"tool": "shell_exec", "args": {"command": "curl -sL \"$page.url\" -o /tmp/chika_page.html && echo ok"}, "store_result_as": "$fetch"},
  {"tool": "file_read", "args": {"path": "/tmp/chika_page.html", "start_line": 1, "end_line": 80}, "store_result_as": "$preview"}
]}
```
""",
)
