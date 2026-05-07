"""Slash-command handlers for the CLI.

Each command is a callable taking ``(ctx, args)`` and returning ``True`` to
keep the REPL running or ``False`` to exit. Commands can read and mutate
runtime state through the :class:`CommandContext`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.console import Console
from rich.text import Text

import api.settings_store as settings_store
import config
from chika._cli import env_file, pets
from chika._cli.renderer import THEME, render_json_block, render_kv_table, render_pet

if TYPE_CHECKING:
    from chika.core.engine import ChikaEngine


# ── Context ────────────────────────────────────────────────────────────────


@dataclass
class CommandContext:
    """State shared across slash commands and the main REPL loop."""
    console: Console
    engine: ChikaEngine
    show_thinking: bool = True
    # Set by /quit and /exit so the REPL can break out cleanly.
    exit_requested: bool = False
    # Returned by /clear so the REPL can wipe scrollback.
    clear_requested: bool = False
    # Set by /reset so the REPL knows to wipe history & vars.
    reset_requested: bool = False


CommandFn = Callable[[CommandContext, list[str]], None]


@dataclass
class Command:
    name: str
    summary: str
    handler: CommandFn
    aliases: tuple[str, ...] = ()
    args_hint: str = ""


_COMMANDS: dict[str, Command] = {}


def register(cmd: Command) -> None:
    _COMMANDS[cmd.name] = cmd
    for alias in cmd.aliases:
        _COMMANDS[alias] = cmd


def list_commands() -> list[Command]:
    """Unique command list (skipping aliases) for /help and autocomplete."""
    seen: set[str] = set()
    out: list[Command] = []
    for cmd in _COMMANDS.values():
        if cmd.name in seen:
            continue
        seen.add(cmd.name)
        out.append(cmd)
    return out


def all_command_names() -> list[str]:
    """Every dispatchable name (including aliases) for autocomplete."""
    return sorted(_COMMANDS.keys())


def dispatch(ctx: CommandContext, raw: str) -> bool:
    """Dispatch a slash-command line. Returns True iff a command was handled."""
    if not raw.startswith("/"):
        return False
    parts = raw[1:].strip().split()
    if not parts:
        return False
    name, args = parts[0].lower(), parts[1:]
    cmd = _COMMANDS.get(name)
    if cmd is None:
        ctx.console.print(Text(
            f"unknown command /{name} — try /help",
            style=THEME.warn,
        ))
        return True
    try:
        cmd.handler(ctx, args)
    except Exception as exc:
        ctx.console.print(Text(f"  /{name} failed: {exc}", style=THEME.error))
    return True


# ── /help ─────────────────────────────────────────────────────────────────


def _cmd_help(ctx: CommandContext, _args: list[str]) -> None:
    rows: list[tuple[str, str]] = []
    for cmd in list_commands():
        name = f"/{cmd.name}"
        if cmd.args_hint:
            name += f" {cmd.args_hint}"
        rows.append((name, cmd.summary))
    render_kv_table(ctx.console, "commands", rows)
    ctx.console.print(Text(
        "tip: tab-complete on / · ctrl+c interrupts a turn · ctrl+d exits",
        style=THEME.dim,
    ))


# ── /quit, /exit ──────────────────────────────────────────────────────────


def _cmd_quit(ctx: CommandContext, _args: list[str]) -> None:
    ctx.exit_requested = True


# ── /clear ────────────────────────────────────────────────────────────────


def _cmd_clear(ctx: CommandContext, _args: list[str]) -> None:
    ctx.clear_requested = True


# ── /reset ────────────────────────────────────────────────────────────────


def _cmd_reset(ctx: CommandContext, _args: list[str]) -> None:
    ctx.engine.reset()
    ctx.reset_requested = True
    ctx.console.print(Text("  · session reset (history + variables cleared)",
                           style=THEME.muted))


# ── /settings ─────────────────────────────────────────────────────────────


def _cmd_settings(ctx: CommandContext, _args: list[str]) -> None:
    s = settings_store.all_settings()
    rows = [
        ("autonomy", s.get("autonomy", "supervised")),
    ]
    perms = s.get("tool_permissions", {})
    if perms:
        rows.append(("tool_permissions",
                     ", ".join(f"{k}={v}" for k, v in perms.items())))
    else:
        rows.append(("tool_permissions", "(none — using global default)"))
    render_kv_table(ctx.console, "settings", rows)


# ── /autonomy ─────────────────────────────────────────────────────────────


def _cmd_autonomy(ctx: CommandContext, args: list[str]) -> None:
    if not args:
        cur = settings_store.get("autonomy", "supervised")
        ctx.console.print(Text(f"  autonomy: {cur}", style=THEME.text))
        return
    target = args[0].lower()
    if target not in ("supervised", "autonomous"):
        ctx.console.print(Text(
            "  /autonomy expects 'supervised' or 'autonomous'",
            style=THEME.error,
        ))
        return
    settings_store.update({"autonomy": target})
    ctx.console.print(Text(f"  · autonomy → {target}", style=THEME.success))


# ── /permissions ──────────────────────────────────────────────────────────


def _cmd_permissions(ctx: CommandContext, args: list[str]) -> None:
    cats = settings_store.CATEGORIES
    perms = settings_store.get("tool_permissions", {}) or {}
    autonomy = settings_store.get("autonomy", "supervised")
    default = "skip" if autonomy == "autonomous" else "ask"

    if len(args) >= 2:
        cat, perm = args[0], args[1].lower()
        if cat not in cats:
            ctx.console.print(Text(
                f"  unknown category: {cat}. options: {', '.join(cats)}",
                style=THEME.error,
            ))
            return
        if perm not in ("ask", "skip"):
            ctx.console.print(Text("  permission must be 'ask' or 'skip'",
                                   style=THEME.error))
            return
        settings_store.update({"tool_permissions": {cat: perm}})
        ctx.console.print(Text(f"  · {cat} → {perm}", style=THEME.success))
        return

    rows = [
        (cat, f"{perms.get(cat, default)}  ({label})")
        for cat, label in cats.items()
    ]
    render_kv_table(ctx.console, f"permissions  (default: {default})", rows)
    ctx.console.print(Text(
        "  set with: /permissions <category> ask|skip",
        style=THEME.dim,
    ))


# ── /provider, /model ─────────────────────────────────────────────────────


def _cmd_provider(ctx: CommandContext, args: list[str]) -> None:
    if not args:
        cfg = config.get_provider_config()
        ctx.console.print(Text(f"  provider: {cfg.provider}",
                               style=THEME.text))
        ctx.console.print(Text(f"  model:    {cfg.model}",
                               style=THEME.text))
        ctx.console.print(Text(
            "  change with: /provider <anthropic|openai|azure|ollama>",
            style=THEME.dim,
        ))
        return
    target = args[0].lower()
    valid = {"anthropic", "openai", "azure", "ollama"}
    if target not in valid:
        ctx.console.print(Text(
            f"  unknown provider: {target}. options: {', '.join(sorted(valid))}",
            style=THEME.error,
        ))
        return
    env_file.write_env({"CHIKA_PROVIDER": target})
    # Hot-swap the engine's LLM client so the very next turn uses the
    # new provider — no restart needed. The previous client object
    # stays alive for any in-flight stream until that stream returns.
    try:
        result = ctx.engine.reload_client()
    except RuntimeError as exc:
        ctx.console.print(Text(
            f"  · CHIKA_PROVIDER → {target}  (.env updated)",
            style=THEME.warn,
        ))
        ctx.console.print(Text(f"  ! {exc}", style=THEME.error))
        return
    ctx.console.print(Text(
        f"  ✓ provider switched live → {result['provider']} · {result['model']}",
        style=THEME.success,
    ))


def _cmd_model(ctx: CommandContext, args: list[str]) -> None:
    cfg = config.get_provider_config()
    if not args:
        ctx.console.print(Text(f"  current model: {cfg.model}",
                               style=THEME.text))
        return
    target = args[0]
    key = {
        "anthropic": "ANTHROPIC_MODEL",
        "openai":    "OPENAI_MODEL",
        "azure":     "AZURE_OPENAI_DEPLOYMENT",
        "ollama":    "OLLAMA_MODEL",
    }.get(cfg.provider)
    if key is None:
        ctx.console.print(Text(f"  cannot set model for provider {cfg.provider}",
                               style=THEME.error))
        return
    env_file.write_env({key: target})
    # Hot-swap so the next turn uses the new model. Model-only
    # changes don't strictly need a new SDK client, but reload_client
    # handles both cases uniformly.
    try:
        result = ctx.engine.reload_client()
    except RuntimeError as exc:
        ctx.console.print(Text(
            f"  · {key} → {target}  (.env updated)",
            style=THEME.warn,
        ))
        ctx.console.print(Text(f"  ! {exc}", style=THEME.error))
        return
    ctx.console.print(Text(
        f"  ✓ model switched live → {result['model']}",
        style=THEME.success,
    ))


# ── /env ──────────────────────────────────────────────────────────────────


def _cmd_env(ctx: CommandContext, args: list[str]) -> None:
    # /env                          → list (masked)
    # /env KEY                      → show one (masked)
    # /env KEY=VALUE  or KEY VALUE  → set
    # /env --unset KEY              → delete
    # /env --show-secrets           → list with values revealed
    show_secrets = "--show-secrets" in args
    args = [a for a in args if a != "--show-secrets"]

    if "--unset" in args:
        idx = args.index("--unset")
        if idx + 1 >= len(args):
            ctx.console.print(Text("  /env --unset <KEY>", style=THEME.error))
            return
        key = args[idx + 1]
        env_file.write_env({key: None})
        ctx.console.print(Text(f"  · removed {key} from .env", style=THEME.success))
        return

    if not args:
        rows = env_file.read_env_for_display(mask_secrets=not show_secrets)
        if not rows:
            ctx.console.print(Text("  .env is empty or missing", style=THEME.muted))
            return
        rendered = [
            (k, f"{v}  [secret]" if secret else v) for k, v, secret in rows
        ]
        title = ".env"
        if not show_secrets:
            title += "  (secrets masked — use --show-secrets to reveal)"
        render_kv_table(ctx.console, title, rendered)
        return

    raw = " ".join(args)
    value: str | None
    if "=" in raw:
        key, _, value = raw.partition("=")
    elif len(args) >= 2:
        key, value = args[0], " ".join(args[1:])
    else:
        key = args[0]
        env = env_file.read_env()
        value = env.get(key)
        if value is None:
            ctx.console.print(Text(f"  {key} is not set", style=THEME.muted))
            return
        display = env_file.mask(value) if env_file.is_sensitive(key) else value
        ctx.console.print(Text(f"  {key}={display}", style=THEME.text))
        return

    cleaned_key = key.strip()
    env_file.write_env({cleaned_key: value.strip().strip('"').strip("'")})
    ctx.console.print(Text(f"  · {cleaned_key} updated in .env",
                           style=THEME.success))
    # Provider/model/API-key changes hot-reload live; everything else
    # may still need a restart. Try a reload and surface the result.
    hot_reloadable = {
        "CHIKA_PROVIDER",
        "ANTHROPIC_MODEL", "ANTHROPIC_API_KEY",
        "OPENAI_MODEL", "OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY",
        "AZURE_OPENAI_DEPLOYMENT", "AZURE_API_VERSION",
        "OLLAMA_BASE_URL", "OLLAMA_MODEL",
        "CHIKA_THINKING", "CHIKA_THINKING_BUDGET",
        "CHIKA_AUTONOMY",
    }
    if cleaned_key in hot_reloadable:
        try:
            ctx.engine.reload_client()
            ctx.console.print(Text("  ✓ applied live", style=THEME.success))
        except RuntimeError as exc:
            ctx.console.print(Text(f"  ! {exc}", style=THEME.error))
    else:
        ctx.console.print(Text(
            "  · this key is read at boot — restart for it to take effect.",
            style=THEME.dim,
        ))


# ── /profile, /profiles ───────────────────────────────────────────────────


def _cmd_profile(ctx: CommandContext, args: list[str]) -> None:
    eng = ctx.engine
    if not args:
        p = eng._active_profile
        if p is None:
            ctx.console.print(Text("  no active profile", style=THEME.muted))
            return
        ctx.console.print(Text(f"  profile:   {p.name}", style=THEME.text))
        ctx.console.print(Text(f"  workspace: {p.workspace}", style=THEME.text))
        return

    name = args[0].strip().lower().replace(" ", "_")
    from api.session_manager import session_manager
    pm = session_manager._profile_manager
    if pm.has_password(name):
        ctx.console.print(Text(
            f"  profile {name!r} is password-protected — switch via the web UI",
            style=THEME.warn,
        ))
        return
    profile = pm.get_or_create(name)
    eng.switch_profile(profile)
    ctx.console.print(Text(f"  · profile → {name}", style=THEME.success))


def _cmd_profiles(ctx: CommandContext, _args: list[str]) -> None:
    from api.session_manager import session_manager
    pm = session_manager._profile_manager
    active = ctx.engine._active_profile.name if ctx.engine._active_profile else ""
    rows: list[tuple[str, str]] = []
    for name in pm.list_profiles():
        prof = pm.get(name)
        ws = prof.workspace if prof else ""
        markers: list[str] = []
        if name == active:
            markers.append("active")
        if pm.has_password(name):
            markers.append("password")
        suffix = f"  [{', '.join(markers)}]" if markers else ""
        rows.append((name, f"{ws}{suffix}"))
    render_kv_table(ctx.console, "profiles", rows)


# ── /tools, /skills, /memory, /vars ──────────────────────────────────────


def _cmd_tools(ctx: CommandContext, _args: list[str]) -> None:
    rows = [
        (t.name, t.description.split("\n")[0])
        for t in ctx.engine._tools._tools.values()
    ]
    render_kv_table(ctx.console, f"tools ({len(rows)})", rows)


def _cmd_skills(ctx: CommandContext, _args: list[str]) -> None:
    skills = ctx.engine._skills.list_skills()
    rows = [(s.get("name", "?"), s.get("description", "")) for s in skills]
    render_kv_table(ctx.console, f"skills ({len(rows)})", rows)


def _cmd_vars(ctx: CommandContext, _args: list[str]) -> None:
    vars_ = ctx.engine._vars.all()
    if not vars_:
        ctx.console.print(Text("  no variables set", style=THEME.muted))
        return
    rows: list[tuple[str, str]] = []
    for name, var in vars_.items():
        try:
            val_repr = repr(var.value)
        except Exception:
            val_repr = "<unrepr-able>"
        if len(val_repr) > 100:
            val_repr = val_repr[:100] + "…"
        type_name = type(var.value).__name__
        rows.append((f"${name}", f"({type_name})  {val_repr}"))
    render_kv_table(ctx.console, "variables", rows)


def _cmd_memory(ctx: CommandContext, _args: list[str]) -> None:
    rendered = ctx.engine._memory.render_for_prompt()
    if not rendered:
        ctx.console.print(Text("  memory is empty", style=THEME.muted))
        return
    ctx.console.print(Text(rendered, style=THEME.text))


# ── /thinking ─────────────────────────────────────────────────────────────


def _cmd_thinking(ctx: CommandContext, args: list[str]) -> None:
    if not args:
        ctx.console.print(Text(
            f"  thinking display: {'on' if ctx.show_thinking else 'off'}",
            style=THEME.text,
        ))
        return
    val = args[0].lower()
    if val in ("on", "true", "1"):
        ctx.show_thinking = True
    elif val in ("off", "false", "0"):
        ctx.show_thinking = False
    else:
        ctx.console.print(Text("  /thinking on|off", style=THEME.error))
        return
    ctx.console.print(Text(
        f"  · thinking display → {'on' if ctx.show_thinking else 'off'}",
        style=THEME.success,
    ))


# ── /log ──────────────────────────────────────────────────────────────────


def _cmd_log(ctx: CommandContext, _args: list[str]) -> None:
    from chika.core.logger import LOG_PATH
    ctx.console.print(Text(f"  log: {LOG_PATH}", style=THEME.text))


# ── /status ───────────────────────────────────────────────────────────────


def _cmd_status(ctx: CommandContext, _args: list[str]) -> None:
    cfg = config.get_provider_config()
    eng = ctx.engine
    p = eng._active_profile
    rows: list[tuple[str, str]] = [
        ("provider",   cfg.provider),
        ("model",      cfg.model),
        ("profile",    p.name if p else "default"),
        ("workspace",  p.workspace if p else ""),
        ("session",    eng.session_id or "cli"),
        ("messages",   str(len(eng._history))),
        ("variables",  str(len(eng._vars.all()))),
        ("autonomy",   settings_store.get("autonomy", "supervised")),
        ("thinking",   "on" if ctx.show_thinking else "off"),
    ]
    render_kv_table(ctx.console, "status", rows)


# ── /pet ──────────────────────────────────────────────────────────────────


def _cmd_pet(ctx: CommandContext, args: list[str]) -> None:
    """Show, list, or change the active profile's pet."""
    eng = ctx.engine
    profile = eng._active_profile
    if profile is None:
        ctx.console.print(Text("  no active profile", style=THEME.muted))
        return

    from api.session_manager import session_manager
    pm = session_manager._profile_manager

    # /pet           → show current pet + how to change
    # /pet list      → catalogue of all pets (preview each)
    # /pet <id>      → switch to that pet for this profile
    # /pet none      → clear pet override (use default)

    if not args:
        pet = pets.get(profile.pet_id)
        ctx.console.print(Text(
            f"  active pet: {pet.name}  ({pet.id})",
            style=THEME.text,
        ))
        render_pet(ctx.console, pet, state="idle")
        ctx.console.print(Text(
            "  /pet list — see all pets · /pet <id> — switch",
            style=THEME.dim,
        ))
        return

    sub = args[0].lower()
    if sub in ("list", "ls"):
        for p in pets.PETS.values():
            render_pet(ctx.console, p, state="idle")
        ctx.console.print(Text(
            "  /pet <id> to choose — id is shown in pet's name",
            style=THEME.dim,
        ))
        return

    if sub in ("none", "default", "clear"):
        pm.set_pet(profile.name, None)
        profile.pet_id = None
        ctx.console.print(Text(
            f"  · pet cleared on profile {profile.name!r}",
            style=THEME.success,
        ))
        return

    if sub == "speech":
        # /pet speech                → show settings
        # /pet speech on|off         → toggle
        # /pet speech tokens N       → cap LLM tokens per quip
        sub_args = args[1:]
        if not sub_args:
            mode = settings_store.get("pet_speech", "off")
            tokens = settings_store.get("pet_speech_tokens", 40)
            ctx.console.print(Text(
                f"  pet speech: {mode}  ·  max tokens per quip: {tokens}",
                style=THEME.text,
            ))
            ctx.console.print(Text(
                "  /pet speech on|off  ·  /pet speech tokens 40",
                style=THEME.dim,
            ))
            return
        head = sub_args[0].lower()
        if head in ("on", "off"):
            settings_store.update({"pet_speech": head})
            ctx.console.print(Text(
                f"  · pet speech → {head}", style=THEME.success,
            ))
            return
        if head == "tokens" and len(sub_args) >= 2:
            try:
                n = int(sub_args[1])
            except ValueError:
                ctx.console.print(Text("  expected an integer", style=THEME.error))
                return
            try:
                settings_store.update({"pet_speech_tokens": n})
            except ValueError as exc:
                ctx.console.print(Text(f"  {exc}", style=THEME.error))
                return
            ctx.console.print(Text(
                f"  · pet_speech_tokens → {n}", style=THEME.success,
            ))
            return
        ctx.console.print(Text(
            "  /pet speech on|off  ·  /pet speech tokens <int>",
            style=THEME.error,
        ))
        return

    if sub not in pets.PETS:
        ctx.console.print(Text(
            f"  unknown pet {sub!r}. options: {', '.join(pets.PETS)}",
            style=THEME.error,
        ))
        return

    pm.set_pet(profile.name, sub)
    profile.pet_id = sub  # update in-memory dataclass too
    pet = pets.get(sub)
    ctx.console.print(Text(
        f"  · {profile.name} → {pet.name}",
        style=THEME.success,
    ))
    render_pet(ctx.console, pet, state="celebrate")


# ── /state ───────────────────────────────────────────────────────────────


def _cmd_state(ctx: CommandContext, args: list[str]) -> None:
    """Show, toggle, or tune the inline state indicator (the
    "◣ ▲ ◢   Thinking… 2.3s" row shown while a turn is in flight).

    /state                  → show current settings
    /state verbs on|off     → context-aware LLM verbs (off = static set)
    /state tokens <int>     → token budget per LLM verb call
    """
    if not args:
        verbs = settings_store.get("state_verbs", "on")
        tokens = settings_store.get("state_verbs_tokens", 80)
        ctx.console.print(Text(
            f"  state verbs: {verbs}  ·  max tokens per call: {tokens}",
            style=THEME.text,
        ))
        ctx.console.print(Text(
            "  /state verbs on|off  ·  /state tokens <int>",
            style=THEME.dim,
        ))
        return
    head = args[0].lower()
    if head == "verbs" and len(args) >= 2:
        val = args[1].lower()
        if val not in ("on", "off"):
            ctx.console.print(Text("  /state verbs on|off", style=THEME.error))
            return
        settings_store.update({"state_verbs": val})
        ctx.console.print(Text(
            f"  · state verbs → {val}", style=THEME.success,
        ))
        return
    if head == "tokens" and len(args) >= 2:
        try:
            n = int(args[1])
        except ValueError:
            ctx.console.print(Text("  expected an integer", style=THEME.error))
            return
        try:
            settings_store.update({"state_verbs_tokens": n})
        except ValueError as exc:
            ctx.console.print(Text(f"  {exc}", style=THEME.error))
            return
        ctx.console.print(Text(
            f"  · state_verbs_tokens → {n}", style=THEME.success,
        ))
        return
    ctx.console.print(Text(
        "  /state verbs on|off  ·  /state tokens <int>",
        style=THEME.error,
    ))


# ── /auto-continue ───────────────────────────────────────────────────────


def _cmd_auto_continue(ctx: CommandContext, args: list[str]) -> None:
    """Show, toggle, or cap the auto-continue feature.

    /auto-continue              → show current settings
    /auto-continue on|off       → toggle
    /auto-continue max <int>    → set the per-call cap
    """
    if not args:
        mode = settings_store.get("auto_continue", "on")
        cap = settings_store.get("auto_continue_max", 5)
        ctx.console.print(Text(
            f"  auto-continue: {mode}  ·  max hops per turn: {cap}",
            style=THEME.text,
        ))
        ctx.console.print(Text(
            "  /auto-continue on|off  ·  /auto-continue max <int>",
            style=THEME.dim,
        ))
        return
    head = args[0].lower()
    if head in ("on", "off"):
        settings_store.update({"auto_continue": head})
        ctx.console.print(Text(
            f"  · auto-continue → {head}", style=THEME.success,
        ))
        return
    if head == "max" and len(args) >= 2:
        try:
            n = int(args[1])
        except ValueError:
            ctx.console.print(Text("  expected an integer", style=THEME.error))
            return
        try:
            settings_store.update({"auto_continue_max": n})
        except ValueError as exc:
            ctx.console.print(Text(f"  {exc}", style=THEME.error))
            return
        ctx.console.print(Text(
            f"  · auto_continue_max → {n}", style=THEME.success,
        ))
        return
    ctx.console.print(Text(
        "  /auto-continue on|off  ·  /auto-continue max <int>",
        style=THEME.error,
    ))


# ── /plan ─────────────────────────────────────────────────────────────────


def _cmd_plan(ctx: CommandContext, args: list[str]) -> None:
    """Inspect the active plan or send accept/reject/edit signals to the agent.

    /plan                → render the current $plan
    /plan accept         → tell the agent the plan is good, proceed
    /plan reject         → reject the plan, ask for a new one
    /plan edit <text>    → send "[plan-edit feedback] <text>" so the agent
                           uses plan_edit() to tweak rather than re-plan
    """
    eng = ctx.engine
    var = eng._vars.get("plan")
    plan = var.value if (var and isinstance(var.value, dict)) else None

    if not args:
        if not plan or not (plan.get("tasks") or []):
            ctx.console.print(Text("  no plan set", style=THEME.muted))
            return
        # Compact text rendering (the full visual panel renders during
        # turns automatically via the Renderer's plan_provider hook).
        goal = (plan.get("goal") or "").strip()
        if goal:
            ctx.console.print(Text(f"  goal: {goal}", style=THEME.text))
        for req in plan.get("requirements") or []:
            ctx.console.print(Text(f"    • {req}", style=THEME.muted))
        ctx.console.print(Text(""))

        def _render(items, depth=0):
            for t in items or []:
                if not isinstance(t, dict):
                    continue
                status = t.get("status") or "pending"
                glyph = {"done": "[x]", "in_progress": "[…]"}.get(status, "[ ]")
                style = (THEME.success if status == "done"
                         else THEME.accent if status == "in_progress"
                         else THEME.muted)
                indent = "  " * (depth + 1)
                line = Text(f"{indent}{glyph} ", style=style)
                line.append(t.get("text") or "(empty)", style=THEME.text)
                line.append(f"  {t.get('id','')}", style=THEME.dim)
                ctx.console.print(line)
                _render(t.get("subtasks") or [], depth + 1)

        _render(plan.get("tasks") or [])
        ctx.console.print(Text(
            "  /plan accept · reject · edit <feedback>",
            style=THEME.dim,
        ))
        return

    head = args[0].lower()
    if head in ("accept", "ok", "go", "proceed"):
        ctx.console.print(Text(
            "  · accept signal queued — type your next message to send it, "
            "or use /quit to stop here.",
            style=THEME.muted,
        ))
        ctx.console.print(Text(
            "  → suggested message: \"Plan looks good. Proceed.\"",
            style=THEME.dim,
        ))
        return
    if head in ("reject", "deny", "no"):
        ctx.console.print(Text(
            "  · reject signal queued — paste this as your next message:",
            style=THEME.muted,
        ))
        ctx.console.print(Text(
            "  → I don't like this plan — drop it and propose a different one.",
            style=THEME.dim,
        ))
        return
    if head == "edit":
        if len(args) < 2:
            ctx.console.print(Text(
                "  /plan edit <feedback> — describe what should change",
                style=THEME.error,
            ))
            return
        feedback = " ".join(args[1:])
        ctx.console.print(Text(
            "  · edit feedback ready — paste this as your next message:",
            style=THEME.muted,
        ))
        ctx.console.print(Text(
            f"  → [plan-edit feedback] {feedback}",
            style=THEME.dim,
        ))
        return
    ctx.console.print(Text(
        f"  unknown /plan subcommand: {head!r}. "
        "Try /plan, /plan accept, /plan reject, /plan edit <text>",
        style=THEME.error,
    ))


# ── /raw ──────────────────────────────────────────────────────────────────


def _cmd_raw(ctx: CommandContext, _args: list[str]) -> None:
    """Dump the last 5 messages of history as JSON for debugging."""
    tail = ctx.engine._history[-5:]
    render_json_block(ctx.console, tail)


# ── /shells, /kill, /killall ───────────────────────────────────────────────

def _cmd_shells(ctx: CommandContext, _args: list[str]) -> None:
    """List every background process the engine has spawned this session."""
    from chika.tools.shell_tool import ProcessRegistry
    procs = ProcessRegistry.all()
    if not procs:
        ctx.console.print(Text("  no shells running", style=THEME.dim))
        return
    rows: list[tuple[str, str]] = []
    for p in procs:
        status = "running" if p.get("running") else f"exited ({p.get('exit_code')})"
        cmd_preview = (p.get("command") or "").strip()
        if len(cmd_preview) > 80:
            cmd_preview = cmd_preview[:80] + "…"
        rows.append((
            f"pid {p.get('pid')}",
            f"{status}  ·  {cmd_preview}",
        ))
    render_kv_table(ctx.console, "active shells", rows)
    ctx.console.print(Text(
        "  /kill <pid> to stop one  ·  /killall to stop all",
        style=THEME.dim,
    ))


def _cmd_kill(ctx: CommandContext, args: list[str]) -> None:
    """Kill a specific background process by PID."""
    from chika.tools.shell_tool import ProcessRegistry
    if not args:
        ctx.console.print(Text("  usage: /kill <pid>", style=THEME.warn))
        return
    try:
        pid = int(args[0])
    except ValueError:
        ctx.console.print(Text(
            f"  /kill expects an integer pid, got {args[0]!r}",
            style=THEME.warn,
        ))
        return
    managed = ProcessRegistry.get(pid)
    if managed is None:
        ctx.console.print(Text(
            f"  no tracked process with pid={pid}", style=THEME.warn,
        ))
        return
    if not managed.running:
        ctx.console.print(Text(
            f"  pid {pid} already exited (code {managed.exit_code})",
            style=THEME.dim,
        ))
        return
    try:
        managed.process.kill()
        managed.running = False
        ctx.console.print(Text(f"  killed pid {pid}", style=THEME.accent))
    except Exception as exc:
        ctx.console.print(Text(
            f"  /kill {pid} failed: {exc}", style=THEME.error,
        ))


# ── /install-extension ────────────────────────────────────────────────────


def _cmd_install_extension(ctx: CommandContext, _args: list[str]) -> None:
    """Copy the bundled browser extension to ``~/.chika/extension/`` and
    open ``chrome://extensions/`` so the user can ``Load unpacked``."""
    from chika._cli.install_extension import install_extension
    try:
        install_extension(console=ctx.console)
    except FileNotFoundError as exc:
        ctx.console.print(Text(f"  · {exc}", style=THEME.error))
    except Exception as exc:
        ctx.console.print(Text(
            f"  · install-extension failed: {exc}", style=THEME.error,
        ))


# ── /update ───────────────────────────────────────────────────────────────


def _cmd_update(ctx: CommandContext, args: list[str]) -> None:
    """Pull the latest version of Chika.

    /update              — apply the update right now
    /update --check      — show whether an update is available, don't apply
    """
    from chika._cli import update as upd

    if args and args[0] in ("--check", "-c", "check"):
        info = upd.check_for_updates()
        cur, lat = info.current, info.latest
        if info.available:
            line = Text("  · ", style=THEME.muted)
            line.append("update available", style=f"bold {THEME.accent}")
            line.append(f": {cur} → {lat}", style=THEME.text)
            if not info.ci_green:
                line.append(
                    "  (ci not green — auto-update will skip)",
                    style=THEME.warn,
                )
            ctx.console.print(line)
        elif info.reason == "up_to_date":
            ctx.console.print(Text(
                f"  · already up to date  ({cur})", style=THEME.success,
            ))
        else:
            ctx.console.print(Text(
                f"  · couldn't determine update status ({info.reason})",
                style=THEME.muted,
            ))
        return

    upd.update_chika(console=ctx.console)


# ── /auto-update ──────────────────────────────────────────────────────────


def _cmd_auto_update(ctx: CommandContext, args: list[str]) -> None:
    """Show or toggle the auto-update setting.

    /auto-update            — show current
    /auto-update on|off     — toggle
    """
    if not args:
        cur = settings_store.get("auto_update", "on")
        ctx.console.print(Text(
            f"  auto-update: {cur}", style=THEME.text,
        ))
        ctx.console.print(Text(
            "  on startup, Chika checks the upstream remote and "
            "auto-applies updates whose CI is green.",
            style=THEME.dim,
        ))
        ctx.console.print(Text(
            "  /auto-update on|off",
            style=THEME.dim,
        ))
        return
    val = args[0].lower()
    if val not in ("on", "off"):
        ctx.console.print(Text("  /auto-update on|off", style=THEME.error))
        return
    settings_store.update({"auto_update": val})
    ctx.console.print(Text(
        f"  · auto-update → {val}", style=THEME.success,
    ))


# ── /doctor ───────────────────────────────────────────────────────────────


def _cmd_doctor(ctx: CommandContext, _args: list[str]) -> None:
    """Run install integrity checks (Python, deps, extension, frontend, .env)."""
    from chika._cli.doctor import run_doctor
    run_doctor(console=ctx.console)


# ── /setup ────────────────────────────────────────────────────────────────


def _cmd_setup(ctx: CommandContext, args: list[str]) -> None:
    """Run the interactive provider/API-key wizard.

    /setup           — refuses if .env already exists with content
    /setup --force   — overwrite an existing .env
    """
    from chika._cli.setup import run_setup
    run_setup(console=ctx.console, force=("--force" in args or "-f" in args))


# ── /uninstall ────────────────────────────────────────────────────────────


def _cmd_uninstall(ctx: CommandContext, args: list[str]) -> None:
    """Show OS-appropriate uninstall instructions, or actually run them.

    /uninstall                — show instructions for the detected install
    /uninstall --yes          — run the uninstaller (no further prompts)
    /uninstall --remove-data  — also wipe ~/.chika/  (settings + chats)
    """
    from chika._cli.uninstall import uninstall_chika
    yes = ("--yes" in args or "-y" in args)
    remove_data = ("--remove-data" in args)
    uninstall_chika(console=ctx.console, yes=yes, remove_data=remove_data)


def _cmd_killall(ctx: CommandContext, _args: list[str]) -> None:
    """Kill every running background process."""
    from chika.tools.shell_tool import ProcessRegistry
    procs = ProcessRegistry.all()
    running = [p for p in procs if p.get("running")]
    if not running:
        ctx.console.print(Text("  no running shells", style=THEME.dim))
        return
    killed: list[int] = []
    failed: list[tuple[int, str]] = []
    for p in running:
        pid = p.get("pid")
        if pid is None:
            continue
        managed = ProcessRegistry.get(int(pid))
        if managed is None:
            continue
        try:
            managed.process.kill()
            managed.running = False
            killed.append(int(pid))
        except Exception as exc:
            failed.append((int(pid), str(exc)))
    if killed:
        ctx.console.print(Text(
            f"  killed {len(killed)} shell{'s' if len(killed) != 1 else ''}: "
            + ", ".join(str(p) for p in killed),
            style=THEME.accent,
        ))
    for pid_failed, err_msg in failed:
        ctx.console.print(Text(
            f"  /kill {pid_failed} failed: {err_msg}", style=THEME.error,
        ))


# ── Registration ──────────────────────────────────────────────────────────


def _register_all() -> None:
    register(Command("help", "list available commands", _cmd_help, ("?",)))
    register(Command("quit", "exit chika", _cmd_quit, ("exit", "q", "bye")))
    register(Command("clear", "clear the screen", _cmd_clear, ("cls",)))
    register(Command("reset", "reset session (history + variables)", _cmd_reset))
    register(Command("status", "show provider, profile, counts", _cmd_status,
                     ("info",)))
    register(Command("settings", "show runtime settings", _cmd_settings))
    register(Command("autonomy", "supervised | autonomous", _cmd_autonomy,
                     args_hint="[supervised|autonomous]"))
    register(Command("permissions", "per-category tool permissions",
                     _cmd_permissions, ("perms",),
                     args_hint="[<category> ask|skip]"))
    register(Command("provider", "show or switch LLM provider", _cmd_provider,
                     args_hint="[anthropic|openai|azure|ollama]"))
    register(Command("model", "show or set the active model", _cmd_model,
                     args_hint="[<model-id>]"))
    register(Command("env", "view / edit .env vars (secrets masked)",
                     _cmd_env,
                     args_hint="[KEY[=VALUE]] | --unset KEY | --show-secrets"))
    register(Command("profile", "show or switch profile", _cmd_profile,
                     args_hint="[<name>]"))
    register(Command("profiles", "list profiles", _cmd_profiles))
    register(Command("tools", "list registered tools", _cmd_tools))
    register(Command("skills", "list registered skills", _cmd_skills))
    register(Command("vars", "show session variables", _cmd_vars,
                     ("variables",)))
    register(Command("memory", "show profile memory", _cmd_memory))
    register(Command("thinking", "toggle extended-thinking display",
                     _cmd_thinking, args_hint="[on|off]"))
    register(Command("log", "show log file path", _cmd_log))
    register(Command("pet", "show or switch your profile's pet",
                     _cmd_pet, ("buddy", "companion"),
                     args_hint="[list | none | <pet-id>]"))
    register(Command("auto-continue",
                     "auto-fire another turn when agent promises more work",
                     _cmd_auto_continue, ("autocontinue", "ac"),
                     args_hint="[on|off | max <int>]"))
    register(Command("state",
                     "configure the inline state indicator (LLM verbs)",
                     _cmd_state,
                     args_hint="[verbs on|off | tokens <int>]"))
    register(Command("plan",
                     "show / accept / reject / edit the active task plan",
                     _cmd_plan,
                     args_hint="[accept | reject | edit <feedback>]"))
    register(Command("raw", "dump last 5 history messages as JSON",
                     _cmd_raw))
    register(Command("shells",
                     "list active background shells (PIDs + commands)",
                     _cmd_shells, ("ps", "processes")))
    register(Command("kill", "kill a background shell by pid",
                     _cmd_kill, args_hint="<pid>"))
    register(Command("killall",
                     "kill every running background shell",
                     _cmd_killall, ("kill-all",)))
    register(Command("install-extension",
                     "copy the browser extension to ~/.chika and open Chrome",
                     _cmd_install_extension, ("install-ext",)))
    register(Command("update",
                     "pull the latest Chika (or --check to peek)",
                     _cmd_update,
                     args_hint="[--check]"))
    register(Command("auto-update",
                     "toggle the on-startup auto-update",
                     _cmd_auto_update, ("autoupdate",),
                     args_hint="[on|off]"))
    # Skill-owned slash commands. Each shipped skill exports an
    # optional ``register_cli()`` returning ``{"slash": {<name>: handler}}``;
    # the dispatcher walks every skill so adding a new skill =
    # automatically gets a new /<name> command (when the skill
    # declares one). Handlers receive ``(args)`` like the argv path.
    from chika.skills import iter_skill_cli as _iter_skill_cli
    for _skill_name, _table in _iter_skill_cli():
        for _cmd_name, _handler in (_table.get("slash") or {}).items():
            def _make_wrapper(name=_cmd_name, handler=_handler):
                def _slash_wrapper(ctx: CommandContext, args: list[str]) -> None:
                    rc = handler(args)
                    if rc and rc != 0:
                        ctx.console.print(Text(
                            f"  · /{name} exited {rc}", style=THEME.dim,
                        ))
                return _slash_wrapper
            register(Command(_cmd_name, f"{_skill_name} skill", _make_wrapper()))
    register(Command("doctor",
                     "verify the install (deps, extension, .env, etc.)",
                     _cmd_doctor))
    register(Command("setup",
                     "interactive wizard — pick a provider, save your API key",
                     _cmd_setup,
                     args_hint="[--force]"))
    register(Command("uninstall",
                     "show OS-appropriate uninstall steps (or --yes to run them)",
                     _cmd_uninstall,
                     args_hint="[--yes] [--remove-data]"))


_register_all()
