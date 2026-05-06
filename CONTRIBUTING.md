# Contributing to Chika

## Dev setup

```bash
# Clone and install (editable, with dev deps)
git clone <repo>
cd chika_v2
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Copy and configure environment
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY or OPENAI_API_KEY
```

## Running tests

```bash
pytest -v
```

For coverage report:

```bash
pytest --cov=chika --cov=api --cov-report=term-missing
```

## Code style

```bash
ruff check .         # lint
ruff check . --fix   # auto-fix
mypy chika/ api/ config.py --ignore-missing-imports
```

Pre-commit runs these automatically on every `git commit`.

## Adding a new tool

1. Create `chika/tools/your_tool.py`.
2. Define an `async` handler and wrap it in a `ToolDefinition`:

```python
from chika.core.tool_registry import ToolDefinition

async def your_handler(param: str) -> dict:
    return {"result": param}

YOUR_TOOL = ToolDefinition(
    name="your_tool",
    description="One-line description the LLM reads to decide when to use this tool.",
    parameters={
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "What param does"},
        },
        "required": ["param"],
    },
    handler=your_handler,
)
```

3. Register it in `api/session_manager.py` alongside the other tools.
4. Add tests in `tests/test_your_tool.py`.

All tool handlers must return `{"error": "<message>"}` on failure — never raise.

## Adding a new skill

Skills are collections of pre-built tool handlers that the LLM can call by name.

1. Create `chika/skills/your_skill/__init__.py`.
2. Export a `SkillDefinition` with `name`, `description`, `tools` (list of `ToolDefinition`), and an optional `system_prompt_fragment`.
3. Register in `api/session_manager.py` via `skill_registry.register(YOUR_SKILL)`.

## Commit format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

[optional body]
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`.

Examples:
- `fix(file_tools): prevent path traversal via .. segments`
- `feat(workflow): add retry step type with backoff`
- `test(variable_store): add concurrency + circular-ref tests`

## Brand mark (the chika trefoil)

Chika's mark is a stroke-only 3-leaf trefoil that renders on **four
surfaces** with incompatible rendering models. There's no shared
runtime that spans them all (Vue ≠ vanilla popup HTML ≠ Chrome MV3
PNG ≠ terminal grid), so the same geometry lives in 4 places. See
ADR-27 for the full rationale.

**Canonical source of truth:** `frontend/src/components/ChikaMark.vue`.

When you change the geometry (petal path, angles, hub radius, stroke
width), update **all four** of these in one PR:

| File | What it owns |
|------|--------------|
| `frontend/src/components/ChikaMark.vue` | The Vue component. Used by the SPA nav. |
| `extension/popup/popup.html` + `popup.css` | Inline SVG in the popup header. Vanilla CSS, same animation keyframes. |
| `extension/icons/_render.html` | The page Playwright screenshots to produce manifest PNGs. |
| `chika/_cli/mark.py` | Python rasteriser — samples the same cubic bezier into half-block characters. |

After editing all four, regenerate the manifest PNGs:

```bash
cd extension
node icons/_render.mjs
```

This writes `icon16/32/48/128.png` from the SVG. Re-run after every
geometry change so the toolbar icons stay in sync.

Spot-check the CLI rasterisation:

```bash
PYTHONIOENCODING=utf-8 python -m chika._cli.mark
```

Should print a recognisable 3-leaf trefoil in half-block characters.

If you change the **animation states** (idle / thinking / streaming /
success / intro), update both `ChikaMark.vue` and `popup.css` — they
share the same `@keyframes` definitions. The CLI doesn't carry per-leaf
animations (terminal grid resolution is too coarse); it uses the inline
state-row indicator instead (see ADR-28).

## Native installers

Chika ships installers for every major OS. End users grab the installer for their platform from the GitHub Pages landing page; contributors build them locally to test changes.

### Tree

```
installers/
├── README.md                  ← per-installer build instructions
├── windows/
│   ├── chika.iss              ← Inno Setup script (the manifest)
│   ├── build_installer.ps1    ← run from repo root: builds wheel + ISCC
│   ├── post_install.ps1       ← creates venv + pip installs wheel
│   ├── pre_uninstall.ps1      ← strips PATH, preserves user data
│   ├── chika.cmd              ← on-PATH launcher (sets CHIKA_DATA_DIR)
│   └── chika.ico              ← Add/Remove Programs icon
├── macos/
│   ├── build_pkg.sh           ← pkgbuild + productbuild
│   ├── scripts/preinstall     ← clears prior venv
│   ├── scripts/postinstall    ← creates venv, /usr/local/bin symlink
│   ├── chika                  ← launcher shim
│   └── uninstall.sh           ← user-runnable uninstaller
└── linux/
    ├── debian/control         ← .deb metadata (Version: VERSION_PLACEHOLDER)
    ├── debian/postinst        ← creates venv, pip installs
    ├── debian/prerm           ← venv cleanup
    ├── chika                  ← launcher shim
    ├── build_deb.sh           ← uses dpkg-deb
    └── install.sh             ← universal curl|bash for any glibc 2.28+
```

### Building locally

| OS | Requirements | Command |
|---|---|---|
| Windows | Inno Setup 6, Python 3.11+ | `.\installers\windows\build_installer.ps1` |
| macOS   | Xcode CLT, Python 3.11+   | `./installers/macos/build_pkg.sh` |
| Linux   | `dpkg-dev`, Python 3.11+   | `./installers/linux/build_deb.sh` |

Each script reads the version from `pyproject.toml` so the installer version is locked to the package version. Pass `--version 2.0.5` to override.

### Adding a new runtime file to the install

If you add a new top-level runtime file (manifest, asset, config), update **every** installer build script's file list:

- `installers/windows/build_installer.ps1` — `$includeFiles` / `$includeDirs` arrays
- `installers/macos/build_pkg.sh` — payload tree population
- `installers/linux/build_deb.sh` — `$PKG_DIR/opt/chika/` copies

The structural test `test_installer_structure.py::test_release_workflow_attaches_all_assets` will catch missing assets at PR time.

### Auto-update path for native installs

When chika is run from a native installer (detected via `install_marker.json`), `chika update` and the on-launch auto-update thread download the next setup file from GitHub Releases and run it silently. The asset name patterns are encoded in `chika._cli.update._expected_asset_name`; **keep this in sync** with the build scripts' output filenames or the auto-update will fail to find the asset.

### Asset filename matrix

Build scripts produce these filenames; `update.py`'s asset detector looks for them:

| Install kind | Filename |
|---|---|
| `windows_installer` | `chika-setup-{version}.exe` |
| `macos_installer`   | `Chika-{version}.pkg`       |
| `linux_deb`         | `chika_{version}_all.deb`   |
| `linux_universal`   | (no asset; updates by re-running `install.sh`) |

A test (`test_installer_structure.py::test_update_asset_names_match_*`) verifies the names match.

## Install / update / doctor CLI

Three argv subcommands sit in front of the REPL — they exit before
booting the engine, so they work even on a half-broken install:

| Command                  | Purpose                                                     |
|--------------------------|-------------------------------------------------------------|
| `chika install-extension`| Copy the bundled extension to `~/.chika/extension/` and open `chrome://extensions/`. Re-run after every release. |
| `chika update`           | `git pull --ff-only` + `pip install -e . --upgrade --no-deps` for clone installs; `pip install --upgrade chika` for pip installs. |
| `chika update --check`   | Peek without applying. Prints `available`, `up_to_date`, or the failure reason (`offline`, `rate_limited`, `ci_red`, `not_on_main`, `working_tree_dirty`, …). |
| `chika doctor`           | Verify the install (Python ≥3.11, every required import, extension intact, frontend built, `.env` present, `data/` writable, console script on PATH). Exit code 1 on `error`, 0 on `ok`/`warn`. |

The same actions are slash commands inside the REPL: `/install-extension`, `/update`, `/update --check`, `/doctor`, `/auto-update [on|off]`.

**Auto-update on startup.** When `auto_update == "on"` (the default — see `data/settings.json`), `_run_rich` spawns a daemon thread that runs `chika._cli.update.auto_update_on_startup`. It hits the GitHub API once per hour (throttled via `~/.chika/update_state.json`), and only auto-applies when **all** these are true:

- The user is on `main` or `master` (not a feature branch — `git pull --ff-only` would pull the wrong ref).
- The working tree is clean (no `git status --porcelain` output).
- A newer commit exists on upstream main.
- Every check-run on that commit has `status=completed` AND `conclusion ∈ {success, skipped, neutral}`.
- We haven't already auto-applied this SHA (state file).

Any failure → notice only, no apply. The full rationale is ADR-29.

**When you add a new runtime dep**, update both `pyproject.toml` *and* `requirements.txt` and add the import to `chika._cli.doctor.REQUIRED_IMPORTS`. The `test_install_chika.py::test_requirements_txt_mirrors_pyproject_runtime` test will fail otherwise. Same goes for adding a top-level runtime file in `extension/` — list it in `chika._cli.install_extension._RUNTIME_TOP_LEVEL_FILES` (or its dir in `_RUNTIME_DIRS`), or `chika install-extension` will ship a broken extension.

## Visual snapshot baselines (Playwright)

Visual baselines live in three places:

- `frontend/e2e/*-snapshots/`
- `extension/e2e/*-snapshots/`
- `docs/e2e/*-snapshots/` *(landing page; ~70 baselines across 7 viewport projects)*

Pixel-compared in CI. Chromium renders fonts + antialiasing slightly
differently on Linux vs macOS vs Windows, so the canonical baselines
are the **Linux ones** (CI runs on `ubuntu-latest`). See ADR-26.

Workflow when you change UI that has a visual baseline:

1. Make your UI change locally; run the relevant suite to see what fails.
   ```bash
   # frontend
   cd frontend && BASE_URL=http://localhost:5173 npx playwright test
   # extension
   cd extension && npm run test:e2e
   # docs landing page
   cd docs && npm run test:e2e
   ```
2. Push your branch and open a PR.
3. CI fails the visual snapshot tests with diff images uploaded as
   `frontend-playwright-report` / `extension-playwright-report` /
   `docs-playwright-report` artifacts — eyeball them to confirm the
   diff is intentional.
4. Add the **`update-snapshots`** label to the PR.
   `.github/workflows/update-snapshots.yml` runs on `ubuntu-latest`,
   regenerates every `-chromium-linux.png` baseline (frontend +
   extension + docs), and commits the updates back onto your PR
   branch.
5. The label auto-removes when done. CI re-runs and goes green.

Manual variant: trigger `update-snapshots.yml` from the Actions tab
(`workflow_dispatch`).

**Don't commit `-chromium-win32.png` or `-chromium-darwin.png`
baselines as if they were ground truth** — CI ignores them. If you
see them in a diff and didn't intend to push them, drop them. They're
only useful as a local design-review preview.

### Landing page (`docs/`) baseline coverage

`docs/e2e/landing.spec.js` runs across 7 device profiles defined in
`docs/playwright.config.js`:

- `desktop` (1440×900)
- `iphone-se` / `iphone-14` / `iphone-14-landscape` / `pixel-7`
- `ipad-mini` / `ipad-pro`

Per-section snapshots: header, terminal showcase, features, install,
update, uninstall, footer. Plus mobile-only full-page, mobile-nav
open state, desktop-only CTA hover, install-card hovers.

When the v0 redesign first lands (or any major design change), there
will be **no baselines yet**. Add the `update-snapshots` label to the
PR to generate them; subsequent diffs are pixel-compared against
those generated baselines.

## Test pyramid health

Per the reviewer's ADR-25 + ADR-36 guidance, we keep the suite shaped
like a pyramid (lots of fast unit tests, fewer integration, even
fewer e2e). `tests/test_pyramid_health.py` enforces this with two
loose floors:

- `MIN_TOTAL_TESTS` — total collected tests in `tests/`
- `MIN_UNIT_LIKE` — tests without an `e2e` / `slow` marker

The floors are set to ~80% of current count so a small handful of
deletions doesn't trip the alarm, but a structural shift does. **If
you legitimately delete a hundred unit tests in one PR, lower the
floor in this file as part of the same PR.** The contract: drift is
visible at PR time, not 6 months later.

## CI-equivalent local check

Before opening a PR, run the same gauntlet CI does:

```bash
# Lint
python -m ruff check .

# Types
python -m mypy chika/ api/ config.py --ignore-missing-imports

# Python tests + coverage gate
python -m pytest -q --ignore=tests/test_cli_e2e.py \
  --cov=chika --cov=api --cov-fail-under=75

# Frontend Playwright (against the dev server for speed)
cd frontend
BASE_URL=http://localhost:5173 npx playwright test
```

If your `chromium-linux.png` baselines don't exist locally, the visual
tests will fail — that's expected. Use the workflow above to generate
them in CI.

## PR checklist

- [ ] Tests pass: `pytest -v`
- [ ] Linting clean: `ruff check .`
- [ ] No type regressions: `mypy chika/ api/ config.py --ignore-missing-imports`
- [ ] Coverage above the 75% gate (`--cov-fail-under=75`)
- [ ] If UI changed: visual snapshot baselines regenerated via the
  `update-snapshots` PR label (don't push Win32 / Darwin baselines)
- [ ] New tools return `{"error": ...}` on failure
- [ ] New tools registered in `session_manager.py`
- [ ] Sensitive data (API keys, tokens) not committed
