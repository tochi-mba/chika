"""
Browser skill security helpers.

Defense-in-depth:
  1. Backend validates before sending any command to the extension.
  2. Extension re-validates in its own security.js (never trust network alone).
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

# ── Domain blocklist ──────────────────────────────────────────────────────────
# Write actions (navigate, click, fill, etc.) are ALWAYS blocked on these
# domains regardless of user approval.  Read actions (get_text, screenshot)
# are permitted so Claude can read page state to advise the user.
_DEFAULT_WRITE_BLOCKED_DOMAINS: frozenset[str] = frozenset({
    # Financial / payments
    "bankofamerica.com",
    "chase.com",
    "wellsfargo.com",
    "citibank.com",
    "hsbc.com",
    "paypal.com",
    "stripe.com",
    "braintreegateway.com",
    "coinbase.com",
    "binance.com",
    "kraken.com",
    # Authentication portals
    "accounts.google.com",
    "login.microsoftonline.com",
    "login.live.com",
    "appleid.apple.com",
    "auth.apple.com",
    "login.yahoo.com",
    "facebook.com",
    "instagram.com",
    # Password managers
    "lastpass.com",
    "1password.com",
    "bitwarden.com",
    "dashlane.com",
})


def _load_blocked_domains() -> frozenset[str]:
    """Merge the default list with any extra domains from env var.

    CHIKA_BROWSER_BLOCKED_DOMAINS=example.com,other.net
    """
    extra = os.getenv("CHIKA_BROWSER_BLOCKED_DOMAINS", "")
    extras = {d.strip().lower() for d in extra.split(",") if d.strip()}
    return _DEFAULT_WRITE_BLOCKED_DOMAINS | extras


WRITE_BLOCKED_DOMAINS = _load_blocked_domains()


def is_write_blocked(url: str) -> bool:
    """Return True if write actions are blocked on this URL."""
    if not url:
        return True  # block blank / empty
    try:
        host = urlparse(url).hostname or ""
        host = host.lower()
        for blocked in WRITE_BLOCKED_DOMAINS:
            if host == blocked or host.endswith("." + blocked):
                return True
        return False
    except Exception:
        return True  # block on parse error


# ── URL validation ────────────────────────────────────────────────────────────

def validate_url(url: str) -> str | None:
    """Return None if URL is valid for navigation, error string otherwise."""
    if not url:
        return "URL is required"
    try:
        parsed = urlparse(url)
    except Exception:
        return "Malformed URL"
    if parsed.scheme not in ("http", "https"):
        return f"Only http/https URLs are supported (got: {parsed.scheme!r})"
    if not parsed.netloc:
        return "URL must include a domain"
    return None


# ── Selector sanitization ─────────────────────────────────────────────────────
# Allow standard CSS selector characters. Reject anything that looks like
# JS injection or script content.
_SAFE_SELECTOR_RE = re.compile(
    r'^[a-zA-Z0-9\s\-_#\.\[\]"\'=:(),>+~\*\^\$\|@/]+$'
)
MAX_SELECTOR_LEN = 500


_SELECTOR_BLOCKLIST = re.compile(
    r'javascript:|vbscript:|data:|expression\s*\(|@import|url\s*\(',
    re.IGNORECASE,
)


def validate_selector(selector: str | None) -> tuple[str | None, str | None]:
    """Return (cleaned_selector, error_message).

    error_message is None on success.
    """
    if selector is None:
        return None, None
    selector = selector.strip()
    if not selector:
        return None, None
    if len(selector) > MAX_SELECTOR_LEN:
        return None, f"Selector too long (max {MAX_SELECTOR_LEN} chars)"
    # Block script injection patterns
    if _SELECTOR_BLOCKLIST.search(selector):
        return None, f"Selector contains prohibited content: {selector!r}"
    if not _SAFE_SELECTOR_RE.match(selector):
        bad = re.sub(r'[a-zA-Z0-9\s\-_#\.\[\]"\'=:(),>+~\*\^\$\|@/]', '', selector)
        return None, f"Selector contains invalid characters: {bad!r}"
    return selector, None


# ── Response size limits ──────────────────────────────────────────────────────

MAX_RESPONSE_BYTES = int(os.getenv("CHIKA_BROWSER_MAX_RESPONSE_BYTES", str(2 * 1024 * 1024)))  # 2 MB


def check_response_size(result: dict) -> dict:
    """If result JSON exceeds MAX_RESPONSE_BYTES, replace with an error dict."""
    import json
    try:
        size = len(json.dumps(result).encode())
    except Exception:
        return result
    if size > MAX_RESPONSE_BYTES:
        return {
            "error":        "response_too_large",
            "size_bytes":   size,
            "limit_bytes":  MAX_RESPONSE_BYTES,
            "message": (
                f"Response is {size // 1024}KB, which exceeds the {MAX_RESPONSE_BYTES // 1024}KB limit. "
                "Use the `selector` parameter to scope the query to a specific element."
            ),
        }
    return result


# ── Rate limiting (simple in-memory token bucket) ─────────────────────────────

import time
from collections import deque

MAX_ACTIONS_PER_MINUTE = int(os.getenv("CHIKA_BROWSER_RATE_LIMIT", "60"))


class RateLimiter:
    def __init__(self, max_per_minute: int = MAX_ACTIONS_PER_MINUTE) -> None:
        self._max = max_per_minute
        self._timestamps: deque[float] = deque()

    def check(self) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.monotonic()
        cutoff = now - 60.0
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._max:
            oldest = self._timestamps[0]
            retry_after = int(60 - (now - oldest)) + 1
            return False, retry_after
        self._timestamps.append(now)
        return True, 0


# Module-level rate limiter shared across all browser tool calls.
rate_limiter = RateLimiter()
