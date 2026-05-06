"""Static structural tests for the all-OS installer artefacts.

These don't actually compile the installers (we don't have ISCC,
pkgbuild, or dpkg-deb available in the test environment), but we
verify everything we *can* verify about the installer files:

  - Inno Setup script has all required sections + the right AppId
  - Build script reads version from pyproject.toml (one source of truth)
  - Asset name patterns in update.py match what the build scripts produce
  - Brand mark geometry in docs/index.html matches the canonical Vue path
  - install_marker.json contracts: every native installer writes the
    same key set the update detector reads
  - Bash scripts pass syntax check via ``bash -n`` when bash is available
  - PowerShell scripts have no obvious syntax errors (heuristic parse)

A failure here means a future installer build would silently produce
something wrong — exactly the kind of regression that's painful to
catch otherwise.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLERS = REPO_ROOT / "installers"
DOCS = REPO_ROOT / "docs"


# ── Tree shape ────────────────────────────────────────────────────────


def test_installer_dirs_exist():
    for sub in ("windows", "macos", "linux"):
        assert (INSTALLERS / sub).is_dir(), f"missing installers/{sub}"


def test_windows_required_files_exist():
    win = INSTALLERS / "windows"
    for f in ("chika.iss", "build_installer.ps1", "post_install.ps1",
              "pre_uninstall.ps1", "chika.cmd"):
        assert (win / f).is_file(), f"missing installers/windows/{f}"


def test_macos_required_files_exist():
    mac = INSTALLERS / "macos"
    for f in ("build_pkg.sh", "chika", "uninstall.sh"):
        assert (mac / f).is_file(), f"missing installers/macos/{f}"
    for f in ("preinstall", "postinstall"):
        assert (mac / "scripts" / f).is_file(), f"missing scripts/{f}"


def test_linux_required_files_exist():
    lin = INSTALLERS / "linux"
    for f in ("chika", "build_deb.sh", "install.sh"):
        assert (lin / f).is_file(), f"missing installers/linux/{f}"
    for f in ("control", "postinst", "prerm"):
        assert (lin / "debian" / f).is_file(), f"missing debian/{f}"


def test_docs_landing_files_exist():
    for f in ("index.html", "style.css", "script.js", "favicon.svg"):
        assert (DOCS / f).is_file(), f"missing docs/{f}"


# ── Inno Setup script: required keys ──────────────────────────────────


@pytest.fixture(scope="module")
def iss() -> str:
    return (INSTALLERS / "windows" / "chika.iss").read_text(encoding="utf-8")


def test_iss_has_setup_section(iss):
    assert "[Setup]" in iss


def test_iss_has_files_icons_run_uninstallrun_sections(iss):
    for s in ("[Setup]", "[Files]", "[Icons]", "[Run]", "[UninstallRun]",
              "[UninstallDelete]", "[Tasks]", "[Languages]"):
        assert s in iss, f"missing {s} section in chika.iss"


def test_iss_app_id_is_a_guid(iss):
    """AppId must NEVER change (would orphan ARP entries on upgrade)."""
    m = re.search(r"AppId=\{\{([0-9A-F\-]+)", iss, re.IGNORECASE)
    assert m, "no AppId line in [Setup]"
    guid = m.group(1)
    # Must be 8-4-4-4-12 hex
    assert re.fullmatch(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}", guid, re.IGNORECASE), \
        f"AppId is not a valid GUID: {guid}"


def test_iss_uses_lowest_privileges(iss):
    """Per-user install. Admin-required would block uninstall in user-mode."""
    assert "PrivilegesRequired=lowest" in iss


def test_iss_post_install_script_referenced(iss):
    assert "post_install.ps1" in iss


def test_iss_pre_uninstall_script_referenced(iss):
    assert "pre_uninstall.ps1" in iss


def test_iss_output_basefilename_uses_version(iss):
    """The filename pattern must produce ``chika-setup-<version>.exe``
    so the auto-update asset lookup finds it."""
    assert "OutputBaseFilename=chika-setup-{#MyAppVersion}" in iss


def test_iss_has_path_addition_task(iss):
    """The 'Add to PATH' task is what makes ``chika`` work in any terminal."""
    assert "addtopath" in iss
    assert "[Registry]" in iss
    assert "Tasks: addtopath" in iss


def test_iss_close_applications_force(iss):
    """When upgrading, force-close any running chika so file replace works."""
    assert "CloseApplications=force" in iss


# ── Build script: version sync ────────────────────────────────────────


def test_build_installer_reads_version_from_pyproject():
    """``build_installer.ps1`` must source the version from pyproject.toml."""
    text = (INSTALLERS / "windows" / "build_installer.ps1").read_text(encoding="utf-8")
    assert "pyproject.toml" in text
    assert re.search(r"version\s*=", text)


def test_build_pkg_reads_version_from_pyproject():
    text = (INSTALLERS / "macos" / "build_pkg.sh").read_text(encoding="utf-8")
    assert "pyproject.toml" in text


def test_build_deb_reads_version_from_pyproject():
    text = (INSTALLERS / "linux" / "build_deb.sh").read_text(encoding="utf-8")
    assert "pyproject.toml" in text


# ── Asset naming consistency ──────────────────────────────────────────


def test_update_asset_names_match_iss_output():
    """``_expected_asset_name("windows_installer", v)`` must match the
    file Inno produces (``chika-setup-{v}.exe``). If they ever
    diverge, ``chika update`` won't find the asset on releases/latest."""
    from chika._cli.update import _expected_asset_name
    assert _expected_asset_name("windows_installer", "2.0.5") == "chika-setup-2.0.5.exe"


def test_update_asset_names_match_pkg_build():
    from chika._cli.update import _expected_asset_name
    pkg_text = (INSTALLERS / "macos" / "build_pkg.sh").read_text(encoding="utf-8")
    assert "Chika-${VERSION}.pkg" in pkg_text
    assert _expected_asset_name("macos_installer", "2.0.5") == "Chika-2.0.5.pkg"


def test_update_asset_names_match_deb_build():
    from chika._cli.update import _expected_asset_name
    deb_text = (INSTALLERS / "linux" / "build_deb.sh").read_text(encoding="utf-8")
    # The .deb pattern is chika_<v>_all
    assert "chika_${VERSION}_all" in deb_text
    assert _expected_asset_name("linux_deb", "2.0.5") == "chika_2.0.5_all.deb"


def test_linux_universal_has_no_asset():
    """linux_universal updates by re-running install.sh, not by
    downloading a single asset. Make sure the convention holds."""
    from chika._cli.update import _expected_asset_name
    assert _expected_asset_name("linux_universal", "2.0.5") is None


# ── install_marker.json contracts ─────────────────────────────────────


def test_windows_marker_kind_present_in_build_script():
    """PowerShell hashtable keys aren't quoted in source — search for
    the bareword key and the kind value instead."""
    text = (INSTALLERS / "windows" / "build_installer.ps1").read_text(encoding="utf-8")
    assert "kind" in text and "windows_installer" in text


def test_macos_marker_kind_present_in_postinstall():
    text = (INSTALLERS / "macos" / "scripts" / "postinstall").read_text(encoding="utf-8")
    assert '"kind"' in text and "macos_installer" in text


def test_macos_marker_kind_present_in_build_pkg():
    """build_pkg.sh also writes a marker before pkgbuild stages it."""
    text = (INSTALLERS / "macos" / "build_pkg.sh").read_text(encoding="utf-8")
    assert "macos_installer" in text


def test_linux_deb_marker_kind_present_in_postinst():
    text = (INSTALLERS / "linux" / "debian" / "postinst").read_text(encoding="utf-8")
    assert '"kind"' in text and "linux_deb" in text


def test_linux_install_sh_marker_kind():
    text = (INSTALLERS / "linux" / "install.sh").read_text(encoding="utf-8")
    assert "linux_universal" in text


def test_update_module_recognises_all_marker_kinds():
    from chika._cli.update import _VALID_INSTALL_KINDS
    expected = {"windows_installer", "macos_installer",
                "linux_deb", "linux_universal"}
    assert expected.issubset(_VALID_INSTALL_KINDS)


# ── Launcher shim env vars ────────────────────────────────────────────


def test_windows_chika_cmd_exports_data_dir():
    text = (INSTALLERS / "windows" / "chika.cmd").read_text(encoding="utf-8")
    assert "CHIKA_DATA_DIR" in text
    assert "CHIKA_SETTINGS_PATH" in text


def test_macos_launcher_exports_data_dir():
    text = (INSTALLERS / "macos" / "chika").read_text(encoding="utf-8")
    assert "CHIKA_DATA_DIR" in text
    assert "CHIKA_SETTINGS_PATH" in text


def test_linux_launcher_exports_data_dir():
    text = (INSTALLERS / "linux" / "chika").read_text(encoding="utf-8")
    assert "CHIKA_DATA_DIR" in text
    assert "CHIKA_SETTINGS_PATH" in text


def test_settings_store_reads_data_dir_env(tmp_path, monkeypatch):
    """CHIKA_DATA_DIR resolves into the settings path when
    CHIKA_SETTINGS_PATH isn't set. This is the contract launchers rely on."""
    # Force a fresh module load so the path lookups re-evaluate.
    monkeypatch.delenv("CHIKA_SETTINGS_PATH", raising=False)
    monkeypatch.setenv("CHIKA_DATA_DIR", str(tmp_path / "data"))

    import importlib

    import api.settings_store as ss
    importlib.reload(ss)
    assert ss._SETTINGS_PATH == tmp_path / "data" / "settings.json"


def test_settings_store_settings_path_wins_over_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIKA_SETTINGS_PATH", str(tmp_path / "explicit.json"))
    monkeypatch.setenv("CHIKA_DATA_DIR", str(tmp_path / "data_dir"))

    import importlib

    import api.settings_store as ss
    importlib.reload(ss)
    assert ss._SETTINGS_PATH == tmp_path / "explicit.json"


# ── Brand-mark geometry parity (docs vs canonical) ───────────────────


_PETAL_PATH = "M 0,-58 C 13,-44 19,-22 0,-6 C -19,-22 -13,-44 0,-58 Z"


def test_landing_page_brand_mark_matches_canonical():
    """The landing page's SVG path must match the canonical Vue path.

    Geometry is duplicated by hand across surfaces (ADR-27); this
    test catches drift before it ships."""
    text = (DOCS / "index.html").read_text(encoding="utf-8")
    occurrences = text.count(_PETAL_PATH)
    # Header mark + footer mark = at least 2 instances. They should
    # both use the same path.
    assert occurrences >= 2, (
        f"docs/index.html should reference the canonical petal path "
        f"({_PETAL_PATH!r}) at least twice; found {occurrences}"
    )


def test_landing_page_uses_canonical_accent():
    """Accent token must match the Theme accent (#6c63ff)."""
    css = (DOCS / "style.css").read_text(encoding="utf-8")
    assert "#6c63ff" in css


def test_favicon_uses_canonical_petal_path():
    text = (DOCS / "favicon.svg").read_text(encoding="utf-8")
    assert _PETAL_PATH in text


def test_landing_page_mentions_settings_change_anytime():
    """User-facing reassurance — the page must tell the user settings
    are changeable. We don't pin exact words, just core phrases."""
    text = (DOCS / "index.html").read_text(encoding="utf-8")
    assert "any time" in text.lower() or "anytime" in text.lower()


def test_landing_page_has_install_section():
    text = (DOCS / "index.html").read_text(encoding="utf-8")
    assert 'id="install"' in text
    # Must mention all four install paths
    for label in ("windows", "macos", ".deb", "install.sh"):
        assert label in text.lower()


def test_landing_page_has_uninstall_section():
    text = (DOCS / "index.html").read_text(encoding="utf-8")
    lower = text.lower()
    assert 'id="uninstall"' in text
    # Must mention OS app manager option (Add/Remove Programs on
    # Windows, sudo /Library on macOS, apt remove on Linux). Match
    # case-insensitively since heading case may evolve.
    assert "settings" in lower and "apps" in lower
    assert "apt remove" in lower


# ── Bash syntax checks (when bash is available) ──────────────────────


@pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt",
    reason=(
        "bash not on PATH (or running on Windows where MSYS bash mangles "
        "Windows paths). These tests run in CI on Linux."
    ),
)
@pytest.mark.parametrize("script", [
    "installers/macos/build_pkg.sh",
    "installers/macos/scripts/preinstall",
    "installers/macos/scripts/postinstall",
    "installers/macos/chika",
    "installers/macos/uninstall.sh",
    "installers/linux/build_deb.sh",
    "installers/linux/install.sh",
    "installers/linux/chika",
    "installers/linux/debian/postinst",
    "installers/linux/debian/prerm",
])
def test_shell_script_passes_bash_syntax_check(script):
    path = REPO_ROOT / script
    proc = subprocess.run(
        ["bash", "-n", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, (
        f"bash -n {script} failed:\n{proc.stderr}"
    )


# ── PowerShell heuristic checks ──────────────────────────────────────


@pytest.mark.parametrize("script", [
    "installers/windows/build_installer.ps1",
    "installers/windows/post_install.ps1",
    "installers/windows/pre_uninstall.ps1",
])
def test_powershell_script_balanced_braces(script):
    """Cheap smoke check: counts of opening/closing braces match.

    Not a full parser — but a missing closing brace is the most
    common typo and shows up in this count immediately."""
    text = (REPO_ROOT / script).read_text(encoding="utf-8")
    open_count = text.count("{")
    close_count = text.count("}")
    assert open_count == close_count, (
        f"{script} has unbalanced braces: {open_count} '{{' vs {close_count} '}}'"
    )


@pytest.mark.parametrize("script", [
    "installers/windows/build_installer.ps1",
    "installers/windows/post_install.ps1",
    "installers/windows/pre_uninstall.ps1",
])
def test_powershell_uses_strict_error_handling(script):
    """Each script should set ``$ErrorActionPreference``."""
    text = (REPO_ROOT / script).read_text(encoding="utf-8")
    assert "$ErrorActionPreference" in text


# ── Debian control file ──────────────────────────────────────────────


def test_debian_control_has_required_fields():
    text = (INSTALLERS / "linux" / "debian" / "control").read_text(encoding="utf-8")
    for field in ("Package:", "Version:", "Architecture:", "Depends:",
                  "Maintainer:", "Description:"):
        assert field in text, f"missing field: {field}"


def test_debian_control_depends_on_python():
    text = (INSTALLERS / "linux" / "debian" / "control").read_text(encoding="utf-8")
    assert "python3" in text
    # The control file should require >= 3.11 since Chika does
    assert "3.11" in text


def test_debian_control_version_placeholder():
    """build_deb.sh substitutes VERSION_PLACEHOLDER → real version."""
    text = (INSTALLERS / "linux" / "debian" / "control").read_text(encoding="utf-8")
    assert "VERSION_PLACEHOLDER" in text
    build_text = (INSTALLERS / "linux" / "build_deb.sh").read_text(encoding="utf-8")
    assert "VERSION_PLACEHOLDER" in build_text


# ── Workflow integration ──────────────────────────────────────────────


def test_release_workflow_builds_all_installers():
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for job in ("build-windows-installer", "build-macos-installer", "build-linux-deb"):
        assert job in text, f"release.yml missing {job} job"


def test_release_workflow_attaches_all_assets():
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "chika-setup-${VERSION}.exe" in text
    assert "Chika-${VERSION}.pkg" in text
    assert "chika_${VERSION}_all.deb" in text


def test_pages_workflow_exists():
    assert (REPO_ROOT / ".github" / "workflows" / "pages.yml").is_file()


def test_pages_workflow_deploys_docs_dir():
    text = (REPO_ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "path: docs" in text


# ── HTML well-formedness (best effort) ───────────────────────────────


def test_landing_page_has_meta_viewport():
    text = (DOCS / "index.html").read_text(encoding="utf-8")
    assert 'name="viewport"' in text


def test_landing_page_links_are_absolute_or_relative_safe():
    """No accidental http://... links in the landing page."""
    text = (DOCS / "index.html").read_text(encoding="utf-8")
    bad = re.findall(r'href="http://[^"]*"', text)
    # http:// allowed only if explicitly local
    bad = [b for b in bad if "localhost" not in b]
    assert not bad, f"plain http:// links found in index.html: {bad}"


def test_landing_script_uses_https_only():
    text = (DOCS / "script.js").read_text(encoding="utf-8")
    bad = re.findall(r'http://[^\s\'"]+', text)
    bad = [b for b in bad if "localhost" not in b]
    assert not bad, f"plain http:// found in script.js: {bad}"


def test_landing_page_content_security_relevant_metas():
    """The page should include description + theme-color for
    a polished social preview."""
    text = (DOCS / "index.html").read_text(encoding="utf-8")
    assert 'name="description"' in text
    assert 'name="theme-color"' in text
