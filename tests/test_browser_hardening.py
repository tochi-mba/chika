"""Tests for browser-skill hardening: selector cascade + idempotency."""
from __future__ import annotations

import pytest

from chika.skills.browser_skill import idempotency, selectors


# ── Selector cascade ─────────────────────────────────────────────────


def test_candidate_specs_always_includes_css_first():
    out = selectors.candidate_specs("button.btn-primary")
    assert out[0].strategy == "css"
    assert out[0].selector == "button.btn-primary"


def test_candidate_specs_for_label_emits_aria_variant():
    out = selectors.candidate_specs('button[aria-label="Submit"]')
    strategies = [s.strategy for s in out]
    assert "aria" in strategies


def test_candidate_specs_for_id_derives_label():
    """An id like #sign-in suggests a 'sign in' label for the ARIA fallback."""
    out = selectors.candidate_specs("button#sign-in")
    aria = next((s for s in out if s.strategy == "aria"), None)
    assert aria is not None
    assert "sign in" in aria.selector.lower()


def test_candidate_specs_emits_text_variant_when_label_present():
    out = selectors.candidate_specs('a[title="Sign in"]')
    text = next((s for s in out if s.strategy == "text"), None)
    assert text is not None
    assert "Sign in" in text.selector


def test_candidate_specs_pure_class_selector_has_no_label():
    out = selectors.candidate_specs(".btn-primary")
    # Only CSS — no label cue
    assert all(s.strategy == "css" for s in out)


def test_aria_variant_uses_case_insensitive_match():
    """ARIA labels should match case-insensitively; class churn often
    flips capitalisation."""
    aria = selectors.aria_variant('button[aria-label="Submit"]')
    assert aria is not None
    assert " i]" in aria  # CSS attr selector case-insensitive flag


def test_text_variant_returns_none_when_no_label():
    assert selectors.text_variant("div.something") is None


def test_aria_variant_returns_none_when_no_label():
    assert selectors.aria_variant(".btn") is None


# ── Resolution cache ─────────────────────────────────────────────────


def test_remember_recall_resolution_round_trip():
    selectors._cache._d.clear()  # reset for test isolation
    spec = selectors.SelectorSpec(selector="button#fixed-id", strategy="aria")
    selectors.remember_resolution("https://x.test/page", "button.broken", spec)
    out = selectors.recall_resolution("https://x.test/page", "button.broken")
    assert out == spec


def test_recall_returns_none_for_unknown():
    selectors._cache._d.clear()
    assert selectors.recall_resolution("https://x.test/", "nope") is None


def test_clear_cache_for_url_drops_only_that_url():
    selectors._cache._d.clear()
    spec = selectors.SelectorSpec(selector="x", strategy="css")
    selectors.remember_resolution("https://a.test/", "sel", spec)
    selectors.remember_resolution("https://b.test/", "sel", spec)
    assert selectors.cache_size() == 2
    selectors.clear_cache_for_url("https://a.test/")
    assert selectors.cache_size() == 1
    assert selectors.recall_resolution("https://a.test/", "sel") is None
    assert selectors.recall_resolution("https://b.test/", "sel") == spec


def test_cache_evicts_oldest_at_capacity():
    selectors._cache._d.clear()
    cache = selectors._LRUCache(maxsize=2)
    spec = selectors.SelectorSpec(selector="x", strategy="css")
    cache.put(("u", "a"), spec)
    cache.put(("u", "b"), spec)
    cache.put(("u", "c"), spec)  # evicts ("u","a")
    assert cache.get(("u", "a")) is None
    assert cache.get(("u", "b")) is not None
    assert cache.get(("u", "c")) is not None


# ── Idempotency cache ────────────────────────────────────────────────


def test_idempotency_key_stable_across_arg_order():
    """Same args, different dict insertion order → same key."""
    a = idempotency.IdempotencyKey.from_call(
        tab_id=1, action="click", args={"selector": ".btn", "force": True},
    )
    b = idempotency.IdempotencyKey.from_call(
        tab_id=1, action="click", args={"force": True, "selector": ".btn"},
    )
    assert a == b


def test_idempotency_key_changes_with_args():
    a = idempotency.IdempotencyKey.from_call(
        tab_id=1, action="click", args={"selector": ".a"},
    )
    b = idempotency.IdempotencyKey.from_call(
        tab_id=1, action="click", args={"selector": ".b"},
    )
    assert a != b


def test_idempotency_key_changes_with_tab():
    a = idempotency.IdempotencyKey.from_call(tab_id=1, action="click", args={})
    b = idempotency.IdempotencyKey.from_call(tab_id=2, action="click", args={})
    assert a != b


def test_idempotency_cache_returns_cached_within_window():
    cache = idempotency.IdempotencyCache(ttl_seconds=10)
    key = idempotency.IdempotencyKey.from_call(tab_id=1, action="click", args={})
    cache.put(key, "result", now=100.0)
    assert cache.get(key, now=109.0) == "result"


def test_idempotency_cache_expires_after_ttl():
    cache = idempotency.IdempotencyCache(ttl_seconds=10)
    key = idempotency.IdempotencyKey.from_call(tab_id=1, action="click", args={})
    cache.put(key, "result", now=100.0)
    assert cache.get(key, now=200.0) is None


def test_idempotency_cache_miss_returns_none():
    cache = idempotency.IdempotencyCache()
    key = idempotency.IdempotencyKey.from_call(tab_id=1, action="click", args={})
    assert cache.get(key) is None


def test_idempotency_cache_evicts_oldest():
    cache = idempotency.IdempotencyCache(ttl_seconds=99999, maxsize=2)
    k1 = idempotency.IdempotencyKey.from_call(tab_id=1, action="a", args={})
    k2 = idempotency.IdempotencyKey.from_call(tab_id=1, action="b", args={})
    k3 = idempotency.IdempotencyKey.from_call(tab_id=1, action="c", args={})
    cache.put(k1, "1", now=0)
    cache.put(k2, "2", now=0)
    cache.put(k3, "3", now=0)
    # k1 evicted (LRU)
    assert cache.get(k1, now=0) is None
    assert cache.get(k2, now=0) == "2"
    assert cache.get(k3, now=0) == "3"


def test_idempotency_cache_prune_removes_expired():
    cache = idempotency.IdempotencyCache(ttl_seconds=10)
    k1 = idempotency.IdempotencyKey.from_call(tab_id=1, action="a", args={})
    k2 = idempotency.IdempotencyKey.from_call(tab_id=1, action="b", args={})
    cache.put(k1, "1", now=0)
    cache.put(k2, "2", now=20)
    assert cache.prune(now=15) == 1   # k1 expired, k2 still valid
    assert cache.get(k1, now=15) is None
    assert cache.get(k2, now=15) == "2"


def test_idempotency_cache_clear():
    cache = idempotency.IdempotencyCache()
    key = idempotency.IdempotencyKey.from_call(tab_id=1, action="a", args={})
    cache.put(key, "x")
    assert len(cache) == 1
    cache.clear()
    assert len(cache) == 0
