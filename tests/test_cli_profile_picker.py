"""Coverage for chika/_cli/profile_picker.py."""
from __future__ import annotations

from io import StringIO
from unittest.mock import patch
from collections import deque

import pytest
from rich.console import Console

from chika._cli import profile_picker as pp


# ── _table_of_profiles ────────────────────────────────────────────────


def test_table_of_profiles_marks_password_protected():
    """A locked profile shows 🔒; unlocked shows a space."""
    table = pp._table_of_profiles(
        ["alice", "bob"], lambda n: n == "alice",
    )
    # We can't easily inspect the rich.Table cells directly — render to a
    # StringIO and look for the lock emoji.
    console = Console(file=StringIO(), force_terminal=False, width=60)
    console.print(table)
    rendered = console.file.getvalue()
    assert "alice" in rendered
    assert "bob" in rendered
    assert "🔒" in rendered


def test_table_of_profiles_empty_iterable_renders_empty():
    """No profiles → table renders without raising."""
    table = pp._table_of_profiles([], lambda _: False)
    console = Console(file=StringIO(), force_terminal=False, width=40)
    console.print(table)  # Should not raise


# ── _authenticate ─────────────────────────────────────────────────────


class FakePM:
    """In-memory profile manager — just enough surface for the picker."""
    def __init__(self, profiles=None, passwords=None):
        self._profiles = list(profiles or [])
        self._passwords = dict(passwords or {})
    def list_profiles(self):
        return list(self._profiles)
    def has_password(self, name):
        return bool(self._passwords.get(name))
    def verify_password(self, name, pw):
        return self._passwords.get(name) == pw
    def exists(self, name):
        return name in self._profiles
    def get_or_create(self, name):
        if name not in self._profiles:
            self._profiles.append(name)
        return type("Profile", (), {"name": name})()
    def set_password(self, name, pw):
        self._passwords[name] = pw


def test_authenticate_succeeds_on_correct_password():
    pm = FakePM(["alice"], {"alice": "hunter2"})
    console = Console(file=StringIO(), force_terminal=False)
    with patch.object(pp.getpass, "getpass", return_value="hunter2"):
        out = pp._authenticate(console, pm, "alice")
    assert out is True


def test_authenticate_fails_after_max_attempts():
    pm = FakePM(["alice"], {"alice": "hunter2"})
    console = Console(file=StringIO(), force_terminal=False)
    with patch.object(pp.getpass, "getpass", return_value="wrong"):
        out = pp._authenticate(console, pm, "alice")
    assert out is False


def test_authenticate_returns_false_on_ctrl_c():
    pm = FakePM(["alice"], {"alice": "hunter2"})
    console = Console(file=StringIO(), force_terminal=False)
    with patch.object(pp.getpass, "getpass", side_effect=KeyboardInterrupt()):
        out = pp._authenticate(console, pm, "alice")
    assert out is False


def test_authenticate_succeeds_on_second_attempt():
    pm = FakePM(["alice"], {"alice": "hunter2"})
    console = Console(file=StringIO(), force_terminal=False)
    pws = deque(["wrong", "hunter2"])
    with patch.object(pp.getpass, "getpass", side_effect=lambda _: pws.popleft()):
        out = pp._authenticate(console, pm, "alice")
    assert out is True


# ── select_profile ─────────────────────────────────────────────────────


def test_select_profile_picks_by_number():
    pm = FakePM(["alice", "bob", "carol"])
    console = Console(file=StringIO(), force_terminal=False)
    with patch("builtins.input", return_value="2"):
        out = pp.select_profile(console, pm, accent="cyan")
    assert out.name == "bob"


def test_select_profile_picks_by_name():
    pm = FakePM(["alice", "bob"])
    console = Console(file=StringIO(), force_terminal=False)
    with patch("builtins.input", return_value="bob"):
        out = pp.select_profile(console, pm, accent="cyan")
    assert out.name == "bob"


def test_select_profile_case_insensitive_match():
    pm = FakePM(["Alice", "Bob"])
    console = Console(file=StringIO(), force_terminal=False)
    with patch("builtins.input", return_value="bob"):
        out = pp.select_profile(console, pm, accent="cyan")
    assert out.name == "Bob"


def test_select_profile_quit_exits():
    pm = FakePM(["alice"])
    console = Console(file=StringIO(), force_terminal=False)
    with patch("builtins.input", return_value="q"):
        with pytest.raises(SystemExit):
            pp.select_profile(console, pm, accent="cyan")


def test_select_profile_keyboard_interrupt_exits():
    pm = FakePM(["alice"])
    console = Console(file=StringIO(), force_terminal=False)
    with patch("builtins.input", side_effect=KeyboardInterrupt()):
        with pytest.raises(SystemExit):
            pp.select_profile(console, pm, accent="cyan")


def test_select_profile_re_prompts_on_unknown_name():
    pm = FakePM(["alice"])
    console = Console(file=StringIO(), force_terminal=False)
    answers = deque(["nonexistent_user", "alice"])
    with patch("builtins.input", side_effect=lambda _: answers.popleft()):
        out = pp.select_profile(console, pm, accent="cyan")
    assert out.name == "alice"


def test_select_profile_re_prompts_on_empty_input():
    pm = FakePM(["alice"])
    console = Console(file=StringIO(), force_terminal=False)
    answers = deque(["", "alice"])
    with patch("builtins.input", side_effect=lambda _: answers.popleft()):
        out = pp.select_profile(console, pm, accent="cyan")
    assert out.name == "alice"


def test_select_profile_with_no_profiles_creates_first():
    """Empty pm → drops into create flow."""
    pm = FakePM([])
    console = Console(file=StringIO(), force_terminal=False)
    inputs = deque(["fresh", "n"])
    with patch("builtins.input", side_effect=lambda _: inputs.popleft()):
        out = pp.select_profile(console, pm, accent="cyan")
    assert out.name == "fresh"


def test_select_profile_new_command_creates():
    pm = FakePM(["alice"])
    console = Console(file=StringIO(), force_terminal=False)
    inputs = deque(["new bob", "n"])
    with patch("builtins.input", side_effect=lambda _: inputs.popleft()):
        out = pp.select_profile(console, pm, accent="cyan")
    assert out.name == "bob"


def test_select_profile_new_with_no_name_re_prompts():
    pm = FakePM(["alice"])
    console = Console(file=StringIO(), force_terminal=False)
    inputs = deque(["new ", "alice"])
    with patch("builtins.input", side_effect=lambda _: inputs.popleft()):
        out = pp.select_profile(console, pm, accent="cyan")
    assert out.name == "alice"


def test_select_profile_picks_locked_with_correct_password():
    pm = FakePM(["alice"], {"alice": "hunter2"})
    console = Console(file=StringIO(), force_terminal=False)
    with patch("builtins.input", return_value="alice"), \
         patch.object(pp.getpass, "getpass", return_value="hunter2"):
        out = pp.select_profile(console, pm, accent="cyan")
    assert out.name == "alice"


def test_select_profile_locked_wrong_password_loops():
    """3 wrong tries → falls back to picker → second attempt picks ok user."""
    pm = FakePM(["locked", "open"], {"locked": "secret"})
    console = Console(file=StringIO(), force_terminal=False)
    inputs = deque(["locked", "open"])
    with patch("builtins.input", side_effect=lambda _: inputs.popleft()), \
         patch.object(pp.getpass, "getpass", return_value="wrong"):
        out = pp.select_profile(console, pm, accent="cyan")
    assert out.name == "open"


# ── _create_profile ───────────────────────────────────────────────────


def test_create_profile_no_password():
    pm = FakePM([])
    console = Console(file=StringIO(), force_terminal=False)
    inputs = deque(["alice", "n"])
    with patch("builtins.input", side_effect=lambda _: inputs.popleft()):
        out = pp._create_profile(console, pm, accent="cyan")
    assert out.name == "alice"
    assert not pm.has_password("alice")


def test_create_profile_with_password():
    pm = FakePM([])
    console = Console(file=StringIO(), force_terminal=False)
    inputs = deque(["alice", "y"])
    with patch("builtins.input", side_effect=lambda _: inputs.popleft()), \
         patch.object(pp.getpass, "getpass", return_value="hunter2"):
        out = pp._create_profile(console, pm, accent="cyan")
    assert out.name == "alice"
    assert pm.has_password("alice")


def test_create_profile_password_mismatch_loops():
    pm = FakePM([])
    console = Console(file=StringIO(), force_terminal=False)
    text_inputs = deque(["alice", "y"])
    pw_inputs = deque(["pw1", "different", "pw2", "pw2"])
    with patch("builtins.input", side_effect=lambda _: text_inputs.popleft()), \
         patch.object(pp.getpass, "getpass",
                      side_effect=lambda _: pw_inputs.popleft()):
        out = pp._create_profile(console, pm, accent="cyan")
    assert out.name == "alice"
    assert pm.has_password("alice")


def test_create_profile_existing_skips_creation():
    pm = FakePM(["alice"])
    console = Console(file=StringIO(), force_terminal=False)
    out = pp._create_profile(console, pm, name="alice", accent="cyan")
    assert out.name == "alice"


def test_create_profile_explicit_name_skips_input():
    pm = FakePM([])
    console = Console(file=StringIO(), force_terminal=False)
    with patch("builtins.input", return_value="n"):
        out = pp._create_profile(console, pm, name="bob", accent="cyan")
    assert out.name == "bob"


def test_create_profile_empty_name_falls_back_to_picker():
    """Empty name → re-runs select_profile (which has more profiles already)."""
    pm = FakePM(["alice"])
    console = Console(file=StringIO(), force_terminal=False)
    inputs = deque(["", "alice"])
    with patch("builtins.input", side_effect=lambda _: inputs.popleft()):
        out = pp._create_profile(console, pm, accent="cyan")
    assert out.name == "alice"


def test_create_profile_keyboard_interrupt_exits():
    pm = FakePM([])
    console = Console(file=StringIO(), force_terminal=False)
    with patch("builtins.input", side_effect=KeyboardInterrupt()):
        with pytest.raises(SystemExit):
            pp._create_profile(console, pm, accent="cyan")
