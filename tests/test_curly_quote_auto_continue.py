"""Curly-quote regression: auto-continue must trigger on text the LLM
produces with Markdown-style typography (U+2019 ’, U+2014 —, etc.).

The user's actual trace:

    "Plan set for Powder Toy clone.
    Next, I’ll scaffold the project (main.py, elements.py, config.py)
    and verify pygame installation with a t…"

was failing the heuristic because ``"i'll"`` (U+0027) ≠ ``"i’ll"`` (U+2019).
Auto-continue silently died, the agent waited for a nudge, the user
typed "wtf is going on here..." and we shipped this fix.
"""
from __future__ import annotations

import pytest

from chika.core.engine import _normalise_text, _should_auto_continue


@pytest.mark.parametrize("text", [
    # The exact text from the user's session.
    "Plan set for Powder Toy clone.\n\n"
    "Next, I’ll scaffold the project (main.py, elements.py, config.py) "
    "and verify pygame installation.",
    # Em-dash variant ("Next — I'll …" style)
    "Step done — now I’ll move on to the renderer.",
    # Mixed: em dash + curly quote
    "Done. Now I’ll wire up the audio — and the controls.",
    # Both quote characters in one sentence
    "Got the data. Next, I’ll parse it and write “results.json”.",
])
def test_curly_quote_text_triggers_auto_continue(text):
    assert _should_auto_continue(text), (
        f"curly-quote text must trigger auto-continue: {text!r}"
    )


def test_normalise_replaces_common_unicode_punctuation():
    raw = "I’ll “verify” — and continue – with the work."
    norm = _normalise_text(raw)
    # All flavours collapsed to ASCII.
    assert "i'll" in norm
    assert '"verify"' in norm
    assert " - " in norm  # em + en dashes both → -
    # Original Unicode characters absent from the normalised output.
    for ch in ("’", "“", "”", "—", "–"):
        assert ch not in norm


def test_curly_quote_question_still_blocks():
    """A trailing question should still suppress auto-continue even when
    the question mark is the only thing after curly quotes."""
    text = "Done — should I now ‘deploy’ the build?"
    assert not _should_auto_continue(text)
