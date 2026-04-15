"""pytest tests for the todo CLI app."""

import json
import sys
from pathlib import Path
import argparse

import pytest

# Make sure the todo directory is importable regardless of cwd.
_TODO_DIR = str(Path(__file__).parent)
if _TODO_DIR not in sys.path:
    sys.path.insert(0, _TODO_DIR)

import main as m  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture -- isolate every test to its own tasks.json
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_tasks(tmp_path, monkeypatch):
    """Redirect TASKS_FILE to a fresh temp file for each test."""
    tasks_file = tmp_path / "tasks.json"
    monkeypatch.setattr(m, "TASKS_FILE", tasks_file)
    return tasks_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def add(title: str):
    m.cmd_add(argparse.Namespace(title=title))

def lst():
    m.cmd_list(argparse.Namespace())

def done(task_id: int):
    m.cmd_done(argparse.Namespace(id=task_id))

def remove(task_id: int):
    m.cmd_remove(argparse.Namespace(id=task_id))

def tasks():
    """Read raw task list from the current TASKS_FILE."""
    if m.TASKS_FILE.exists():
        return json.loads(m.TASKS_FILE.read_text())
    return []


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

class TestAdd:
    def test_add_single_task_output(self, capsys):
        add("Buy milk")
        out = capsys.readouterr().out
        assert "Added task #1" in out
        assert "Buy milk" in out

    def test_add_increments_ids(self):
        add("Task A")
        add("Task B")
        add("Task C")
        assert [t["id"] for t in tasks()] == [1, 2, 3]

    def test_add_persists_to_json(self):
        add("Persist me")
        ts = tasks()
        assert len(ts) == 1
        assert ts[0]["title"] == "Persist me"
        assert ts[0]["done"] is False

    def test_add_multiple_titles(self):
        add("Alpha")
        add("Beta")
        ts = tasks()
        assert ts[0]["title"] == "Alpha"
        assert ts[1]["title"] == "Beta"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

class TestList:
    def test_list_empty(self, capsys):
        lst()
        assert "No tasks yet" in capsys.readouterr().out

    def test_list_shows_titles(self, capsys):
        add("Alpha")
        add("Beta")
        capsys.readouterr()  # discard add output
        lst()
        out = capsys.readouterr().out
        assert "Alpha" in out
        assert "Beta" in out

    def test_list_shows_done_status(self, capsys):
        add("Checkable")
        done(1)
        capsys.readouterr()
        lst()
        out = capsys.readouterr().out
        assert "[x]" in out

    def test_list_shows_pending_status(self, capsys):
        add("Pending")
        capsys.readouterr()
        lst()
        out = capsys.readouterr().out
        assert "[ ]" in out


# ---------------------------------------------------------------------------
# done
# ---------------------------------------------------------------------------

class TestDone:
    def test_mark_done_output(self, capsys):
        add("Finish report")
        capsys.readouterr()
        done(1)
        out = capsys.readouterr().out
        assert "Marked task #1 as done" in out

    def test_mark_done_persists(self):
        add("Finish report")
        done(1)
        assert tasks()[0]["done"] is True

    def test_done_already_done_message(self, capsys):
        add("Already done")
        done(1)
        capsys.readouterr()
        done(1)  # second call
        out = capsys.readouterr().out
        assert "already marked done" in out

    def test_done_missing_id_exits(self):
        with pytest.raises(SystemExit):
            done(99)


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

class TestRemove:
    def test_remove_output(self, capsys):
        add("Delete me")
        capsys.readouterr()
        remove(1)
        assert "Removed task #1" in capsys.readouterr().out

    def test_remove_deletes_task(self):
        add("Delete me")
        remove(1)
        assert tasks() == []

    def test_remove_leaves_others(self):
        add("Keep")
        add("Toss")
        add("Keep too")
        remove(2)
        remaining = tasks()
        assert len(remaining) == 2
        assert all(t["id"] != 2 for t in remaining)

    def test_remove_missing_id_exits(self):
        with pytest.raises(SystemExit):
            remove(999)
