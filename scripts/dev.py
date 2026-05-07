"""``python scripts/dev.py`` (or ``chika dev``) — boot the full dev stack.

What it runs (in parallel, both with hot-reload):

  - ``[api]`` uvicorn on the FastAPI app at http://localhost:8000
                 with --reload watching ``api/`` and ``chika/``.
  - ``[web]`` ``vite`` dev server on http://localhost:5173 with HMR.

Output from both is multiplexed into the current terminal with
colored ``[api]`` / ``[web]`` prefixes so you can see what's
happening on each side at a glance.

Ctrl+C terminates both cleanly. If either process dies on its own,
the other gets terminated too — keeps the dev loop honest.

Why this exists: the OAuth callback hand-off (e.g. ``chika spotify
connect``) needs the API server running to receive the redirect.
Without a one-shot launcher, every dev round-trip needed three
terminals (server, frontend, REPL) and getting one out of sync
silently broke flows.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

REPO_ROOT     = Path(__file__).resolve().parent.parent
FRONTEND_DIR  = REPO_ROOT / "frontend"
API_HOST      = os.environ.get("CHIKA_DEV_API_HOST", "127.0.0.1")
API_PORT      = os.environ.get("CHIKA_DEV_API_PORT", "8000")
WEB_PORT      = os.environ.get("CHIKA_DEV_WEB_PORT", "5173")

# ANSI colour codes — disabled if stdout isn't a TTY (CI logs).
_ENABLE_COLOUR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
_COLOURS = {
    "api":   "\033[36m",   # cyan
    "web":   "\033[35m",   # magenta
    "warn":  "\033[33m",   # yellow
    "err":   "\033[31m",   # red
    "reset": "\033[0m",
}


def _paint(tag: str, kind: str = "tag") -> str:
    if not _ENABLE_COLOUR:
        return tag
    code = _COLOURS.get(kind) or _COLOURS.get(tag) or _COLOURS["reset"]
    return f"{code}{tag}{_COLOURS['reset']}"


def _stream(proc: subprocess.Popen, prefix: str, kind: str) -> None:
    """Read lines from ``proc.stdout`` and prefix them. Runs in a
    thread per process so both streams interleave naturally."""
    label = _paint(f"[{prefix}]", kind)
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(f"{label} {line}")
        sys.stdout.flush()


def _which_npm() -> str | None:
    """Locate ``npm`` — checks PATH first, then a couple of usual
    Windows install dirs (``npm.cmd`` on PATH usually fails to find
    the bare 'npm' Python passes to ``Popen``)."""
    for name in ("npm", "npm.cmd"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _start_api() -> subprocess.Popen:
    """Boot uvicorn with --reload so backend code changes hot-reload."""
    cmd = [
        sys.executable, "-m", "uvicorn",
        "api.server:app",
        "--host", API_HOST,
        "--port", API_PORT,
        "--reload",
        "--reload-dir", str(REPO_ROOT / "api"),
        "--reload-dir", str(REPO_ROOT / "chika"),
        # Force asyncio loop on Windows (matches api/server.py's __main__).
        "--loop", "asyncio",
    ]
    return subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        # New process group on Windows so Ctrl+C only fires once and
        # we can kill children cleanly.
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0),
    )


def _start_web() -> subprocess.Popen | None:
    """Boot ``vite`` dev server. Returns None if npm isn't installed —
    backend-only dev still works, just no live frontend."""
    npm = _which_npm()
    if npm is None:
        sys.stdout.write(
            f"{_paint('[dev]', 'warn')} npm not found on PATH — "
            "skipping frontend dev server. "
            "(Install Node ≥ 20 if you want HMR on the Vue app.)\n"
        )
        return None
    if not (FRONTEND_DIR / "package.json").is_file():
        sys.stdout.write(
            f"{_paint('[dev]', 'warn')} {FRONTEND_DIR}/package.json missing — "
            "skipping frontend.\n"
        )
        return None
    if not (FRONTEND_DIR / "node_modules").is_dir():
        sys.stdout.write(
            f"{_paint('[dev]', 'warn')} frontend/node_modules missing. "
            "Run `cd frontend && npm install` first if you want the web UI.\n"
        )
        return None
    return subprocess.Popen(
        [npm, "run", "dev", "--", "--port", WEB_PORT, "--strictPort"],
        cwd=str(FRONTEND_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        shell=False,
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0),
    )


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            # CTRL_BREAK_EVENT to the new process group — graceful for
            # uvicorn + node, won't leave orphan workers.
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> int:
    sys.stdout.write(
        f"{_paint('[dev]', 'warn')} starting Chika dev stack — "
        f"API on http://{API_HOST}:{API_PORT}, "
        f"frontend on http://localhost:{WEB_PORT}. "
        "Ctrl+C to stop both.\n"
    )

    api_proc = _start_api()
    web_proc = _start_web()
    procs = [(p, tag) for p, tag in [(api_proc, "api"), (web_proc, "web")] if p is not None]

    threads: list[threading.Thread] = []
    for proc, tag in procs:
        t = threading.Thread(target=_stream, args=(proc, tag, tag), daemon=True)
        t.start()
        threads.append(t)

    rc = 0
    try:
        # Wait for ANY process to exit — once one dies, tear the
        # other down so the dev loop doesn't quietly run with half
        # the stack missing.
        while True:
            for proc, tag in procs:
                rc_one = proc.poll()
                if rc_one is not None:
                    sys.stdout.write(
                        f"{_paint('[dev]', 'err')} [{tag}] exited "
                        f"with code {rc_one} — stopping the rest.\n"
                    )
                    rc = rc_one or 1
                    return _shutdown(procs, rc)
            try:
                threads[0].join(timeout=0.5)
            except Exception:
                pass
    except KeyboardInterrupt:
        sys.stdout.write(f"\n{_paint('[dev]', 'warn')} Ctrl+C — shutting down…\n")
        return _shutdown(procs, 0)


def _shutdown(procs: list[tuple[subprocess.Popen, str]], rc: int) -> int:
    for proc, _tag in procs:
        _terminate(proc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
