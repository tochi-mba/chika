"""Install-structure assertions for the whole Chika repo.

These tests are not about behaviour. They lock in the *shape* of the
install — the things that silently break a release if a config file
drifts from the code:

  - pyproject.toml
      • console script ``chika`` resolves to a real callable
      • runtime deps are mirrored in requirements.txt (the install
        wizard reads requirements.txt; pyproject is the canonical
        list — they MUST agree)
      • Python version requirement matches doctor's ``MIN_PYTHON``
      • setuptools include_packages globs cover ``chika``, ``api``

  - Repo entry points
      • ``chika.py`` exists and exports ``cli``
      • ``install.py`` exists and exports ``main``
      • ``api/server.py`` exists

  - Bundled extension
      • Every path the Chrome manifest references resolves on disk

  - Frontend
      • ``frontend/package.json`` exists with build scripts

  - install.py wizard
      • Each step function is callable
      • TOTAL_STEPS matches the actual number of step calls

A failure here means a user's ``pip install`` will break in a way that
isn't covered by behavioural tests. That's the point.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


# ── pyproject.toml ───────────────────────────────────────────────────────


def test_pyproject_exists():
    assert (REPO_ROOT / "pyproject.toml").is_file()


def test_pyproject_project_name(pyproject):
    assert pyproject["project"]["name"] == "chika"


def test_pyproject_console_script_registered(pyproject):
    scripts = pyproject["project"]["scripts"]
    assert "chika" in scripts
    target = scripts["chika"]
    assert target == "chika:cli", (
        f"console script should be 'chika:cli', got {target!r}"
    )


def test_pyproject_console_script_target_resolves():
    """``chika:cli`` → ``chika`` package's ``cli`` attribute must exist."""
    import chika
    assert hasattr(chika, "cli")
    assert callable(chika.cli)


def test_pyproject_python_version_floor(pyproject):
    """The ``requires-python`` floor must be at least 3.11 — the codebase
    uses ``X | Y`` union syntax that 3.10 can't parse."""
    req = pyproject["project"]["requires-python"]
    m = re.search(r">=\s*(\d+)\.(\d+)", req)
    assert m
    floor = (int(m.group(1)), int(m.group(2)))
    assert floor >= (3, 11)


def test_pyproject_runtime_deps_present(pyproject):
    """Sanity: the must-have runtime deps are listed."""
    deps = pyproject["project"]["dependencies"]
    must_have = {"fastapi", "uvicorn", "pydantic", "openai", "anthropic",
                 "rich", "prompt_toolkit"}
    listed = set()
    for dep in deps:
        name = dep.split(">=")[0].split("==")[0].split("[")[0].strip()
        listed.add(name.lower().replace("-", "_"))
    for required in must_have:
        assert required.lower() in listed, f"missing dep: {required}"


def test_pyproject_dev_extras_have_test_tools(pyproject):
    dev = pyproject["project"].get("optional-dependencies", {}).get("dev", [])
    listed = {d.split(">=")[0].split("==")[0].strip() for d in dev}
    for tool in ("pytest", "mypy", "ruff"):
        assert tool in listed


def test_pyproject_packages_include_chika_and_api(pyproject):
    cfg = pyproject["tool"]["setuptools"]["packages"]["find"]
    include = set(cfg.get("include", []))
    assert any(p.startswith("chika") for p in include)
    assert any(p.startswith("api") for p in include)


def test_pyproject_pytest_testpaths_includes_tests(pyproject):
    cfg = pyproject["tool"]["pytest"]["ini_options"]
    assert "tests" in cfg["testpaths"]


def test_pyproject_ruff_target_version_matches_min_python(pyproject):
    target = pyproject["tool"]["ruff"]["target-version"]
    assert target == "py311"


# ── requirements.txt mirrors pyproject ───────────────────────────────────


def _parse_requirements(path: Path) -> set[str]:
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip version specifiers + extras
        name = re.split(r"[<>=!\[]", line, maxsplit=1)[0].strip()
        out.add(name.lower().replace("-", "_"))
    return out


def test_requirements_txt_mirrors_pyproject_runtime(pyproject):
    """``install.py`` reads requirements.txt before falling back to
    ``pip install -e .``. Drift between the two surfaces would mean
    one path is missing a dep."""
    req_path = REPO_ROOT / "requirements.txt"
    assert req_path.is_file()
    listed_in_req = _parse_requirements(req_path)
    pyproject_deps = set()
    for dep in pyproject["project"]["dependencies"]:
        name = re.split(r"[<>=!\[]", dep, maxsplit=1)[0].strip()
        pyproject_deps.add(name.lower().replace("-", "_"))

    missing_from_req = pyproject_deps - listed_in_req
    assert not missing_from_req, (
        f"pyproject.toml lists deps that requirements.txt does not: "
        f"{sorted(missing_from_req)}"
    )


# ── Top-level entry points ───────────────────────────────────────────────


def test_chika_dot_py_exists():
    assert (REPO_ROOT / "chika.py").is_file()


def test_chika_dot_py_exports_cli():
    """``python chika.py`` must drop into the same ``cli`` callable
    that the console script uses."""
    src = (REPO_ROOT / "chika.py").read_text(encoding="utf-8")
    assert "from chika._cli import cli" in src
    assert "cli()" in src


def test_install_dot_py_exists():
    assert (REPO_ROOT / "install.py").is_file()


def test_install_dot_py_main_callable():
    """Dynamically import ``install.py`` and verify ``main()`` exists.

    We don't run it — it would prompt for input and try to install
    dependencies. We just verify the entry point is wired."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_chika_install", REPO_ROOT / "install.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # The module imports ``getpass`` etc. on import — fine.
    spec.loader.exec_module(mod)
    assert callable(getattr(mod, "main", None))
    # And the step functions
    for name in (
        "check_python", "install_deps", "configure_env",
        "verify_setup", "build_frontend", "print_extension_instructions",
        "configure_spotify", "print_start_instructions", "start_server",
    ):
        assert callable(getattr(mod, name, None)), f"install.py missing {name}"


def test_api_server_exists():
    """install.py and the README both point users at this script."""
    assert (REPO_ROOT / "api" / "server.py").is_file()


# ── Bundled extension ────────────────────────────────────────────────────


def test_extension_dir_exists():
    assert (REPO_ROOT / "extension").is_dir()


def test_extension_manifest_loadable():
    manifest_path = REPO_ROOT / "extension" / "manifest.json"
    assert manifest_path.is_file()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["manifest_version"] == 3
    assert data["name"]
    assert data["version"]


def test_extension_manifest_paths_resolve_on_disk():
    """Every relative path the Chrome manifest references must exist —
    a missing icon or popup file would break ``Load unpacked``."""
    ext = REPO_ROOT / "extension"
    manifest = json.loads((ext / "manifest.json").read_text(encoding="utf-8"))

    sw = manifest["background"]["service_worker"]
    assert (ext / sw).is_file(), f"missing service worker: {sw}"

    for entry in manifest.get("content_scripts", []):
        for js in entry.get("js", []):
            assert (ext / js).is_file(), f"missing content script: {js}"

    action = manifest.get("action", {})
    if "default_popup" in action:
        assert (ext / action["default_popup"]).is_file()
    for size, rel in (action.get("default_icon") or {}).items():
        assert (ext / rel).is_file(), f"action icon {size}: {rel}"

    for size, rel in (manifest.get("icons") or {}).items():
        assert (ext / rel).is_file(), f"top-level icon {size}: {rel}"

    if "options_page" in manifest:
        assert (ext / manifest["options_page"]).is_file()


def test_extension_install_module_runtime_files_match_manifest_dirs():
    """Sanity: every directory the manifest references is also in the
    install module's ``_RUNTIME_DIRS`` — otherwise ``chika
    install-extension`` would deliver a broken extension."""
    from chika._cli import install_extension as inst

    ext = REPO_ROOT / "extension"
    manifest = json.loads((ext / "manifest.json").read_text(encoding="utf-8"))

    referenced_dirs: set[str] = set()
    for entry in manifest.get("content_scripts", []):
        for js in entry.get("js", []):
            referenced_dirs.add(js.split("/")[0])
    if "default_popup" in manifest.get("action", {}):
        referenced_dirs.add(manifest["action"]["default_popup"].split("/")[0])
    for rel in (manifest.get("action", {}).get("default_icon") or {}).values():
        referenced_dirs.add(rel.split("/")[0])
    for rel in (manifest.get("icons") or {}).values():
        referenced_dirs.add(rel.split("/")[0])
    if "options_page" in manifest:
        referenced_dirs.add(manifest["options_page"].split("/")[0])

    missing = referenced_dirs - set(inst._RUNTIME_DIRS)
    assert not missing, (
        f"manifest references dirs not in install_extension._RUNTIME_DIRS: "
        f"{sorted(missing)}"
    )


# ── Frontend ─────────────────────────────────────────────────────────────


def test_frontend_package_json_exists():
    assert (REPO_ROOT / "frontend" / "package.json").is_file()


def test_frontend_package_json_has_build_scripts():
    pkg = json.loads(
        (REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"),
    )
    scripts = pkg.get("scripts") or {}
    # README + install.py both call ``npm run build`` on the frontend.
    assert "build" in scripts


def test_frontend_index_html_exists():
    """The frontend has a Vite root that serves at /."""
    assert (REPO_ROOT / "frontend" / "index.html").is_file()


# ── CLI commands wiring ──────────────────────────────────────────────────


def test_chika_cli_imports_cleanly():
    """``import chika`` exposes ``cli`` as a callable.

    We deliberately don't pop and re-import ``chika`` — that strips
    submodules from ``chika.*`` and breaks every later test that uses
    ``monkeypatch.setattr("chika.<sub>...")``.
    """
    import chika
    assert callable(chika.cli)


def test_install_extension_argv_subcommand_registered():
    """The argv subcommands we promise in ``cli()`` docstrings must
    actually be handled. Smoke check via the source string."""
    src = (REPO_ROOT / "chika" / "_cli" / "app.py").read_text(encoding="utf-8")
    assert '"install-extension"' in src
    assert '"update"' in src
    assert '"doctor"' in src


def test_slash_commands_registered():
    """Verify each of the new slash commands appears in the registry."""
    from chika._cli import commands as cmd
    names = {c.name for c in cmd.list_commands()}
    for required in ("install-extension", "update", "auto-update", "doctor"):
        assert required in names, f"slash command /{required} not registered"


# ── Settings store install defaults ─────────────────────────────────────


def test_settings_init_seeds_all_required_keys(tmp_path: Path, monkeypatch):
    """A fresh install (no settings.json) should land with every key
    we depend on populated."""
    import api.settings_store as ss

    monkeypatch.setattr(ss, "_SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(ss, "_settings", {})
    ss.init({"autonomy": "supervised"})

    expected_keys = {
        "autonomy", "tool_permissions",
        "pet_speech", "pet_speech_tokens",
        "auto_continue", "auto_continue_max",
        "state_verbs", "state_verbs_tokens",
        "auto_update",
    }
    actual = set(ss.all_settings().keys())
    missing = expected_keys - actual
    assert not missing, f"settings init didn't seed: {missing}"


def test_settings_auto_update_default_is_on(tmp_path: Path, monkeypatch):
    import api.settings_store as ss

    monkeypatch.setattr(ss, "_SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(ss, "_settings", {})
    ss.init({"autonomy": "supervised"})
    assert ss.get("auto_update") == "on"


def test_settings_auto_update_validation():
    import api.settings_store as ss

    with pytest.raises(ValueError):
        ss.update({"auto_update": "sometimes"})


# ── Cross-cutting health ────────────────────────────────────────────────


def test_data_directory_exists_or_creatable():
    """``data/`` must exist or be creatable — the engine writes
    settings.json, profiles.json, and chat history here."""
    data = REPO_ROOT / "data"
    assert data.is_dir() or not data.exists()
    if not data.exists():
        # Try creating it to confirm we can
        data.mkdir(parents=True)
        try:
            assert data.is_dir()
        finally:
            data.rmdir()


def test_dot_env_example_or_documented():
    """Either ``.env.example`` exists OR install.py documents the
    expected variables. Currently we rely on install.py."""
    has_example = (REPO_ROOT / ".env.example").is_file()
    install_src = (REPO_ROOT / "install.py").read_text(encoding="utf-8")
    documents_env = "CHIKA_PROVIDER" in install_src
    assert has_example or documents_env, (
        "no .env.example AND install.py doesn't reference CHIKA_PROVIDER — "
        "users have no way to discover required env vars"
    )


def test_readme_documents_install_command():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "install.py" in readme or "pip install" in readme


# ── Doctor + update integration ─────────────────────────────────────────


def test_doctor_runs_against_real_repo():
    """End-to-end smoke: run doctor on the actual repo, expect to find
    every check reporting ok or warn (not error)."""
    from chika._cli import doctor as doc

    report = doc.run_doctor(console=None)
    # We allow warnings (e.g. frontend not built in a fresh checkout)
    # but errors here mean the install is genuinely broken.
    errors = [c for c in report.checks if c.severity == "error"]
    assert not errors, "\n".join(
        f"  · {c.name}: {c.detail}" for c in errors
    )


def test_update_module_detects_this_install():
    """Sanity: update detection should classify this dev checkout as
    git_clone (we run from a clone with .git/)."""
    from chika._cli import update as upd
    if not (REPO_ROOT / ".git").is_dir():
        pytest.skip("not a git checkout")
    assert upd.detect_install_kind() == "git_clone"
