"""CLI entry point — interactive REPL with a Claude Code-style UI.

Layout:

  ╭─ chika v2.0.0 ─ provider · model ───────────────────────────╮
  │   the agentic AI assistant.                                  │
  │   /help for commands · /quit to exit                         │
  ╰──────────────────────────────────────────────────────────────╯

  > what files changed today?
  ⏺ shell_exec  command="git log --since='24 hours ago' --name-only"
    ⎿ chika/_cli.py
       chika/core/engine.py …

  Today you touched 4 files…

  · provider anthropic · model claude-sonnet-4-6 · profile default · supervised

The renderer ( :mod:`chika._cli.renderer`) translates engine events into rich
panels and inline tool blocks. Slash commands ( :mod:`chika._cli.commands`)
edit settings, .env, and runtime state without leaving the CLI.

The REPL gracefully degrades when ``rich`` or ``prompt_toolkit`` are missing —
it falls back to the legacy plain printer in :mod:`chika._cli.fallback`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def _ensure_root_on_path() -> None:
    """Add the project root to sys.path so api.* imports resolve."""
    root = Path(__file__).resolve().parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


# ── Optional-dependency probe ─────────────────────────────────────────────


def _have_rich() -> bool:
    try:
        import rich  # noqa: F401
        return True
    except Exception:
        return False


def _have_prompt_toolkit() -> bool:
    try:
        import prompt_toolkit  # noqa: F401
        return True
    except Exception:
        return False


# ── Public entry point ────────────────────────────────────────────────────


def _enable_utf8_stdout() -> None:
    """Best-effort: switch stdout/stderr to UTF-8 so brand glyphs render on Windows."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass


def cli(argv: list[str] | None = None) -> None:
    """Entry point for the ``chika`` console script.

    Without args (or with unrecognised args) drops into the REPL.
    Recognised one-shot subcommands:

        chika install-extension     — install the browser extension and
                                      open chrome://extensions/, then exit
        chika update                — pull the latest Chika and refresh
                                      the editable install
        chika update --check        — report whether an update is available
                                      without applying it
        chika doctor                — verify the install is healthy and
                                      exit non-zero on broken environments
    """
    _enable_utf8_stdout()
    _ensure_root_on_path()

    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("install-extension", "install-ext"):
        _run_install_extension()
        return
    if args and args[0] == "update":
        _run_update_subcommand(args[1:])
        return
    if args and args[0] == "doctor":
        _run_doctor_subcommand()
        return
    if args and args[0] == "setup":
        _run_setup_subcommand(args[1:])
        return
    if args and args[0] == "uninstall":
        _run_uninstall_subcommand(args[1:])
        return
    if args and args[0] == "replay":
        from chika._cli import replay as replay_mod
        sys.exit(replay_mod.main(args[1:]))
    if args and args[0] == "spotify":
        from chika._cli import spotify as spotify_cmd
        sys.exit(spotify_cmd.main(args[1:]))

    if not _have_rich():
        from chika._cli.fallback import run_plain
        print(
            "chika: install 'rich' and 'prompt_toolkit' for the full TUI "
            "(`pip install rich prompt_toolkit`). Falling back to plain mode.\n"
        )
        asyncio.run(run_plain())
        return

    asyncio.run(_run_rich())


def _run_install_extension() -> None:
    """One-shot ``chika install-extension`` handler.

    Renders the install panel via rich when available; falls back to
    plain ``print`` so users without rich still get clear next-steps.
    """
    from chika._cli.install_extension import (
        CHROME_EXTENSIONS_URL,
        install_extension,
    )

    if _have_rich():
        from rich.console import Console
        console = Console(highlight=False, soft_wrap=True)
        try:
            install_extension(console=console)
        except FileNotFoundError as exc:
            console.print(f"chika: {exc}")
            sys.exit(1)
        return

    try:
        dest = install_extension(console=None)
    except FileNotFoundError as exc:
        print(f"chika: {exc}")
        sys.exit(1)
        return
    print(f"chika: extension installed to {dest}")
    print(f"chika: open {CHROME_EXTENSIONS_URL}, toggle Developer mode,")
    print("       click 'Load unpacked', then select the folder above.")


def _run_update_subcommand(args: list[str]) -> None:
    """``chika update [--check]`` handler."""
    from chika._cli import update as upd

    check_only = bool(args) and args[0] in ("--check", "-c", "check")

    if _have_rich():
        from rich.console import Console
        from rich.text import Text

        console = Console(highlight=False, soft_wrap=True)
        if check_only:
            info = upd.check_for_updates()
            cur, lat = info.current, info.latest
            if info.available:
                line = Text("update available", style="bold")
                line.append(f": {cur} → {lat}")
                if not info.ci_green:
                    line.append("  (ci not green — auto-update will skip)")
                console.print(line)
                return
            if info.reason == "up_to_date":
                console.print(Text(f"already up to date  ({cur})"))
                return
            console.print(Text(f"couldn't determine update status ({info.reason})"))
            return
        result = upd.update_chika(console=console)
        if not result.success:
            sys.exit(1)
        return

    # Plain-mode fallback (no rich)
    if check_only:
        info = upd.check_for_updates()
        if info.available:
            print(f"chika: update available {info.current} → {info.latest}")
            if not info.ci_green:
                print("chika: ci not green — auto-update would skip")
        elif info.reason == "up_to_date":
            print(f"chika: already up to date ({info.current})")
        else:
            print(f"chika: couldn't determine update status ({info.reason})")
        return
    result = upd.update_chika(console=None)
    print(f"chika: {result.message}")
    if result.restart_required:
        print("chika: restart Chika to load the new code.")
    if not result.success:
        sys.exit(1)


def _run_setup_subcommand(args: list[str]) -> None:
    """``chika setup [--force]`` argv handler."""
    from chika._cli.setup import run_setup
    force = ("--force" in args or "-f" in args)
    if _have_rich():
        from rich.console import Console
        console = Console(highlight=False, soft_wrap=True)
        result = run_setup(console=console, force=force)
    else:
        result = run_setup(console=None, force=force)
        print(f"chika: {result.message}")
    if not result.success:
        sys.exit(1)


def _run_uninstall_subcommand(args: list[str]) -> None:
    """``chika uninstall [--yes] [--remove-data]`` argv handler."""
    from chika._cli.uninstall import uninstall_chika
    yes = ("--yes" in args or "-y" in args)
    remove_data = ("--remove-data" in args)
    if _have_rich():
        from rich.console import Console
        console = Console(highlight=False, soft_wrap=True)
        result = uninstall_chika(console=console, yes=yes, remove_data=remove_data)
    else:
        result = uninstall_chika(console=None, yes=yes, remove_data=remove_data)
        print(f"chika: {result.message}")
    if not result.success:
        sys.exit(1)


def _start_auto_update_thread(console) -> None:
    """Kick off a background thread that runs the upstream update check.

    Errors are swallowed at the boundary — a broken update check must
    never crash the REPL. The check itself respects an hour-long
    throttle (see ``chika._cli.update``) so back-to-back chika
    invocations don't burn through GitHub's unauthed rate limit.
    """
    import threading

    def _worker():
        try:
            from chika._cli.update import auto_update_on_startup
            auto_update_on_startup(console=console)
        except Exception:
            pass

    threading.Thread(
        target=_worker, name="chika-auto-update", daemon=True,
    ).start()


def _run_doctor_subcommand() -> None:
    """``chika doctor`` handler — exit non-zero on errors."""
    from chika._cli.doctor import run_doctor

    if _have_rich():
        from rich.console import Console
        console = Console(highlight=False, soft_wrap=True)
        report = run_doctor(console=console)
    else:
        report = run_doctor(console=None)
        for c in report.checks:
            glyph = {"ok": "[ok]", "warn": "[warn]", "error": "[error]"}[c.severity]
            print(f"{glyph} {c.name}  {c.detail}")
    sys.exit(report.exit_code)


# ── Rich REPL implementation ──────────────────────────────────────────────


async def _run_rich() -> None:
    # Imports are local so the module loads even when deps are missing.
    from rich.console import Console
    from rich.text import Text

    import api.settings_store as settings_store
    import config
    from api.session_manager import session_manager
    from chika._cli import pet_speech, pets
    from chika._cli.commands import CommandContext, dispatch
    from chika._cli.renderer import (
        THEME,
        Renderer,
        render_banner,
        render_pet,
        render_status_line,
    )

    console = Console(highlight=False, soft_wrap=True)
    cfg = config.get_provider_config()

    # Banner up-front so the user sees Chika's identity before they pick a
    # profile (mirrors the frontend / extension where the brand renders
    # before the gate, not after).
    render_banner(console, version=_chika_version(), provider=cfg.provider, model=cfg.model)

    # First-run nudge — when ``.env`` is missing or empty, surface a
    # one-line "run /setup" hint right after the banner. Doesn't block,
    # doesn't auto-launch the wizard (a user might be CI-piping into
    # the REPL and not want a blocking prompt). Reassures the user
    # that settings can be changed later.
    try:
        from chika._cli.setup import needs_first_run_setup, render_first_run_nudge
        if needs_first_run_setup():
            render_first_run_nudge(console)
    except Exception:
        pass

    # Fire-and-forget background update check. Never blocks startup —
    # if the network is down, GitHub is rate-limiting, or anything
    # else fails, the function logs the reason in update_state.json
    # and we move on. When auto_update is "on" and upstream CI is
    # green it silently applies the update and prints a single-line
    # notice; the user just needs to restart to pick up the new code.
    _start_auto_update_thread(console)

    # Profile gate — never default-pick. Forces the user to identify
    # themselves and authenticate when their profile has a password.
    # When stdin isn't a TTY (piped tests, e2e harnesses) we fall back
    # to whichever profile the runtime would have picked anyway, since
    # there's no human to prompt.
    engine = session_manager.get_or_create("cli")
    if sys.stdin.isatty() and sys.stdout.isatty():
        from chika._cli.profile_picker import select_profile
        chosen = select_profile(
            console,
            session_manager._profile_manager,
            accent=THEME.accent,
        )
        engine.switch_profile(chosen)

        # Wire interactive handlers so the CLI gets the same approval +
        # question prompts the frontend modal does. Without this:
        #   - the plan-approval gate silently skips (agent runs the plan
        #     before the user has a chance to weigh in)
        #   - workspace-scope writes silently auto-grant
        #   - ask_user / question_skill returns ``no_question_handler``
        # The renderer is built below; we hand the handlers a small
        # late-binding proxy so they can pause/resume the Live region
        # at prompt time (otherwise the prompt is invisible behind it).
        _renderer_holder: list = [None]
        from chika._cli.interactive import (
            make_approval_handler,
            make_question_handler,
        )

        class _RendererProxy:
            """Forwards attribute access to the live Renderer once it
            exists. Avoids a circular dependency between Renderer
            construction and the handlers' need for it."""
            def __getattr__(self, name):
                r = _renderer_holder[0]
                return getattr(r, name) if r is not None else None

        _proxy = _RendererProxy()
        engine._workflow_engine.approval_handler = make_approval_handler(
            console, renderer=_proxy,
        )
        engine._workflow_engine.question_handler = make_question_handler(
            console, renderer=_proxy,
        )
        # Workspace-scope tool gate uses the same approval handler — wire
        # the live policy + handler into the file_tools module-level
        # context vars so file_write / file_replace / file_append /
        # file_edit_lines pick them up.
        try:
            from chika.core.workspace_policy import WorkspacePolicy
            from chika.tools import file_tools as _ft
            if engine._active_profile:
                _policy = WorkspacePolicy(
                    workspace=str(engine._active_profile.workspace),
                )
                _ft.configure_workspace_policy(
                    _policy, engine._workflow_engine.approval_handler,
                )
        except Exception:
            pass

    # Active pet greeting (static idle frame above the prompt)
    pet = pets.get(engine._active_profile.pet_id if engine._active_profile else None)
    render_pet(console, pet, state="idle", speech=_greet_speech(pet))

    ctx = CommandContext(console=console, engine=engine)

    # Plan provider — the renderer calls this on every paint to fetch the
    # current $plan. Tasks tick / appear / disappear live as the agent
    # calls plan_update / plan_add / plan_remove.
    def _read_plan() -> dict | None:
        var = engine._vars.get("plan")
        if var is None:
            return None
        return var.value if isinstance(var.value, dict) else None

    # Renderer owns the pet during turns — animator thread cycles frames +
    # speech bubbles in lockstep with engine events.
    renderer = Renderer(
        console=console,
        show_thinking=True,
        pet=pet,
        plan_provider=_read_plan,
    )
    # Patch the late-binding handler proxy so approval / question
    # prompts can pause the Live region cleanly. ``_renderer_holder``
    # only exists when the interactive (TTY) branch above ran; the
    # piped-stdin branch skips this whole block.
    try:
        _renderer_holder[0] = renderer  # type: ignore[name-defined]
    except NameError:
        pass

    # Build the input session (prompt_toolkit if available, else plain input).
    read_input = _build_input_reader(console)

    while True:
        # Sync show_thinking with the live context flag.
        renderer.show_thinking = ctx.show_thinking

        # Status line — printed before each prompt.
        cfg = config.get_provider_config()
        p = engine._active_profile
        autonomy = _safe_get_setting("autonomy", "supervised")
        render_status_line(
            console,
            **{
                "provider": cfg.provider,
                "model":    cfg.model,
                "profile":  p.name if p else "default",
                "mode":     autonomy,
            },
        )

        try:
            user_input = await read_input()
        except (KeyboardInterrupt, EOFError):
            console.print(Text("\n  · bye", style=THEME.muted))
            break

        if user_input is None:
            break
        # Strip UTF-8 BOM (﻿) and surrounding whitespace. Piped input
        # on Windows sometimes prefixes the first line with a BOM.
        text = user_input.lstrip("﻿").strip()
        if not text:
            continue

        # Slash command?
        if text.startswith("/"):
            handled = dispatch(ctx, text)
            if ctx.exit_requested:
                console.print(Text("  · bye", style=THEME.muted))
                break
            if ctx.clear_requested:
                console.clear()
                ctx.clear_requested = False
                render_banner(
                    console,
                    version=_chika_version(),
                    provider=cfg.provider,
                    model=cfg.model,
                )
            if handled:
                continue

        # Pet may have been swapped between turns (via /pet or the WS).
        # Pick up the current selection from the active profile each turn.
        renderer.set_pet(pets.get(
            engine._active_profile.pet_id if engine._active_profile else None
        ))

        # Normal chat turn — stream events through the renderer. The
        # renderer owns pet animation; we just track the final state so the
        # animator-driven panel finishes on the right frame.
        renderer.start_turn()
        # Kick off a fire-and-forget LLM call for context-aware verbs
        # in the inline state indicator. Lands in the renderer once it
        # returns; falls back to static verbs if it fails or is off.
        renderer.prime_state_verbs(engine, text)
        pet_state = "working"
        turn_events: list[dict] = []
        try:
            async for event in engine.chat(text):
                etype = event.get("type", "")
                if etype.startswith("_"):
                    continue
                turn_events.append(event)
                if etype == "done":
                    break
                if etype == "error":
                    pet_state = "sad"
                elif etype == "workflow_done" and pet_state != "sad":
                    pet_state = "celebrate"
                renderer.handle(event)
        except KeyboardInterrupt:
            engine.cancel()
            renderer.update_pet_state("sad", speech="stopped.")
            console.print(Text("  · interrupted", style=THEME.warn))
            pet_state = "sad"
        except Exception as exc:
            renderer.update_pet_state("sad", speech="something broke")
            console.print(Text(f"  · error: {exc}", style=THEME.error))
            pet_state = "sad"
        finally:
            renderer.end_turn()

        # Optional LLM-generated quip — runs in parallel and prints a
        # standalone pet panel below the answer when it returns. Static
        # personality bubbles already fire LIVE during the turn from the
        # renderer; this just gives the model the floor for one extra line.
        if settings_store.get("pet_speech", "off") == "on":
            active_pet = renderer.pet
            max_tokens = int(settings_store.get("pet_speech_tokens", 40))

            def _emit(line: str, *, _pet=active_pet, _state=pet_state) -> None:
                if line:
                    render_pet(console, _pet, state=_state, speech=line)

            pet_speech.fire_and_forget(
                engine, active_pet,
                state=pet_state,
                turn_events=turn_events,
                max_tokens=max_tokens,
                on_done=_emit,
            )


# ── Helpers ────────────────────────────────────────────────────────────────


def _chika_version() -> str:
    try:
        from importlib.metadata import version
        return version("chika")
    except Exception:
        return "2.0.0"


def _greet_speech(pet) -> str:
    """Pick a static greeting line for the pet's startup banner."""
    try:
        opts = pet.quotes.get("greet") or pet.quotes.get("idle") or []
    except Exception:
        opts = []
    return opts[0] if opts else ""


def _safe_get_setting(key: str, default: str) -> str:
    try:
        import api.settings_store as settings_store
        return settings_store.get(key, default)
    except Exception:
        return default


def _build_input_reader(console):
    """Return an async ``read_input()`` callable.

    Uses ``prompt_toolkit`` when available AND stdin/stdout are real TTYs
    for slash-command autocomplete, multi-line editing, and history. Falls
    back to ``input()`` when piped or in environments without a console
    buffer (CI, IDE consoles, test runs).
    """
    if not _have_prompt_toolkit():
        return _build_plain_input_reader(console)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return _build_plain_input_reader(console)

    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style

    from chika._cli.commands import all_command_names
    from chika._cli.renderer import THEME

    history_path = Path.home() / ".chika_cli_history"
    try:
        history_path.touch(exist_ok=True)
    except Exception:
        history_path = None

    completer = WordCompleter(
        ["/" + name for name in all_command_names()],
        ignore_case=True,
        match_middle=False,
        sentence=False,
        WORD=True,
    )

    style = Style.from_dict({
        "prompt-glyph": THEME.accent,
        "prompt-line":  THEME.text,
    })

    kb = KeyBindings()

    @kb.add("c-c")
    def _ctrl_c(event):  # cancel current line
        event.app.current_buffer.text = ""
        event.app.exit(exception=KeyboardInterrupt)

    session = PromptSession(
        history=FileHistory(str(history_path)) if history_path else None,
        completer=completer,
        complete_while_typing=True,
        enable_history_search=True,
        mouse_support=False,
        key_bindings=kb,
        style=style,
    )

    async def read_input() -> str:
        prompt = FormattedText([
            ("class:prompt-glyph", "› "),
        ])
        return await session.prompt_async(prompt)

    return read_input


def _build_plain_input_reader(console):
    """Plain stdin reader used when prompt_toolkit isn't usable (no TTY,
    not installed, IDE console, etc).

    Uses ``asyncio.to_thread`` around builtin ``input`` so the engine's
    cancel handler can still respond to ctrl+c during a chat turn.
    """
    from chika._cli.renderer import THEME

    async def read_input() -> str:
        prompt = f"\033[1;38;5;141m{THEME.arrow_glyph} \033[0m"
        try:
            return await asyncio.to_thread(input, prompt)
        except EOFError:
            raise

    return read_input
