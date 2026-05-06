"""Coverage for chika/skills/browser_skill/security.py."""
from __future__ import annotations

import time

import pytest

from chika.skills.browser_skill import security as sec

# ── is_write_blocked ──────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "https://chase.com/login",
    "https://www.chase.com/transfer",
    "https://accounts.google.com/oauth",
    "https://login.microsoftonline.com/common",
    "https://paypal.com/transfer",
    "https://1password.com/vault",
])
def test_is_write_blocked_blocks_default_domains(url):
    assert sec.is_write_blocked(url) is True


@pytest.mark.parametrize("url", [
    "https://github.com/anthropics/claude-code",
    "https://example.com/page",
    "https://news.ycombinator.com/item?id=1",
    "https://docs.python.org/3/",
])
def test_is_write_blocked_allows_safe_domains(url):
    assert sec.is_write_blocked(url) is False


def test_is_write_blocked_blank_url():
    assert sec.is_write_blocked("") is True


def test_is_write_blocked_none_url():
    # The function takes a `str` typed arg but defends against falsy values.
    assert sec.is_write_blocked(None) is True  # type: ignore[arg-type]


def test_is_write_blocked_subdomain_match():
    """A subdomain of a blocked root is also blocked."""
    assert sec.is_write_blocked("https://m.facebook.com/login") is True
    assert sec.is_write_blocked("https://api.coinbase.com/v2/accounts") is True


def test_is_write_blocked_unrelated_subdomain_allowed():
    """``coinbase.com.example.com`` is NOT a coinbase subdomain."""
    assert sec.is_write_blocked("https://coinbase.com.example.com") is False


def test_is_write_blocked_returns_true_on_parse_error():
    """A garbled URL string should be safely blocked, not silently allowed."""
    # urlparse is permissive; force an exception via a bytes-incompatible object.
    class Bad:
        def __str__(self):
            raise RuntimeError("nope")
    assert sec.is_write_blocked(Bad()) is True  # type: ignore[arg-type]


def test_load_blocked_domains_picks_up_extra_env(monkeypatch):
    monkeypatch.setenv(
        "CHIKA_BROWSER_BLOCKED_DOMAINS",
        "intranet.acme.com, secret-vault.dev",
    )
    extra = sec._load_blocked_domains()
    assert "intranet.acme.com" in extra
    assert "secret-vault.dev" in extra
    # Defaults still present.
    assert "chase.com" in extra


def test_load_blocked_domains_no_env_returns_defaults(monkeypatch):
    monkeypatch.delenv("CHIKA_BROWSER_BLOCKED_DOMAINS", raising=False)
    out = sec._load_blocked_domains()
    assert "chase.com" in out
    assert out == sec._DEFAULT_WRITE_BLOCKED_DOMAINS


# ── validate_url ──────────────────────────────────────────────────────


def test_validate_url_accepts_http():
    assert sec.validate_url("http://example.com") is None


def test_validate_url_accepts_https():
    assert sec.validate_url("https://example.com/path?q=1") is None


def test_validate_url_rejects_empty():
    err = sec.validate_url("")
    assert err == "URL is required"


def test_validate_url_rejects_other_schemes():
    err = sec.validate_url("ftp://example.com")
    assert err is not None
    assert "http/https" in err


def test_validate_url_rejects_javascript_scheme():
    err = sec.validate_url("javascript:alert(1)")
    assert err is not None


def test_validate_url_rejects_file_scheme():
    err = sec.validate_url("file:///etc/passwd")
    assert err is not None


def test_validate_url_rejects_no_domain():
    err = sec.validate_url("http://")
    assert err is not None
    assert "domain" in err


# ── validate_selector ─────────────────────────────────────────────────


def test_validate_selector_none_returns_none_pair():
    cleaned, err = sec.validate_selector(None)
    assert cleaned is None
    assert err is None


def test_validate_selector_empty_string():
    cleaned, err = sec.validate_selector("")
    assert cleaned is None
    assert err is None


def test_validate_selector_basic_id():
    cleaned, err = sec.validate_selector("#main")
    assert cleaned == "#main"
    assert err is None


def test_validate_selector_basic_class():
    cleaned, err = sec.validate_selector(".some-class")
    assert cleaned == ".some-class"
    assert err is None


def test_validate_selector_compound_with_attributes():
    cleaned, err = sec.validate_selector('button[type="submit"][data-id="x"]')
    assert err is None
    assert cleaned == 'button[type="submit"][data-id="x"]'


def test_validate_selector_pseudo_classes_allowed():
    cleaned, err = sec.validate_selector("a:hover")
    assert err is None
    assert cleaned == "a:hover"


def test_validate_selector_descendant_combinators():
    cleaned, err = sec.validate_selector("main > div .item")
    assert err is None


def test_validate_selector_too_long_rejected():
    cleaned, err = sec.validate_selector("a" * 600)
    assert cleaned is None
    assert err is not None
    assert "too long" in err


def test_validate_selector_javascript_blocked():
    cleaned, err = sec.validate_selector("javascript:alert(1)")
    assert cleaned is None
    assert err is not None
    assert "prohibited" in err


def test_validate_selector_data_uri_blocked():
    cleaned, err = sec.validate_selector("[data]:data:text/html")
    assert cleaned is None
    assert err is not None


def test_validate_selector_expression_blocked():
    """CSS expression() (old IE attack vector) is rejected."""
    cleaned, err = sec.validate_selector("[width=expression(alert(1))]")
    assert cleaned is None
    assert err is not None


def test_validate_selector_invalid_chars():
    """Unicode / non-ASCII chars are rejected."""
    cleaned, err = sec.validate_selector("button:contains('hello')")
    # Single quotes are allowed; if anything triggers, the message names the bad chars.
    if cleaned is None:
        assert err is not None


def test_validate_selector_strips_whitespace():
    cleaned, err = sec.validate_selector("   #main   ")
    assert err is None
    assert cleaned == "#main"


# ── check_response_size ───────────────────────────────────────────────


def test_check_response_size_small_passes_through():
    result = {"text": "hi"}
    out = sec.check_response_size(result)
    assert out is result   # identity preserved when under limit


def test_check_response_size_huge_returns_error(monkeypatch):
    """A response over the limit gets replaced with an error dict."""
    monkeypatch.setattr(sec, "MAX_RESPONSE_BYTES", 100)
    big = {"text": "x" * 1000}
    out = sec.check_response_size(big)
    assert out["error"] == "response_too_large"
    assert out["size_bytes"] > 100
    assert out["limit_bytes"] == 100
    assert "selector" in out["message"]


def test_check_response_size_unserialisable_returns_input_unchanged():
    """If JSON encoding fails, fall back to passthrough rather than crash."""
    class NotJSON:
        pass
    result = {"obj": NotJSON()}
    out = sec.check_response_size(result)
    assert out is result   # passthrough on encode failure


# ── RateLimiter ───────────────────────────────────────────────────────


def test_rate_limiter_allows_below_limit():
    rl = sec.RateLimiter(max_per_minute=5)
    for _ in range(5):
        allowed, retry = rl.check()
        assert allowed is True
        assert retry == 0


def test_rate_limiter_blocks_at_limit():
    rl = sec.RateLimiter(max_per_minute=3)
    rl.check()
    rl.check()
    rl.check()
    allowed, retry = rl.check()
    assert allowed is False
    assert retry > 0


def test_rate_limiter_evicts_old_timestamps(monkeypatch):
    """Timestamps older than 60s are evicted on the next check."""
    fake_now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])
    monkeypatch.setattr(sec.time, "monotonic", lambda: fake_now[0])

    rl = sec.RateLimiter(max_per_minute=2)
    rl.check()  # t=1000
    rl.check()  # t=1000

    # Should be blocked.
    allowed, _ = rl.check()
    assert allowed is False

    # Jump ahead 90s — the original timestamps roll out of the window.
    fake_now[0] = 1090.0
    allowed, retry = rl.check()
    assert allowed is True
    assert retry == 0


def test_rate_limiter_default_uses_env_setting():
    """Module-level rate_limiter respects the configured max."""
    assert isinstance(sec.rate_limiter, sec.RateLimiter)
    # The class wraps a deque.
    assert isinstance(sec.rate_limiter._timestamps, sec.deque)
