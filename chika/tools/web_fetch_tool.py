from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from chika.core.tool_registry import ToolDefinition


async def web_fetch(url: str, save_path: str | None = None, max_size_kb: int = 2048) -> dict:
    """
    Download a URL using Python's requests library (no curl dependency).
    Returns the response status, headers, and either saves to file or returns text content.
    """
    try:
        import requests  # type: ignore[import-untyped]
    except ImportError:
        return {"error": "requests library not installed. Run: pip install requests"}

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        )

        content_type = response.headers.get("content-type", "")
        final_url = response.url if hasattr(response, "url") else url

        result: dict[str, Any] = {
            "url": str(final_url),
            "status_code": response.status_code,
            "content_type": content_type,
            "ok": response.status_code == 200,
        }

        if response.status_code != 200:
            result["error"] = f"HTTP {response.status_code}"
            result["body_preview"] = response.text[:500]
            return result

        # Binary content (images, etc.) — save to file or report size
        is_binary = any(t in content_type for t in ("image/", "application/octet", "audio/", "video/"))

        if save_path:
            if ".." in Path(save_path).parts:
                return {"error": f"save_path traversal not allowed: {save_path!r}"}
            p = Path(save_path).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            content = response.content
            max_bytes = max_size_kb * 1024
            if len(content) > max_bytes:
                content = content[:max_bytes]
                result["truncated"] = True
                result["original_size_bytes"] = len(response.content)
            p.write_bytes(content)
            result["saved_to"] = save_path
            result["size_bytes"] = len(content)
        elif is_binary:
            result["binary"] = True
            result["size_bytes"] = len(response.content)
            result["hint"] = "Binary content — provide save_path to save it to a file"
        else:
            text = response.text
            max_chars = max_size_kb * 1024
            if len(text) > max_chars:
                result["text"] = text[:max_chars]
                result["truncated"] = True
                result["total_chars"] = len(text)
                result["hint"] = "Response truncated. Provide save_path to save the full content then use file_read."
            else:
                result["text"] = text

        return result

    except requests.exceptions.Timeout:
        return {"error": f"Request timed out fetching {url}"}
    except requests.exceptions.ConnectionError as e:
        return {"error": f"Connection failed: {e}"}
    except Exception as e:
        return {"error": str(e)}


async def web_head(url: str) -> dict:
    """
    Send a HEAD request to check if a URL exists and what type it is.
    Use this to verify a URL before using it — checks status code and content-type.
    """
    try:
        import requests
    except ImportError:
        return {"error": "requests library not installed"}

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.head(url, headers=headers, timeout=10, allow_redirects=True)
        )
        content_type = response.headers.get("content-type", "")
        return {
            "url": str(response.url),
            "status_code": response.status_code,
            "content_type": content_type,
            "ok": response.status_code == 200,
            "is_image": content_type.startswith("image/"),
            "is_html": "text/html" in content_type,
        }
    except Exception as e:
        return {"error": str(e), "ok": False}


WEB_FETCH_TOOLS = [
    ToolDefinition(
        name="web_fetch",
        description=(
            "Download a URL using Python (no curl needed — works on all platforms). "
            "Use save_path to write to a file (e.g. '$chika.tmp/page.html'), then use file_read to read it in sections. "
            "Without save_path, returns text content directly (truncated if large). "
            "Returns status_code, content_type, ok (true if 200)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url":         {"type": "string",  "description": "URL to fetch"},
                "save_path":   {"type": "string",  "description": "File path to save the response to (recommended for HTML pages)"},
                "max_size_kb": {"type": "integer", "description": "Max KB to download (default 2048)"},
            },
            "required": ["url"],
        },
        handler=web_fetch,
    ),
    ToolDefinition(
        name="web_head",
        description=(
            "Check if a URL exists and what type it is (HEAD request — no download). "
            "Returns status_code, content_type, ok, is_image, is_html. "
            "Use this to verify a URL before embedding it in HTML or opening it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to check"},
            },
            "required": ["url"],
        },
        handler=web_head,
    ),
]
