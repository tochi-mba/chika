"""``chika doctor`` — verify the install is healthy.

Runs a battery of cheap checks and prints a status table. Designed to
catch the silent failure modes that bite users:

  - Python version below the minimum
  - A required runtime dependency missing from the active env
  - The bundled ``extension/`` directory missing or stripped
  - The frontend ``dist/`` not built (warns rather than errors —
    the CLI works fine without it)
  - ``data/`` not writable
  - ``.env`` missing or empty (warning, not error)
  - The console script ``chika`` not registered (warning)

Each check returns a :class:`Check` with one of:

  ok     — green "✓"
  warn   — yellow "⚠" — non-fatal, user should be aware
  error  — red "✗"   — install is broken

Exit code mirrors the worst severity (0 = ok/warn, 1 = any error)
so this can plug into CI / install scripts that want to verify
the result.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent

# Hard floor: pyproject.toml says ``requires-python = ">=3.11"`` so
# anything below is broken on its face. Keep this in sync with
# pyproject.toml — ``test_install_chika.py`` asserts the match.
MIN_PYTHON: tuple[int, int] = (3, 11)

# Runtime deps we expect to be importable. Drawn from
# pyproject.toml's ``dependencies`` list. We deliberately don't
# verify versions — pip resolves those at install time and a
# version drift here would be a false positive at runtime.
REQUIRED_IMPORTS: tuple[str, ...] = (
    "fastapi",
    "uvicorn",
    "websockets",
    "pydantic",
    "dotenv",          # python-dotenv exposes ``dotenv``
    "openai",
    "anthropic",
    "httpx",
    "ddgs",
    "rich",
    "prompt_toolkit",
)


@dataclass(frozen=True)
class Check:
    name: str
    severity: str       # "ok" | "warn" | "error"
    detail: str = ""


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[Check, ...]

    @property
    def worst(self) -> str:
        if any(c.severity == "error" for c in self.checks):
            return "error"
        if any(c.severity == "warn" for c in self.checks):
            return "warn"
        return "ok"

    @property
    def exit_code(self) -> int:
        return 1 if self.worst == "error" else 0


# ── Public API ────────────────────────────────────────────────────────────


def run_doctor(
    console: Console | None = None,
    *,
    root: Path | None = None,
) -> DoctorReport:
    """Run all checks; render results when ``console`` is provided."""
    r = (root or REPO_ROOT).resolve()
    checks = (
        check_python_version(),
        *check_required_imports(),
        check_extension_directory(r),
        check_frontend_dist(r),
        check_env_file(r),
        check_data_writable(r),
        check_console_script(),
        # Auto-gen drift checks (added in ADR-37). Each is a warn,
        # not error — drift is a contributor concern, not a runtime
        # break. Errors here would block users on a stale checkout.
        check_event_types_in_sync(r),
        check_brand_parity(r),
        check_skill_summaries_in_sync(r),
    )
    report = DoctorReport(checks=checks)
    if console is not None:
        _render_doctor_report(console, report)
    return report


# ── Auto-gen drift checks (ADR-37) ───────────────────────────────────


def _run_check_script(root: Path, script: str, args: list[str]) -> tuple[int, str]:
    """Invoke ``python scripts/<script>`` with ``--check``-flavour args.

    Returns ``(exit_code, last_stderr_line)`` so the caller can map
    the result to a Check severity + detail.
    """
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(root), timeout=60,
    )
    err_tail = ""
    for line in (proc.stderr or "").splitlines():
        if line.strip():
            err_tail = line.strip()
    return proc.returncode, err_tail


def check_event_types_in_sync(root: Path) -> Check:
    """Verify the auto-generated TS + JSDoc event types are current."""
    script = root / "scripts" / "gen_event_types.py"
    if not script.is_file():
        return Check(
            name="event types in sync", severity="warn",
            detail="gen_event_types.py missing",
        )
    rc, _err = _run_check_script(root, "gen_event_types.py", ["--check"])
    if rc == 0:
        return Check(
            name="event types in sync", severity="ok",
            detail="frontend + extension types match api/models.py",
        )
    return Check(
        name="event types in sync", severity="warn",
        detail="run: python scripts/gen_event_types.py",
    )


def check_brand_parity(root: Path) -> Check:
    """Verify the trefoil path is byte-identical across all 5 surfaces."""
    script = root / "scripts" / "check_brand_parity.py"
    if not script.is_file():
        return Check(
            name="brand parity", severity="warn",
            detail="check_brand_parity.py missing",
        )
    rc, err = _run_check_script(root, "check_brand_parity.py", [])
    if rc == 0:
        return Check(
            name="brand parity", severity="ok",
            detail="trefoil path identical on every surface",
        )
    return Check(
        name="brand parity", severity="warn",
        detail=err or "drift detected — see ADR-27",
    )


def check_skill_summaries_in_sync(root: Path) -> Check:
    """Every committed SKILL.md has a matching-hash summary cache."""
    script = root / "scripts" / "regenerate_skill_summaries.py"
    if not script.is_file():
        return Check(
            name="skill summaries in sync", severity="warn",
            detail="regenerate_skill_summaries.py missing",
        )
    rc, _err = _run_check_script(root, "regenerate_skill_summaries.py", ["--check"])
    if rc == 0:
        return Check(
            name="skill summaries in sync", severity="ok",
            detail="every SKILL.md has a matching-hash summary",
        )
    return Check(
        name="skill summaries in sync", severity="warn",
        detail="run: python scripts/regenerate_skill_summaries.py",
    )


# ── Individual checks ─────────────────────────────────────────────────────


def check_python_version() -> Check:
    cur = sys.version_info[:2]
    detail = f"{cur[0]}.{cur[1]}.{sys.version_info.micro}"
    if cur < MIN_PYTHON:
        return Check(
            name="python version",
            severity="error",
            detail=f"{detail} — need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+",
        )
    return Check(name="python version", severity="ok", detail=detail)


def check_required_imports() -> tuple[Check, ...]:
    out: list[Check] = []
    for mod in REQUIRED_IMPORTS:
        try:
            importlib.import_module(mod)
            out.append(Check(name=f"import {mod}", severity="ok"))
        except Exception as exc:
            out.append(Check(
                name=f"import {mod}",
                severity="error",
                detail=f"{type(exc).__name__}: {exc}",
            ))
    return tuple(out)


def check_extension_directory(root: Path) -> Check:
    ext = root / "extension"
    if not ext.is_dir():
        return Check(
            name="bundled extension",
            severity="error",
            detail=f"missing: {ext}",
        )
    manifest = ext / "manifest.json"
    if not manifest.is_file():
        return Check(
            name="bundled extension",
            severity="error",
            detail=f"manifest.json missing in {ext}",
        )
    return Check(
        name="bundled extension", severity="ok",
        detail=f"{ext}",
    )


def check_frontend_dist(root: Path) -> Check:
    dist = root / "frontend" / "dist"
    if dist.is_dir() and (dist / "index.html").is_file():
        return Check(
            name="frontend build",
            severity="ok",
            detail=f"{dist}",
        )
    return Check(
        name="frontend build",
        severity="warn",
        detail=(
            "not built — run `cd frontend && npm install && npm run build`. "
            "CLI still works without it."
        ),
    )


def check_env_file(root: Path) -> Check:
    env = root / ".env"
    if not env.exists():
        return Check(
            name=".env",
            severity="warn",
            detail="not found — run install.py to configure your provider",
        )
    if env.stat().st_size == 0:
        return Check(name=".env", severity="warn", detail="empty")
    return Check(name=".env", severity="ok", detail=f"{env}")


def check_data_writable(root: Path) -> Check:
    """Ensure ``data/`` is writable. Tries to create + delete a probe
    file rather than relying on ``os.access`` which lies on Windows."""
    data = root / "data"
    try:
        data.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return Check(
            name="data/ writable",
            severity="error",
            detail=f"can't create {data}: {exc}",
        )
    probe = data / ".doctor_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as exc:
        return Check(
            name="data/ writable",
            severity="error",
            detail=f"can't write to {data}: {exc}",
        )
    return Check(name="data/ writable", severity="ok", detail=f"{data}")


def check_console_script() -> Check:
    """Best-effort check for whether ``chika`` is on PATH.

    ``shutil.which`` doesn't see scripts pip installed into a venv
    that isn't activated yet, so a missing entry is a *warn*, not an
    *error* — the user can always run ``python chika.py``.
    """
    found = shutil.which("chika") or shutil.which("chika.exe")
    if found:
        return Check(
            name="chika command",
            severity="ok",
            detail=f"on PATH at {found}",
        )
    return Check(
        name="chika command",
        severity="warn",
        detail=(
            "not on PATH — run `pip install -e .` from the repo root, or "
            "use `python chika.py`."
        ),
    )


# ── Rendering ─────────────────────────────────────────────────────────────


def _render_doctor_report(console: Console, report: DoctorReport) -> None:
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from chika._cli.renderer import THEME

    glyph = {"ok": "✓", "warn": "⚠", "error": "✗"}
    style = {"ok": THEME.success, "warn": THEME.warn, "error": THEME.error}

    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style=THEME.text, no_wrap=False)
    table.add_column(style=THEME.muted, no_wrap=False, overflow="fold")
    for c in report.checks:
        table.add_row(
            Text(glyph[c.severity], style=f"bold {style[c.severity]}"),
            c.name,
            c.detail,
        )

    summary_style = style[report.worst]
    summary_label = {
        "ok":    "all checks passed",
        "warn":  "passed with warnings",
        "error": "errors found — install is broken",
    }[report.worst]

    title = Text("chika doctor", style=f"bold {THEME.accent}")
    title.append(f"  ·  {summary_label}", style=summary_style)

    console.print(Panel(
        table,
        title=title, title_align="left",
        border_style=summary_style,
        padding=(1, 1),
    ))
    if report.worst == "error":
        console.print(Text(
            f"  exit code {report.exit_code} — fix the errors above and re-run.",
            style=THEME.muted,
        ))


# Helper for tests on systems where ``importlib`` lookup needs to go
# through a clean module table (e.g. simulating a missing dep).
def _force_clear_module_cache(name: str) -> None:
    sys.modules.pop(name, None)
    # Ensure namespace packages are also wiped
    for k in [k for k in sys.modules if k.startswith(name + ".")]:
        sys.modules.pop(k, None)


# Helper exposed for tests so they don't need to monkeypatch
# ``sys.platform`` for the rare path checks.
def _is_windows() -> bool:
    return os.name == "nt"
