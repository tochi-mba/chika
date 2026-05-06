"""Tests for the ``chika install-extension`` flow.

We cover four layers:

  1. ``install_extension(...)`` itself — copy semantics, exclusions,
     idempotency, browser open, error handling.
  2. The ``/install-extension`` slash command — dispatches into the
     module, surfaces errors via the console.
  3. The ``chika install-extension`` argv subcommand — bypasses the
     REPL.
  4. A smoke test against the real ``extension/`` directory in this
     repo so we catch regressions if a new runtime file lands.

Browser-open is mocked everywhere — we never want a CI run to launch
``chrome://extensions/`` on a developer's box.
"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from chika._cli import install_extension as inst


REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_EXTENSION = REPO_ROOT / "extension"


# ── Source fixture ──────────────────────────────────────────────────────


@pytest.fixture
def fake_source(tmp_path: Path) -> Path:
    """Build a minimal but realistic ``extension/`` source tree.

    Includes one file/dir from each runtime category plus dev-only
    artefacts that should be excluded so we can assert the filter.
    """
    src = tmp_path / "extension_src"
    src.mkdir()

    # Runtime top-level files
    (src / "manifest.json").write_text('{"name": "Chika", "version": "1.0.0"}')
    (src / "background.js").write_text("// service worker entry")

    # Runtime dirs — one file each
    (src / "popup").mkdir()
    (src / "popup" / "popup.html").write_text("<html></html>")
    (src / "popup" / "popup.js").write_text("// popup")
    (src / "popup" / "popup.css").write_text("body {}")

    (src / "content").mkdir()
    (src / "content" / "bridge.js").write_text("// bridge")

    (src / "lib").mkdir()
    (src / "lib" / "actions.js").write_text("// actions")
    (src / "lib" / "tool-summaries.js").write_text("// tool summaries")

    (src / "options").mkdir()
    (src / "options" / "options.html").write_text("<html></html>")

    (src / "icons").mkdir()
    (src / "icons" / "icon16.png").write_bytes(b"\x89PNG\r\n\x1a\n_fake16_")
    (src / "icons" / "icon128.png").write_bytes(b"\x89PNG\r\n\x1a\n_fake128_")
    # Dev-only icon helpers — must be excluded
    (src / "icons" / "_render.html").write_text("<html>render</html>")
    (src / "icons" / "_render.mjs").write_text("// playwright rasteriser")
    (src / "icons" / "generate_icons.js").write_text("// legacy generator")

    # Top-level dev junk — must be excluded
    (src / "node_modules").mkdir()
    (src / "node_modules" / "playwright").mkdir()
    (src / "node_modules" / "playwright" / "package.json").write_text("{}")
    (src / "e2e").mkdir()
    (src / "e2e" / "popup.spec.js").write_text("// spec")
    (src / "test-results").mkdir()
    (src / "test-results" / "trace.zip").write_bytes(b"trace")
    (src / "package.json").write_text('{"name": "chika-extension"}')
    (src / "package-lock.json").write_text("{}")
    (src / "playwright.config.js").write_text("// config")

    return src


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    """Per-test destination so ``~/.chika/extension`` is never touched."""
    return tmp_path / "out" / "chika" / "extension"


# ── Default destination ─────────────────────────────────────────────────


def test_default_destination_is_home_chika_extension():
    assert inst.EXTENSION_DEST == Path.home() / ".chika" / "extension"


def test_chrome_extensions_url_constant():
    assert inst.CHROME_EXTENSIONS_URL == "chrome://extensions/"


def test_default_source_resolves_to_repo_extension_dir():
    src = inst.default_source()
    assert src.name == "extension"
    # Whether it exists depends on install layout; in this repo it must.
    assert src.is_dir()
    assert (src / "manifest.json").exists()


# ── Copy semantics ──────────────────────────────────────────────────────


def test_install_creates_destination_directory(fake_source: Path, dest: Path):
    assert not dest.exists()
    with patch.object(inst.webbrowser, "open", return_value=True) as wb:
        result = inst.install_extension(source=fake_source, dest=dest)
    assert result == dest.resolve()
    assert dest.is_dir()
    wb.assert_called_once_with(inst.CHROME_EXTENSIONS_URL)


def test_install_copies_manifest_and_background(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    assert (dest / "manifest.json").read_text() == '{"name": "Chika", "version": "1.0.0"}'
    assert (dest / "background.js").read_text() == "// service worker entry"


def test_install_copies_popup_subdirectory(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    assert (dest / "popup" / "popup.html").exists()
    assert (dest / "popup" / "popup.js").exists()
    assert (dest / "popup" / "popup.css").exists()


def test_install_copies_lib_subdirectory(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    assert (dest / "lib" / "actions.js").exists()
    assert (dest / "lib" / "tool-summaries.js").exists()


def test_install_copies_content_scripts(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    assert (dest / "content" / "bridge.js").exists()


def test_install_copies_options_page(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    assert (dest / "options" / "options.html").exists()


def test_install_copies_icon_pngs(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    assert (dest / "icons" / "icon16.png").read_bytes().startswith(b"\x89PNG")
    assert (dest / "icons" / "icon128.png").read_bytes().startswith(b"\x89PNG")


# ── Exclusions ──────────────────────────────────────────────────────────


def test_install_excludes_node_modules(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    assert not (dest / "node_modules").exists()


def test_install_excludes_e2e(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    assert not (dest / "e2e").exists()


def test_install_excludes_test_results(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    assert not (dest / "test-results").exists()


def test_install_excludes_top_level_dev_files(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    assert not (dest / "package.json").exists()
    assert not (dest / "package-lock.json").exists()
    assert not (dest / "playwright.config.js").exists()


def test_install_excludes_icon_dev_helpers(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    icons = dest / "icons"
    assert not (icons / "_render.html").exists()
    assert not (icons / "_render.mjs").exists()
    assert not (icons / "generate_icons.js").exists()


def test_install_top_level_dest_listing_matches_runtime_set(fake_source: Path, dest: Path):
    """The destination's top-level entries should be exactly the runtime set."""
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    actual = {p.name for p in dest.iterdir()}
    expected = set(inst._RUNTIME_TOP_LEVEL_FILES) | set(inst._RUNTIME_DIRS)
    assert actual == expected


# ── Idempotency ─────────────────────────────────────────────────────────


def test_install_is_idempotent(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
        # Second run shouldn't raise; should produce the same tree.
        inst.install_extension(source=fake_source, dest=dest)
    assert (dest / "manifest.json").exists()


def test_install_removes_stale_files_on_rerun(fake_source: Path, dest: Path):
    """If a release renames a file, the old one must NOT linger."""
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)

    stale = dest / "popup" / "old_removed.js"
    stale.write_text("// stale")
    assert stale.exists()

    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)

    assert not stale.exists()
    assert (dest / "popup" / "popup.js").exists()


def test_install_overwrites_changed_file_contents(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)

    # Mutate source as if a release shipped
    (fake_source / "manifest.json").write_text('{"name": "Chika", "version": "1.0.1"}')

    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest)
    assert (dest / "manifest.json").read_text().endswith('"1.0.1"}')


# ── Browser open ────────────────────────────────────────────────────────


def test_open_browser_default_calls_webbrowser_open(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open", return_value=True) as wb:
        inst.install_extension(source=fake_source, dest=dest)
    wb.assert_called_once_with("chrome://extensions/")


def test_open_browser_false_skips_webbrowser_open(fake_source: Path, dest: Path):
    with patch.object(inst.webbrowser, "open") as wb:
        inst.install_extension(
            source=fake_source, dest=dest, open_browser=False,
        )
    wb.assert_not_called()


def test_install_swallows_webbrowser_open_exceptions(
    fake_source: Path, dest: Path,
):
    """A browser-open failure must not abort the install."""
    with patch.object(inst.webbrowser, "open", side_effect=RuntimeError("no DISPLAY")):
        # No exception escapes — install still completes
        result = inst.install_extension(source=fake_source, dest=dest)
    assert result == dest.resolve()
    assert (dest / "manifest.json").exists()


# ── Panel rendering ─────────────────────────────────────────────────────


def _render_to_str(fake_source: Path, dest: Path, *, opened: bool) -> str:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=100, color_system=None)
    with patch.object(inst.webbrowser, "open", return_value=opened):
        inst.install_extension(source=fake_source, dest=dest, console=console)
    return buf.getvalue()


def test_panel_includes_destination_path(fake_source: Path, dest: Path):
    out = _render_to_str(fake_source, dest, opened=True)
    # Path may wrap; check the basename is present
    assert "extension" in out
    assert "chrome://extensions/" in out


def test_panel_lists_three_steps(fake_source: Path, dest: Path):
    out = _render_to_str(fake_source, dest, opened=True)
    assert "1." in out
    assert "2." in out
    assert "3." in out
    assert "Developer mode" in out
    assert "Load unpacked" in out


def test_panel_says_opened_when_browser_succeeded(fake_source: Path, dest: Path):
    out = _render_to_str(fake_source, dest, opened=True)
    assert "opened" in out.lower()


def test_panel_tells_user_to_open_when_browser_failed(fake_source: Path, dest: Path):
    out = _render_to_str(fake_source, dest, opened=False)
    # "open chrome://..." (imperative) rather than "opened"
    assert "open" in out.lower()
    # Should NOT claim it opened
    assert "opened chrome://extensions/" not in out


def test_no_panel_rendered_when_console_is_none(fake_source: Path, dest: Path):
    """``console=None`` should silently skip rendering — used in tests."""
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(source=fake_source, dest=dest, console=None)
    # Ensure nothing crashed and the install still happened
    assert (dest / "manifest.json").exists()


# ── Error handling ──────────────────────────────────────────────────────


def test_missing_source_raises_file_not_found(tmp_path: Path):
    bogus = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError) as exc:
        inst.install_extension(source=bogus, dest=tmp_path / "out")
    assert "extension source not found" in str(exc.value)


def test_source_pointing_at_a_file_raises(tmp_path: Path):
    f = tmp_path / "not_a_dir.txt"
    f.write_text("oops")
    with pytest.raises(FileNotFoundError):
        inst.install_extension(source=f, dest=tmp_path / "out")


# ── /install-extension slash command ────────────────────────────────────


def test_slash_command_dispatches_to_install(monkeypatch, tmp_path: Path):
    """Dispatching ``/install-extension`` should call our function."""
    from chika._cli import commands as cmd

    called: dict[str, object] = {}

    def fake_install(*, console, **kwargs):
        called["console"] = console
        called["kwargs"] = kwargs
        return tmp_path / "fake_dest"

    monkeypatch.setattr(inst, "install_extension", fake_install)

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=100, color_system=None)
    ctx = cmd.CommandContext(console=console, engine=None)  # type: ignore[arg-type]

    handled = cmd.dispatch(ctx, "/install-extension")
    assert handled is True
    assert called["console"] is console


def test_slash_command_alias_install_ext(monkeypatch, tmp_path: Path):
    from chika._cli import commands as cmd

    called: list[bool] = []
    monkeypatch.setattr(
        inst, "install_extension",
        lambda **_: called.append(True) or (tmp_path / "x"),
    )
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=100, color_system=None)
    ctx = cmd.CommandContext(console=console, engine=None)  # type: ignore[arg-type]
    cmd.dispatch(ctx, "/install-ext")
    assert called == [True]


def test_slash_command_surfaces_missing_source_error(monkeypatch):
    from chika._cli import commands as cmd

    def boom(**_):
        raise FileNotFoundError("extension source not found: /bogus")

    monkeypatch.setattr(inst, "install_extension", boom)

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=200, color_system=None)
    ctx = cmd.CommandContext(console=console, engine=None)  # type: ignore[arg-type]
    cmd.dispatch(ctx, "/install-extension")
    out = buf.getvalue()
    assert "extension source not found" in out


def test_slash_command_in_help_listing():
    from chika._cli import commands as cmd
    names = [c.name for c in cmd.list_commands()]
    assert "install-extension" in names


def test_slash_command_aliases_registered():
    from chika._cli import commands as cmd
    assert "install-ext" in cmd.all_command_names()
    assert "install-extension" in cmd.all_command_names()


# ── chika install-extension argv subcommand ─────────────────────────────


def test_argv_subcommand_invokes_install(monkeypatch, tmp_path: Path):
    """``chika install-extension`` should call install_extension and exit
    without booting the REPL."""
    from chika._cli import app as appmod

    called: dict[str, object] = {}

    def fake_install(*, console, **_):
        called["console_provided"] = console is not None
        return tmp_path / "ext"

    monkeypatch.setattr(inst, "install_extension", fake_install)
    # If _run_rich got called we'd boot the engine — guard against it.
    monkeypatch.setattr(appmod, "_run_rich", _fail_if_called)

    appmod.cli(argv=["install-extension"])
    assert called.get("console_provided") is True


def test_argv_subcommand_alias_install_ext(monkeypatch, tmp_path: Path):
    from chika._cli import app as appmod

    called: list[bool] = []
    monkeypatch.setattr(
        inst, "install_extension",
        lambda **_: called.append(True) or (tmp_path / "ext"),
    )
    monkeypatch.setattr(appmod, "_run_rich", _fail_if_called)

    appmod.cli(argv=["install-ext"])
    assert called == [True]


def test_argv_subcommand_does_not_boot_repl(monkeypatch, tmp_path: Path):
    from chika._cli import app as appmod

    monkeypatch.setattr(inst, "install_extension", lambda **_: tmp_path / "ext")
    boot = []
    monkeypatch.setattr(appmod, "_run_rich",
                         lambda: boot.append("nope"))
    appmod.cli(argv=["install-extension"])
    assert boot == []


def test_argv_no_args_still_falls_through_to_repl(monkeypatch):
    """No subcommand → REPL boots (``_run_rich`` invoked)."""
    from chika._cli import app as appmod

    booted: list[bool] = []

    async def fake_run_rich():
        booted.append(True)

    monkeypatch.setattr(appmod, "_run_rich", fake_run_rich)
    monkeypatch.setattr(appmod, "_have_rich", lambda: True)
    appmod.cli(argv=[])
    assert booted == [True]


def test_argv_unknown_subcommand_falls_through_to_repl(monkeypatch):
    """Unknown subcommands shouldn't be handled — REPL takes over."""
    from chika._cli import app as appmod

    booted: list[bool] = []

    async def fake_run_rich():
        booted.append(True)

    monkeypatch.setattr(appmod, "_run_rich", fake_run_rich)
    monkeypatch.setattr(appmod, "_have_rich", lambda: True)
    appmod.cli(argv=["chat", "hello"])
    assert booted == [True]


def test_argv_subcommand_exits_nonzero_on_missing_source(monkeypatch):
    from chika._cli import app as appmod

    def boom(**_):
        raise FileNotFoundError("nope")

    monkeypatch.setattr(inst, "install_extension", boom)
    monkeypatch.setattr(appmod, "_run_rich", _fail_if_called)

    with pytest.raises(SystemExit) as ei:
        appmod.cli(argv=["install-extension"])
    assert ei.value.code == 1


def test_argv_subcommand_plain_mode_when_rich_missing(monkeypatch, tmp_path, capsys):
    """If rich isn't importable, the subcommand still works via plain print."""
    from chika._cli import app as appmod

    monkeypatch.setattr(appmod, "_have_rich", lambda: False)
    monkeypatch.setattr(inst, "install_extension", lambda **_: tmp_path / "ext")
    monkeypatch.setattr(appmod, "_run_rich", _fail_if_called)

    appmod.cli(argv=["install-extension"])
    out = capsys.readouterr().out
    assert "extension installed to" in out
    assert "chrome://extensions/" in out
    assert "Load unpacked" in out


def _fail_if_called():
    raise AssertionError("_run_rich should not be called for install-extension subcommand")


# ── Smoke test against the real extension/ dir ──────────────────────────


@pytest.mark.skipif(
    not REAL_EXTENSION.is_dir(),
    reason="real extension/ directory missing — fresh checkout?",
)
def test_real_extension_install_smoke(tmp_path: Path):
    """End-to-end smoke against the real bundled extension.

    Catches regressions like a new top-level runtime file being added
    to the repo without being added to ``_RUNTIME_TOP_LEVEL_FILES``.
    """
    dest = tmp_path / "real_install"
    with patch.object(inst.webbrowser, "open", return_value=False):
        result = inst.install_extension(
            source=REAL_EXTENSION, dest=dest, open_browser=False,
        )
    assert result == dest.resolve()
    # manifest_version 3 should round-trip
    manifest = (dest / "manifest.json").read_text(encoding="utf-8")
    assert '"manifest_version": 3' in manifest
    assert (dest / "background.js").exists()
    assert (dest / "popup" / "popup.html").exists()
    assert (dest / "popup" / "popup.js").exists()
    assert (dest / "lib" / "actions.js").exists()
    assert (dest / "icons" / "icon16.png").exists()
    assert (dest / "icons" / "icon128.png").exists()
    # Dev cruft must not be present
    assert not (dest / "node_modules").exists()
    assert not (dest / "e2e").exists()
    assert not (dest / "playwright.config.js").exists()
    assert not (dest / "icons" / "_render.mjs").exists()


@pytest.mark.skipif(
    not REAL_EXTENSION.is_dir(),
    reason="real extension/ directory missing",
)
def test_real_extension_manifest_paths_resolve_in_dest(tmp_path: Path):
    """Every path Chrome will look up from manifest.json must exist
    in the installed copy — otherwise "Load unpacked" will fail."""
    import json

    dest = tmp_path / "real_install"
    with patch.object(inst.webbrowser, "open", return_value=False):
        inst.install_extension(
            source=REAL_EXTENSION, dest=dest, open_browser=False,
        )
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))

    sw = manifest["background"]["service_worker"]
    assert (dest / sw).is_file(), f"manifest references missing file: {sw}"

    for entry in manifest.get("content_scripts", []):
        for js in entry.get("js", []):
            assert (dest / js).is_file(), f"content_scripts missing: {js}"

    action = manifest.get("action", {})
    if "default_popup" in action:
        assert (dest / action["default_popup"]).is_file()
    for size, rel in (action.get("default_icon") or {}).items():
        assert (dest / rel).is_file(), f"action icon {size} missing: {rel}"

    for size, rel in (manifest.get("icons") or {}).items():
        assert (dest / rel).is_file(), f"top-level icon {size} missing: {rel}"

    if "options_page" in manifest:
        assert (dest / manifest["options_page"]).is_file()
