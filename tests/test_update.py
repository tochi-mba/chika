"""Tests for ``chika update`` + auto-update on startup.

Layers:

  1. ``parse_github_remote`` — covers SSH, HTTPS, .git suffix, non-GH.
  2. ``detect_install_kind`` — git_clone / pip_pypi / unknown branches.
  3. ``check_for_updates`` — git path + pypi path, with mocked HTTP and
     mocked ``git`` subprocess.
  4. ``update_chika`` — git_clone success/fail, pip_pypi success/fail,
     unknown install message.
  5. ``auto_update_on_startup`` — orchestration: setting=off short-circuit,
     throttling, eligibility (must be available + ci_green + new SHA),
     state file written, restart notice rendered.
  6. The ``/update``, ``/auto-update``, ``/doctor`` slash commands.
  7. The ``chika update`` and ``chika update --check`` argv subcommands.
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from chika._cli import update as upd


# ── parse_github_remote ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/tochi-mba/chika.git", ("tochi-mba", "chika")),
        ("https://github.com/tochi-mba/chika",     ("tochi-mba", "chika")),
        ("https://github.com/tochi-mba/chika/",    ("tochi-mba", "chika")),
        ("http://github.com/foo/bar.git",          ("foo", "bar")),
        ("https://www.github.com/x/y",             ("x", "y")),
        ("git@github.com:tochi-mba/chika.git",     ("tochi-mba", "chika")),
        ("git@github.com:tochi-mba/chika",         ("tochi-mba", "chika")),
        ("https://gitlab.com/foo/bar",             None),
        ("https://bitbucket.org/foo/bar",          None),
        ("",                                        None),
        ("not a url",                               None),
    ],
)
def test_parse_github_remote(url, expected):
    assert upd.parse_github_remote(url) == expected


# ── detect_install_kind ─────────────────────────────────────────────────


def test_detect_install_kind_git_clone(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    assert upd.detect_install_kind(tmp_path) == "git_clone"


def test_detect_install_kind_pip(tmp_path: Path, monkeypatch):
    # No .git dir; pretend pip metadata reports the package.
    monkeypatch.setattr(upd, "_is_pip_installed", lambda: True)
    assert upd.detect_install_kind(tmp_path) == "pip_pypi"


def test_detect_install_kind_unknown(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(upd, "_is_pip_installed", lambda: False)
    assert upd.detect_install_kind(tmp_path) == "unknown"


# ── check_for_updates: git path ─────────────────────────────────────────


def _proc(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def _make_fake_git(
    *,
    head_sha: str = "a" * 40,
    branch: str = "main",
    status_porcelain: str = "",
    remote_url: str = "https://github.com/tochi-mba/chika.git",
    remote_returncode: int = 0,
):
    """Build a fake_git callable matching the full sequence of git
    invocations the production code makes:

      rev-parse HEAD                  → head_sha
      rev-parse --abbrev-ref HEAD     → branch
      status --porcelain              → status_porcelain
      remote get-url origin           → remote_url
    """
    def fake_git(args):
        # The args list always starts with ["-C", root_path, ...].
        sub = args[2:]
        if sub == ["rev-parse", "HEAD"]:
            return _proc(head_sha + "\n")
        if sub == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return _proc(branch + "\n")
        if sub == ["status", "--porcelain"]:
            return _proc(status_porcelain)
        if sub == ["remote", "get-url", "origin"]:
            return _proc(remote_url + "\n", returncode=remote_returncode)
        return _proc()
    return fake_git


@pytest.fixture
def fake_git_root(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_check_for_updates_up_to_date(fake_git_root: Path):
    sha = "a" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": sha}
        return {}

    info = upd.check_for_updates(
        root=fake_git_root, http_get=fake_http,
        git_runner=_make_fake_git(head_sha=sha),
    )
    assert info.kind == "git_clone"
    assert info.available is False
    assert info.reason == "up_to_date"
    assert info.current == sha[:7]


def test_check_for_updates_available_ci_green(fake_git_root: Path):
    local = "a" * 40
    remote = "b" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": remote}
        if "check-runs" in url:
            return {"check_runs": [
                {"status": "completed", "conclusion": "success"},
                {"status": "completed", "conclusion": "skipped"},
            ]}
        return {}

    info = upd.check_for_updates(
        root=fake_git_root, http_get=fake_http,
        git_runner=_make_fake_git(
            head_sha=local,
            remote_url="git@github.com:tochi-mba/chika.git",
        ),
    )
    assert info.available is True
    assert info.ci_green is True
    assert info.reason == "ok"
    assert info.current == local[:7]
    assert info.latest == remote[:7]


def test_check_for_updates_available_ci_red(fake_git_root: Path):
    local = "a" * 40
    remote = "b" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": remote}
        if "check-runs" in url:
            return {"check_runs": [
                {"status": "completed", "conclusion": "failure"},
            ]}
        return {}

    info = upd.check_for_updates(
        root=fake_git_root, http_get=fake_http,
        git_runner=_make_fake_git(head_sha=local),
    )
    assert info.available is True
    assert info.ci_green is False
    assert info.reason == "ci_red"


def test_check_for_updates_ci_in_progress_is_red(fake_git_root: Path):
    """A check-run still ``in_progress`` is treated as not green."""
    local = "a" * 40
    remote = "b" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": remote}
        if "check-runs" in url:
            return {"check_runs": [
                {"status": "in_progress", "conclusion": None},
            ]}
        return {}

    info = upd.check_for_updates(
        root=fake_git_root, http_get=fake_http,
        git_runner=_make_fake_git(head_sha=local),
    )
    assert info.ci_green is False


def test_check_for_updates_no_check_runs_is_not_green(fake_git_root: Path):
    """No CI configured → fail-safe (don't auto-update)."""
    local = "a" * 40
    remote = "b" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": remote}
        if "check-runs" in url:
            return {"check_runs": []}
        return {}

    info = upd.check_for_updates(
        root=fake_git_root, http_get=fake_http,
        git_runner=_make_fake_git(head_sha=local),
    )
    assert info.ci_green is False


def test_check_for_updates_offline(fake_git_root: Path):
    def fake_http(url, *, timeout):
        raise upd._HttpError("offline")

    info = upd.check_for_updates(
        root=fake_git_root, http_get=fake_http,
        git_runner=_make_fake_git(),
    )
    assert info.available is False
    assert info.reason == "offline"


def test_check_for_updates_rate_limited(fake_git_root: Path):
    def fake_http(url, *, timeout):
        raise upd._HttpError("rate_limited")

    info = upd.check_for_updates(
        root=fake_git_root, http_get=fake_http,
        git_runner=_make_fake_git(),
    )
    assert info.reason == "rate_limited"


def test_check_for_updates_ci_endpoint_fails_after_new_sha_seen(
    fake_git_root: Path,
):
    """New SHA visible but CI fetch fails → mark available=False, ci_green=False
    (fail-safe), reason='ci_unknown'."""
    local = "a" * 40
    remote = "b" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": remote}
        raise upd._HttpError("offline")

    info = upd.check_for_updates(
        root=fake_git_root, http_get=fake_http,
        git_runner=_make_fake_git(head_sha=local),
    )
    assert info.available is False
    assert info.ci_green is False
    assert info.reason == "ci_unknown"
    # The latest SHA was still recorded so the user can decide manually.
    assert info.latest == remote[:7]


def test_check_for_updates_non_github_remote(fake_git_root: Path):
    info = upd.check_for_updates(
        root=fake_git_root, http_get=lambda *a, **k: {},
        git_runner=_make_fake_git(remote_url="https://gitlab.com/foo/bar"),
    )
    assert info.reason == "non_github_remote"


def test_check_for_updates_no_remote(fake_git_root: Path):
    info = upd.check_for_updates(
        root=fake_git_root, http_get=lambda *a, **k: {},
        git_runner=_make_fake_git(remote_returncode=128),
    )
    assert info.reason == "no_remote"


def test_check_for_updates_skips_when_on_feature_branch(fake_git_root: Path):
    """User on a feature branch must NOT trigger auto-update — pulling
    upstream main into a feature branch would be wrong."""
    info = upd.check_for_updates(
        root=fake_git_root, http_get=lambda *a, **k: {},
        git_runner=_make_fake_git(branch="feature/cool-thing"),
    )
    assert info.reason == "not_on_main"
    assert info.available is False


def test_check_for_updates_master_branch_proceeds(fake_git_root: Path):
    """Repos using ``master`` as default should still pass the branch guard."""
    sha = "a" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": sha}
        return {}

    info = upd.check_for_updates(
        root=fake_git_root, http_get=fake_http,
        git_runner=_make_fake_git(head_sha=sha, branch="master"),
    )
    assert info.reason == "up_to_date"


def test_check_for_updates_detached_head_proceeds(fake_git_root: Path):
    """``git rev-parse --abbrev-ref HEAD`` returns 'HEAD' on detached.
    We let the check proceed (it'll report up_to_date or available)
    but auto-update can't fast-forward — that's a real-world tradeoff."""
    sha = "a" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": sha}
        return {}

    info = upd.check_for_updates(
        root=fake_git_root, http_get=fake_http,
        git_runner=_make_fake_git(head_sha=sha, branch="HEAD"),
    )
    # Should NOT short-circuit at 'not_on_main'
    assert info.reason != "not_on_main"


def test_check_for_updates_skips_when_working_tree_dirty(fake_git_root: Path):
    """Dirty working tree → skip auto-update. ``git pull`` could
    interfere with the user's WIP."""
    info = upd.check_for_updates(
        root=fake_git_root, http_get=lambda *a, **k: {},
        git_runner=_make_fake_git(status_porcelain=" M chika/_cli/app.py\n"),
    )
    assert info.reason == "working_tree_dirty"
    assert info.available is False


def test_check_for_updates_clean_tree_passes_through(fake_git_root: Path):
    """A clean tree must NOT mistakenly hit the dirty guard."""
    sha = "a" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": sha}
        return {}

    info = upd.check_for_updates(
        root=fake_git_root, http_get=fake_http,
        # Whitespace-only stdout is not 'dirty' — strip() collapses it
        git_runner=_make_fake_git(head_sha=sha, status_porcelain="   \n"),
    )
    assert info.reason == "up_to_date"


def test_check_for_updates_git_missing_returns_reason(
    fake_git_root: Path, monkeypatch,
):
    monkeypatch.setattr(upd.shutil, "which", lambda _: None)
    info = upd.check_for_updates(
        root=fake_git_root, http_get=lambda *a, **k: {},
        git_runner=lambda _: _proc(),
    )
    assert info.reason == "git_missing"


# ── check_for_updates: pypi path ────────────────────────────────────────


def test_check_for_updates_pypi_up_to_date(monkeypatch, tmp_path):
    monkeypatch.setattr(upd, "_is_pip_installed", lambda: True)
    monkeypatch.setattr(upd, "current_version", lambda: "2.0.0")

    def fake_http(url, *, timeout):
        return {"info": {"version": "2.0.0"}}

    info = upd.check_for_updates(
        root=tmp_path, http_get=fake_http,
        git_runner=lambda _: _proc(),
    )
    assert info.kind == "pip_pypi"
    assert info.available is False
    assert info.reason == "up_to_date"


def test_check_for_updates_pypi_newer_available(monkeypatch, tmp_path):
    monkeypatch.setattr(upd, "_is_pip_installed", lambda: True)
    monkeypatch.setattr(upd, "current_version", lambda: "2.0.0")

    def fake_http(url, *, timeout):
        return {"info": {"version": "2.0.5"}}

    info = upd.check_for_updates(
        root=tmp_path, http_get=fake_http,
        git_runner=lambda _: _proc(),
    )
    assert info.available is True
    assert info.ci_green is True   # PyPI release implies CI passed upstream
    assert info.latest == "2.0.5"


def test_check_for_updates_unknown_install(tmp_path, monkeypatch):
    monkeypatch.setattr(upd, "_is_pip_installed", lambda: False)
    info = upd.check_for_updates(
        root=tmp_path, http_get=lambda *a, **k: {},
        git_runner=lambda _: _proc(),
    )
    assert info.kind == "unknown"
    assert info.available is False
    assert info.reason == "unknown_install"


# ── update_chika ────────────────────────────────────────────────────────


def test_update_chika_unknown_install(tmp_path, monkeypatch):
    # Force the unknown branch — chika is editable-installed in this
    # repo, so without this override we'd fall into pip_pypi.
    monkeypatch.setattr(upd, "_is_pip_installed", lambda: False)
    result = upd.update_chika(console=None, root=tmp_path)
    assert result.success is False
    assert result.kind == "unknown"
    assert "manually" in result.message or "install -e" in result.message


def test_update_chika_dry_run_git_clone(fake_git_root: Path):
    result = upd.update_chika(console=None, root=fake_git_root, dry_run=True)
    assert result.success is True
    assert result.kind == "git_clone"
    assert result.restart_required is True
    assert "dry-run" in result.message


def test_update_chika_git_clone_success(fake_git_root: Path):
    """Mock subprocess.run to succeed for both git pull and pip install."""
    def fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="ok", stderr="",
        )

    with patch.object(upd.subprocess, "run", fake_run):
        result = upd.update_chika(console=None, root=fake_git_root)
    assert result.success is True
    assert result.kind == "git_clone"
    assert result.restart_required is True


def test_update_chika_git_pull_fails(fake_git_root: Path):
    def fake_run(cmd, *args, **kwargs):
        if "pull" in cmd:
            return subprocess.CompletedProcess(
                args=cmd, returncode=1, stdout="", stderr="conflict",
            )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch.object(upd.subprocess, "run", fake_run):
        result = upd.update_chika(console=None, root=fake_git_root)
    assert result.success is False
    assert "git pull failed" in result.message


def test_update_chika_pip_refresh_fails(fake_git_root: Path):
    def fake_run(cmd, *args, **kwargs):
        if "pull" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="pip explosion",
        )

    with patch.object(upd.subprocess, "run", fake_run):
        result = upd.update_chika(console=None, root=fake_git_root)
    assert result.success is False
    assert "pip refresh failed" in result.message


def test_update_chika_git_missing(fake_git_root: Path, monkeypatch):
    monkeypatch.setattr(upd.shutil, "which", lambda _: None)
    result = upd.update_chika(console=None, root=fake_git_root)
    assert result.success is False
    assert "git not found" in result.message


def test_update_chika_pypi_dry_run(monkeypatch, tmp_path):
    monkeypatch.setattr(upd, "_is_pip_installed", lambda: True)
    result = upd.update_chika(console=None, root=tmp_path, dry_run=True)
    assert result.kind == "pip_pypi"
    assert result.success is True


def test_update_chika_pypi_success(monkeypatch, tmp_path):
    monkeypatch.setattr(upd, "_is_pip_installed", lambda: True)
    monkeypatch.setattr(
        upd.subprocess, "run",
        lambda cmd, *a, **k: subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr="",
        ),
    )
    result = upd.update_chika(console=None, root=tmp_path)
    assert result.success is True
    assert result.kind == "pip_pypi"


def test_update_chika_pypi_pip_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(upd, "_is_pip_installed", lambda: True)
    monkeypatch.setattr(
        upd.subprocess, "run",
        lambda cmd, *a, **k: subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="resolver failed",
        ),
    )
    result = upd.update_chika(console=None, root=tmp_path)
    assert result.success is False


def test_update_chika_renders_panel(fake_git_root: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120, color_system=None)
    with patch.object(upd.subprocess, "run",
                       lambda cmd, *a, **k: subprocess.CompletedProcess(
                           args=cmd, returncode=0, stdout="", stderr="")):
        upd.update_chika(console=console, root=fake_git_root)
    out = buf.getvalue()
    assert "git_clone" in out
    assert "restart" in out.lower()


# ── auto_update_on_startup ──────────────────────────────────────────────


def test_auto_update_setting_off_short_circuits(tmp_path: Path):
    state = tmp_path / "state.json"
    result = upd.auto_update_on_startup(
        console=None, root=tmp_path, setting="off", state_path=state,
    )
    assert result is None
    assert not state.exists()


def test_auto_update_throttled(fake_git_root: Path, tmp_path):
    state = tmp_path / "state.json"
    # Pre-seed state so the throttle short-circuits.
    state.write_text(json.dumps({
        "last_check_at": 1_000_000.0,
        "last_info": {
            "kind": "git_clone", "current": "aaaaaaa", "latest": "bbbbbbb",
            "ci_green": True, "reason": "ok",
        },
    }))
    info = upd.auto_update_on_startup(
        console=None, root=fake_git_root, setting="on",
        state_path=state, now=1_000_001.0,
        http_get=lambda *a, **k: pytest.fail("http should not be called"),
        git_runner=lambda _: pytest.fail("git should not be called"),
    )
    assert info is not None
    assert info.reason == "throttled"
    assert info.available is False  # never auto-apply on a throttled check


def test_auto_update_applies_when_eligible(
    fake_git_root: Path, tmp_path: Path,
):
    state = tmp_path / "state.json"
    local, remote = "a" * 40, "b" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": remote}
        if "check-runs" in url:
            return {"check_runs": [
                {"status": "completed", "conclusion": "success"},
            ]}
        return {}

    update_calls: list[Path] = []

    def fake_update_chika(*, console, root):
        update_calls.append(root)
        return upd.UpdateResult(
            kind="git_clone", success=True, message="updated",
            restart_required=True,
        )

    with patch.object(upd, "update_chika", fake_update_chika):
        info = upd.auto_update_on_startup(
            console=None, root=fake_git_root, setting="on",
            state_path=state, now=2_000_000.0,
            http_get=fake_http, git_runner=_make_fake_git(head_sha=local),
        )

    assert info is not None
    assert info.available is True
    assert info.ci_green is True
    assert update_calls == [fake_git_root]

    written = json.loads(state.read_text())
    assert written["last_applied_sha"] == remote[:7]
    assert written["last_apply_success"] is True


def test_auto_update_skips_when_ci_red(
    fake_git_root: Path, tmp_path: Path,
):
    state = tmp_path / "state.json"
    local, remote = "a" * 40, "b" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": remote}
        if "check-runs" in url:
            return {"check_runs": [
                {"status": "completed", "conclusion": "failure"},
            ]}
        return {}

    with patch.object(upd, "update_chika",
                       lambda **_: pytest.fail("must not run when ci red")):
        info = upd.auto_update_on_startup(
            console=None, root=fake_git_root, setting="on",
            state_path=state, now=3_000_000.0,
            http_get=fake_http, git_runner=_make_fake_git(head_sha=local),
        )

    assert info is not None
    assert info.available is True
    assert info.ci_green is False
    written = json.loads(state.read_text())
    assert "last_applied_sha" not in written  # never applied


def test_auto_update_skips_when_already_applied(
    fake_git_root: Path, tmp_path: Path,
):
    """If the latest SHA matches ``last_applied_sha`` we don't reapply."""
    state = tmp_path / "state.json"
    local, remote = "a" * 40, "b" * 40
    state.write_text(json.dumps({
        "last_applied_sha": remote[:7],
        "last_check_at": 0.0,  # don't trigger throttle short-circuit
    }))

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": remote}
        if "check-runs" in url:
            return {"check_runs": [
                {"status": "completed", "conclusion": "success"},
            ]}
        return {}

    with patch.object(upd, "update_chika",
                       lambda **_: pytest.fail("must not run on same SHA")):
        upd.auto_update_on_startup(
            console=None, root=fake_git_root, setting="on",
            state_path=state, now=4_000_000.0,
            http_get=fake_http, git_runner=_make_fake_git(head_sha=local),
        )


def test_auto_update_skips_when_on_feature_branch(
    fake_git_root: Path, tmp_path: Path,
):
    """Even with auto_update=on, never auto-pull on a feature branch."""
    state = tmp_path / "state.json"
    local, remote = "a" * 40, "b" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": remote}
        return {}

    with patch.object(upd, "update_chika",
                       lambda **_: pytest.fail("must not run on feature branch")):
        info = upd.auto_update_on_startup(
            console=None, root=fake_git_root, setting="on",
            state_path=state, now=2_500_000.0,
            http_get=fake_http,
            git_runner=_make_fake_git(head_sha=local, branch="feature/x"),
        )
    assert info is not None
    assert info.reason == "not_on_main"


def test_auto_update_skips_when_dirty_tree(
    fake_git_root: Path, tmp_path: Path,
):
    """Dirty working tree → never auto-update, even if everything else
    looks good."""
    state = tmp_path / "state.json"
    local = "a" * 40

    with patch.object(upd, "update_chika",
                       lambda **_: pytest.fail("must not run on dirty tree")):
        info = upd.auto_update_on_startup(
            console=None, root=fake_git_root, setting="on",
            state_path=state, now=2_700_000.0,
            http_get=lambda *a, **k: {},
            git_runner=_make_fake_git(
                head_sha=local, status_porcelain=" M somefile.py",
            ),
        )
    assert info is not None
    assert info.reason == "working_tree_dirty"


def test_auto_update_renders_notice_when_applied(
    fake_git_root: Path, tmp_path: Path,
):
    state = tmp_path / "state.json"
    local, remote = "a" * 40, "b" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": remote}
        if "check-runs" in url:
            return {"check_runs": [{"status": "completed", "conclusion": "success"}]}
        return {}

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120, color_system=None)
    with patch.object(upd, "update_chika",
                       lambda **_: upd.UpdateResult(
                           kind="git_clone", success=True,
                           message="updated", restart_required=True,
                       )):
        upd.auto_update_on_startup(
            console=console, root=fake_git_root, setting="on",
            state_path=state, now=5_000_000.0,
            http_get=fake_http, git_runner=_make_fake_git(head_sha=local),
        )
    out = buf.getvalue()
    assert "auto-updated" in out
    assert "restart" in out.lower()


def test_auto_update_renders_failure_notice(
    fake_git_root: Path, tmp_path: Path,
):
    """When the auto-apply itself fails we render a 'tried but failed'
    notice rather than silently swallowing it."""
    state = tmp_path / "state.json"
    local, remote = "a" * 40, "b" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": remote}
        if "check-runs" in url:
            return {"check_runs": [{"status": "completed", "conclusion": "success"}]}
        return {}

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120, color_system=None)
    with patch.object(upd, "update_chika",
                       lambda **_: upd.UpdateResult(
                           kind="git_clone", success=False,
                           message="git pull failed: conflict",
                       )):
        upd.auto_update_on_startup(
            console=console, root=fake_git_root, setting="on",
            state_path=state, now=5_500_000.0,
            http_get=fake_http, git_runner=_make_fake_git(head_sha=local),
        )
    out = buf.getvalue()
    assert "tried but failed" in out


def test_auto_update_renders_available_notice_when_ci_red(
    fake_git_root: Path, tmp_path: Path,
):
    state = tmp_path / "state.json"
    local, remote = "a" * 40, "b" * 40

    def fake_http(url, *, timeout):
        if url.endswith("/commits/main"):
            return {"sha": remote}
        if "check-runs" in url:
            return {"check_runs": [{"status": "completed", "conclusion": "failure"}]}
        return {}

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120, color_system=None)
    upd.auto_update_on_startup(
        console=console, root=fake_git_root, setting="on",
        state_path=state, now=6_000_000.0,
        http_get=fake_http, git_runner=_make_fake_git(head_sha=local),
    )
    out = buf.getvalue()
    assert "update available" in out
    assert "ci not green" in out


def test_auto_update_persists_state_on_offline_check(
    fake_git_root: Path, tmp_path: Path,
):
    """Even when the network fails we still persist last_check_at so the
    throttle holds for the next launch."""
    state = tmp_path / "state.json"

    def fake_http(url, *, timeout):
        raise upd._HttpError("offline")

    info = upd.auto_update_on_startup(
        console=None, root=fake_git_root, setting="on",
        state_path=state, now=7_000_000.0,
        http_get=fake_http, git_runner=_make_fake_git(),
    )
    assert info is not None
    assert info.reason == "offline"
    written = json.loads(state.read_text())
    assert written["last_check_at"] == 7_000_000.0


# ── _check_runs_all_green ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"check_runs": []}, False),
        ({"check_runs": [{"status": "completed", "conclusion": "success"}]}, True),
        ({"check_runs": [{"status": "completed", "conclusion": "skipped"}]}, True),
        ({"check_runs": [{"status": "completed", "conclusion": "neutral"}]}, True),
        ({"check_runs": [{"status": "completed", "conclusion": "failure"}]}, False),
        ({"check_runs": [{"status": "completed", "conclusion": "cancelled"}]}, False),
        ({"check_runs": [{"status": "queued", "conclusion": None}]}, False),
        ({"check_runs": [{"status": "in_progress", "conclusion": None}]}, False),
        # Mix: one fail tanks the lot
        ({"check_runs": [
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "failure"},
        ]}, False),
        # All success
        ({"check_runs": [
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "success"},
        ]}, True),
        ({}, False),
        ({"check_runs": None}, False),
    ],
)
def test_check_runs_all_green(payload, expected):
    assert upd._check_runs_all_green(payload) is expected


# ── State file persistence ─────────────────────────────────────────────


def test_state_file_load_missing_returns_empty(tmp_path):
    assert upd._load_state(tmp_path / "missing.json") == {}


def test_state_file_load_corrupt_returns_empty(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("{not json")
    assert upd._load_state(p) == {}


def test_state_file_save_creates_parent_dir(tmp_path):
    p = tmp_path / "nested" / "subdir" / "state.json"
    upd._save_state({"x": 1}, p)
    assert json.loads(p.read_text()) == {"x": 1}


def test_state_file_save_swallows_errors(tmp_path, monkeypatch):
    """Even if the disk write fails we don't raise — startup must continue."""
    def boom(*a, **k):
        raise OSError("disk full")

    p = tmp_path / "state.json"
    monkeypatch.setattr(Path, "write_text", boom)
    # Should not raise
    upd._save_state({"x": 1}, p)


# ── Slash commands ─────────────────────────────────────────────────────


def _make_ctx():
    from chika._cli import commands as cmd
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=140, color_system=None)
    ctx = cmd.CommandContext(console=console, engine=None)  # type: ignore[arg-type]
    return ctx, buf


def test_slash_update_check_up_to_date(monkeypatch):
    from chika._cli import commands as cmd

    monkeypatch.setattr(
        upd, "check_for_updates",
        lambda **_: upd.UpdateInfo(
            kind="git_clone", available=False,
            current="abc1234", latest="abc1234",
            ci_green=True, reason="up_to_date",
        ),
    )
    ctx, buf = _make_ctx()
    cmd.dispatch(ctx, "/update --check")
    assert "up to date" in buf.getvalue()


def test_slash_update_check_available(monkeypatch):
    from chika._cli import commands as cmd

    monkeypatch.setattr(
        upd, "check_for_updates",
        lambda **_: upd.UpdateInfo(
            kind="git_clone", available=True,
            current="abc1234", latest="def5678",
            ci_green=True, reason="ok",
        ),
    )
    ctx, buf = _make_ctx()
    cmd.dispatch(ctx, "/update --check")
    out = buf.getvalue()
    assert "update available" in out
    assert "abc1234" in out
    assert "def5678" in out


def test_slash_update_apply(monkeypatch):
    from chika._cli import commands as cmd

    called: list[bool] = []

    def fake_update(*, console):
        called.append(True)
        return upd.UpdateResult(
            kind="git_clone", success=True, message="ok", restart_required=True,
        )

    monkeypatch.setattr(upd, "update_chika", fake_update)
    ctx, _buf = _make_ctx()
    cmd.dispatch(ctx, "/update")
    assert called == [True]


def test_slash_auto_update_show(monkeypatch):
    from chika._cli import commands as cmd
    import api.settings_store as ss

    monkeypatch.setattr(ss, "get", lambda key, default=None: "on" if key == "auto_update" else default)
    ctx, buf = _make_ctx()
    cmd.dispatch(ctx, "/auto-update")
    assert "auto-update: on" in buf.getvalue()


def test_slash_auto_update_set_off():
    from chika._cli import commands as cmd
    import api.settings_store as ss

    ctx, buf = _make_ctx()
    cmd.dispatch(ctx, "/auto-update off")
    assert ss.get("auto_update") == "off"
    assert "auto-update" in buf.getvalue()


def test_slash_auto_update_invalid_value():
    from chika._cli import commands as cmd

    ctx, buf = _make_ctx()
    cmd.dispatch(ctx, "/auto-update sometimes")
    assert "/auto-update on|off" in buf.getvalue()


def test_slash_doctor_runs():
    from chika._cli import commands as cmd

    ctx, buf = _make_ctx()
    cmd.dispatch(ctx, "/doctor")
    out = buf.getvalue()
    # Should at least mention python version in the report
    assert "python" in out.lower()


def test_commands_registered():
    from chika._cli import commands as cmd
    names = [c.name for c in cmd.list_commands()]
    assert "update" in names
    assert "auto-update" in names
    assert "doctor" in names


# ── argv subcommands ────────────────────────────────────────────────────


def test_argv_update_subcommand(monkeypatch):
    from chika._cli import app as appmod

    called: list[bool] = []
    monkeypatch.setattr(
        upd, "update_chika",
        lambda **_: called.append(True) or upd.UpdateResult(
            kind="git_clone", success=True, message="ok", restart_required=True,
        ),
    )
    monkeypatch.setattr(appmod, "_run_rich",
                         lambda: pytest.fail("REPL must not boot"))

    appmod.cli(argv=["update"])
    assert called == [True]


def test_argv_update_check_subcommand(monkeypatch, capsys):
    from chika._cli import app as appmod

    monkeypatch.setattr(
        upd, "check_for_updates",
        lambda **_: upd.UpdateInfo(
            kind="git_clone", available=True,
            current="abc1234", latest="def5678",
            ci_green=True, reason="ok",
        ),
    )
    monkeypatch.setattr(appmod, "_run_rich",
                         lambda: pytest.fail("REPL must not boot"))

    appmod.cli(argv=["update", "--check"])
    # When rich is available, output goes through Console rather than
    # capsys' stdout, so we just assert it didn't error and didn't boot
    # the REPL — covered by the lambda above.


def test_argv_update_subcommand_exits_nonzero_on_failure(monkeypatch):
    from chika._cli import app as appmod

    monkeypatch.setattr(
        upd, "update_chika",
        lambda **_: upd.UpdateResult(
            kind="git_clone", success=False, message="boom",
        ),
    )
    monkeypatch.setattr(appmod, "_run_rich", lambda: pytest.fail("nope"))

    with pytest.raises(SystemExit) as ei:
        appmod.cli(argv=["update"])
    assert ei.value.code == 1


def test_argv_doctor_subcommand_exits_zero_on_healthy(monkeypatch):
    from chika._cli import app as appmod
    from chika._cli import doctor as doc

    monkeypatch.setattr(
        doc, "run_doctor",
        lambda **_: doc.DoctorReport(checks=(
            doc.Check(name="python version", severity="ok", detail="3.14"),
        )),
    )
    monkeypatch.setattr(appmod, "_run_rich", lambda: pytest.fail("nope"))

    with pytest.raises(SystemExit) as ei:
        appmod.cli(argv=["doctor"])
    assert ei.value.code == 0


def test_argv_doctor_subcommand_exits_one_on_errors(monkeypatch):
    from chika._cli import app as appmod
    from chika._cli import doctor as doc

    monkeypatch.setattr(
        doc, "run_doctor",
        lambda **_: doc.DoctorReport(checks=(
            doc.Check(name="python version", severity="error", detail="3.10"),
        )),
    )
    monkeypatch.setattr(appmod, "_run_rich", lambda: pytest.fail("nope"))

    with pytest.raises(SystemExit) as ei:
        appmod.cli(argv=["doctor"])
    assert ei.value.code == 1


def test_argv_update_plain_mode_when_rich_missing(monkeypatch, capsys):
    from chika._cli import app as appmod

    monkeypatch.setattr(appmod, "_have_rich", lambda: False)
    monkeypatch.setattr(
        upd, "update_chika",
        lambda **_: upd.UpdateResult(
            kind="git_clone", success=True, message="updated", restart_required=True,
        ),
    )
    monkeypatch.setattr(appmod, "_run_rich", lambda: pytest.fail("nope"))
    appmod.cli(argv=["update"])
    out = capsys.readouterr().out
    assert "updated" in out
    assert "restart" in out.lower()


def test_argv_update_check_plain_mode(monkeypatch, capsys):
    from chika._cli import app as appmod

    monkeypatch.setattr(appmod, "_have_rich", lambda: False)
    monkeypatch.setattr(
        upd, "check_for_updates",
        lambda **_: upd.UpdateInfo(
            kind="git_clone", available=True,
            current="aaa", latest="bbb",
            ci_green=False, reason="ci_red",
        ),
    )
    appmod.cli(argv=["update", "--check"])
    out = capsys.readouterr().out
    assert "update available" in out
    assert "ci not green" in out


def test_argv_doctor_plain_mode(monkeypatch, capsys):
    from chika._cli import app as appmod
    from chika._cli import doctor as doc

    monkeypatch.setattr(appmod, "_have_rich", lambda: False)
    monkeypatch.setattr(
        doc, "run_doctor",
        lambda **_: doc.DoctorReport(checks=(
            doc.Check(name="python version", severity="ok", detail="3.14"),
            doc.Check(name="frontend build", severity="warn", detail="missing"),
        )),
    )
    with pytest.raises(SystemExit) as ei:
        appmod.cli(argv=["doctor"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "[ok]" in out
    assert "[warn]" in out
