"""Tests for MemoryManager — persist, forget, compact, seed, render."""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


import pytest

from chika.core.memory_manager import MemoryManager


@pytest.fixture
def mem(tmp_path):
    return MemoryManager(path=str(tmp_path / "memory.md"), max_tokens=100)


def test_persist_and_read(mem):
    mem.persist("key1", "value1")
    assert mem.read("key1") == "value1"


def test_forget(mem):
    mem.persist("k", "v")
    mem.forget("k")
    assert mem.read("k") is None


def test_seed_does_not_overwrite(mem):
    mem.persist("existing", "original")
    mem.seed("existing", "new_value")
    assert mem.read("existing") == "original"


def test_seed_sets_if_missing(mem):
    mem.seed("fresh", "seeded")
    assert mem.read("fresh") == "seeded"


def test_list_keys(mem):
    mem.persist("a", "1")
    mem.persist("b", "2")
    keys = mem.list_keys()
    assert "a" in keys
    assert "b" in keys


def test_render_for_prompt_empty(mem):
    assert mem.render_for_prompt() == ""


def test_render_for_prompt_has_content(mem):
    mem.persist("tip", "Use conventional commits")
    rendered = mem.render_for_prompt()
    assert "tip" in rendered
    assert "Use conventional commits" in rendered


def test_all_entries(mem):
    mem.persist("x", "val", ttl_days=7)
    entries = mem.all_entries()
    assert len(entries) == 1
    assert entries[0]["key"] == "x"
    assert entries[0]["ttl_days"] == 7


def test_persistence_to_file(tmp_path):
    path = str(tmp_path / "m.md")
    m1 = MemoryManager(path=path)
    m1.persist("saved", "this was saved")
    # Load fresh
    m2 = MemoryManager(path=path)
    assert m2.read("saved") == "this was saved"


def test_compaction_drops_least_accessed(tmp_path):
    path = str(tmp_path / "m.md")
    # Set a very small threshold to force compaction
    mem = MemoryManager(path=path, max_tokens=10)
    # Add many entries to force compaction
    for i in range(20):
        mem.persist(f"key{i}", f"this is value number {i} with extra text to fill up the token count")
    # After compaction, should be under threshold
    assert mem._estimate_tokens() <= 10


def test_accessed_counter_increments(mem):
    mem.persist("track", "some value")
    mem.read("track")
    mem.read("track")
    entries = mem.all_entries()
    assert entries[0]["accessed"] == 2


def test_append(mem):
    mem.persist("log", "line1")
    mem.append("log", "line2")
    val = mem.read("log")
    assert "line1" in val
    assert "line2" in val
