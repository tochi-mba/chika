"""Selector resolution with graceful degradation.

The audit identified browser tooling as the subsystem most likely to
dominate maintenance: 18 tools, all CSS-``querySelector``-only, no
fallback when markup changes. This module is the cushion.

Strategy
--------
``resolve_selector(spec)`` tries strategies in order:

  1. **CSS** — the spec as-is. Fastest, most precise. Most LLM-emitted
     selectors are CSS, so this hits 90%+ of the time.
  2. **ARIA** — derived variants like ``[role="button"][aria-label*="..."]``
     when the original CSS contained a label-like substring. Survives
     class-name churn.
  3. **Text content** — visible text match. Last resort; matches what a
     human would describe ("the 'Sign in' button").

Resolution **caches** successful (url, original_spec) → working_spec
mappings so a successful resolution survives across actions on the
same page. The cache is per-process and bounded; a page navigation
clears the URL's entries.

This module is pure Python — the actual DOM query happens in the
extension's content script. The extension imports the cascade contract
from here via the shared event schema; this Python file is the source
of truth + the unit-test surface.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass

# Bounded cache so a long-running session doesn't grow without limit.
_CACHE_MAX = 1024


@dataclass(frozen=True)
class SelectorSpec:
    """A resolved selector + the strategy that found it."""
    selector: str
    strategy: str   # "css" | "aria" | "text"


class _LRUCache:
    """Tiny insertion-ordered LRU. Reuses ``OrderedDict.move_to_end``
    so we don't pull in functools.lru_cache (we need a custom key shape).
    """
    def __init__(self, maxsize: int = _CACHE_MAX) -> None:
        self._d: OrderedDict[tuple[str, str], SelectorSpec] = OrderedDict()
        self._max = maxsize

    def get(self, key: tuple[str, str]) -> SelectorSpec | None:
        if key not in self._d:
            return None
        self._d.move_to_end(key)
        return self._d[key]

    def put(self, key: tuple[str, str], value: SelectorSpec) -> None:
        self._d[key] = value
        self._d.move_to_end(key)
        while len(self._d) > self._max:
            self._d.popitem(last=False)

    def clear_url(self, url: str) -> int:
        """Clear all entries for a given URL. Called on navigation."""
        keys = [k for k in self._d if k[0] == url]
        for k in keys:
            del self._d[k]
        return len(keys)

    def __len__(self) -> int:
        return len(self._d)


_cache = _LRUCache()


def cache_size() -> int:
    return len(_cache)


def clear_cache_for_url(url: str) -> int:
    """Forget cached resolutions for ``url`` (call on navigation)."""
    return _cache.clear_url(url)


# ── Strategy generators ──────────────────────────────────────────────


def _looks_like_label(spec: str) -> str | None:
    """Extract a likely human label from a selector string.

    Examples:
      'button.btn-primary'           → None (no label hint)
      'button[aria-label*="submit"]' → 'submit'
      'button[title="Sign in"]'      → 'Sign in'
      '#sign-in'                     → 'sign-in' (id with words)
    """
    m = re.search(r'aria-label[*~|^$]?="([^"]+)"', spec)
    if m:
        return m.group(1)
    m = re.search(r'(?:title|alt)[*~|^$]?="([^"]+)"', spec)
    if m:
        return m.group(1)
    m = re.search(r'#([a-zA-Z][\w-]*)', spec)
    if m:
        return m.group(1).replace("-", " ").replace("_", " ")
    return None


def aria_variant(spec: str) -> str | None:
    """Produce an ARIA-aware variant of ``spec`` when one is meaningful.

    Returns ``None`` when no derivable variant exists — caller skips
    this strategy.
    """
    label = _looks_like_label(spec)
    if not label:
        return None

    # Pull out the leading element (button, a, input, etc.) if present.
    m = re.match(r'^\s*([a-zA-Z][a-zA-Z0-9]*)', spec)
    elt = m.group(1) if m else "*"
    return f'{elt}[aria-label*="{label}" i], [role][aria-label*="{label}" i]'


def text_variant(spec: str) -> str | None:
    """Produce a text-content variant for visible-text matching.

    The extension's content script supports a synthetic ``:has-text("...")``
    pseudo (implemented client-side because CSS itself doesn't expose
    text content). We emit that pseudo here.
    """
    label = _looks_like_label(spec)
    if not label:
        return None
    m = re.match(r'^\s*([a-zA-Z][a-zA-Z0-9]*)', spec)
    elt = m.group(1) if m else "*"
    return f'{elt}:has-text("{label}")'


# ── Public API ───────────────────────────────────────────────────────


def candidate_specs(spec: str) -> list[SelectorSpec]:
    """Return strategies the extension should try, in priority order.

    The extension calls this for every selector-bearing tool (click,
    fill, scroll, watch, get_text, etc.) when the original CSS spec
    fails to match. Returned list is always at least one entry (the
    original CSS); ARIA + text variants append when derivable.
    """
    out = [SelectorSpec(selector=spec, strategy="css")]
    aria = aria_variant(spec)
    if aria and aria != spec:
        out.append(SelectorSpec(selector=aria, strategy="aria"))
    text = text_variant(spec)
    if text and text != spec:
        out.append(SelectorSpec(selector=text, strategy="text"))
    return out


def remember_resolution(url: str, original: str, resolved: SelectorSpec) -> None:
    """Cache that ``original`` resolved to ``resolved`` on ``url``."""
    _cache.put((url, original), resolved)


def recall_resolution(url: str, original: str) -> SelectorSpec | None:
    """Return a previously-cached resolution for (url, original_spec)."""
    return _cache.get((url, original))
