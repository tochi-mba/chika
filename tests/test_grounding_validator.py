"""
Tests for ChikaEngine._validate_grounding — the post-response check that
flags fabricated URLs and ungrounded citations in the final reply.
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
from unittest.mock import MagicMock

from chika.core.variable_store import VariableStore, VarType


def _make_engine_with_vars(facts_list=None):
    """
    Build a minimal ChikaEngine-like object that satisfies _validate_grounding's
    dependencies: a variable store, an _active_profile, and the method itself.
    We bypass __init__ (which needs API keys) by manually wiring attributes.
    """
    from chika.core.engine import ChikaEngine
    eng = ChikaEngine.__new__(ChikaEngine)
    eng._vars = VariableStore()
    eng._active_profile = MagicMock()
    eng._active_profile.name = "test"
    if facts_list is not None:
        eng._vars.set("facts", facts_list, VarType.JSON, source="engine:ledger")
    return eng


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── Short responses skip validation ──────────────────────────────────────────

def test_short_response_is_not_validated():
    eng = _make_engine_with_vars()
    result = _run(eng._validate_grounding("ok"))
    assert result is None


# ── Ungrounded URL detection ─────────────────────────────────────────────────

def test_ungrounded_url_is_flagged():
    eng = _make_engine_with_vars(facts_list=[])  # empty ledger
    response = (
        "I found the info you wanted. The source I used is "
        "https://totally-fabricated-site.com/page and it confirms the claim. "
        "This is a reasonably long response with specific claims in it."
    )
    result = _run(eng._validate_grounding(response))
    assert result is not None
    assert result["type"] == "validation_warning"
    assert result["reason"] == "ungrounded_urls"
    assert "https://totally-fabricated-site.com/page" in result["urls"]


def test_grounded_url_is_not_flagged():
    facts = [{"source": "web_search:s1", "url": "https://example.com/real-page",
              "snippet": "..."}]
    eng = _make_engine_with_vars(facts_list=facts)
    response = (
        "According to what I retrieved, see https://example.com/real-page "
        "for the full details. The response is long enough to trigger validation."
    )
    result = _run(eng._validate_grounding(response))
    # URL is in the ledger → not flagged as ungrounded
    # (may still be flagged for citation markers if no facts... but there ARE facts)
    if result is not None:
        assert result.get("reason") != "ungrounded_urls"


def test_root_domain_urls_are_whitelisted():
    eng = _make_engine_with_vars(facts_list=[])
    response = (
        "You can find more info at https://google.com and https://github.com "
        "which are well-known root domains so they don't need grounding. "
        "This message is long enough to cross the validation threshold."
    )
    result = _run(eng._validate_grounding(response))
    # Only root domains cited, no other specific URLs, no citation markers
    # → should not be flagged
    assert result is None or result.get("reason") != "ungrounded_urls"


# ── Citation-markers without retrieval ───────────────────────────────────────

def test_citations_without_retrieval_is_flagged():
    eng = _make_engine_with_vars(facts_list=[])  # no tool ran
    response = (
        "According to my sources, the most popular dessert is the waffle. "
        "The references for this claim are consistent across the data. "
        "This response is long enough to be validated by the engine."
    )
    result = _run(eng._validate_grounding(response))
    assert result is not None
    assert result["reason"] == "citations_without_retrieval"


def test_citations_with_facts_are_not_flagged():
    facts = [{"source": "web_search:s1", "url": "https://a.com", "snippet": "waffle popular"}]
    eng = _make_engine_with_vars(facts_list=facts)
    response = (
        "According to my sources, the most popular dessert is the waffle. "
        "This information comes from the retrieved evidence. "
        "The response is long enough to cross the validation threshold for checks."
    )
    result = _run(eng._validate_grounding(response))
    # Has citation marker but facts exist and no ungrounded URLs → not flagged
    assert result is None
