"""Tests for file_tools — read, edit_lines, write, append, info."""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
import base64

from chika.tools.file_tools import file_append, file_edit_lines, file_info, file_read, file_write


def run(coro):
    return asyncio.run(coro)


# ── file_write ────────────────────────────────────────────────────────────────

def test_write_creates_file(tmp_path):
    p = tmp_path / "test.txt"
    result = run(file_write(str(p), "hello"))
    assert p.exists()
    assert p.read_text() == "hello"
    assert result["path"] == str(p)
    assert result["size_bytes"] > 0


def test_write_creates_parent_dirs(tmp_path):
    p = tmp_path / "a" / "b" / "c" / "file.txt"
    run(file_write(str(p), "deep"))
    assert p.exists()
    assert p.read_text() == "deep"


def test_write_overwrites_existing(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("old content")
    run(file_write(str(p), "new content"))
    assert p.read_text() == "new content"


def test_write_returns_size(tmp_path):
    p = tmp_path / "s.txt"
    result = run(file_write(str(p), "12345"))
    assert result["size_bytes"] == 5


def test_write_accepts_contents_alias(tmp_path):
    """LLMs frequently send ``contents=`` instead of ``content=``. The
    tool must absorb that drift instead of crashing — same pattern as
    plan_set / scaffold_web_app."""
    p = tmp_path / "drift.txt"
    result = run(file_write(path=str(p), contents="hello drift"))
    assert "error" not in result
    assert p.read_text(encoding="utf-8") == "hello drift"


def test_write_accepts_text_and_body_aliases(tmp_path):
    """Other common drift kwargs the LLM substitutes for ``content``."""
    a = tmp_path / "text.txt"
    result_a = run(file_write(path=str(a), text="via text"))
    assert "error" not in result_a
    assert a.read_text(encoding="utf-8") == "via text"

    b = tmp_path / "body.txt"
    run(file_write(path=str(b), body="via body"))
    assert b.read_text(encoding="utf-8") == "via body"


def test_write_accepts_file_path_alias(tmp_path):
    """``file_path=`` instead of ``path=`` resolves correctly."""
    p = tmp_path / "fp.txt"
    result = run(file_write(file_path=str(p), content="ok"))
    assert "error" not in result
    assert p.read_text(encoding="utf-8") == "ok"


def test_write_missing_path_returns_error(tmp_path):
    result = run(file_write(content="anything"))
    assert "error" in result
    assert "path" in result["error"].lower()


# ── file_read ─────────────────────────────────────────────────────────────────

def test_read_returns_content(tmp_path):
    p = tmp_path / "r.txt"
    p.write_text("line1\nline2\nline3")
    result = run(file_read(str(p)))
    assert result["content"] == "line1\nline2\nline3"
    assert result["line_count"] == 3
    assert result["lines"] == ["line1", "line2", "line3"]


def test_read_missing_file_returns_error(tmp_path):
    result = run(file_read(str(tmp_path / "nonexistent.txt")))
    assert "error" in result


def test_read_directory_returns_error(tmp_path):
    result = run(file_read(str(tmp_path)))
    assert "error" in result


def test_read_as_bytes(tmp_path):
    p = tmp_path / "b.bin"
    p.write_bytes(b"\x00\x01\x02\x03")
    result = run(file_read(str(p), as_bytes=True))
    assert result["encoding"] == "base64"
    decoded = base64.b64decode(result["content"])
    assert decoded == b"\x00\x01\x02\x03"


def test_read_size_bytes(tmp_path):
    p = tmp_path / "sz.txt"
    p.write_text("hello")
    result = run(file_read(str(p)))
    assert result["size_bytes"] == 5


def test_read_empty_file(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("")
    result = run(file_read(str(p)))
    assert result["content"] == ""
    assert result["line_count"] == 0


# ── file_edit_lines ───────────────────────────────────────────────────────────

def test_edit_lines_replaces_single_line(tmp_path):
    p = tmp_path / "e.txt"
    p.write_text("line1\nline2\nline3\n")
    run(file_edit_lines(str(p), 2, 2, "REPLACED"))
    lines = p.read_text().splitlines()
    assert lines[0] == "line1"
    assert lines[1] == "REPLACED"
    assert lines[2] == "line3"


def test_edit_lines_replaces_range(tmp_path):
    p = tmp_path / "e.txt"
    p.write_text("a\nb\nc\nd\n")
    run(file_edit_lines(str(p), 2, 3, "x\ny\nz"))
    lines = p.read_text().splitlines()
    assert lines[0] == "a"
    assert lines[1] == "x"
    assert lines[2] == "y"
    assert lines[3] == "z"
    assert lines[4] == "d"


def test_edit_lines_missing_file_returns_error(tmp_path):
    result = run(file_edit_lines(str(tmp_path / "no.txt"), 1, 1, "content"))
    assert "error" in result


def test_edit_lines_returns_metadata(tmp_path):
    p = tmp_path / "m.txt"
    p.write_text("line1\nline2\n")
    result = run(file_edit_lines(str(p), 1, 1, "new"))
    assert "lines_replaced" in result
    assert "total_lines" in result
    assert result["lines_replaced"] == 1


def test_edit_lines_first_line(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("old\nsecond\nthird\n")
    run(file_edit_lines(str(p), 1, 1, "new_first"))
    assert p.read_text().startswith("new_first")


def test_edit_lines_last_line(tmp_path):
    p = tmp_path / "l.txt"
    p.write_text("first\nsecond\nold_last\n")
    run(file_edit_lines(str(p), 3, 3, "new_last"))
    lines = p.read_text().splitlines()
    assert lines[-1] == "new_last"


# ── file_append ───────────────────────────────────────────────────────────────

def test_append_to_existing(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("first\n")
    run(file_append(str(p), "second\n"))
    assert p.read_text() == "first\nsecond\n"


def test_append_creates_file_if_missing(tmp_path):
    p = tmp_path / "new.txt"
    assert not p.exists()
    run(file_append(str(p), "created"))
    assert p.exists()
    assert p.read_text() == "created"


def test_append_returns_appended_bytes(tmp_path):
    p = tmp_path / "b.txt"
    p.write_text("")
    result = run(file_append(str(p), "hello"))
    assert result["appended_bytes"] == 5


def test_append_multiple_times(tmp_path):
    p = tmp_path / "m.txt"
    for i in range(5):
        run(file_append(str(p), f"line{i}\n"))
    lines = p.read_text().splitlines()
    assert len(lines) == 5
    assert lines[0] == "line0"
    assert lines[4] == "line4"


# ── file_info ─────────────────────────────────────────────────────────────────

def test_info_for_file(tmp_path):
    p = tmp_path / "i.txt"
    p.write_text("some content")
    result = run(file_info(str(p)))
    assert result["is_file"] is True
    assert result["is_dir"] is False
    assert result["size_bytes"] > 0
    assert "modified_ts" in result


def test_info_for_directory(tmp_path):
    result = run(file_info(str(tmp_path)))
    assert result["is_dir"] is True
    assert result["is_file"] is False


def test_info_missing_returns_error(tmp_path):
    result = run(file_info(str(tmp_path / "missing.txt")))
    assert "error" in result


def test_info_extension(tmp_path):
    p = tmp_path / "script.py"
    p.write_text("pass")
    result = run(file_info(str(p)))
    assert result["extension"] == ".py"


def test_info_no_extension(tmp_path):
    p = tmp_path / "Makefile"
    p.write_text("all:")
    result = run(file_info(str(p)))
    assert result["extension"] == ""
