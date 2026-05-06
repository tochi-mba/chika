"""Coverage for chika/_cli/commands.py — slash command dispatch + handlers.

Each command is a callable taking (ctx, args). We mock the engine + console
and assert the command mutated the right context fields, called the right
settings_store key, or printed the right summary.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from chika._cli import commands as c


def _ctx(engine_attrs: dict | None = None) -> c.CommandContext:
    """Build a CommandContext with a recording console + mocked engine."""
    console = Console(record=True, width=120, file=io.StringIO(),
                      force_terminal=False)
    engine = MagicMock()
    if engine_attrs:
        for k, v in engine_attrs.items():
            setattr(engine, k, v)
    return c.CommandContext(console=console, engine=engine,
                            show_thinking=True)


# ── dispatch / register / list_commands ────────────────────────────────


def test_dispatch_returns_false_for_non_slash():
    ctx = _ctx()
    assert c.dispatch(ctx, "hello world") is False


def test_dispatch_returns_false_for_empty_slash():
    ctx = _ctx()
    assert c.dispatch(ctx, "/") is False


def test_dispatch_unknown_command_prints_warning():
    ctx = _ctx()
    handled = c.dispatch(ctx, "/totally-bogus")
    assert handled is True
    out = ctx.console.export_text()
    assert "unknown command" in out


def test_dispatch_known_command_runs_handler():
    ctx = _ctx()
    handled = c.dispatch(ctx, "/quit")
    assert handled is True
    assert ctx.exit_requested is True


def test_dispatch_handler_exception_caught_gracefully():
    """A handler raising mid-call is reported, not propagated."""
    ctx = _ctx()
    sentinel = c.Command("explode", "boom",
                         lambda _ctx, _args: (_ for _ in ()).throw(RuntimeError("boom")))
    c.register(sentinel)
    handled = c.dispatch(ctx, "/explode")
    assert handled is True
    out = ctx.console.export_text()
    assert "failed" in out


def test_list_commands_includes_help():
    names = {cmd.name for cmd in c.list_commands()}
    assert "help" in names
    assert "quit" in names


def test_list_commands_skips_aliases():
    """Aliases share a Command — list_commands returns each Command once."""
    cmds = c.list_commands()
    seen_objects = set()
    for cmd in cmds:
        seen_objects.add(id(cmd))
    assert len(cmds) == len(seen_objects)


def test_all_command_names_includes_aliases():
    names = c.all_command_names()
    assert "quit" in names
    assert "exit" in names  # alias
    assert "?" in names     # alias for help


# ── /help / /quit / /clear / /reset ───────────────────────────────────


def test_cmd_help_renders_table():
    ctx = _ctx()
    c._cmd_help(ctx, [])
    out = ctx.console.export_text()
    assert "/quit" in out
    assert "/help" in out


def test_cmd_quit_sets_exit_flag():
    ctx = _ctx()
    c._cmd_quit(ctx, [])
    assert ctx.exit_requested is True


def test_cmd_clear_sets_clear_flag():
    ctx = _ctx()
    c._cmd_clear(ctx, [])
    assert ctx.clear_requested is True


def test_cmd_reset_calls_engine_reset():
    ctx = _ctx()
    c._cmd_reset(ctx, [])
    ctx.engine.reset.assert_called_once()
    assert ctx.reset_requested is True


# ── /settings / /autonomy / /permissions ──────────────────────────────


def test_cmd_settings_shows_autonomy(monkeypatch):
    monkeypatch.setattr(
        c.settings_store, "all_settings",
        lambda: {"autonomy": "supervised", "tool_permissions": {}},
    )
    ctx = _ctx()
    c._cmd_settings(ctx, [])
    out = ctx.console.export_text()
    assert "autonomy" in out
    assert "supervised" in out


def test_cmd_settings_shows_perms(monkeypatch):
    monkeypatch.setattr(
        c.settings_store, "all_settings",
        lambda: {"autonomy": "autonomous", "tool_permissions": {"shell": "ask"}},
    )
    ctx = _ctx()
    c._cmd_settings(ctx, [])
    out = ctx.console.export_text()
    assert "shell=ask" in out


def test_cmd_autonomy_no_args_shows_current(monkeypatch):
    monkeypatch.setattr(c.settings_store, "get",
                        lambda k, d=None: "autonomous")
    ctx = _ctx()
    c._cmd_autonomy(ctx, [])
    assert "autonomous" in ctx.console.export_text()


def test_cmd_autonomy_invalid_arg_errors():
    ctx = _ctx()
    c._cmd_autonomy(ctx, ["weird"])
    assert "expects" in ctx.console.export_text().lower()


def test_cmd_autonomy_sets_value(monkeypatch):
    captured = {}
    monkeypatch.setattr(c.settings_store, "update",
                        lambda d: captured.update(d))
    ctx = _ctx()
    c._cmd_autonomy(ctx, ["supervised"])
    assert captured == {"autonomy": "supervised"}


def test_cmd_permissions_no_args_lists(monkeypatch):
    monkeypatch.setattr(
        c.settings_store, "CATEGORIES",
        {"shell": "shell exec", "browser": "browser actions"},
    )
    monkeypatch.setattr(c.settings_store, "get",
                        lambda k, d=None: {} if k == "tool_permissions" else "supervised")
    ctx = _ctx()
    c._cmd_permissions(ctx, [])
    out = ctx.console.export_text()
    assert "shell" in out


def test_cmd_permissions_invalid_category(monkeypatch):
    monkeypatch.setattr(c.settings_store, "CATEGORIES", {"shell": "x"})
    monkeypatch.setattr(c.settings_store, "get", lambda k, d=None: {})
    ctx = _ctx()
    c._cmd_permissions(ctx, ["unknown", "ask"])
    assert "unknown category" in ctx.console.export_text()


def test_cmd_permissions_invalid_perm(monkeypatch):
    monkeypatch.setattr(c.settings_store, "CATEGORIES", {"shell": "x"})
    monkeypatch.setattr(c.settings_store, "get", lambda k, d=None: {})
    ctx = _ctx()
    c._cmd_permissions(ctx, ["shell", "weird"])
    assert "ask" in ctx.console.export_text() or "skip" in ctx.console.export_text()


def test_cmd_permissions_sets_value(monkeypatch):
    monkeypatch.setattr(c.settings_store, "CATEGORIES", {"shell": "x"})
    monkeypatch.setattr(c.settings_store, "get", lambda k, d=None: {})
    captured = {}
    monkeypatch.setattr(c.settings_store, "update",
                        lambda d: captured.update(d))
    ctx = _ctx()
    c._cmd_permissions(ctx, ["shell", "ask"])
    assert captured["tool_permissions"] == {"shell": "ask"}


# ── /provider, /model ─────────────────────────────────────────────────


def test_cmd_provider_no_args_shows_current(monkeypatch):
    cfg = MagicMock(provider="anthropic", model="opus")
    monkeypatch.setattr(c.config, "get_provider_config", lambda: cfg)
    ctx = _ctx()
    c._cmd_provider(ctx, [])
    out = ctx.console.export_text()
    assert "anthropic" in out
    assert "opus" in out


def test_cmd_provider_unknown_provider_errors():
    ctx = _ctx()
    c._cmd_provider(ctx, ["bogus"])
    assert "unknown provider" in ctx.console.export_text()


def test_cmd_provider_writes_env(monkeypatch):
    captured = {}
    monkeypatch.setattr(c.env_file, "write_env",
                        lambda d: captured.update(d))
    ctx = _ctx()
    c._cmd_provider(ctx, ["openai"])
    assert captured == {"CHIKA_PROVIDER": "openai"}


def test_cmd_model_no_args_shows_current(monkeypatch):
    cfg = MagicMock(provider="anthropic", model="opus-4-7")
    monkeypatch.setattr(c.config, "get_provider_config", lambda: cfg)
    ctx = _ctx()
    c._cmd_model(ctx, [])
    assert "opus-4-7" in ctx.console.export_text()


def test_cmd_model_writes_env(monkeypatch):
    cfg = MagicMock(provider="anthropic", model="opus")
    monkeypatch.setattr(c.config, "get_provider_config", lambda: cfg)
    captured = {}
    monkeypatch.setattr(c.env_file, "write_env",
                        lambda d: captured.update(d))
    ctx = _ctx()
    c._cmd_model(ctx, ["sonnet-4-6"])
    assert captured == {"ANTHROPIC_MODEL": "sonnet-4-6"}


def test_cmd_model_unsupported_provider(monkeypatch):
    cfg = MagicMock(provider="xyz", model="m")
    monkeypatch.setattr(c.config, "get_provider_config", lambda: cfg)
    ctx = _ctx()
    c._cmd_model(ctx, ["new-model"])
    assert "cannot set model" in ctx.console.export_text()


# ── /env ──────────────────────────────────────────────────────────────


def test_cmd_env_list_empty(monkeypatch):
    monkeypatch.setattr(c.env_file, "read_env_for_display", lambda mask_secrets=True: [])
    ctx = _ctx()
    c._cmd_env(ctx, [])
    assert "empty" in ctx.console.export_text() or "missing" in ctx.console.export_text()


def test_cmd_env_list_masks_secrets_by_default(monkeypatch):
    rows = [("KEY1", "value1", False), ("API_KEY", "***", True)]
    monkeypatch.setattr(c.env_file, "read_env_for_display",
                        lambda mask_secrets=True: rows)
    ctx = _ctx()
    c._cmd_env(ctx, [])
    out = ctx.console.export_text()
    assert "KEY1" in out
    assert "secret" in out


def test_cmd_env_show_secrets(monkeypatch):
    rows = [("API_KEY", "real_value", True)]
    monkeypatch.setattr(c.env_file, "read_env_for_display",
                        lambda mask_secrets=True: rows)
    ctx = _ctx()
    c._cmd_env(ctx, ["--show-secrets"])


def test_cmd_env_unset_missing_key():
    ctx = _ctx()
    c._cmd_env(ctx, ["--unset"])
    assert "/env --unset" in ctx.console.export_text()


def test_cmd_env_unset_with_key(monkeypatch):
    captured = {}
    monkeypatch.setattr(c.env_file, "write_env",
                        lambda d: captured.update(d))
    ctx = _ctx()
    c._cmd_env(ctx, ["--unset", "MY_KEY"])
    assert captured == {"MY_KEY": None}


def test_cmd_env_set_via_equals(monkeypatch):
    captured = {}
    monkeypatch.setattr(c.env_file, "write_env",
                        lambda d: captured.update(d))
    ctx = _ctx()
    c._cmd_env(ctx, ["KEY=value"])
    assert captured == {"KEY": "value"}


def test_cmd_env_set_via_pair(monkeypatch):
    captured = {}
    monkeypatch.setattr(c.env_file, "write_env",
                        lambda d: captured.update(d))
    ctx = _ctx()
    c._cmd_env(ctx, ["KEY", "longer", "value"])
    assert captured == {"KEY": "longer value"}


def test_cmd_env_show_one_set(monkeypatch):
    monkeypatch.setattr(c.env_file, "read_env",
                        lambda: {"KEY": "actual"})
    monkeypatch.setattr(c.env_file, "is_sensitive", lambda k: False)
    ctx = _ctx()
    c._cmd_env(ctx, ["KEY"])
    assert "actual" in ctx.console.export_text()


def test_cmd_env_show_one_unset(monkeypatch):
    monkeypatch.setattr(c.env_file, "read_env", lambda: {})
    ctx = _ctx()
    c._cmd_env(ctx, ["MISSING"])
    assert "not set" in ctx.console.export_text()


def test_cmd_env_show_one_sensitive_masked(monkeypatch):
    monkeypatch.setattr(c.env_file, "read_env",
                        lambda: {"API_KEY": "secret123"})
    monkeypatch.setattr(c.env_file, "is_sensitive", lambda k: True)
    monkeypatch.setattr(c.env_file, "mask", lambda v: "***")
    ctx = _ctx()
    c._cmd_env(ctx, ["API_KEY"])
    assert "***" in ctx.console.export_text()


# ── /thinking ─────────────────────────────────────────────────────────


def test_cmd_thinking_no_args_shows():
    ctx = _ctx()
    ctx.show_thinking = True
    c._cmd_thinking(ctx, [])
    assert "on" in ctx.console.export_text()


def test_cmd_thinking_on():
    ctx = _ctx()
    ctx.show_thinking = False
    c._cmd_thinking(ctx, ["on"])
    assert ctx.show_thinking is True


def test_cmd_thinking_off():
    ctx = _ctx()
    ctx.show_thinking = True
    c._cmd_thinking(ctx, ["off"])
    assert ctx.show_thinking is False


def test_cmd_thinking_invalid_arg():
    ctx = _ctx()
    c._cmd_thinking(ctx, ["maybe"])
    assert "/thinking on|off" in ctx.console.export_text()


# ── /tools, /skills, /vars, /memory ───────────────────────────────────


def test_cmd_tools_renders_table():
    ctx = _ctx()
    fake_tool = MagicMock()
    fake_tool.name = "file_read"
    fake_tool.description = "read a file"
    ctx.engine._tools._tools = {"file_read": fake_tool}
    c._cmd_tools(ctx, [])
    assert "file_read" in ctx.console.export_text()


def test_cmd_skills_renders_table():
    ctx = _ctx()
    ctx.engine._skills.list_skills = MagicMock(return_value=[
        {"name": "browser", "description": "browser tools"},
    ])
    c._cmd_skills(ctx, [])
    assert "browser" in ctx.console.export_text()


def test_cmd_vars_empty():
    ctx = _ctx()
    ctx.engine._vars.all = MagicMock(return_value={})
    c._cmd_vars(ctx, [])
    assert "no variables" in ctx.console.export_text()


def test_cmd_vars_renders():
    ctx = _ctx()
    var = MagicMock()
    var.value = {"some": "data"}
    ctx.engine._vars.all = MagicMock(return_value={"x": var})
    c._cmd_vars(ctx, [])
    assert "$x" in ctx.console.export_text()


def test_cmd_vars_truncates_long_values():
    ctx = _ctx()
    var = MagicMock()
    var.value = "x" * 200
    ctx.engine._vars.all = MagicMock(return_value={"big": var})
    c._cmd_vars(ctx, [])
    out = ctx.console.export_text()
    assert "$big" in out


def test_cmd_memory_empty():
    ctx = _ctx()
    ctx.engine._memory.render_for_prompt = MagicMock(return_value="")
    c._cmd_memory(ctx, [])
    assert "empty" in ctx.console.export_text()


def test_cmd_memory_renders():
    ctx = _ctx()
    ctx.engine._memory.render_for_prompt = MagicMock(return_value="memory body")
    c._cmd_memory(ctx, [])
    assert "memory body" in ctx.console.export_text()


# ── /log, /status ─────────────────────────────────────────────────────


def test_cmd_log_shows_path():
    ctx = _ctx()
    c._cmd_log(ctx, [])
    out = ctx.console.export_text()
    assert "log" in out


def test_cmd_status_renders(monkeypatch):
    cfg = MagicMock(provider="anthropic", model="opus")
    monkeypatch.setattr(c.config, "get_provider_config", lambda: cfg)
    monkeypatch.setattr(c.settings_store, "get",
                        lambda k, d=None: "supervised")
    ctx = _ctx()
    profile = MagicMock(name="dev", workspace="/ws")
    profile.name = "dev"
    ctx.engine._active_profile = profile
    ctx.engine.session_id = "sess-1"
    ctx.engine._history = [{"role": "user"}]
    ctx.engine._vars.all = MagicMock(return_value={})
    c._cmd_status(ctx, [])
    out = ctx.console.export_text()
    assert "anthropic" in out
    assert "opus" in out


# ── /auto-continue ────────────────────────────────────────────────────


def test_cmd_auto_continue_show(monkeypatch):
    monkeypatch.setattr(c.settings_store, "get",
                        lambda k, d=None: "on" if k == "auto_continue" else 5)
    ctx = _ctx()
    c._cmd_auto_continue(ctx, [])
    assert "auto-continue" in ctx.console.export_text()


def test_cmd_auto_continue_on(monkeypatch):
    captured = {}
    monkeypatch.setattr(c.settings_store, "update",
                        lambda d: captured.update(d))
    ctx = _ctx()
    c._cmd_auto_continue(ctx, ["on"])
    assert captured == {"auto_continue": "on"}


def test_cmd_auto_continue_max(monkeypatch):
    captured = {}
    monkeypatch.setattr(c.settings_store, "update",
                        lambda d: captured.update(d))
    ctx = _ctx()
    c._cmd_auto_continue(ctx, ["max", "20"])
    assert captured == {"auto_continue_max": 20}


def test_cmd_auto_continue_max_non_integer():
    ctx = _ctx()
    c._cmd_auto_continue(ctx, ["max", "abc"])
    assert "integer" in ctx.console.export_text()


def test_cmd_auto_continue_invalid_subcmd():
    ctx = _ctx()
    c._cmd_auto_continue(ctx, ["weird"])
    out = ctx.console.export_text()
    assert "on|off" in out


def test_cmd_auto_continue_max_validation_error(monkeypatch):
    def raise_value_error(d):
        raise ValueError("must be in [1, 50]")
    monkeypatch.setattr(c.settings_store, "update", raise_value_error)
    ctx = _ctx()
    c._cmd_auto_continue(ctx, ["max", "100"])
    assert "must be in" in ctx.console.export_text()


# ── /state — inline state indicator settings ──────────────────────────


def test_cmd_state_show(monkeypatch):
    monkeypatch.setattr(
        c.settings_store, "get",
        lambda k, d=None: "on" if k == "state_verbs" else 80,
    )
    ctx = _ctx()
    c._cmd_state(ctx, [])
    out = ctx.console.export_text()
    assert "state verbs" in out
    assert "max tokens" in out


def test_cmd_state_verbs_on(monkeypatch):
    captured = {}
    monkeypatch.setattr(c.settings_store, "update",
                        lambda d: captured.update(d))
    ctx = _ctx()
    c._cmd_state(ctx, ["verbs", "on"])
    assert captured == {"state_verbs": "on"}


def test_cmd_state_verbs_off(monkeypatch):
    captured = {}
    monkeypatch.setattr(c.settings_store, "update",
                        lambda d: captured.update(d))
    ctx = _ctx()
    c._cmd_state(ctx, ["verbs", "off"])
    assert captured == {"state_verbs": "off"}


def test_cmd_state_verbs_invalid_value():
    ctx = _ctx()
    c._cmd_state(ctx, ["verbs", "maybe"])
    assert "/state verbs on|off" in ctx.console.export_text()


def test_cmd_state_tokens(monkeypatch):
    captured = {}
    monkeypatch.setattr(c.settings_store, "update",
                        lambda d: captured.update(d))
    ctx = _ctx()
    c._cmd_state(ctx, ["tokens", "120"])
    assert captured == {"state_verbs_tokens": 120}


def test_cmd_state_tokens_non_integer():
    ctx = _ctx()
    c._cmd_state(ctx, ["tokens", "lots"])
    assert "integer" in ctx.console.export_text()


def test_cmd_state_tokens_validation_error(monkeypatch):
    def raise_value_error(d):
        raise ValueError("must be in [16, 200]")
    monkeypatch.setattr(c.settings_store, "update", raise_value_error)
    ctx = _ctx()
    c._cmd_state(ctx, ["tokens", "999"])
    assert "must be in" in ctx.console.export_text()


def test_cmd_state_unknown_subcommand():
    ctx = _ctx()
    c._cmd_state(ctx, ["nonsense"])
    assert "verbs on|off" in ctx.console.export_text()


# ── /raw / /shells / /kill / /killall ─────────────────────────────────


def test_cmd_raw_dumps_history():
    ctx = _ctx()
    ctx.engine._history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    c._cmd_raw(ctx, [])
    out = ctx.console.export_text()
    assert "user" in out


def test_cmd_shells_no_processes():
    ctx = _ctx()
    with patch("chika.tools.shell_tool.ProcessRegistry") as pr:
        pr.all = MagicMock(return_value=[])
        c._cmd_shells(ctx, [])
    assert "no shells" in ctx.console.export_text()


def test_cmd_shells_lists_running_and_exited():
    ctx = _ctx()
    procs = [
        {"pid": 1234, "running": True, "command": "npm run dev",
         "exit_code": None},
        {"pid": 5678, "running": False, "command": "python -m http.server",
         "exit_code": 0},
    ]
    with patch("chika.tools.shell_tool.ProcessRegistry") as pr:
        pr.all = MagicMock(return_value=procs)
        c._cmd_shells(ctx, [])
    out = ctx.console.export_text()
    assert "1234" in out
    assert "5678" in out


def test_cmd_kill_no_pid():
    ctx = _ctx()
    c._cmd_kill(ctx, [])
    assert "/kill <pid>" in ctx.console.export_text()


def test_cmd_kill_non_integer():
    ctx = _ctx()
    c._cmd_kill(ctx, ["not-a-pid"])
    assert "integer" in ctx.console.export_text()


def test_cmd_kill_unknown_pid():
    ctx = _ctx()
    with patch("chika.tools.shell_tool.ProcessRegistry") as pr:
        pr.get = MagicMock(return_value=None)
        c._cmd_kill(ctx, ["9999"])
    assert "no tracked" in ctx.console.export_text()


def test_cmd_kill_already_exited():
    ctx = _ctx()
    managed = MagicMock(running=False, exit_code=0)
    with patch("chika.tools.shell_tool.ProcessRegistry") as pr:
        pr.get = MagicMock(return_value=managed)
        c._cmd_kill(ctx, ["1234"])
    assert "already exited" in ctx.console.export_text()


def test_cmd_kill_kills_running_process():
    ctx = _ctx()
    managed = MagicMock(running=True)
    with patch("chika.tools.shell_tool.ProcessRegistry") as pr:
        pr.get = MagicMock(return_value=managed)
        c._cmd_kill(ctx, ["1234"])
    managed.process.kill.assert_called_once()
    assert managed.running is False


def test_cmd_kill_kill_failure():
    ctx = _ctx()
    managed = MagicMock(running=True)
    managed.process.kill = MagicMock(side_effect=OSError("perm denied"))
    with patch("chika.tools.shell_tool.ProcessRegistry") as pr:
        pr.get = MagicMock(return_value=managed)
        c._cmd_kill(ctx, ["1234"])
    assert "failed" in ctx.console.export_text()


def test_cmd_killall_no_running():
    ctx = _ctx()
    with patch("chika.tools.shell_tool.ProcessRegistry") as pr:
        pr.all = MagicMock(return_value=[{"pid": 1, "running": False}])
        c._cmd_killall(ctx, [])
    assert "no running" in ctx.console.export_text()


def test_cmd_killall_kills_processes():
    ctx = _ctx()
    p1 = MagicMock(running=True)
    p2 = MagicMock(running=True)
    procs = [{"pid": 1, "running": True}, {"pid": 2, "running": True}]
    with patch("chika.tools.shell_tool.ProcessRegistry") as pr:
        pr.all = MagicMock(return_value=procs)
        pr.get = MagicMock(side_effect=[p1, p2])
        c._cmd_killall(ctx, [])
    assert p1.process.kill.called
    assert p2.process.kill.called
    assert "killed" in ctx.console.export_text()


def test_cmd_killall_partial_failure():
    ctx = _ctx()
    p1 = MagicMock(running=True)
    p2 = MagicMock(running=True)
    p2.process.kill = MagicMock(side_effect=OSError("denied"))
    procs = [{"pid": 1, "running": True}, {"pid": 2, "running": True}]
    with patch("chika.tools.shell_tool.ProcessRegistry") as pr:
        pr.all = MagicMock(return_value=procs)
        pr.get = MagicMock(side_effect=[p1, p2])
        c._cmd_killall(ctx, [])
    out = ctx.console.export_text()
    assert "killed" in out


# ── _register_all wiring ──────────────────────────────────────────────


def test_register_all_wires_expected_commands():
    """Module-level _register_all() runs at import — these should all be present."""
    expected = {
        "help", "quit", "exit", "clear", "reset", "status",
        "settings", "autonomy", "permissions", "perms",
        "provider", "model", "env",
        "profile", "profiles", "tools", "skills", "vars",
        "memory", "thinking", "log", "pet", "auto-continue",
        "plan", "raw", "shells", "kill", "killall",
    }
    names = set(c.all_command_names())
    missing = expected - names
    assert not missing, f"missing commands: {missing}"
