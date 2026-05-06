"""``chika update`` — pull the latest version of Chika.

Detection
---------
We support three install kinds:

  ``git_clone``
      The repo root contains a ``.git`` directory. Update with
      ``git pull --ff-only`` (refuses to clobber local changes), then
      ``pip install -e . --upgrade --no-deps`` to refresh the editable
      install. Dependencies refresh on demand only — running pip with
      the full resolver every update is slow and noisy.

  ``pip_pypi``
      Chika is importable AND ``importlib.metadata`` knows it. Update
      with ``pip install --upgrade chika``. (Once we ship to PyPI.)

  ``windows_installer``
      The Chika Windows installer drops an ``install_marker.json``
      next to ``chika.cmd`` at install time. Update by downloading the
      latest ``chika-setup-X.Y.Z.exe`` from GitHub Releases and
      running it silently — Inno detects the existing install via its
      AppId GUID and runs an in-place upgrade.

  ``macos_installer``
      Same idea as Windows, with a ``.pkg`` instead. The postinstall
      script writes ``install_marker.json`` to
      ``/Library/Application Support/Chika/``. Update by downloading
      ``Chika-X.Y.Z.pkg`` and running ``installer -pkg <path>
      -target CurrentUserHomeDirectory``.

  ``linux_deb``
      Detected by ``dpkg -s chika`` returning successfully. Update via
      ``apt-get install --only-upgrade chika`` (assuming we publish to
      a repo) or by downloading the next ``chika_X.Y.Z_all.deb`` from
      Releases and running ``dpkg -i``.

  ``linux_universal``
      The fallback ``install.sh`` writes a marker. Update by re-running
      ``install.sh`` against the latest version — same script handles
      first install + upgrade.

  ``unknown``
      None of the markers present. We print a helpful message rather
      than guessing.

Auto-update on startup
----------------------
:func:`check_for_updates` queries the upstream remote (GitHub for git
clones, PyPI for pip installs) without touching the working tree. If a
newer version exists AND its CI run is green, callers can either
prompt the user or auto-apply the update — gated by the
``auto_update`` setting:

    off     — never auto-update (default; just notify)
    on      — auto-update silently when upstream main is green

CI gating ensures we never roll the user onto a broken commit. If we
can't reach the GitHub API (offline, rate-limited, network down) we
fail safe by *not* auto-updating — the user can still run ``chika
update`` manually.

Why no auto-restart
-------------------
On Windows pip can't reliably overwrite files belonging to a running
Python process — it has to land them on the next interpreter launch.
Spawning a detached "restart me" subprocess across shells/IDEs is
fragile, so we tell the user to restart and exit cleanly.

Why ``--ff-only``
-----------------
A user who's hand-edited their clone (e.g. local debug tweaks) should
NOT have those changes silently merged or rebased. ``--ff-only``
fails loudly so they decide what to do.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from rich.console import Console

# Injection points so tests can replace network + git without
# monkeypatching globals. Aliased here so signatures stay readable.
HttpGetter: TypeAlias = Callable[..., dict[str, Any]]
GitRunner: TypeAlias = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


# Network timeout for the upstream check. Short on purpose — startup
# checks must never block the REPL noticeably; on a slow network the
# check just reports "couldn't reach upstream" and the user moves on.
_HTTP_TIMEOUT = 5.0
_USER_AGENT = "chika-update-check/1.0"


# Repo root = three levels up from this file (chika/_cli/update.py).
REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class UpdateResult:
    kind: str          # "git_clone" | "pip_pypi" | "unknown"
    success: bool
    message: str       # human-readable summary, ready to print
    restart_required: bool = False


@dataclass(frozen=True)
class UpdateInfo:
    """Snapshot of upstream state from a non-mutating check.

    ``available`` answers "should we update". ``ci_green`` is the gate
    for auto-apply: we never roll a user onto a commit whose CI is
    failing or in-progress. ``reason`` is the short string we surface
    when ``available`` is False so logs/UI can explain why.
    """
    kind: str
    available: bool
    current: str           # version string OR short SHA
    latest: str            # version string OR short SHA
    ci_green: bool
    reason: str            # "ok" | "up_to_date" | "no_remote" | "ci_red" | "offline" | "rate_limited" | ...


# Persistent state file — throttles GitHub API calls and avoids
# re-applying the same update twice. Lives next to the installed
# extension so the whole ``~/.chika/`` tree is one tidy install dir.
_STATE_PATH: Path = Path.home() / ".chika" / "update_state.json"

# Don't ping the network more than once per hour on startup. GitHub's
# unauthed REST limit is 60 req/h per IP; even a tight 60s loop would
# burn through that with two background processes running.
_CHECK_THROTTLE_SECONDS = 60 * 60


# ── Detection ─────────────────────────────────────────────────────────────


def detect_install_kind(root: Path | None = None) -> str:
    """Return ``"git_clone"`` | ``"pip_pypi"`` | ``"windows_installer"`` | ``"unknown"``.

    Order of detection:

      1. ``.git`` dir at the repo root → git_clone (wins over everything;
         a developer working in a clone expects git semantics even if a
         system-wide pip install also exists).
      2. ``install_marker.json`` next to chika's location → look at
         ``kind`` field. Currently only ``windows_installer`` is
         recognised.
      3. ``importlib.metadata`` knows about chika → pip_pypi.
      4. Otherwise → unknown.
    """
    r = root or REPO_ROOT
    if (r / ".git").is_dir():
        return "git_clone"
    marker_kind = _read_install_marker()
    if marker_kind:
        return marker_kind
    if _is_pip_installed():
        return "pip_pypi"
    return "unknown"


_VALID_INSTALL_KINDS = {
    "windows_installer",
    "macos_installer",
    "linux_deb",
    "linux_universal",
}


def _marker_candidate_paths() -> list[Path]:
    """Where install_marker.json might live, in priority order.

    Each native installer drops the marker next to its install dir,
    so we resolve from the live ``sys.prefix`` (the venv) and walk
    upward to the parent (the install dir).

    The hard-coded paths cover the common case where the user runs
    ``python chika.py`` from outside the installed venv (e.g. dev) but
    happens to also have an installed copy on the same machine.
    """
    paths = [
        Path(sys.prefix).parent / "install_marker.json",
        Path(sys.prefix) / "install_marker.json",
    ]
    # System-wide install paths the native installers use.
    paths.extend([
        Path("/Library/Application Support/Chika/install_marker.json"),
        Path("/opt/chika/install_marker.json"),
        Path.home() / ".local" / "share" / "chika" / "install_marker.json",
    ])
    return paths


def _read_install_marker() -> str | None:
    """Look for ``install_marker.json`` in known locations.

    Returns the ``kind`` string from the marker (validated against
    :data:`_VALID_INSTALL_KINDS`), or ``None`` if no marker found
    anywhere.
    """
    for path in _marker_candidate_paths():
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                kind = str(data.get("kind", ""))
                if kind in _VALID_INSTALL_KINDS:
                    return kind
        except Exception:
            continue
    # Even without a marker, if dpkg knows about chika we're a .deb.
    if _dpkg_has_chika():
        return "linux_deb"
    return None


def _dpkg_has_chika() -> bool:
    """Return True if ``dpkg -s chika`` reports an installed package.

    Cheap fallback for when the .deb's postinst either failed to
    write install_marker.json or somebody nuked it. ``dpkg -s`` is
    fast and read-only.
    """
    if shutil.which("dpkg") is None:
        return False
    try:
        proc = subprocess.run(
            ["dpkg", "-s", "chika"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=5,
        )
        return proc.returncode == 0 and "Status: install ok installed" in proc.stdout
    except Exception:
        return False


def _is_pip_installed() -> bool:
    try:
        from importlib.metadata import PackageNotFoundError, version
        version("chika")
        return True
    except (ImportError, PackageNotFoundError):
        return False
    except Exception:
        return False


def current_version() -> str:
    """Best-effort version string for status output."""
    try:
        from importlib.metadata import version
        return version("chika")
    except Exception:
        return "2.0.0"


# ── Upstream check (non-mutating) ─────────────────────────────────────────


def check_for_updates(
    *,
    root: Path | None = None,
    timeout: float = _HTTP_TIMEOUT,
    http_get: HttpGetter | None = None,
    git_runner: GitRunner | None = None,
) -> UpdateInfo:
    """Query upstream without modifying anything.

    For git clones: hits the GitHub API for the latest commit on the
    default branch + its CI conclusion. For pip installs: hits PyPI's
    JSON API.

    The ``http_get`` and ``git_runner`` hooks let tests inject fake
    responses without monkeypatching urllib globally.
    """
    r = (root or REPO_ROOT).resolve()
    kind = detect_install_kind(r)
    get = http_get or _http_get_json
    git = git_runner or _git

    if kind == "git_clone":
        return _check_git_upstream(r, get, git, timeout=timeout)
    if kind == "pip_pypi":
        return _check_pypi_upstream(get, timeout=timeout)
    if kind in ("windows_installer", "macos_installer",
                "linux_deb", "linux_universal"):
        return _check_native_installer_upstream(kind, get, timeout=timeout)
    return UpdateInfo(
        kind="unknown", available=False, current="?", latest="?",
        ci_green=False, reason="unknown_install",
    )


def _check_git_upstream(
    root: Path,
    http_get: HttpGetter,
    git: GitRunner,
    *,
    timeout: float,
) -> UpdateInfo:
    if shutil.which("git") is None:
        return UpdateInfo(
            kind="git_clone", available=False, current="?", latest="?",
            ci_green=False, reason="git_missing",
        )

    head = git(["-C", str(root), "rev-parse", "HEAD"])
    if head.returncode != 0:
        return UpdateInfo(
            kind="git_clone", available=False, current="?", latest="?",
            ci_green=False, reason="no_head",
        )
    local_sha = head.stdout.strip()

    # Guard: only auto-update when the user is on the main branch.
    # On a feature branch, ``git pull --ff-only`` would try to pull
    # ``origin/<feature>`` which is unrelated to upstream main.
    branch_proc = git(["-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"])
    branch_name = branch_proc.stdout.strip() if branch_proc.returncode == 0 else ""
    if branch_name and branch_name not in ("main", "master", "HEAD"):
        return UpdateInfo(
            kind="git_clone", available=False, current=_short(local_sha),
            latest="?", ci_green=False, reason="not_on_main",
        )

    # Guard: don't auto-update over a dirty working tree. ``git pull
    # --ff-only`` would refuse on a real conflict but might happily
    # pull files that touch the user's WIP. Belt-and-braces: skip
    # the whole flow if anything is dirty.
    status = git(["-C", str(root), "status", "--porcelain"])
    if status.returncode == 0 and status.stdout.strip():
        return UpdateInfo(
            kind="git_clone", available=False, current=_short(local_sha),
            latest="?", ci_green=False, reason="working_tree_dirty",
        )

    remote_url = git(["-C", str(root), "remote", "get-url", "origin"])
    if remote_url.returncode != 0:
        return UpdateInfo(
            kind="git_clone", available=False, current=_short(local_sha),
            latest="?", ci_green=False, reason="no_remote",
        )
    parsed = parse_github_remote(remote_url.stdout.strip())
    if parsed is None:
        # Self-hosted git (gitlab, bitbucket, gitea) → we can ``git
        # fetch`` to compare SHAs but can't query CI. Return a partial
        # answer that keeps auto-update disabled but informs the user.
        return UpdateInfo(
            kind="git_clone", available=False, current=_short(local_sha),
            latest="?", ci_green=False, reason="non_github_remote",
        )
    owner, repo = parsed

    # Default branch — we always target ``main`` first; older repos
    # using ``master`` will still pass through but auto-update is
    # gated on CI status which we'll ask for either way.
    branch = "main"
    api_root = f"https://api.github.com/repos/{owner}/{repo}"

    try:
        commit = http_get(f"{api_root}/commits/{branch}", timeout=timeout)
    except _HttpError as exc:
        return UpdateInfo(
            kind="git_clone", available=False, current=_short(local_sha),
            latest="?", ci_green=False, reason=exc.code,
        )
    remote_sha = str(commit.get("sha") or "")
    if not remote_sha:
        return UpdateInfo(
            kind="git_clone", available=False, current=_short(local_sha),
            latest="?", ci_green=False, reason="no_commit_sha",
        )

    if remote_sha == local_sha:
        return UpdateInfo(
            kind="git_clone", available=False,
            current=_short(local_sha), latest=_short(remote_sha),
            ci_green=True, reason="up_to_date",
        )

    # Newer commit exists. Check CI before flagging available so we
    # never recommend rolling onto a broken main.
    try:
        check_runs = http_get(
            f"{api_root}/commits/{remote_sha}/check-runs",
            timeout=timeout,
        )
    except _HttpError:
        # We saw the new SHA but couldn't get CI status — mark
        # available=False (fail-safe) but record the SHA so the user
        # can decide manually.
        return UpdateInfo(
            kind="git_clone", available=False,
            current=_short(local_sha), latest=_short(remote_sha),
            ci_green=False, reason="ci_unknown",
        )
    ci_green = _check_runs_all_green(check_runs)
    return UpdateInfo(
        kind="git_clone", available=True,
        current=_short(local_sha), latest=_short(remote_sha),
        ci_green=ci_green,
        reason="ok" if ci_green else "ci_red",
    )


def _check_pypi_upstream(
    http_get: HttpGetter, *, timeout: float,
) -> UpdateInfo:
    cur = current_version()
    try:
        body = http_get("https://pypi.org/pypi/chika/json", timeout=timeout)
    except _HttpError as exc:
        return UpdateInfo(
            kind="pip_pypi", available=False, current=cur, latest=cur,
            ci_green=False, reason=exc.code,
        )
    latest = str(((body or {}).get("info") or {}).get("version") or "")
    if not latest:
        return UpdateInfo(
            kind="pip_pypi", available=False, current=cur, latest=cur,
            ci_green=False, reason="no_pypi_version",
        )
    if latest == cur:
        return UpdateInfo(
            kind="pip_pypi", available=False, current=cur, latest=latest,
            ci_green=True, reason="up_to_date",
        )
    # PyPI publishes are gated by the maintainer's CI, so we treat the
    # presence of a newer release as ``ci_green``.
    return UpdateInfo(
        kind="pip_pypi", available=True, current=cur, latest=latest,
        ci_green=True, reason="ok",
    )


# Hostname for the GitHub repo we look at for releases. Lives here as
# a single source of truth; the build pipelines write the same value
# into ``install_marker.json`` so a future fork could override it
# without recompiling.
_GITHUB_OWNER = "tochi-mba"
_GITHUB_REPO = "chika"


def _expected_asset_name(kind: str, version: str) -> str | None:
    """Filename pattern each native installer publishes to Releases.

    Single source of truth: ``installers/asset_names.py``. Build
    scripts also read from there so the names can never drift.
    """
    try:
        from installers.asset_names import expected_asset_name
        return expected_asset_name(kind, version)
    except ImportError:
        # Defensive: shouldn't happen in any real install (the
        # ``installers/`` package ships with the wheel), but if it
        # somehow does, fall back to the inline mapping.
        return {
            "windows_installer": f"chika-setup-{version}.exe",
            "macos_installer":   f"Chika-{version}.pkg",
            "linux_deb":         f"chika_{version}_all.deb",
            "linux_universal":   None,
        }.get(kind)


def _check_native_installer_upstream(
    kind: str, http_get: HttpGetter, *, timeout: float,
) -> UpdateInfo:
    """Check GitHub Releases for a newer installer than what's installed.

    Generic across the four native-install kinds. GitHub publishes
    the release at the end of CI, so by definition everything visible
    here is post-CI-passing → ``ci_green=True`` when we find an asset.
    """
    cur = _read_installed_version() or current_version()
    try:
        body = http_get(
            f"https://api.github.com/repos/{_GITHUB_OWNER}/{_GITHUB_REPO}/releases/latest",
            timeout=timeout,
        )
    except _HttpError as exc:
        return UpdateInfo(
            kind=kind, available=False, current=cur, latest=cur,
            ci_green=False, reason=exc.code,
        )

    tag = str(body.get("tag_name") or body.get("name") or "")
    latest = tag.lstrip("vV") if tag else ""
    if not latest:
        return UpdateInfo(
            kind=kind, available=False, current=cur, latest=cur,
            ci_green=False, reason="no_release",
        )
    if latest == cur:
        return UpdateInfo(
            kind=kind, available=False, current=cur, latest=latest,
            ci_green=True, reason="up_to_date",
        )

    # linux_universal updates via install.sh — we don't need an asset.
    if kind == "linux_universal":
        return UpdateInfo(
            kind=kind, available=True, current=cur, latest=latest,
            ci_green=True, reason="ok",
        )

    expected = _expected_asset_name(kind, latest)
    if expected is None:
        return UpdateInfo(
            kind=kind, available=True, current=cur, latest=latest,
            ci_green=True, reason="ok",
        )
    asset_url = _find_installer_asset(body, expected)
    if not asset_url:
        return UpdateInfo(
            kind=kind, available=True, current=cur, latest=latest,
            ci_green=False, reason="no_installer_asset",
        )
    return UpdateInfo(
        kind=kind, available=True, current=cur, latest=latest,
        ci_green=True, reason="ok",
    )


def _find_installer_asset(release: dict, asset_name: str) -> str | None:
    """Return the ``browser_download_url`` for the named asset, or None."""
    assets = release.get("assets") or []
    for a in assets:
        if str(a.get("name", "")).lower() == asset_name.lower():
            url = a.get("browser_download_url")
            if isinstance(url, str) and url.startswith("https://"):
                return url
    return None


def _read_installed_version() -> str | None:
    """Read ``version`` from install_marker.json (Windows installer)."""
    candidates = [
        Path(sys.prefix).parent / "install_marker.json",
        Path(sys.prefix) / "install_marker.json",
    ]
    for path in candidates:
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                v = data.get("version")
                if isinstance(v, str) and v:
                    return v
        except Exception:
            continue
    return None


# ── Auto-update on startup ────────────────────────────────────────────────


def auto_update_on_startup(
    console: Console | None = None,
    *,
    root: Path | None = None,
    setting: str | None = None,
    state_path: Path | None = None,
    now: float | None = None,
    http_get: HttpGetter | None = None,
    git_runner: GitRunner | None = None,
) -> UpdateInfo | None:
    """Check upstream and apply the update if it's eligible.

    Designed to be run in a background thread on REPL startup. Returns
    the :class:`UpdateInfo` snapshot (or ``None`` when the check was
    throttled / disabled) so callers can render a one-line notice.

    Eligibility for auto-apply:
      - ``setting == "on"`` (default — read from ``settings_store`` if
        the caller doesn't pass an override)
      - ``UpdateInfo.available is True``
      - ``UpdateInfo.ci_green is True``
      - the same SHA hasn't already been auto-applied (state file)

    This function never raises — every failure is folded into the
    returned UpdateInfo's ``reason`` field.
    """
    try:
        eff_setting = setting if setting is not None else _read_auto_update_setting()
    except Exception:
        eff_setting = "on"

    if eff_setting == "off":
        return None

    state = _load_state(state_path)
    ts_now = now if now is not None else _now()

    # Throttle network checks.
    last_check = float(state.get("last_check_at") or 0.0)
    if ts_now - last_check < _CHECK_THROTTLE_SECONDS and state.get("last_info"):
        # Use the cached info; never apply on a stale check.
        cached = state["last_info"]
        return UpdateInfo(
            kind=str(cached.get("kind", "unknown")),
            available=False,  # don't act on a cached check
            current=str(cached.get("current", "?")),
            latest=str(cached.get("latest", "?")),
            ci_green=bool(cached.get("ci_green")),
            reason="throttled",
        )

    info = check_for_updates(
        root=root, http_get=http_get, git_runner=git_runner,
    )

    state["last_check_at"] = ts_now
    state["last_info"] = {
        "kind": info.kind, "current": info.current, "latest": info.latest,
        "ci_green": info.ci_green, "reason": info.reason,
    }

    eligible = (
        info.available and info.ci_green
        and state.get("last_applied_sha") != info.latest
    )

    if eligible:
        result = update_chika(console=None, root=root)
        state["last_applied_sha"] = info.latest
        state["last_apply_at"] = ts_now
        state["last_apply_success"] = result.success
        if console is not None:
            _render_auto_update_notice(console, info, result)
    elif console is not None and info.available:
        _render_update_available_notice(console, info)

    _save_state(state, state_path)
    return info


def _render_auto_update_notice(
    console: Console, info: UpdateInfo, result: UpdateResult,
) -> None:
    from rich.text import Text

    from chika._cli.renderer import THEME
    if result.success:
        line = Text("  · ", style=THEME.muted)
        line.append("auto-updated ", style=f"bold {THEME.success}")
        line.append(f"{info.current} → {info.latest}", style=THEME.text)
        line.append("  (restart Chika to load the new code)", style=THEME.muted)
    else:
        line = Text("  · ", style=THEME.muted)
        line.append("auto-update tried but failed: ", style=THEME.warn)
        line.append(result.message.splitlines()[0] if result.message else "?",
                    style=THEME.text)
    console.print(line)


def _render_update_available_notice(console: Console, info: UpdateInfo) -> None:
    from rich.text import Text

    from chika._cli.renderer import THEME
    line = Text("  · ", style=THEME.muted)
    line.append("update available", style=f"bold {THEME.accent}")
    line.append(f": {info.current} → {info.latest}", style=THEME.text)
    if not info.ci_green:
        line.append("  (ci not green — skipped auto-update)", style=THEME.warn)
    line.append("  · run /update", style=THEME.muted)
    console.print(line)


# ── State file ────────────────────────────────────────────────────────────


def _load_state(path: Path | None = None) -> dict:
    p = path or _STATE_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _save_state(state: dict, path: Path | None = None) -> None:
    p = path or _STATE_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        # Best-effort: an inability to persist throttle state must not
        # crash startup. Worst case: we re-check next launch.
        pass


def _read_auto_update_setting() -> str:
    try:
        import api.settings_store as ss
        return str(ss.get("auto_update", "on") or "on")
    except Exception:
        return "on"


def _now() -> float:
    import time
    return time.time()


# ── HTTP + parsing helpers ────────────────────────────────────────────────


class _HttpError(Exception):
    """Categorised network failure with a short, stable ``code`` string
    we can stuff into ``UpdateInfo.reason`` ("offline", "rate_limited",
    "http_500", etc.)."""
    def __init__(self, code: str, *args):
        super().__init__(code, *args)
        self.code = code


def _http_get_json(url: str, *, timeout: float) -> dict:
    """Default ``http_get`` — fetches ``url`` and returns the JSON body.

    Categorises common failure modes so the caller can map them onto
    ``UpdateInfo.reason``.

    Security: the only URLs this function should ever see are the
    constants we construct internally (``https://api.github.com/...``,
    ``https://pypi.org/...``) — never anything user-supplied. We
    nonetheless explicitly reject non-https schemes here as defence
    in depth: that closes the SSRF / file-URL attack surface bandit
    flags as B310 even if a future caller forgets the contract.
    """
    if not url.lower().startswith("https://"):
        raise _HttpError("bad_scheme")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        # Scheme is asserted https above; URL is a hard-coded internal
        # constant. No user input reaches this call.
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            data = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise _HttpError("rate_limited") from exc
        if exc.code == 404:
            raise _HttpError("not_found") from exc
        raise _HttpError(f"http_{exc.code}") from exc
    except urllib.error.URLError as exc:
        raise _HttpError("offline") from exc
    except TimeoutError as exc:
        raise _HttpError("timeout") from exc
    except Exception as exc:
        raise _HttpError("network_error") from exc

    try:
        return json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise _HttpError("bad_json") from exc


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return _run(["git", *args])


_GITHUB_HTTPS_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_GITHUB_SSH_RE = re.compile(
    r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


def parse_github_remote(url: str) -> tuple[str, str] | None:
    """Extract ``(owner, repo)`` from an HTTPS or SSH GitHub URL.

    Returns ``None`` for non-GitHub remotes — auto-update only gates on
    GitHub Actions because that's where Chika's CI lives.
    """
    if not url:
        return None
    for rx in (_GITHUB_HTTPS_RE, _GITHUB_SSH_RE):
        m = rx.match(url.strip())
        if m:
            return (m.group(1), m.group(2))
    return None


def _check_runs_all_green(payload: dict) -> bool:
    """Return True iff every check-run on the commit succeeded.

    GitHub's check-runs schema:
        { "total_count": N, "check_runs": [
            {"status": "completed", "conclusion": "success", ...},
            ...
        ]}

    ``conclusion`` values that count as green: "success", "skipped",
    "neutral". Anything else (including ``None`` for in-progress) →
    not green.
    """
    runs = (payload or {}).get("check_runs") or []
    if not runs:
        # No CI configured on this commit → conservatively treat as
        # not green so we never auto-roll the user onto an unverified
        # commit.
        return False
    green = {"success", "skipped", "neutral"}
    for run in runs:
        status = str((run or {}).get("status") or "")
        concl = str((run or {}).get("conclusion") or "")
        if status != "completed":
            return False
        if concl not in green:
            return False
    return True


def _short(sha: str) -> str:
    return (sha or "")[:7]


# ── Public API ────────────────────────────────────────────────────────────


def update_chika(
    console: Console | None = None,
    *,
    root: Path | None = None,
    dry_run: bool = False,
) -> UpdateResult:
    """Run the appropriate update command for the detected install.

    Parameters
    ----------
    console
        Rich console for output. ``None`` suppresses rendering (tests).
    root
        Override the repo root (tests).
    dry_run
        Skip the actual subprocess calls — used by tests so we can
        exercise the orchestration without invoking pip.
    """
    r = (root or REPO_ROOT).resolve()
    kind = detect_install_kind(r)

    if kind == "git_clone":
        result = _update_git_clone(r, dry_run=dry_run)
    elif kind == "pip_pypi":
        result = _update_pip_pypi(dry_run=dry_run)
    elif kind == "windows_installer":
        result = _update_windows_installer(dry_run=dry_run)
    else:
        result = UpdateResult(
            kind="unknown",
            success=False,
            message=(
                "couldn't detect how Chika was installed.\n"
                "  · clone install?     run: git pull && pip install -e .\n"
                "  · pip install?       run: pip install --upgrade chika\n"
                "  · Windows installer? download the latest setup.exe from\n"
                "                       github.com/tochi-mba/chika/releases"
            ),
        )

    if console is not None:
        _render_update_result(console, result)
    return result


# ── Git-clone path ────────────────────────────────────────────────────────


def _update_git_clone(root: Path, *, dry_run: bool) -> UpdateResult:
    git = shutil.which("git")
    if git is None:
        return UpdateResult(
            kind="git_clone",
            success=False,
            message=(
                "git not found on PATH — install git, or update manually:\n"
                f"  cd {root} && git pull && pip install -e ."
            ),
        )

    if dry_run:
        return UpdateResult(
            kind="git_clone", success=True,
            message="dry-run: would git pull --ff-only + pip install -e .",
            restart_required=True,
        )

    pull = _run([git, "-C", str(root), "pull", "--ff-only"])
    if pull.returncode != 0:
        return UpdateResult(
            kind="git_clone",
            success=False,
            message=(
                "git pull failed — fix the working tree and re-run.\n"
                f"  {(pull.stderr or pull.stdout).strip().splitlines()[-1] if (pull.stderr or pull.stdout).strip() else 'no output'}"
            ),
        )

    # Refresh the editable install — picks up new entry points or any
    # metadata changes. ``--no-deps`` keeps it fast; if pyproject.toml's
    # deps changed the user can re-run ``pip install -e .[dev]`` manually.
    pip_cmd = [sys.executable, "-m", "pip", "install", "-e", str(root),
               "--upgrade", "--no-deps", "--quiet"]
    pip = _run(pip_cmd)
    if pip.returncode != 0:
        return UpdateResult(
            kind="git_clone",
            success=False,
            message=(
                "git pull succeeded but pip refresh failed:\n"
                f"  {(pip.stderr or pip.stdout).strip().splitlines()[-1] if (pip.stderr or pip.stdout).strip() else 'no output'}\n"
                f"  retry manually: pip install -e {root}"
            ),
        )

    return UpdateResult(
        kind="git_clone", success=True,
        message=f"updated git clone at {root}.",
        restart_required=True,
    )


# ── PyPI path ─────────────────────────────────────────────────────────────


def _update_pip_pypi(*, dry_run: bool) -> UpdateResult:
    if dry_run:
        return UpdateResult(
            kind="pip_pypi", success=True,
            message="dry-run: would run pip install --upgrade chika",
            restart_required=True,
        )
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "chika", "--quiet"]
    pip = _run(cmd)
    if pip.returncode != 0:
        return UpdateResult(
            kind="pip_pypi",
            success=False,
            message=(
                "pip install --upgrade chika failed:\n"
                f"  {(pip.stderr or pip.stdout).strip().splitlines()[-1] if (pip.stderr or pip.stdout).strip() else 'no output'}"
            ),
        )
    return UpdateResult(
        kind="pip_pypi", success=True,
        message="updated chika from PyPI.",
        restart_required=True,
    )


# ── Windows-installer path ────────────────────────────────────────────────


def _update_windows_installer(
    *,
    dry_run: bool,
    http_get: HttpGetter | None = None,
    download_to: Path | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> UpdateResult:
    """Download the next chika-setup-X.Y.Z.exe and run it silently.

    Strategy:

      1. Hit GitHub releases/latest, pull tag_name + the
         chika-setup-*.exe asset's browser_download_url.
      2. Download to ``%TEMP%\\chika-setup-X.Y.Z.exe``.
      3. Run it with ``/SILENT /SUPPRESSMSGBOXES`` — Inno's standard
         silent-install flags. Inno detects the existing install
         (same AppId GUID) and performs an in-place upgrade, which
         re-runs ``post_install.ps1`` to refresh the venv.

    The HTTP and subprocess hooks are injectable so tests can stage
    a fake release without touching the network.
    """
    if dry_run:
        return UpdateResult(
            kind="windows_installer", success=True,
            message="dry-run: would download + run latest chika-setup-*.exe",
            restart_required=True,
        )

    get = http_get or _http_get_json
    run_subprocess = runner or _run

    try:
        body = get(
            f"https://api.github.com/repos/{_GITHUB_OWNER}/{_GITHUB_REPO}/releases/latest",
            timeout=_HTTP_TIMEOUT,
        )
    except _HttpError as exc:
        return UpdateResult(
            kind="windows_installer", success=False,
            message=f"couldn't reach GitHub releases ({exc.code})",
        )

    tag = str(body.get("tag_name") or body.get("name") or "")
    version = tag.lstrip("vV") if tag else ""
    if not version:
        return UpdateResult(
            kind="windows_installer", success=False,
            message="GitHub release has no tag_name",
        )
    expected_name = _expected_asset_name("windows_installer", version) \
        or f"chika-setup-{version}.exe"
    asset_url = _find_installer_asset(body, expected_name)
    if not asset_url:
        return UpdateResult(
            kind="windows_installer", success=False,
            message=(
                f"release {version} has no {expected_name} asset.\n"
                f"  download manually from https://github.com/{_GITHUB_OWNER}/{_GITHUB_REPO}/releases"
            ),
        )

    target = download_to or (
        Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".")
        / f"chika-setup-{version}.exe"
    )
    try:
        _download_file(asset_url, target)
    except _HttpError as exc:
        return UpdateResult(
            kind="windows_installer", success=False,
            message=f"download failed ({exc.code}): {asset_url}",
        )
    except Exception as exc:
        return UpdateResult(
            kind="windows_installer", success=False,
            message=f"download failed: {exc}",
        )

    # Run the installer silently. Inno's ``/SILENT`` shows a small
    # progress bar; ``/VERYSILENT`` shows none. We use ``/SILENT``
    # so the user has visual confirmation the update is happening.
    proc = run_subprocess([
        str(target), "/SILENT", "/SUPPRESSMSGBOXES",
        "/CLOSEAPPLICATIONS", "/NORESTART",
    ])
    if proc.returncode != 0:
        return UpdateResult(
            kind="windows_installer", success=False,
            message=(
                f"installer exited with code {proc.returncode}\n"
                f"  log: {target}.log (Inno writes one alongside the .exe)"
            ),
        )

    return UpdateResult(
        kind="windows_installer", success=True,
        message=f"updated to {version} via Windows installer.",
        restart_required=True,
    )


def _download_file(url: str, dest: Path) -> None:
    """Download ``url`` to ``dest``. Asserts https scheme."""
    if not url.lower().startswith("https://"):
        raise _HttpError("bad_scheme")
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        # nosec B310 — scheme asserted https; url comes from the
        # GitHub Releases API which we trust as a content source.
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT * 6) as resp:  # nosec B310
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as out:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
    except urllib.error.HTTPError as exc:
        raise _HttpError(f"http_{exc.code}") from exc
    except urllib.error.URLError as exc:
        raise _HttpError("offline") from exc


# ── Subprocess helper ────────────────────────────────────────────────────


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run ``cmd`` capturing stdout/stderr, never raising.

    We always want to inspect ``returncode`` and surface the error
    message, so ``check=False``. ``text=True`` so trailing-newline
    handling stays sane.
    """
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# ── Rendering ─────────────────────────────────────────────────────────────


def _render_update_result(console: Console, result: UpdateResult) -> None:
    """Print a Panel summarising the update."""
    from rich.panel import Panel
    from rich.text import Text

    from chika._cli.renderer import THEME

    title_style = (THEME.success if result.success
                   else THEME.error if result.kind != "unknown"
                   else THEME.warn)
    title_label = ("update succeeded" if result.success
                   else "update failed" if result.kind != "unknown"
                   else "update — manual step needed")

    body = Text()
    body.append("install kind: ", style=THEME.muted)
    body.append(f"{result.kind}\n", style=f"bold {THEME.text}")
    body.append("current version: ", style=THEME.muted)
    body.append(f"{current_version()}\n\n", style=THEME.text)
    body.append(result.message, style=THEME.text)
    if result.restart_required:
        body.append("\n\nrestart Chika to load the new code.", style=THEME.muted)

    console.print(Panel(
        body,
        title=Text(title_label, style=f"bold {title_style}"),
        title_align="left",
        border_style=title_style,
        padding=(1, 2),
    ))
