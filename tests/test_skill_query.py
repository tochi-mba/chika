"""Tests for the BM25 SKILL.md retrieval index + skill_query tool.

Covers:
- Chunking: by ## headings, with sub-split on oversized sections.
- BM25: relevant chunks rank above irrelevant ones; exact identifier
  matches (e.g. "plan_set") score perfectly.
- Cache: index is reused on repeat queries and rebuilt when SKILL.md mtime
  changes.
- Tool integration: skill_query returns a clean dict and tolerates LLM
  kwarg slips (q vs query, name vs skill).
- Real shipped SKILL.md: a question about the plan skill returns a chunk
  that mentions plan_set.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from chika.tools.skill_doc_tool import SKILL_QUERY_TOOL
from chika.tools.skill_query_index import (
    BM25Index,
    _build_index,
    _chunk_markdown,
    _tokenize,
    get_index,
    query,
)


_REPO = Path(__file__).resolve().parent.parent


# ── Tokenisation ──────────────────────────────────────────────────────────

def test_tokenizer_strips_stopwords_and_punctuation():
    out = _tokenize("This is a Test of plan_set, the canonical entry-point.")
    # Stopwords removed
    assert "this" not in out
    assert "is" not in out
    assert "of" not in out
    assert "the" not in out
    # Identifiers split on underscores so partial matches still score.
    assert "plan" in out
    assert "set" in out
    # Lowercased
    assert "test" in out
    # Single-char tokens dropped (the "a")
    assert "a" not in out


def test_tokenizer_handles_empty_input():
    assert _tokenize("") == []
    assert _tokenize("   \n\n   ") == []


# ── Chunking ──────────────────────────────────────────────────────────────

def test_chunking_splits_on_h2_headings():
    doc = (
        "# Title\n\n"
        "Intro paragraph that's long enough to keep as preface.\n\n"
        "## First section\n\n"
        + ("first body line. " * 8) + "\n\n"
        "## Second section\n\n"
        + ("second body line. " * 8) + "\n\n"
        "## Third section\n\n"
        + ("third body line. " * 8) + "\n"
    )
    chunks = _chunk_markdown("dummy", doc)
    headings = [c.heading for c in chunks]
    # Each h2 produces exactly one chunk; preface kept; nothing duplicated.
    assert "preface" in headings
    assert "First section" in headings
    assert "Second section" in headings
    assert "Third section" in headings
    assert len(headings) == len(set(headings))


def test_chunking_subsplits_oversize_sections():
    """A single section bigger than _MAX_CHUNK_CHARS gets sub-split."""
    huge_para = "lorem ipsum dolor sit amet " * 50  # ~1350 chars per copy
    doc = "# Title\n\n## big\n\n" + huge_para + "\n\n" + huge_para + "\n\n" + huge_para
    chunks = _chunk_markdown("dummy", doc)
    big_chunks = [c for c in chunks if c.heading.startswith("big")]
    assert len(big_chunks) >= 2, (
        "expected 'big' section to be sub-split, got "
        f"{[c.heading for c in big_chunks]}"
    )
    # Every sub-chunk fits the cap with reasonable slack.
    assert all(len(c.body) <= 1400 for c in big_chunks)


def test_chunking_drops_tiny_noise_chunks():
    doc = "# Title\n\n## tiny\n\nHi.\n\n## real\n\n" + ("real content " * 30)
    chunks = _chunk_markdown("dummy", doc)
    # 'tiny' was below the min threshold and dropped.
    assert all(c.heading != "tiny" for c in chunks), [c.heading for c in chunks]


# ── BM25 ranking ─────────────────────────────────────────────────────────

def _make_index():
    """Tiny synthetic skill doc used for ranking assertions."""
    doc = (
        "# Demo skill\n\n"
        "## Setup\n\n"
        "To bootstrap, call setup_tool with a config path.\n\n"
        "## Cleanup\n\n"
        "Call cleanup_tool when finished. It frees the buffers.\n\n"
        "## Bug fixing\n\n"
        "Use the fix_bug tool with bug_id and patch_text. Mandatory: read "
        "the source file first.\n\n"
    )
    chunks = _chunk_markdown("demo", doc)
    avg_length = sum(c.length for c in chunks) / len(chunks)
    df: dict[str, int] = {}
    for c in chunks:
        for tok in set(c.tokens):
            df[tok] = df.get(tok, 0) + 1
    return BM25Index(
        skill="demo", doc_path="<test>", doc_mtime=0.0,
        chunks=chunks, avg_length=avg_length, df=df,
    )


def test_bm25_ranks_relevant_chunk_first():
    idx = _make_index()
    top = idx.score_query("how do I fix a bug?", k=3)
    assert top, "expected at least one matching chunk"
    assert top[0][0].heading == "Bug fixing"


def test_bm25_exact_identifier_match_scores_well():
    idx = _make_index()
    top = idx.score_query("setup_tool", k=2)
    assert top[0][0].heading == "Setup"


def test_bm25_returns_empty_for_pure_stopwords():
    """A query of nothing-but-stopwords tokenises to empty → score is empty."""
    idx = _make_index()
    assert idx.score_query("the and a is or", k=3) == []


def test_bm25_respects_k():
    idx = _make_index()
    top = idx.score_query("tool", k=1)
    assert len(top) == 1


# ── Cache lifecycle ──────────────────────────────────────────────────────

def test_index_is_cached_and_rebuilt_on_mtime_change(tmp_path: Path,
                                                       monkeypatch):
    """Build a fake skill folder under tmp_path and patch _SKILLS_DIR."""
    skill_dir = tmp_path / "fake_skill"
    skill_dir.mkdir()
    md = skill_dir / "SKILL.md"
    md.write_text("# Fake\n\n## Section A\n\n" + ("alpha beta gamma " * 30),
                  encoding="utf-8")

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(
        "chika.tools.skill_query_index._SKILLS_DIR", tmp_path,
    )
    monkeypatch.setattr(
        "chika.tools.skill_query_index._CACHE_DIR", cache_dir,
    )

    idx1 = get_index("fake")
    assert idx1 is not None
    cache_path = cache_dir / "fake.json"
    assert cache_path.is_file(), "cache file should be written on first build"
    initial_data = json.loads(cache_path.read_text(encoding="utf-8"))

    # Second call returns the cached version (no rebuild) — assert
    # mtime field unchanged.
    idx2 = get_index("fake")
    assert idx2 is not None
    assert idx2.doc_mtime == idx1.doc_mtime

    # Mutate the file, advance mtime, and verify the index rebuilds.
    md.write_text("# Fake\n\n## Section B\n\n" + ("delta epsilon zeta " * 30),
                  encoding="utf-8")
    new_mtime = time.time() + 5
    os.utime(md, (new_mtime, new_mtime))
    idx3 = get_index("fake")
    assert idx3 is not None
    assert idx3.doc_mtime != initial_data["doc_mtime"], (
        "index must rebuild when SKILL.md mtime changes"
    )
    assert any("Section B" in c.heading for c in idx3.chunks)
    assert all("Section A" not in c.heading for c in idx3.chunks)


# ── query() entry point ──────────────────────────────────────────────────

def test_query_unknown_skill_returns_clean_error():
    out = query("definitely-not-a-skill-9999", "anything")
    assert out.get("error") == "skill_not_found"
    assert "hint" in out


def test_query_empty_query_returns_clean_error():
    out = query("plan", "")
    assert "error" in out


def test_query_against_shipped_plan_skill_returns_relevant_chunk():
    """The agent asking 'how do I call plan_set?' should get a chunk that
    actually mentions plan_set. This is the regression we shipped against —
    if BM25 ever ranks irrelevant sections higher we want to know."""
    out = query("plan", "how do I call plan_set", k=3)
    assert "error" not in out, out
    assert out["skill"] == "plan"
    assert out["chunks"], f"expected at least one chunk, got {out}"
    bodies = " ".join(c["body"] for c in out["chunks"]).lower()
    assert "plan_set" in bodies, (
        f"top results don't mention plan_set: "
        f"{[c['heading'] for c in out['chunks']]}"
    )


def test_query_against_browser_skill_finds_specific_rule():
    """The browser SKILL.md is huge (~28KB) — chunking + BM25 must be able
    to surface a specific behaviour rule out of it."""
    out = query("browser", "how do I read what's on the user's screen", k=3)
    assert "error" not in out, out
    assert out["chunks"]
    bodies = " ".join(c["body"] for c in out["chunks"]).lower()
    # At least one of the obvious browser-read tools should appear.
    assert any(t in bodies for t in
               ("browser_get_text", "browser_get_active_tab",
                "browser_get_page_var")), (
        "expected a browser-read tool in the top-k chunks, got: "
        f"{[c['heading'] for c in out['chunks']]}"
    )


# ── Tool integration ─────────────────────────────────────────────────────

def test_skill_query_tool_handler_resolves_aliases():
    """The agent often types `q=` or `name=` — tool should accept both."""
    handler = SKILL_QUERY_TOOL.handler
    # canonical form
    out1 = asyncio.run(handler(skill="plan", query="how to set the plan", k=2))
    assert "error" not in out1
    # alias: q for query, name for skill
    out2 = asyncio.run(handler(name="plan", q="how to set the plan", k=2))
    assert "error" not in out2
    # Both return the same skill.
    assert out1["skill"] == out2["skill"] == "plan"


def test_skill_query_tool_clamps_k_to_safe_range():
    handler = SKILL_QUERY_TOOL.handler
    out = asyncio.run(handler(skill="plan", query="plan_set", k=999))
    assert "error" not in out
    # Cap is 10 (clamped).
    assert len(out["chunks"]) <= 10
