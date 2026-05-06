"""Tests for ``chika doctor``.

Each individual check has its own test plus the orchestration is
covered (worst-severity calculation, exit code mapping, panel render).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from chika._cli import doctor as doc


# ── Individual checks ─────────────────────────────────────────────────


def test_check_python_version_ok():
    c = doc.check_python_version()
    assert c.severity == "ok"
    assert c.detail.startswith(f"{sys.version_info.major}.{sys.version_info.minor}")


def test_check_python_version_too_old(monkeypatch):
    """Simulate Python 3.10 by patching the module-level reference."""
    class _FakeVI(tuple):
        major = 3
        minor = 10
        micro = 0

    fake = _FakeVI((3, 10, 0, "final", 0))
    monkeypatch.setattr(doc.sys, "version_info", fake)
    c = doc.check_python_version()
    assert c.severity == "error"
    assert "need" in c.detail


def test_check_required_imports_all_present():
    """In this dev env all listed imports should be importable."""
    checks = doc.check_required_imports()
    assert len(checks) == len(doc.REQUIRED_IMPORTS)
    severities = {c.severity for c in checks}
    # Every required import should resolve
    assert severities == {"ok"}


def test_check_required_imports_reports_missing(monkeypatch):
    """A missing module gets reported as an error with the cause."""
    real_import = doc.importlib.import_module

    def selective_import(name):
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name)

    monkeypatch.setattr(doc.importlib, "import_module", selective_import)
    checks = doc.check_required_imports()
    failed = [c for c in checks if c.severity == "error"]
    assert len(failed) == 1
    assert "anthropic" in failed[0].name
    assert "ImportError" in failed[0].detail


def test_check_extension_directory_ok(tmp_path: Path):
    ext = tmp_path / "extension"
    ext.mkdir()
    (ext / "manifest.json").write_text("{}")
    c = doc.check_extension_directory(tmp_path)
    assert c.severity == "ok"
    assert "extension" in c.detail


def test_check_extension_directory_missing(tmp_path: Path):
    c = doc.check_extension_directory(tmp_path)
    assert c.severity == "error"
    assert "missing" in c.detail


def test_check_extension_directory_no_manifest(tmp_path: Path):
    (tmp_path / "extension").mkdir()
    c = doc.check_extension_directory(tmp_path)
    assert c.severity == "error"
    assert "manifest.json missing" in c.detail


def test_check_frontend_dist_ok(tmp_path: Path):
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>")
    c = doc.check_frontend_dist(tmp_path)
    assert c.severity == "ok"


def test_check_frontend_dist_missing_dir(tmp_path: Path):
    c = doc.check_frontend_dist(tmp_path)
    assert c.severity == "warn"
    assert "not built" in c.detail


def test_check_frontend_dist_missing_index(tmp_path: Path):
    """``dist/`` exists but no ``index.html`` (partial build)."""
    (tmp_path / "frontend" / "dist").mkdir(parents=True)
    c = doc.check_frontend_dist(tmp_path)
    assert c.severity == "warn"


def test_check_env_file_ok(tmp_path: Path):
    (tmp_path / ".env").write_text("CHIKA_PROVIDER=anthropic\n")
    c = doc.check_env_file(tmp_path)
    assert c.severity == "ok"


def test_check_env_file_missing(tmp_path: Path):
    c = doc.check_env_file(tmp_path)
    assert c.severity == "warn"
    assert "not found" in c.detail


def test_check_env_file_empty(tmp_path: Path):
    (tmp_path / ".env").touch()
    c = doc.check_env_file(tmp_path)
    assert c.severity == "warn"
    assert "empty" in c.detail


def test_check_data_writable_creates_directory(tmp_path: Path):
    c = doc.check_data_writable(tmp_path)
    assert c.severity == "ok"
    assert (tmp_path / "data").is_dir()
    # Probe file should be cleaned up after the check
    assert not (tmp_path / "data" / ".doctor_probe").exists()


def test_check_data_writable_existing_dir(tmp_path: Path):
    (tmp_path / "data").mkdir()
    c = doc.check_data_writable(tmp_path)
    assert c.severity == "ok"


def test_check_data_writable_mkdir_fails(tmp_path: Path, monkeypatch):
    """Permission denied on mkdir must be reported as an error."""
    def boom(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "mkdir", boom)
    c = doc.check_data_writable(tmp_path)
    assert c.severity == "error"
    assert "can't create" in c.detail


def test_check_data_writable_write_fails(tmp_path: Path, monkeypatch):
    """Probe file write failure → error."""
    (tmp_path / "data").mkdir()

    def boom(self, *a, **k):
        raise PermissionError("read only fs")

    monkeypatch.setattr(Path, "write_text", boom)
    c = doc.check_data_writable(tmp_path)
    assert c.severity == "error"
    assert "can't write" in c.detail


def test_check_console_script_present(monkeypatch):
    monkeypatch.setattr(doc.shutil, "which", lambda name: "/fake/bin/chika")
    c = doc.check_console_script()
    assert c.severity == "ok"
    assert "/fake/bin/chika" in c.detail


def test_check_console_script_missing(monkeypatch):
    monkeypatch.setattr(doc.shutil, "which", lambda name: None)
    c = doc.check_console_script()
    assert c.severity == "warn"
    assert "not on PATH" in c.detail


def test_check_console_script_finds_exe(monkeypatch):
    """On Windows the binary is ``chika.exe`` — ``which`` should be
    asked for both."""
    seen: list[str] = []

    def fake_which(name):
        seen.append(name)
        return "/path/chika.exe" if name == "chika.exe" else None

    monkeypatch.setattr(doc.shutil, "which", fake_which)
    c = doc.check_console_script()
    assert c.severity == "ok"
    assert seen == ["chika", "chika.exe"]


# ── ADR-37 auto-gen drift checks ────────────────────────────────────


def test_check_event_types_in_sync_returns_ok_or_warn():
    """Smoke: the check runs and produces ok|warn (never error)."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    c = doc.check_event_types_in_sync(repo_root)
    assert c.severity in ("ok", "warn")


def test_check_brand_parity_returns_ok_or_warn():
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    c = doc.check_brand_parity(repo_root)
    assert c.severity in ("ok", "warn")


def test_check_skill_summaries_in_sync_runs():
    """Smoke: the skill-summary drift check runs without crashing.
    It will return ``warn`` until the contributor regenerates summaries."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    c = doc.check_skill_summaries_in_sync(repo_root)
    assert c.severity in ("ok", "warn")
    # The detail must include a remediation hint
    assert ("regenerate_skill_summaries.py" in c.detail
            or "every SKILL.md" in c.detail)


def test_run_doctor_includes_drift_checks():
    """The full doctor report must include the three new auto-gen
    checks added in ADR-37."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    report = doc.run_doctor(console=None, root=repo_root)
    names = [c.name for c in report.checks]
    assert "event types in sync" in names
    assert "brand parity" in names
    assert "skill summaries in sync" in names


def test_doctor_drift_checks_are_warn_severity_only():
    """Drift checks must be ``warn``, never ``error`` — drift is a
    contributor concern, not a runtime break. A user on a stale
    checkout should still get exit code 0 from doctor."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    report = doc.run_doctor(console=None, root=repo_root)
    drift_check_names = {"event types in sync", "brand parity", "skill summaries in sync"}
    drift_severities = {
        c.severity for c in report.checks if c.name in drift_check_names
    }
    assert "error" not in drift_severities, (
        "drift checks must be warn-only; saw an error severity"
    )


def test_doctor_drift_check_falls_back_when_script_missing(tmp_path):
    """If a check script is missing on a fresh checkout, the check
    surfaces 'warn' with a clear ``script missing`` detail."""
    # Tmp_path has no scripts/ dir — every drift check should warn.
    c = doc.check_event_types_in_sync(tmp_path)
    assert c.severity == "warn"
    assert "missing" in c.detail.lower()


# ── DoctorReport orchestration ───────────────────────────────────────


def test_report_worst_ok():
    r = doc.DoctorReport(checks=(
        doc.Check(name="a", severity="ok"),
        doc.Check(name="b", severity="ok"),
    ))
    assert r.worst == "ok"
    assert r.exit_code == 0


def test_report_worst_warn():
    r = doc.DoctorReport(checks=(
        doc.Check(name="a", severity="ok"),
        doc.Check(name="b", severity="warn"),
        doc.Check(name="c", severity="ok"),
    ))
    assert r.worst == "warn"
    assert r.exit_code == 0  # warn doesn't fail


def test_report_worst_error_with_warns():
    r = doc.DoctorReport(checks=(
        doc.Check(name="a", severity="warn"),
        doc.Check(name="b", severity="error"),
        doc.Check(name="c", severity="ok"),
    ))
    assert r.worst == "error"
    assert r.exit_code == 1


def test_report_empty():
    r = doc.DoctorReport(checks=())
    assert r.worst == "ok"
    assert r.exit_code == 0


# ── run_doctor end-to-end ────────────────────────────────────────────


def test_run_doctor_returns_report(tmp_path: Path):
    """End-to-end: feed a fully-good install and verify the structure."""
    ext = tmp_path / "extension"
    ext.mkdir()
    (ext / "manifest.json").write_text("{}")
    (tmp_path / ".env").write_text("CHIKA_PROVIDER=test\n")
    (tmp_path / "data").mkdir()

    report = doc.run_doctor(console=None, root=tmp_path)
    # Should include all our checks
    names = [c.name for c in report.checks]
    assert "python version" in names
    assert any(n.startswith("import ") for n in names)
    assert "bundled extension" in names
    assert "frontend build" in names
    assert ".env" in names
    assert "data/ writable" in names
    assert "chika command" in names


def test_run_doctor_renders_panel(tmp_path: Path):
    ext = tmp_path / "extension"
    ext.mkdir()
    (ext / "manifest.json").write_text("{}")

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=140, color_system=None)
    doc.run_doctor(console=console, root=tmp_path)
    out = buf.getvalue()
    assert "chika doctor" in out
    assert "python version" in out


def test_run_doctor_marks_broken_install_as_error(tmp_path: Path):
    """Missing extension dir should make the worst severity 'error'."""
    report = doc.run_doctor(console=None, root=tmp_path)
    severities = [c.severity for c in report.checks]
    assert "error" in severities
    assert report.worst == "error"
    assert report.exit_code == 1


def test_run_doctor_default_root_uses_repo_root():
    """When ``root`` is omitted the repo's actual structure is checked.
    This is a smoke test — we don't assert on exit code because the
    user's local env may genuinely have warnings."""
    report = doc.run_doctor(console=None)
    assert len(report.checks) > 0
    # The repo's bundled extension should always be present
    ext_check = next(c for c in report.checks if c.name == "bundled extension")
    assert ext_check.severity == "ok"


# ── REQUIRED_IMPORTS curation ────────────────────────────────────────


def test_required_imports_match_pyproject():
    """Catch drift: every entry in REQUIRED_IMPORTS must correspond to
    a package listed in pyproject.toml's ``dependencies``."""
    import tomllib

    pyproject = doc.REPO_ROOT / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    deps = data["project"]["dependencies"]
    # Strip version specifiers + extras
    listed = set()
    for dep in deps:
        name = dep.split(">=")[0].split("==")[0].split("<")[0].split("[")[0].strip()
        listed.add(name.lower().replace("_", "-"))

    # Map from import name → canonical package name when they differ.
    rename = {
        "dotenv": "python-dotenv",
        "prompt_toolkit": "prompt_toolkit",
    }
    for imp in doc.REQUIRED_IMPORTS:
        canonical = rename.get(imp, imp).lower().replace("_", "-")
        assert canonical in listed, (
            f"REQUIRED_IMPORTS contains {imp!r} but pyproject.toml has no "
            f"dependency for {canonical!r}"
        )


def test_min_python_matches_pyproject():
    """Doctor's MIN_PYTHON must match pyproject.toml's requires-python."""
    import re
    import tomllib

    pyproject = doc.REPO_ROOT / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    requires = data["project"]["requires-python"]
    m = re.search(r">=\s*(\d+)\.(\d+)", requires)
    assert m, f"unparseable requires-python: {requires}"
    expected = (int(m.group(1)), int(m.group(2)))
    assert doc.MIN_PYTHON == expected


# ── Module helpers ───────────────────────────────────────────────────


def test_force_clear_module_cache_helper():
    """Smoke: clearing a module from ``sys.modules`` should not blow up
    even if it has submodules."""
    import json as _json  # noqa: F401 — load it
    assert "json" in sys.modules
    # Clone to avoid wrecking the real cache
    with patch.dict(sys.modules, {}):
        sys.modules["json"] = sys.modules["json"]
        sys.modules["json.decoder"] = sys.modules["json"]
        doc._force_clear_module_cache("json")
        assert "json" not in sys.modules
        assert "json.decoder" not in sys.modules


def test_is_windows_helper():
    assert doc._is_windows() is (sys.platform == "win32")
