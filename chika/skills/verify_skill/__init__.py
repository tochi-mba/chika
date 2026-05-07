"""
verify_skill — grounding, verification, and retrieval tools.

Exposes:
  - verify_url(url)    — HTTP HEAD check so the agent can confirm a URL exists
                          before writing it into a file or opening it.
  - web_fetch(url)     — GET a URL and return its body as text (handles
                          redirects, caps size, tags source for grounding).
  - fact_check(claim)  — look up the claim in the session's $facts ledger.
"""
from __future__ import annotations

from chika.core.skill_registry import Skill
from chika.core.tool_registry import ToolDefinition

# Canonical name used by the engine's skill registry.
SKILL_NAME = "verify"


async def web_fetch(url: str, max_chars: int = 20000, timeout: float = 15.0, **_ignored) -> dict:
    """
    Fetch a URL and return its body as text. Much better than curl + file_read
    for most cases: follows redirects, handles encoding, caps size.
    Tags result with `_source: web_fetch` so the $facts ledger picks it up.

    **_ignored absorbs common arg mistakes (save_path=, output_file=, etc.)
    so the LLM reaching for them doesn't error — it just gets the body back.
    """
    try:
        import httpx
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; chika/2.0)",
                "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.1",
            })
            ct = resp.headers.get("content-type", "")
            final_url = str(resp.url)
            truncated = False
            # Only decode text-like content; binaries return a hint instead.
            if ct.startswith(("text/", "application/json", "application/xml", "application/xhtml")):
                body = resp.text or ""
                if len(body) > max_chars:
                    body = body[:max_chars]
                    truncated = True
            else:
                body = f"(binary content: {ct}, {len(resp.content)} bytes — use curl via shell_exec if you need raw bytes)"
            return {
                "_source": "web_fetch",
                "url": url,
                "final_url": final_url,
                "status": resp.status_code,
                "content_type": ct,
                "content": body,
                "truncated": truncated,
                "bytes": len(resp.content),
            }
    except Exception as exc:
        return {"_source": "web_fetch", "url": url, "error": str(exc)}


async def verify_url(url: str, timeout: float = 8.0) -> dict:
    """
    HEAD the URL. Returns status, content_type, reachable, and whether it
    redirected. Never raises — always returns a dict (errors become
    `reachable: False` + error text).
    """
    try:
        import httpx
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            # Prefer HEAD; some servers disallow it — fall back to GET with stream.
            try:
                resp = await client.head(url)
                if resp.status_code == 405:  # Method Not Allowed
                    raise ValueError("HEAD not allowed")
            except ValueError:
                resp = await client.get(url)
            final_url = str(resp.url)
            ct = resp.headers.get("content-type", "")
            return {
                "_source": "verify_url",
                "url": url,
                "final_url": final_url,
                "redirected": final_url != url,
                "status": resp.status_code,
                "content_type": ct,
                "reachable": 200 <= resp.status_code < 400,
                "is_image": ct.startswith("image/"),
                "is_html": ct.startswith("text/html"),
            }
    except Exception as exc:
        return {
            "_source": "verify_url",
            "url": url,
            "reachable": False,
            "error": str(exc),
        }


def _make_fact_check(variable_store):
    """
    Build a fact_check tool bound to the session's variable store, so it can
    read the live $facts ledger that workflow_engine populates after every
    fact-producing tool call.
    """
    import re as _re

    def _tokens(s: str) -> set[str]:
        return {w.lower() for w in _re.findall(r"[a-zA-Z0-9]{3,}", s or "")}

    async def fact_check(claim: str, min_overlap: int = 2) -> dict:
        """
        Search the $facts ledger for evidence supporting `claim`.
        Returns `supported: True` with the matching fact entries, or
        `supported: False` with a directive to go retrieve evidence.
        """
        var = variable_store.get("facts")
        ledger = var.value if (var and isinstance(var.value, list)) else []
        if not ledger:
            return {
                "_source": "fact_check",
                "claim": claim,
                "supported": False,
                "reason": "ledger_empty",
                "directive": (
                    "No tools have produced any facts this session. You MUST "
                    "run a tool (web_search, file_read, shell_exec) to gather "
                    "evidence before asserting this claim, or explicitly tell "
                    "the user you don't have grounded information."
                ),
            }
        claim_tokens = _tokens(claim)
        matches: list[dict] = []
        for fact in ledger:
            blob = " ".join(
                str(v) for k, v in fact.items()
                if k in ("snippet", "title", "url", "query", "command", "path")
            )
            overlap = len(claim_tokens & _tokens(blob))
            if overlap >= min_overlap:
                matches.append({**fact, "overlap": overlap})
        matches.sort(key=lambda f: -f["overlap"])
        supported = bool(matches)
        return {
            "_source": "fact_check",
            "claim": claim,
            "supported": supported,
            "matches": matches[:5],
            "reason": None if supported else "no_matching_fact_in_ledger",
            "directive": None if supported else (
                "No fact in the ledger supports this claim. Either retrieve "
                "evidence via a tool, or rephrase the answer to say you don't "
                "have grounded information on this."
            ),
        }

    return fact_check


def build_verify_skill(variable_store) -> Skill:
    """Factory — wires fact_check to the session's variable store."""
    fact_check = _make_fact_check(variable_store)
    return Skill(
        name="verify",
        description="URL reachability, page fetching, and claim grounding against the $facts ledger",
        tools=[
            ToolDefinition(
                name="web_fetch",
                description=(
                    "Fetch a URL and return its body as text. Handles redirects, "
                    "caps size at max_chars (default 20000). Prefer this over "
                    "`shell_exec` curl + `file_read` for reading web pages — "
                    "it's one call, handles encoding, and tags the source so "
                    "claims citing it can be grounded."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url":       {"type": "string", "description": "URL to fetch"},
                        "max_chars": {"type": "integer", "description": "Truncate body at this many chars (default 20000)"},
                        "timeout":   {"type": "number",  "description": "Seconds (default 15)"},
                    },
                    "required": ["url"],
                },
                handler=web_fetch,
            ),
            ToolDefinition(
                name="verify_url",
                description=(
                    "HEAD an URL and report status, content_type, and whether it is "
                    "reachable. ALWAYS use this before writing a URL into a file, "
                    "citing it to the user, or opening it."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The URL to check"},
                        "timeout": {"type": "number", "description": "Seconds (default 8)"},
                    },
                    "required": ["url"],
                },
                handler=verify_url,
            ),
            ToolDefinition(
                name="fact_check",
                description=(
                    "Look up whether a claim is supported by the $facts ledger "
                    "(facts automatically accumulated from web_search, file_read, "
                    "shell_exec, etc). Returns supported=True with matching fact "
                    "sources, or supported=False with a directive to go retrieve "
                    "evidence. Use this before asserting any factual claim to the "
                    "user when you're not 100% sure you just saw the evidence in "
                    "this turn."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "claim": {
                            "type": "string",
                            "description": "The factual claim to verify against retrieved evidence",
                        },
                        "min_overlap": {
                            "type": "integer",
                            "description": "Minimum token overlap to consider a fact a match (default 2)",
                        },
                    },
                    "required": ["claim"],
                },
                handler=fact_check,
            ),
        ],
        workflow_examples="",
    )


def build_skill(context):
    """Auto-discovery entry point. Wires fact_check to the session's
    variable store via the build context."""
    return build_verify_skill(context.variable_store)


INTENT_CASES: dict = {
    "plan": {
        "positive": [
            "build me a link-checker that verifies every URL in our docs daily",
        ],
        "negative": [
            "check if this URL is reachable",
            "fact-check this claim against what we've seen this turn",
            "fetch this page and summarise it",
        ],
    },
    "ask": {
        "positive": [
            "check if it's working",
            "verify the link",
        ],
        "negative": [
            "verify https://example.com is reachable",
            "fact-check the claim that openai released gpt-5",
            "fetch https://news.ycombinator.com",
        ],
    },
    # Research — verify is the canonical grounding skill, so almost
    # every "is this true / is this still up" question is positive.
    "research": {
        "positive": [
            "is openai's pricing page still showing $0.50 per 1M tokens",
            "verify the URL we cited in the last reply",
            "is this RSS feed still live",
            "does this changelog still show v3.5 as the latest",
        ],
        "negative": [
            "what's a good definition of latency",
            "explain what a CDN does",
        ],
    },
}
