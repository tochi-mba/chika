"""``scaffold_web_app`` — drop a working starter for any browser-based stack.

Two paths:

1. **Built-in templates** (instant, no network): ``vanilla``, ``static-site``.
   We write the files ourselves so the agent can build something runnable
   in <50ms with no npm round-trip.

2. **Delegate to canonical scaffolders** (``npm create``, ``npx``): for
   anything based on Vite, Next, Nuxt, Astro, SvelteKit, etc. We map the
   stack id to its idiomatic ``create-*`` invocation and run it
   non-interactively. Unknown stack ids fall through to a generic
   ``npm create <stack>@latest`` attempt — pip-equivalent for "I bet there
   is a create package for this."

The tool returns the project path, the exact command that ran, and the
suggested next step (install / dev server). It does NOT auto-start a dev
server — that decision is left to the agent so it can chain ``live_server``
or ``python_run`` as appropriate.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any

from chika.core.tool_registry import ToolDefinition

# ── Stack catalogue ──────────────────────────────────────────────────────────
#
# Each entry tells the tool how to materialise a starter for one stack.
# - kind="builtin": we write a known set of files ourselves.
# - kind="vite":    runs ``npm create vite@latest`` with --template <vite_template>.
# - kind="cmd":     runs ``cmd_template`` after `.format(name=…)` substitution.
#
# Adding a new stack is a one-line entry — the dispatcher handles the rest.

_VITE_TEMPLATES = (
    "vanilla", "vanilla-ts",
    "vue", "vue-ts",
    "react", "react-ts", "react-swc", "react-swc-ts",
    "preact", "preact-ts",
    "lit", "lit-ts",
    "svelte", "svelte-ts",
    "solid", "solid-ts",
    "qwik", "qwik-ts",
)

_STACKS: dict[str, dict] = {
    # Built-in (no network): instantly usable
    "vanilla":     {"kind": "builtin", "template": "vanilla"},
    "static-site": {"kind": "builtin", "template": "static-site"},

    # Vite family (handled via `npm create vite@latest`)
    **{
        f"vite-{t}": {"kind": "vite", "vite_template": t}
        for t in _VITE_TEMPLATES
    },
    # Convenient aliases
    "vue":     {"kind": "vite", "vite_template": "vue-ts"},
    "react":   {"kind": "vite", "vite_template": "react-ts"},
    "svelte":  {"kind": "vite", "vite_template": "svelte-ts"},
    "preact":  {"kind": "vite", "vite_template": "preact-ts"},
    "lit":     {"kind": "vite", "vite_template": "lit-ts"},
    "solid":   {"kind": "vite", "vite_template": "solid-ts"},
    "qwik":    {"kind": "vite", "vite_template": "qwik-ts"},

    # Other canonical scaffolders. ``cmd_template`` uses ``{name}`` for the
    # project directory; we run it via a shell so the create-* binaries
    # resolve through npm's bin path.
    "next":      {"kind": "cmd",
                  "cmd_template": "npx --yes create-next-app@latest {name} --ts --eslint --app --use-npm --no-tailwind --import-alias '@/*' --src-dir --no-turbopack"},
    "nuxt":      {"kind": "cmd",
                  "cmd_template": "npm create -y nuxt@latest {name} -- --no-install --packageManager npm"},
    "astro":     {"kind": "cmd",
                  "cmd_template": "npm create -y astro@latest {name} -- --template basics --no-install --skip-houston --no-git"},
    "sveltekit": {"kind": "cmd",
                  "cmd_template": "npm create -y svelte@latest {name}"},
    "remix":     {"kind": "cmd",
                  "cmd_template": "npx --yes create-remix@latest {name} --no-install --no-git-init --yes"},
    "qwik-city": {"kind": "cmd",
                  "cmd_template": "npm create -y qwik@latest {name}"},
    "lit-app":   {"kind": "cmd",
                  "cmd_template": "npx --yes create-lit-app@latest {name}"},
    "three":     {"kind": "vite",  "vite_template": "vanilla-ts",
                  "extra_packages": ["three", "@types/three"]},
    "p5":        {"kind": "vite",  "vite_template": "vanilla",
                  "extra_packages": ["p5"]},
    "phaser":    {"kind": "vite",  "vite_template": "vanilla-ts",
                  "extra_packages": ["phaser"]},
}


def list_stacks() -> list[str]:
    return sorted(_STACKS.keys())


# ── Alias resolution ──────────────────────────────────────────────────────
#
# Agents commonly guess stack ids that LOOK like they should work
# (``vite-three``, ``react-vite``, ``threejs``) but don't match the
# catalogue. Falling through to ``npm create <stack>@latest`` then takes
# 20+s to fail with a 404. Resolving aliases up-front turns those guesses
# into clean dispatches.
#
# Order of resolution:
#   1. Direct lookup in _STACKS (case-insensitive).
#   2. Drop ``vite-`` prefix and re-lookup (e.g. ``vite-three`` → ``three``).
#   3. Static synonym table.
#   4. Strip non-alphanumerics and retry (e.g. ``three.js`` → ``threejs`` → ``three``).
#   5. Give up — caller falls through to the npm-create attempt.

_SYNONYMS: dict[str, str] = {
    # Plain vanilla family
    "html":        "vanilla",
    "html-css-js": "vanilla",
    "js":          "vanilla",
    "javascript":  "vanilla",
    "static":      "static-site",
    "site":        "static-site",
    "ssg":         "astro",

    # Game / canvas / 3D
    "threejs":     "three",
    "three.js":    "three",
    "three-js":    "three",
    "vite-three":  "three",
    "vite-threejs":"three",
    "p5js":        "p5",
    "p5.js":       "p5",
    "vite-p5":     "p5",
    "vite-phaser": "phaser",

    # Framework synonyms
    "nextjs":      "next",
    "next.js":     "next",
    "nuxtjs":      "nuxt",
    "nuxt.js":     "nuxt",
    "sveltek":     "sveltekit",
    "kit":         "sveltekit",
    "sveltekit-app": "sveltekit",
    "react-vite":  "vite-react",
    "vue-vite":    "vite-vue",
    "svelte-vite": "vite-svelte",
    "solidjs":     "solid",
    "solid.js":    "solid",
}


def _resolve_stack(stack: str) -> tuple[str, dict | None]:
    """Map a user-supplied stack id to a canonical (id, spec) pair.

    Returns ``(canonical_id, spec_dict)`` if known, ``(stack, None)`` if not.
    Tries direct lookup, ``vite-`` prefix strip, the synonym table, and a
    last-ditch alphanumeric-only retry.
    """
    if not isinstance(stack, str):
        return stack, None
    raw = stack.strip().lower()
    if raw in _STACKS:
        return raw, _STACKS[raw]

    # Strip a leading ``vite-`` only when the unprefixed id is itself a
    # built-in alias (so ``vite-three`` → ``three``, but ``vite-vue``
    # stays as ``vite-vue`` because it's already in _STACKS).
    if raw.startswith("vite-"):
        bare = raw[5:]
        if bare in _STACKS:
            return bare, _STACKS[bare]
        if bare in _SYNONYMS:
            target = _SYNONYMS[bare]
            return target, _STACKS.get(target)

    # Static synonyms
    if raw in _SYNONYMS:
        target = _SYNONYMS[raw]
        return target, _STACKS.get(target)

    # Last-ditch: drop ``.``, ``_`` etc and retry
    cleaned = "".join(c for c in raw if c.isalnum() or c == "-")
    if cleaned and cleaned != raw:
        if cleaned in _STACKS:
            return cleaned, _STACKS[cleaned]
        if cleaned in _SYNONYMS:
            target = _SYNONYMS[cleaned]
            return target, _STACKS.get(target)

    return stack, None


def _suggest_stacks(stack: str, n: int = 5) -> list[str]:
    """Return up to ``n`` catalogue ids closest to ``stack`` (Levenshtein-ish)."""
    import difflib
    return difflib.get_close_matches(
        stack.lower(), list(_STACKS.keys()) + list(_SYNONYMS.keys()),
        n=n, cutoff=0.5,
    )


# ── Built-in template content ─────────────────────────────────────────────


def _write_vanilla(target: Path, name: str) -> list[str]:
    """Write a polished single-page vanilla HTML/CSS/JS starter."""
    files = {
        "index.html": _VANILLA_HTML.format(name=name),
        "styles.css": _VANILLA_CSS,
        "main.js":    _VANILLA_JS,
        "README.md":  _VANILLA_README.format(name=name),
        ".gitignore": "node_modules/\n.DS_Store\n*.log\ndist/\n",
    }
    return _materialise(target, files)


def _write_static_site(target: Path, name: str) -> list[str]:
    """Multi-page static site starter — index, about, contact + shared CSS."""
    files = {
        "index.html":   _STATIC_INDEX_HTML.format(name=name),
        "about.html":   _STATIC_ABOUT_HTML.format(name=name),
        "contact.html": _STATIC_CONTACT_HTML.format(name=name),
        "styles.css":   _STATIC_CSS,
        "main.js":      "// Shared JS goes here.\nconsole.log('site loaded');\n",
        "README.md":    _STATIC_README.format(name=name),
        ".gitignore":   "node_modules/\n.DS_Store\n*.log\n",
    }
    return _materialise(target, files)


def _materialise(target: Path, files: dict[str, str]) -> list[str]:
    written: list[str] = []
    for relpath, body in files.items():
        path = target / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        written.append(str(path))
    return written


# ── Subprocess helpers ────────────────────────────────────────────────────


async def _run(cmd: str, cwd: Path,
                timeout: float = 120.0) -> tuple[int, str]:
    """Run a scaffolder shell command, returning (returncode, combined_output).

    Critical safety details for npm-create-style scaffolders:

    - **stdin closed**: many ``create-*`` packages prompt interactively
      (Vite 6+ asks "Use rolldown-vite?", Astro asks for git init, etc.).
      Without an explicit ``stdin=DEVNULL`` the subprocess waits FOREVER
      on a prompt that has nowhere to come from. We hard-close it.
    - **Non-interactive env vars**: ``CI=1`` / ``npm_config_yes=true`` so
      that scaffolders fall back to defaults instead of prompts when they
      check for a TTY.
    - **Timeout**: bounded at ``timeout`` seconds (default 120). On
      timeout the process is killed and the partial output returned with
      a synthetic ``[scaffold timed out after Ns]`` marker so the caller
      can surface it cleanly instead of hanging the user's CLI.
    """
    env = {
        # Inherit the user's PATH etc. then overlay non-interactive flags.
        **__import__("os").environ,
        "CI":              "1",
        "npm_config_yes":  "true",
        "ADBLOCK":         "1",         # silence sponsorship banners
    }
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(cwd),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
    except NotImplementedError:
        # Selector loop fallback: run synchronously in a thread.
        return await asyncio.to_thread(_run_sync, cmd, cwd, timeout)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        with __import__("contextlib").suppress(Exception):
            proc.kill()
        partial = b""
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
            partial = out or b""
        except Exception:
            pass
        return -1, (partial.decode(errors="replace")
                    + f"\n[scaffold timed out after {timeout:.0f}s — process killed]\n")
    return proc.returncode or 0, (out or b"").decode(errors="replace")


def _run_sync(cmd: str, cwd: Path, timeout: float = 120.0) -> tuple[int, str]:
    """Threaded fallback for ``_run`` (used on Selector event loops).

    ``subprocess.run(timeout=…, shell=True)`` doesn't reliably kill child
    processes on Windows — when the shell spawns a child that holds the
    pipe handles, ``run`` blocks on ``communicate()`` even after the
    timeout fires. We use explicit ``Popen`` + ``taskkill /T /F`` (Win)
    or ``killpg`` (POSIX) so the entire process tree dies on timeout.
    """
    import os as _os
    import sys as _sys

    env = {**_os.environ, "CI": "1", "npm_config_yes": "true", "ADBLOCK": "1"}
    creationflags = 0
    preexec_fn = None
    if _sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP lets us send CTRL_BREAK / taskkill /T to
        # the entire group reliably.
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        # Put the shell in its own process group so killpg reaches all
        # descendants.
        preexec_fn = _os.setsid  # type: ignore[assignment,attr-defined]

    try:
        popen = subprocess.Popen(
            cmd, cwd=str(cwd), shell=True,  # nosec B602 — scaffolder commands
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            env=env,
            creationflags=creationflags,
            preexec_fn=preexec_fn,
        )
    except Exception as exc:
        return -1, f"[failed to spawn: {type(exc).__name__}: {exc}]"

    try:
        out, _ = popen.communicate(timeout=timeout)
        return popen.returncode or 0, out or ""
    except subprocess.TimeoutExpired:
        # Reliably tear down the whole process tree.
        if _sys.platform == "win32":
            with __import__("contextlib").suppress(Exception):
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(popen.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
        else:
            with __import__("contextlib").suppress(Exception):
                # POSIX-only — mypy on Windows doesn't see these attrs.
                _os.killpg(_os.getpgid(popen.pid), 9)  # type: ignore[attr-defined]
        # Drain any partial output that may have made it into the pipe
        # before the process died. Use a short, hard timeout — if the
        # tree didn't die, we've at least guaranteed our return.
        partial = ""
        try:
            partial, _ = popen.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            with __import__("contextlib").suppress(Exception):
                popen.kill()
        return -1, (partial or "") + f"\n[scaffold timed out after {timeout:.0f}s — process tree killed]\n"


def _which(tool: str) -> str | None:
    return shutil.which(tool)


# ── Tool entry point ──────────────────────────────────────────────────────


async def _scaffold_web_app(
    stack: str | None = None,
    name: str | None = None,
    target_dir: str | None = None,
    install: bool = False,
    package_manager: str = "npm",
    **_kw,
) -> dict[str, Any]:
    # Tolerate alias keywords the LLM sometimes uses instead of the
    # documented names ("template" for stack, "project_name" for name)
    # so a small spec mismatch doesn't crash the run.
    stack = stack or _kw.get("template")
    name = name or _kw.get("project_name") or _kw.get("project")

    if not isinstance(stack, str) or not stack.strip():
        return {"error": "stack must be a non-empty string (e.g. 'vite-vue', 'three', 'vanilla')"}
    if not isinstance(name, str) or not name.strip():
        return {"error": "name must be a non-empty string (project folder name)"}

    safe_name = "".join(c if (c.isalnum() or c in "-_") else "-" for c in name.strip())
    # Require at least one alphanumeric — pure-dash names like "---" come
    # from inputs that were entirely punctuation, which we don't treat as
    # a valid project name.
    if not any(c.isalnum() for c in safe_name):
        return {"error": f"name {name!r} contained no alphanumerics"}

    parent = Path(target_dir).resolve() if target_dir else Path.cwd()
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    project = parent / safe_name
    if project.exists():
        return {
            "error":   "target_exists",
            "project": str(project),
            "hint":    "Pick a different name or remove the existing folder.",
        }

    canonical, spec = _resolve_stack(stack)
    kind = spec["kind"] if spec else "fallback"
    # Track whether we rewrote the user's stack id so the result tells the
    # agent what actually got used. Helps it learn the canonical form.
    resolved_from = stack if canonical != stack.strip().lower() else None

    # ── 1. Built-in templates (instant) ──────────────────────────────
    if kind == "builtin":
        assert spec is not None  # kind='builtin' implies spec was found
        project.mkdir(parents=True)
        template = spec["template"]
        if template == "vanilla":
            written = _write_vanilla(project, safe_name)
        elif template == "static-site":
            written = _write_static_site(project, safe_name)
        else:
            return {"error": f"unknown builtin template: {template!r}"}
        return {
            "ok":            True,
            "stack":         canonical,
            "resolved_from": resolved_from,
            "kind":          "builtin",
            "project":       str(project),
            "files":         written,
            "command":       None,
            "next_step": (
                f'live_server(directory="{project.as_posix()}")  '
                "to serve it (no build needed)."
            ),
        }

    # ── 2. Network-backed scaffolders ────────────────────────────────
    if _which("npm") is None and _which("npx") is None:
        return {
            "error":     "npm_not_found",
            "hint":      (
                "npm / npx not found in PATH. Install Node.js first via "
                'app_open(target="https://nodejs.org/en/download").'
            ),
            "stack":     stack,
        }

    if kind == "vite":
        assert spec is not None  # kind='vite' implies spec was found
        template = spec["vite_template"]
        cmd = (
            f"npm create vite@latest {safe_name} -- "
            f"--template {template} --no-rolldown"
        )
        # Some Vite versions don't recognise --no-rolldown; strip if it errors.
        rc, log = await _run(cmd, parent)
        if rc != 0 and "--no-rolldown" in log:
            cmd = f"npm create vite@latest {safe_name} -- --template {template}"
            rc, log = await _run(cmd, parent)
    elif kind == "cmd":
        assert spec is not None  # kind='cmd' implies spec was found
        cmd = spec["cmd_template"].format(name=safe_name)
        rc, log = await _run(cmd, parent)
    else:
        # Unknown stack — best-effort: try npm create <stack>@latest.
        # Surface suggestions UP-FRONT so the agent can retry with a known
        # id rather than burn 20+s on a 404.
        suggestions = _suggest_stacks(stack)
        cmd = f"npm create -y {stack}@latest {safe_name}"
        rc, log = await _run(cmd, parent)
        if rc != 0 or not project.exists():
            return {
                "error":       "unknown_stack",
                "stack":       stack,
                "command":     cmd,
                "returncode":  rc,
                "log_tail":    (log[-1500:] if log else ""),
                "suggestions": suggestions,
                "hint": (
                    f"`{stack}` isn't a known stack id and `npm create "
                    f"{stack}@latest` failed. Try one of these instead "
                    f"(closest matches): {suggestions or list_stacks()[:8]}. "
                    "Re-call scaffold_web_app with the correct id; do NOT "
                    "report defeat to the user — pick the closest match."
                ),
            }

    if rc != 0 or not project.exists():
        return {
            "error":         "scaffolder_failed",
            "stack":         stack,
            "command":       cmd,
            "returncode":    rc,
            "log_tail":      log[-2500:] if log else "",
            "hint": (
                "Show the user a copy-paste fix for the command. Common "
                "causes: outdated npm cache (`npm cache clean --force`), "
                "wrong stack id (see scaffold_web_app's stacks[] for valid "
                "ids), or a network error."
            ),
        }

    # ── 3. Optional npm install + extra packages ─────────────────────
    pkg = package_manager if package_manager in ("npm", "pnpm", "yarn", "bun") else "npm"
    extra = (spec or {}).get("extra_packages") or []
    install_log = ""
    if install or extra:
        install_cmd = f"{pkg} install"
        rc_i, log_i = await _run(install_cmd, project)
        install_log += f"$ {install_cmd}\n{log_i[-1500:]}\n"
        if rc_i != 0:
            return {
                "ok":          False,
                "stack":       stack,
                "project":     str(project),
                "command":     cmd,
                "error":       "install_failed",
                "log_tail":    log_i[-2500:],
                "hint":        f"Project scaffolded but {install_cmd} failed.",
            }
        if extra:
            add_cmd = f"{pkg} install " + " ".join(extra)
            rc_e, log_e = await _run(add_cmd, project)
            install_log += f"$ {add_cmd}\n{log_e[-1500:]}\n"

    return {
        "ok":              True,
        "stack":           canonical,
        "resolved_from":   resolved_from,
        "kind":            kind,
        "project":         str(project),
        "command":         cmd,
        "package_manager": pkg,
        "installed":       bool(install or extra),
        "install_log":     install_log[-2000:] if install_log else None,
        "next_step":       _next_step(kind, pkg, project),
    }


def _next_step(kind: str, pkg: str, project: Path) -> str:
    if kind == "vite":
        return (
            f"cd {project} && {pkg} install && {pkg} run dev  "
            "— or call shell_exec to start the dev server in the workspace."
        )
    if kind == "cmd":
        return (
            f"cd {project} && {pkg} install && {pkg} run dev  "
            "(check the project's README for the exact dev script)."
        )
    return f"Open {project} and read the README for next steps."


# ── ToolDefinition ────────────────────────────────────────────────────────


SCAFFOLD_WEB_APP_TOOL = ToolDefinition(
    name="scaffold_web_app",
    description=(
        "Scaffold a new browser-based web app project. Supports any stack: "
        "built-in instant templates (vanilla, static-site) and 30+ npm-create "
        "stacks (vite-vue, vite-react, vite-svelte, vite-solid, vite-lit, "
        "next, nuxt, astro, sveltekit, remix, three, p5, phaser, …). "
        "Unknown stack ids fall through to `npm create <stack>@latest`. "
        "Returns the project path + the suggested next command "
        "(usually live_server or `npm run dev`). Does NOT auto-start the "
        "dev server — chain live_server / shell_exec yourself when ready."
    ),
    parameters={
        "type": "object",
        "properties": {
            "stack": {
                "type": "string",
                "description": (
                    "Stack id. Common: 'vanilla', 'static-site', 'vite-vue', "
                    "'vite-react', 'vite-svelte', 'vite-solid', 'vite-lit', "
                    "'vite-vanilla-ts', 'vue', 'react', 'svelte', 'next', "
                    "'nuxt', 'astro', 'sveltekit', 'remix', 'three', 'p5', "
                    "'phaser'. Any other id is passed to `npm create <id>@latest`."
                ),
            },
            "name": {
                "type": "string",
                "description": "Project folder name (alphanum, dashes, underscores only).",
            },
            "target_dir": {
                "type": "string",
                "description": "Parent directory to scaffold into. Defaults to CWD.",
            },
            "install": {
                "type": "boolean",
                "description": "Run `<pkg> install` after scaffold. Default false (the agent should do it explicitly).",
            },
            "package_manager": {
                "type": "string",
                "description": "Package manager for install: npm | pnpm | yarn | bun. Default npm.",
            },
        },
        "required": ["stack", "name"],
    },
    handler=_scaffold_web_app,
    requires_approval=True,
    approval_message="Scaffold a new web-app project (creates a directory and may run npm)",
    approval_type="confirm",
)


# ── Built-in template content ─────────────────────────────────────────────
# Kept at the bottom so the file reads top-down. Tweaks here ship to every
# new ``vanilla`` / ``static-site`` scaffold.

_VANILLA_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{name}</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <main class="page">
    <header class="hero">
      <h1>{name}</h1>
      <p class="lede">Built with vanilla HTML, CSS, and JS.</p>
    </header>

    <section class="card">
      <h2>Get started</h2>
      <p>Edit <code>main.js</code>, <code>styles.css</code>, or this file.
         The dev server reloads on change.</p>
      <button id="ping" type="button">Click me</button>
      <p id="status" class="status"></p>
    </section>
  </main>

  <script src="main.js" type="module"></script>
</body>
</html>
"""

_VANILLA_CSS = """:root {
  --bg:        #0b0b12;
  --surface:   #14141d;
  --surface-2: #1c1c28;
  --border:    rgba(255, 255, 255, 0.08);
  --accent:    #9d7fff;
  --text-1:    #ededf2;
  --text-2:    #8888a2;
  --radius:    12px;
  --font:      ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  min-height: 100vh;
  font-family: var(--font);
  background: var(--bg);
  color: var(--text-1);
  display: grid;
  place-items: center;
}

.page {
  width: min(720px, 92vw);
  padding: 64px 0;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.hero h1 {
  margin: 0;
  font-size: clamp(28px, 5vw, 48px);
  letter-spacing: -0.02em;
}

.lede {
  margin: 8px 0 0;
  color: var(--text-2);
  font-size: 16px;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 28px;
}

.card h2 {
  margin: 0 0 8px;
  font-size: 18px;
}

.card p {
  margin: 0 0 16px;
  color: var(--text-2);
  line-height: 1.5;
}

code {
  font-family: ui-monospace, "JetBrains Mono", Consolas, monospace;
  background: var(--surface-2);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}

button {
  font: inherit;
  font-size: 14px;
  font-weight: 500;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: 8px;
  padding: 9px 18px;
  cursor: pointer;
  transition: transform 120ms, filter 120ms;
}
button:hover  { filter: brightness(1.1); }
button:active { transform: translateY(1px); }

.status {
  margin-top: 12px !important;
  font-size: 13px;
  min-height: 1.5em;
}
"""

_VANILLA_JS = """// Entry point. Wire DOM events here.

const button = document.querySelector('#ping');
const status = document.querySelector('#status');

let count = 0;
button?.addEventListener('click', () => {
  count += 1;
  status.textContent = `Clicked ${count} time${count === 1 ? '' : 's'}.`;
});

console.log('app loaded');
"""

_VANILLA_README = """# {name}

A vanilla HTML/CSS/JS starter — no build step, no dependencies.

## Run

```
# In Chika, just call:
live_server(directory=".")

# Or with any local static server:
python -m http.server 8000
npx serve .
```

Then open http://localhost:8000.

## Files

- `index.html` — markup
- `styles.css` — styles (CSS custom properties for theming)
- `main.js`    — JS entry, loaded as an ES module
"""

_STATIC_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{name} — Home</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <nav><a href="index.html">Home</a> <a href="about.html">About</a> <a href="contact.html">Contact</a></nav>
  <main>
    <h1>{name}</h1>
    <p>Static-site starter. Three pages, shared stylesheet.</p>
  </main>
  <script src="main.js" type="module"></script>
</body>
</html>
"""

_STATIC_ABOUT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{name} — About</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <nav><a href="index.html">Home</a> <a href="about.html">About</a> <a href="contact.html">Contact</a></nav>
  <main>
    <h1>About</h1>
    <p>Replace this with the project's story.</p>
  </main>
  <script src="main.js" type="module"></script>
</body>
</html>
"""

_STATIC_CONTACT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{name} — Contact</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <nav><a href="index.html">Home</a> <a href="about.html">About</a> <a href="contact.html">Contact</a></nav>
  <main>
    <h1>Contact</h1>
    <p>hello@example.com</p>
  </main>
  <script src="main.js" type="module"></script>
</body>
</html>
"""

_STATIC_CSS = """:root {
  --accent: #6c63ff;
  --bg:     #f7f7fb;
  --text:   #1a1a2e;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: ui-sans-serif, system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
}
nav {
  display: flex;
  gap: 16px;
  padding: 16px 24px;
  border-bottom: 1px solid #ddd;
  background: white;
}
nav a {
  color: var(--text);
  text-decoration: none;
}
nav a:hover { color: var(--accent); }
main {
  max-width: 720px;
  margin: 0 auto;
  padding: 48px 24px;
}
h1 { letter-spacing: -0.02em; }
"""

_STATIC_README = """# {name}

A static multi-page starter. Three pages share one stylesheet.

## Run

```
live_server(directory=".")
```

Or:

```
python -m http.server 8000
npx serve .
```
"""

# Re-export the catalogue so tests / other callers can introspect.
__all__ = [
    "SCAFFOLD_WEB_APP_TOOL",
    "list_stacks",
    "_STACKS",
]
