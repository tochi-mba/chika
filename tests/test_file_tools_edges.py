"""Edge-case coverage for chika/tools/file_tools.py.

Complements test_file_tools.py by exercising:
- _safe_path traversal guard
- file_read line slicing + encoding errors + size cap
- file_replace (not-found / not-unique / suggestions / type guards)
- file_write content type errors
- workspace policy gate (_gate_write)
- _suggest_anchor_lines heuristic
- module __getattr__ shim
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from chika.tools import file_tools as ft


# ── _safe_path ─────────────────────────────────────────────────────────


def test_safe_path_blocks_traversal():
    p, err = ft._safe_path("../../etc/passwd")
    assert err is not None
    assert "traversal" in err.lower()


def test_safe_path_resolves_normal_path(tmp_path):
    p, err = ft._safe_path(str(tmp_path / "ok.txt"))
    assert err is None
    assert p.is_absolute()


# ── file_read edge cases ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_read_traversal_blocked():
    out = await ft.file_read("../../etc/passwd")
    assert "error" in out
    assert "traversal" in out["error"].lower()


@pytest.mark.asyncio
async def test_file_read_line_slice(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("a\nb\nc\nd\ne\n")
    out = await ft.file_read(str(p), start_line=2, end_line=4)
    assert out["start_line"] == 2
    assert out["end_line"] == 4
    assert out["line_count"] == 3
    assert out["lines"] == ["b", "c", "d"]
    assert out["total_lines"] == 5


@pytest.mark.asyncio
async def test_file_read_line_slice_clamps_low(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("a\nb\nc")
    out = await ft.file_read(str(p), start_line=0, end_line=2)
    assert out["start_line"] == 1


@pytest.mark.asyncio
async def test_file_read_line_slice_clamps_high(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("a\nb\nc")
    out = await ft.file_read(str(p), start_line=1, end_line=999)
    assert out["end_line"] == 3


@pytest.mark.asyncio
async def test_file_read_only_start_line(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("a\nb\nc\n")
    out = await ft.file_read(str(p), start_line=2)
    assert out["lines"] == ["b", "c"]


@pytest.mark.asyncio
async def test_file_read_only_end_line(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("a\nb\nc\n")
    out = await ft.file_read(str(p), end_line=2)
    assert out["lines"] == ["a", "b"]


@pytest.mark.asyncio
async def test_file_read_encoding_error_returns_hint(tmp_path):
    """Binary data triggers UnicodeDecodeError → structured error."""
    p = tmp_path / "bin.dat"
    p.write_bytes(b"\xff\xfe\xfd\x00\x01")
    out = await ft.file_read(str(p))
    assert out["error"] == "encoding_error"
    assert "as_bytes" in out["hint"].lower()


@pytest.mark.asyncio
async def test_file_read_oversize_rejected(tmp_path, monkeypatch):
    """When file exceeds MAX_FILE_SIZE_BYTES, return an error."""
    monkeypatch.setattr(ft, "MAX_FILE_SIZE_BYTES", 8)
    p = tmp_path / "big.txt"
    p.write_text("more than eight bytes here")
    out = await ft.file_read(str(p))
    assert "error" in out
    assert "too large" in out["error"].lower()


# ── file_replace ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_replace_succeeds(tmp_path):
    p = tmp_path / "r.txt"
    p.write_text("hello world")
    out = await ft.file_replace(str(p), "world", "Earth")
    assert out["replaced"] is True
    assert p.read_text() == "hello Earth"


@pytest.mark.asyncio
async def test_file_replace_old_string_must_be_string(tmp_path):
    p = tmp_path / "r.txt"
    p.write_text("hello")
    out = await ft.file_replace(str(p), 123, "x")  # type: ignore[arg-type]
    assert "error" in out
    assert "must be a string" in out["error"]


@pytest.mark.asyncio
async def test_file_replace_new_string_must_be_string(tmp_path):
    p = tmp_path / "r.txt"
    p.write_text("hello")
    out = await ft.file_replace(str(p), "hello", 42)  # type: ignore[arg-type]
    assert "error" in out
    assert "must be a string" in out["error"]


@pytest.mark.asyncio
async def test_file_replace_traversal_blocked():
    out = await ft.file_replace("../../etc/passwd", "x", "y")
    assert "error" in out
    assert "traversal" in out["error"].lower()


@pytest.mark.asyncio
async def test_file_replace_missing_file(tmp_path):
    out = await ft.file_replace(str(tmp_path / "ghost.txt"), "x", "y")
    assert "error" in out
    assert "not found" in out["error"].lower()


@pytest.mark.asyncio
async def test_file_replace_old_string_not_found_with_suggestions(tmp_path):
    p = tmp_path / "r.txt"
    p.write_text(
        "def hello():\n"
        "    print('hi')\n"
        "def goodbye():\n"
        "    print('bye')\n"
    )
    out = await ft.file_replace(
        str(p),
        "def hello():\n    print('different')",
        "doesnt matter",
    )
    assert out["error"] == "old_string_not_found"
    assert out["anchor"].startswith("def hello")
    assert out["total_lines"] >= 4
    assert any(s["text"].startswith("def hello") for s in out["suggestions"])


@pytest.mark.asyncio
async def test_file_replace_not_unique_returns_line_numbers(tmp_path):
    p = tmp_path / "r.txt"
    p.write_text("foo\nbar\nfoo\nbar\nfoo\n")
    out = await ft.file_replace(str(p), "foo", "X")
    assert out["error"] == "old_string_not_unique"
    assert out["occurrences"] == 3
    # 1, 3, 5 (lines containing "foo")
    assert set(out["line_numbers"]) == {1, 3, 5}


@pytest.mark.asyncio
async def test_file_replace_not_unique_caps_line_numbers_at_12(tmp_path):
    """Even when the match repeats >12 times, we only report the first 12."""
    p = tmp_path / "r.txt"
    p.write_text("\n".join(["foo"] * 30))
    out = await ft.file_replace(str(p), "foo", "X")
    assert out["error"] == "old_string_not_unique"
    assert len(out["line_numbers"]) == 12


# ── _suggest_anchor_lines ──────────────────────────────────────────────


def test_suggest_anchor_lines_empty_input():
    assert ft._suggest_anchor_lines("file content here", "") == []


def test_suggest_anchor_lines_short_anchor_returns_empty():
    """Anchors under 4 chars are too noisy."""
    assert ft._suggest_anchor_lines("body", "ab") == []


def test_suggest_anchor_lines_exact_match_scored_higher():
    text = (
        "def hello():\n"
        "    pass\n"
        "def hello_world():\n"
        "    pass\n"
    )
    result = ft._suggest_anchor_lines(text, "def hello():")
    assert result
    # The exact match is scored 100; partial 50. The line number for the
    # exact match should appear first.
    assert result[0]["line_no"] == 1


def test_suggest_anchor_lines_truncates_long_lines():
    """Lines >160 chars are truncated in the surfaced text."""
    long = "anchor_line " + "x" * 300
    text = long + "\n" + "irrelevant"
    result = ft._suggest_anchor_lines(text, "anchor_line ")
    assert result
    assert len(result[0]["text"]) <= 160


def test_suggest_anchor_lines_only_whitespace():
    """An old_string with only blank lines yields no anchor → empty."""
    assert ft._suggest_anchor_lines("anything", "  \n\t\n") == []


# ── file_write type guard ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_write_non_string_content_returns_error(tmp_path):
    out = await ft.file_write(str(tmp_path / "f.txt"), content={"json": True})  # type: ignore[arg-type]
    assert "error" in out
    assert "string" in out["error"].lower()


@pytest.mark.asyncio
async def test_file_write_traversal_blocked():
    out = await ft.file_write("../../etc/escape.txt", content="x")
    assert "error" in out
    assert "traversal" in out["error"].lower()


@pytest.mark.asyncio
async def test_file_write_data_alias(tmp_path):
    p = tmp_path / "data.txt"
    out = await ft.file_write(path=str(p), data="content via data")
    assert "error" not in out
    assert p.read_text(encoding="utf-8") == "content via data"


@pytest.mark.asyncio
async def test_file_write_source_alias(tmp_path):
    p = tmp_path / "src.txt"
    out = await ft.file_write(path=str(p), source="content via source")
    assert "error" not in out
    assert p.read_text(encoding="utf-8") == "content via source"


@pytest.mark.asyncio
async def test_file_write_filepath_alias(tmp_path):
    p = tmp_path / "fp.txt"
    out = await ft.file_write(filepath=str(p), content="x")
    assert "error" not in out
    assert p.exists()


# ── file_append edges ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_append_non_string_content_returns_error(tmp_path):
    out = await ft.file_append(str(tmp_path / "x.txt"), content=[1, 2, 3])  # type: ignore[arg-type]
    assert "error" in out


@pytest.mark.asyncio
async def test_file_append_traversal_blocked():
    out = await ft.file_append("../../etc/escape.txt", "x")
    assert "error" in out


@pytest.mark.asyncio
async def test_file_append_creates_parent_dirs(tmp_path):
    p = tmp_path / "deep" / "dir" / "f.txt"
    out = await ft.file_append(str(p), "hi")
    assert "error" not in out
    assert p.exists()


# ── file_info traversal ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_info_traversal_blocked():
    out = await ft.file_info("../../etc/passwd")
    assert "error" in out


# ── _gate_write — workspace policy gate ────────────────────────────────


@pytest.mark.asyncio
async def test_gate_write_returns_none_when_no_policy(tmp_path):
    """No active policy → no gating."""
    ft._WORKSPACE_POLICY.set(None)
    out = await ft._gate_write(tmp_path / "x.txt", "write")
    assert out is None


@pytest.mark.asyncio
async def test_gate_write_returns_none_when_allowed(tmp_path):
    decision = type("D", (), {"allowed": True, "scope": "workspace", "reason": ""})()
    fake_policy = type(
        "P", (),
        {
            "check": AsyncMock(return_value=decision),
            "workspace": str(tmp_path),
        },
    )()
    ft._WORKSPACE_POLICY.set(fake_policy)
    try:
        out = await ft._gate_write(tmp_path / "x.txt", "write")
        assert out is None
    finally:
        ft._WORKSPACE_POLICY.set(None)


@pytest.mark.asyncio
async def test_gate_write_returns_error_when_denied(tmp_path):
    decision = type(
        "D", (),
        {"allowed": False, "scope": "out_of_workspace", "reason": "denied"},
    )()
    fake_policy = type(
        "P", (),
        {
            "check": AsyncMock(return_value=decision),
            "workspace": str(tmp_path),
        },
    )()
    ft._WORKSPACE_POLICY.set(fake_policy)
    try:
        out = await ft._gate_write(tmp_path / "x.txt", "write")
        assert out is not None
        assert out["error"] == "denied_by_workspace_policy"
        assert out["scope"] == "out_of_workspace"
        assert out["reason"] == "denied"
        assert out["workspace"] == str(tmp_path)
    finally:
        ft._WORKSPACE_POLICY.set(None)


@pytest.mark.asyncio
async def test_file_write_blocked_by_policy(tmp_path):
    decision = type(
        "D", (),
        {"allowed": False, "scope": "external", "reason": "outside ws"},
    )()
    fake_policy = type(
        "P", (),
        {
            "check": AsyncMock(return_value=decision),
            "workspace": str(tmp_path),
        },
    )()
    ft._WORKSPACE_POLICY.set(fake_policy)
    try:
        out = await ft.file_write(path=str(tmp_path / "x.txt"), content="data")
        assert out["error"] == "denied_by_workspace_policy"
    finally:
        ft._WORKSPACE_POLICY.set(None)


@pytest.mark.asyncio
async def test_file_replace_blocked_by_policy(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("hello")
    decision = type(
        "D", (),
        {"allowed": False, "scope": "external", "reason": "outside ws"},
    )()
    fake_policy = type(
        "P", (),
        {
            "check": AsyncMock(return_value=decision),
            "workspace": str(tmp_path),
        },
    )()
    ft._WORKSPACE_POLICY.set(fake_policy)
    try:
        out = await ft.file_replace(str(p), "hello", "world")
        assert out["error"] == "denied_by_workspace_policy"
    finally:
        ft._WORKSPACE_POLICY.set(None)


@pytest.mark.asyncio
async def test_file_edit_lines_blocked_by_policy(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("a\nb\nc\n")
    decision = type(
        "D", (),
        {"allowed": False, "scope": "external", "reason": "outside ws"},
    )()
    fake_policy = type(
        "P", (),
        {
            "check": AsyncMock(return_value=decision),
            "workspace": str(tmp_path),
        },
    )()
    ft._WORKSPACE_POLICY.set(fake_policy)
    try:
        out = await ft.file_edit_lines(str(p), 1, 1, "x")
        assert out["error"] == "denied_by_workspace_policy"
    finally:
        ft._WORKSPACE_POLICY.set(None)


@pytest.mark.asyncio
async def test_file_append_blocked_by_policy(tmp_path):
    decision = type(
        "D", (),
        {"allowed": False, "scope": "external", "reason": "outside ws"},
    )()
    fake_policy = type(
        "P", (),
        {
            "check": AsyncMock(return_value=decision),
            "workspace": str(tmp_path),
        },
    )()
    ft._WORKSPACE_POLICY.set(fake_policy)
    try:
        out = await ft.file_append(str(tmp_path / "x.txt"), "data")
        assert out["error"] == "denied_by_workspace_policy"
    finally:
        ft._WORKSPACE_POLICY.set(None)


# ── configure_workspace_policy ─────────────────────────────────────────


def test_configure_workspace_policy_sets_both_vars():
    pol = object()
    handler = object()
    ft.configure_workspace_policy(pol, handler)
    assert ft._WORKSPACE_POLICY.get() is pol
    assert ft._WORKSPACE_APPROVAL_HANDLER.get() is handler
    ft.configure_workspace_policy(None, None)


# ── module __getattr__ shim ────────────────────────────────────────────


def test_module_getattr_workspace_policy():
    ft._WORKSPACE_POLICY.set("sentinel")  # type: ignore[arg-type]
    try:
        assert ft.WORKSPACE_POLICY == "sentinel"
    finally:
        ft._WORKSPACE_POLICY.set(None)


def test_module_getattr_workspace_approval_handler():
    ft._WORKSPACE_APPROVAL_HANDLER.set("h")  # type: ignore[arg-type]
    try:
        assert ft.WORKSPACE_APPROVAL_HANDLER == "h"
    finally:
        ft._WORKSPACE_APPROVAL_HANDLER.set(None)


def test_module_getattr_unknown_raises():
    with pytest.raises(AttributeError):
        ft.does_not_exist  # type: ignore[attr-defined]
