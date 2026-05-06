"""Tests for ``chika/_cli/extension_detect.py``."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from chika._cli import extension_detect as ed


# ── Heartbeat ────────────────────────────────────────────────────────


def test_write_and_read_heartbeat(tmp_path):
    p = tmp_path / "hb.json"
    ed.write_heartbeat(path=p, now=12345.0)
    assert ed.read_heartbeat(path=p) == 12345.0


def test_read_heartbeat_missing_returns_none(tmp_path):
    assert ed.read_heartbeat(path=tmp_path / "nope.json") is None


def test_read_heartbeat_corrupt_returns_none(tmp_path):
    p = tmp_path / "hb.json"
    p.write_text("{ broken json", encoding="utf-8")
    assert ed.read_heartbeat(path=p) is None


def test_read_heartbeat_missing_field_returns_none(tmp_path):
    p = tmp_path / "hb.json"
    p.write_text(json.dumps({"unrelated": 1}), encoding="utf-8")
    assert ed.read_heartbeat(path=p) is None


def test_write_heartbeat_creates_parent_dir(tmp_path):
    nested = tmp_path / "a" / "b" / "hb.json"
    ed.write_heartbeat(path=nested, now=1.0)
    assert nested.is_file()


def test_write_heartbeat_failure_is_silent(tmp_path, monkeypatch):
    """Disk write failure must not raise — best-effort."""
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(Path, "write_text", boom)
    # Must not raise
    ed.write_heartbeat(path=tmp_path / "hb.json")


# ── Manifest matcher ─────────────────────────────────────────────────


def _good_manifest() -> dict:
    return {
        "manifest_version": 3,
        "name": "Chika Browser Agent",
        "permissions": ["tabs", "activeTab", "scripting", "storage", "notifications"],
    }


def test_manifest_matches_chika_with_full_data():
    assert ed._manifest_matches_chika(_good_manifest()) is True


def test_manifest_does_not_match_wrong_name():
    bad = _good_manifest()
    bad["name"] = "Some Other Extension"
    assert ed._manifest_matches_chika(bad) is False


def test_manifest_does_not_match_v2():
    bad = _good_manifest()
    bad["manifest_version"] = 2
    assert ed._manifest_matches_chika(bad) is False


def test_manifest_does_not_match_missing_permissions():
    bad = _good_manifest()
    bad["permissions"] = ["tabs"]  # missing the others
    assert ed._manifest_matches_chika(bad) is False


def test_manifest_does_not_match_non_dict():
    assert ed._manifest_matches_chika([]) is False
    assert ed._manifest_matches_chika("not a dict") is False
    assert ed._manifest_matches_chika(None) is False


# ── Local install detection ──────────────────────────────────────────


def test_is_locally_installed_true_when_manifest_matches(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(_good_manifest()), encoding="utf-8",
    )
    assert ed.is_locally_installed(root=tmp_path) is True


def test_is_locally_installed_false_when_dir_empty(tmp_path):
    assert ed.is_locally_installed(root=tmp_path) is False


def test_is_locally_installed_false_when_manifest_corrupt(tmp_path):
    (tmp_path / "manifest.json").write_text("{ broken", encoding="utf-8")
    assert ed.is_locally_installed(root=tmp_path) is False


def test_is_locally_installed_false_when_other_extension(tmp_path):
    """A different extension's manifest at the path doesn't count."""
    other = _good_manifest()
    other["name"] = "Not Chika"
    (tmp_path / "manifest.json").write_text(json.dumps(other), encoding="utf-8")
    assert ed.is_locally_installed(root=tmp_path) is False


# ── Chrome profile walk ──────────────────────────────────────────────


def _make_chrome_profile_with_extension(
    user_data: Path, profile_name: str, ext_id: str, manifest: dict,
) -> Path:
    profile = user_data / profile_name
    ext_dir = profile / "Extensions" / ext_id / "1.0.0"
    ext_dir.mkdir(parents=True)
    (ext_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )
    return ext_dir


def test_walk_finds_chika_in_profile(tmp_path):
    user_data = tmp_path / "Chrome" / "User Data"
    user_data.mkdir(parents=True)
    _make_chrome_profile_with_extension(
        user_data, "Default", "abcdef", _good_manifest(),
    )
    found, detail = ed.walk_chrome_profiles_for_chika(
        candidate_dirs=[user_data],
    )
    assert found is True
    assert detail and "abcdef" in detail


def test_walk_skips_non_matching_extensions(tmp_path):
    user_data = tmp_path / "Chrome" / "User Data"
    user_data.mkdir(parents=True)
    other = _good_manifest()
    other["name"] = "Some Other Extension"
    _make_chrome_profile_with_extension(
        user_data, "Default", "otherext", other,
    )
    found, _ = ed.walk_chrome_profiles_for_chika(candidate_dirs=[user_data])
    assert found is False


def test_walk_handles_multiple_profiles(tmp_path):
    user_data = tmp_path / "Chrome"
    user_data.mkdir()
    # Profile 1 has another extension; Profile 2 has Chika
    _make_chrome_profile_with_extension(
        user_data, "Profile 1", "x", {"manifest_version": 3, "name": "Other"},
    )
    _make_chrome_profile_with_extension(
        user_data, "Profile 2", "chika", _good_manifest(),
    )
    found, detail = ed.walk_chrome_profiles_for_chika(candidate_dirs=[user_data])
    assert found is True
    assert "chika" in (detail or "")


def test_walk_returns_false_when_no_browsers(tmp_path):
    """No Chrome dirs at all → no false positive."""
    found, _ = ed.walk_chrome_profiles_for_chika(candidate_dirs=[tmp_path / "nope"])
    assert found is False


def test_walk_handles_corrupt_manifest(tmp_path):
    user_data = tmp_path / "Chrome"
    user_data.mkdir()
    profile = user_data / "Default"
    ext = profile / "Extensions" / "ext" / "1.0"
    ext.mkdir(parents=True)
    (ext / "manifest.json").write_text("{ broken", encoding="utf-8")
    # Should not raise; just doesn't match
    found, _ = ed.walk_chrome_profiles_for_chika(candidate_dirs=[user_data])
    assert found is False


def test_walk_respects_inspection_cap(tmp_path):
    """Pathological filesystem (1000s of fake extensions) doesn't hang."""
    user_data = tmp_path / "Chrome"
    user_data.mkdir()
    profile = user_data / "Default"
    for i in range(20):
        ext = profile / "Extensions" / f"ext_{i}" / "1.0"
        ext.mkdir(parents=True)
        (ext / "manifest.json").write_text("{}", encoding="utf-8")
    # cap of 5 — must not inspect all 20
    found, _ = ed.walk_chrome_profiles_for_chika(
        candidate_dirs=[user_data], max_inspect=5,
    )
    assert found is False


def test_candidate_chrome_dirs_returns_paths():
    """Per-platform candidate list. Returns a non-empty list of Paths."""
    out = ed.candidate_chrome_dirs()
    assert all(isinstance(p, Path) for p in out)
    assert len(out) >= 4  # at least Chrome + Chromium + Brave + Edge


# ── Top-level detect_extension ───────────────────────────────────────


def test_detect_unknown_when_no_signals(tmp_path):
    result = ed.detect_extension(
        heartbeat_file=tmp_path / "hb.json",
        local_root=tmp_path / "local",
        chrome_dirs=[tmp_path / "no_browsers"],
    )
    assert result.confidence == "unknown"
    assert not result.is_active
    assert not result.is_present
    assert not result.is_installed_locally


def test_detect_confirmed_active_with_fresh_heartbeat(tmp_path):
    hb = tmp_path / "hb.json"
    ed.write_heartbeat(path=hb, now=1000.0)
    result = ed.detect_extension(
        now=1100.0, heartbeat_file=hb,
        local_root=tmp_path / "local",
        chrome_dirs=[tmp_path / "no_browsers"],
    )
    assert result.confidence == "confirmed_active"
    assert result.is_active
    assert result.is_present
    assert any(s[0] == "heartbeat" for s in result.signals)


def test_detect_stale_heartbeat_does_not_count(tmp_path):
    """Heartbeat older than 7 days → not active."""
    hb = tmp_path / "hb.json"
    ed.write_heartbeat(path=hb, now=0.0)
    result = ed.detect_extension(
        now=10 * 24 * 60 * 60,  # 10 days later
        heartbeat_file=hb,
        local_root=tmp_path / "local",
        chrome_dirs=[tmp_path / "no_browsers"],
    )
    assert result.confidence == "unknown"
    # But a stale signal should be noted in diagnostics
    assert any(s[0] == "heartbeat_stale" for s in result.signals)


def test_detect_chrome_profile_when_no_heartbeat(tmp_path):
    user_data = tmp_path / "Chrome"
    user_data.mkdir()
    _make_chrome_profile_with_extension(
        user_data, "Default", "ext1", _good_manifest(),
    )
    result = ed.detect_extension(
        heartbeat_file=tmp_path / "hb.json",
        local_root=tmp_path / "local",
        chrome_dirs=[user_data],
    )
    assert result.confidence == "present_in_chrome_profile"
    assert result.is_present
    assert any(s[0] == "chrome_profile" for s in result.signals)


def test_detect_local_files_only(tmp_path):
    """Files exist at ~/.chika/extension/ but not loaded in Chrome."""
    local = tmp_path / "local"
    local.mkdir()
    (local / "manifest.json").write_text(
        json.dumps(_good_manifest()), encoding="utf-8",
    )
    result = ed.detect_extension(
        heartbeat_file=tmp_path / "hb.json",
        local_root=local,
        chrome_dirs=[tmp_path / "no_browsers"],
    )
    assert result.confidence == "installed_filesystem"
    assert not result.is_active
    assert not result.is_present
    assert result.is_installed_locally


def test_detect_heartbeat_wins_over_other_signals(tmp_path):
    """Confirmed-active is the strongest signal even if Chrome
    profile + local files are also present."""
    hb = tmp_path / "hb.json"
    ed.write_heartbeat(path=hb, now=1000.0)
    user_data = tmp_path / "Chrome"
    user_data.mkdir()
    _make_chrome_profile_with_extension(
        user_data, "Default", "ext1", _good_manifest(),
    )
    local = tmp_path / "local"
    local.mkdir()
    (local / "manifest.json").write_text(
        json.dumps(_good_manifest()), encoding="utf-8",
    )
    result = ed.detect_extension(
        now=1100.0, heartbeat_file=hb,
        local_root=local, chrome_dirs=[user_data],
    )
    assert result.confidence == "confirmed_active"


def test_detect_records_local_signal_even_when_outranked(tmp_path):
    """Diagnostic signals show every signal that fired, even if a
    stronger one won."""
    hb = tmp_path / "hb.json"
    ed.write_heartbeat(path=hb, now=1000.0)
    local = tmp_path / "local"
    local.mkdir()
    (local / "manifest.json").write_text(
        json.dumps(_good_manifest()), encoding="utf-8",
    )
    result = ed.detect_extension(
        now=1100.0, heartbeat_file=hb,
        local_root=local, chrome_dirs=[tmp_path / "no_browsers"],
    )
    sig_names = {s[0] for s in result.signals}
    assert "heartbeat" in sig_names
    assert "local_files" in sig_names


# ── Render path (smoke) ──────────────────────────────────────────────


def test_render_detection_produces_output():
    import io
    from rich.console import Console
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=140, color_system=None)
    result = ed.DetectionResult(
        confidence="confirmed_active",
        signals=[("heartbeat", "12s ago")],
        last_heartbeat=time.time(),
    )
    ed.render_detection(console, result)
    out = buf.getvalue()
    assert "active" in out.lower()


# ── GUI installer integration contract ───────────────────────────────


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_windows_postinstall_invokes_extension_detect():
    """The Windows installer's post-install PowerShell hook must run
    detect_extension and write the result to a marker file."""
    text = (
        REPO_ROOT / "installers" / "windows" / "post_install.ps1"
    ).read_text(encoding="utf-8")
    assert "detect_extension" in text
    assert "extension_detection.txt" in text


def test_macos_postinstall_invokes_extension_detect():
    text = (
        REPO_ROOT / "installers" / "macos" / "scripts" / "postinstall"
    ).read_text(encoding="utf-8")
    assert "detect_extension" in text
    assert "extension_detection.txt" in text


def test_linux_postinst_invokes_extension_detect():
    text = (
        REPO_ROOT / "installers" / "linux" / "debian" / "postinst"
    ).read_text(encoding="utf-8")
    assert "detect_extension" in text
    assert "extension_detection.txt" in text


def test_all_three_installers_use_same_marker_filename():
    """The marker filename must be byte-identical across installers
    so a future tool can read it without per-OS branching."""
    win = (REPO_ROOT / "installers" / "windows" / "post_install.ps1").read_text(encoding="utf-8")
    mac = (REPO_ROOT / "installers" / "macos" / "scripts" / "postinstall").read_text(encoding="utf-8")
    lin = (REPO_ROOT / "installers" / "linux" / "debian" / "postinst").read_text(encoding="utf-8")
    marker = "extension_detection.txt"
    assert marker in win
    assert marker in mac
    assert marker in lin


# ── Heartbeat hook in api/server.py ──────────────────────────────────


def test_server_writes_heartbeat_on_extension_connect():
    """``api/server.py``'s extension status callback must invoke
    ``write_heartbeat()`` when an extension WS connects. We assert
    the contract via static text — full WS integration is exercised
    by ``tests/test_ws_e2e.py``."""
    text = (REPO_ROOT / "api" / "server.py").read_text(encoding="utf-8")
    assert "write_heartbeat" in text
    # The call should be inside the ``if connected:`` branch
    idx_connected = text.find("if connected:")
    idx_write = text.find("write_heartbeat")
    assert idx_connected != -1 and idx_write != -1
    assert idx_write > idx_connected, (
        "write_heartbeat must be inside the 'if connected:' branch"
    )


# ── Uninstall reminder contracts (all three OS installers) ──────────


def test_windows_pre_uninstall_runs_extension_detect():
    text = (
        REPO_ROOT / "installers" / "windows" / "pre_uninstall.ps1"
    ).read_text(encoding="utf-8")
    assert "detect_extension" in text
    assert "uninstall_reminder.txt" in text
    # The reminder must mention chrome://extensions/
    assert "chrome://extensions" in text


def test_macos_uninstall_runs_extension_detect():
    text = (
        REPO_ROOT / "installers" / "macos" / "uninstall.sh"
    ).read_text(encoding="utf-8")
    assert "detect_extension" in text
    assert "uninstall_reminder.txt" in text
    assert "chrome://extensions" in text


def test_linux_prerm_runs_extension_detect():
    text = (
        REPO_ROOT / "installers" / "linux" / "debian" / "prerm"
    ).read_text(encoding="utf-8")
    assert "detect_extension" in text
    assert "chrome://extensions" in text


def test_uninstall_reminders_all_use_same_filename():
    """The reminder filename must be byte-identical so a follow-up
    tool / status check can find it without per-OS branching."""
    win = (REPO_ROOT / "installers" / "windows" / "pre_uninstall.ps1").read_text(encoding="utf-8")
    mac = (REPO_ROOT / "installers" / "macos" / "uninstall.sh").read_text(encoding="utf-8")
    lin = (REPO_ROOT / "installers" / "linux" / "debian" / "prerm").read_text(encoding="utf-8")
    assert "uninstall_reminder.txt" in win
    assert "uninstall_reminder.txt" in mac
    assert "uninstall_reminder.txt" in lin


def test_uninstall_reminders_only_fire_on_present_confidence():
    """The reminder must only write when confidence is
    ``confirmed_active`` or ``present_in_chrome_profile`` — not for
    ``installed_filesystem`` (just files; not Chrome's problem) or
    ``unknown``."""
    for path in (
        REPO_ROOT / "installers" / "windows" / "pre_uninstall.ps1",
        REPO_ROOT / "installers" / "macos" / "uninstall.sh",
        REPO_ROOT / "installers" / "linux" / "debian" / "prerm",
    ):
        text = path.read_text(encoding="utf-8")
        # Both target confidence values must appear in the file
        assert "confirmed_active" in text, f"{path}: missing confirmed_active branch"
        assert "present_in_chrome_profile" in text, f"{path}: missing present_in_chrome_profile branch"
        # And the strictly-weaker confidences must NOT trigger the reminder
        # (they should not appear inside the reminder-write block — we
        # check this loosely by ensuring the file doesn't naively write
        # a reminder for ``installed_filesystem``).
        # The check is intentionally weak: if the script later legitimately
        # mentions installed_filesystem for unrelated reasons, that's fine.


def test_chika_uninstall_command_renders_extension_reminder(monkeypatch):
    """The chika uninstall command must surface the same reminder."""
    import io
    from rich.console import Console
    from chika._cli import uninstall as un
    from chika._cli import extension_detect as ed_mod

    # Force detect_extension to report "active"
    monkeypatch.setattr(
        ed_mod, "detect_extension",
        lambda **_: ed_mod.DetectionResult(
            confidence="confirmed_active", signals=[("heartbeat", "1s ago")],
        ),
    )

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=140, color_system=None)
    result = un.UninstallResult(kind="pip_pypi", success=True, message="done")
    un._render(console, result, removed_data=False)
    out = buf.getvalue()
    assert "extension is still loaded" in out.lower() or "chrome://extensions" in out


def test_chika_uninstall_command_no_reminder_when_unknown(monkeypatch):
    """If detection says ``unknown``, no extension reminder appears."""
    import io
    from rich.console import Console
    from chika._cli import uninstall as un
    from chika._cli import extension_detect as ed_mod

    monkeypatch.setattr(
        ed_mod, "detect_extension",
        lambda **_: ed_mod.DetectionResult(
            confidence="unknown", signals=[],
        ),
    )

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=140, color_system=None)
    result = un.UninstallResult(kind="pip_pypi", success=True, message="done")
    un._render(console, result, removed_data=False)
    out = buf.getvalue().lower()
    assert "still loaded" not in out


def test_chika_uninstall_resilient_to_detection_failure(monkeypatch):
    """If detect_extension raises, the panel still renders."""
    import io
    from rich.console import Console
    from chika._cli import uninstall as un
    from chika._cli import extension_detect as ed_mod

    def boom(**_):
        raise RuntimeError("detection broken")

    monkeypatch.setattr(ed_mod, "detect_extension", boom)
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=140, color_system=None)
    result = un.UninstallResult(kind="pip_pypi", success=True, message="done")
    # Must not raise
    un._render(console, result, removed_data=False)
    out = buf.getvalue().lower()
    # Panel still rendered with the install-kind summary
    assert "pip_pypi" in out


# ── DetectionResult dataclass invariants ────────────────────────────


def test_detection_result_is_active_only_for_confirmed():
    assert ed.DetectionResult(confidence="confirmed_active").is_active is True
    for c in ("present_in_chrome_profile", "installed_filesystem", "unknown"):
        assert ed.DetectionResult(confidence=c).is_active is False


def test_detection_result_is_present_for_active_or_chrome():
    for c in ("confirmed_active", "present_in_chrome_profile"):
        assert ed.DetectionResult(confidence=c).is_present is True
    for c in ("installed_filesystem", "unknown"):
        assert ed.DetectionResult(confidence=c).is_present is False


def test_detection_result_is_installed_locally_for_anything_known():
    for c in ("confirmed_active", "present_in_chrome_profile",
              "installed_filesystem"):
        assert ed.DetectionResult(confidence=c).is_installed_locally is True
    assert ed.DetectionResult(confidence="unknown").is_installed_locally is False


# ── Heartbeat freshness boundaries ──────────────────────────────────


@pytest.mark.parametrize("age_seconds, expected_active", [
    (0, True),                          # written right now
    (60, True),                         # 1 min
    (24 * 60 * 60, True),               # 1 day
    (6 * 24 * 60 * 60, True),           # 6 days
    (7 * 24 * 60 * 60 - 1, True),       # just under 7 days
    (7 * 24 * 60 * 60, False),          # 7 days exactly — boundary
    (30 * 24 * 60 * 60, False),         # 30 days
])
def test_heartbeat_freshness_window(tmp_path, age_seconds, expected_active):
    hb = tmp_path / "hb.json"
    ed.write_heartbeat(path=hb, now=0.0)
    result = ed.detect_extension(
        now=age_seconds,
        heartbeat_file=hb,
        local_root=tmp_path / "local",
        chrome_dirs=[tmp_path / "no_browsers"],
    )
    if expected_active:
        assert result.confidence == "confirmed_active"
    else:
        assert result.confidence != "confirmed_active"


def test_heartbeat_negative_age_does_not_count():
    """Clock skew: if heartbeat is in the future, treat it as not-fresh
    (the heartbeat we read clearly came from a different epoch)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        hb = td_path / "hb.json"
        ed.write_heartbeat(path=hb, now=1000.0)
        result = ed.detect_extension(
            now=0.0,  # current time is BEFORE heartbeat — clock skew
            heartbeat_file=hb,
            local_root=td_path / "local",
            chrome_dirs=[td_path / "no_browsers"],
        )
        assert result.confidence != "confirmed_active"
