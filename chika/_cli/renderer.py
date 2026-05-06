"""Render engine events into rich terminal output.

The renderer translates the typed event stream from
:meth:`chika.core.engine.ChikaEngine.chat` into terminal output:

- token / thinking         → live streamed assistant text
- workflow_start / done    → hairline separators
- step_start               → muted breadcrumb
- tool_call                → bordered tool block (Claude Code style)
- tool_result              → indented result preview under the tool block
- variable_set             → muted ``$name = type (Nb)`` line
- compaction / error / etc → contextual notices

All output is colour-coordinated through the :class:`Theme`. When ``rich`` is
unavailable the caller should fall back to the legacy plain renderer in
:mod:`chika._cli.fallback`.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

# ── Theme ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Theme:
    """Colour tokens for the CLI. Mirrors the v0 frontend palette so every
    surface (Vue web app, extension popup, CLI) speaks the same vocabulary."""

    accent:    str = "#6c63ff"      # canonical v0 accent (was #9d7fff)
    accent_2:  str = "#7c70ff"
    success:   str = "#3dd68c"
    error:     str = "#e05c5c"
    warn:      str = "#e0b35c"
    muted:     str = "#a8a8b8"      # v0 dark text-2 — was #6b6b85
    dim:       str = "#6b6b85"      # v0 dark text-3 — was #4f4f6a
    text:      str = "#ededf2"
    thinking:  str = "italic #6b6b85"

    # Unicode glyphs (used when the terminal supports them)
    user_glyph:      str = ">"
    assistant_glyph: str = "●"
    tool_glyph:      str = "⏺"
    result_glyph:    str = "⎿"
    arrow_glyph:     str = "›"
    loop_glyph:      str = "↻"
    map_glyph:       str = "▸"
    retry_glyph:     str = "↺"
    warn_glyph:      str = "⚠"
    bullet_glyph:    str = "·"
    # Spinner frames cycled while a tool is in-flight. Braille pattern reads
    # as smooth motion at any tick rate ≤ 200ms.
    spinner_frames:  tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼",
                                         "⠴", "⠦", "⠧", "⠇", "⠏")


_ASCII_THEME = Theme(
    user_glyph=">",
    assistant_glyph="*",
    tool_glyph="*",
    result_glyph="L",
    arrow_glyph=">",
    loop_glyph="@",
    map_glyph=">",
    retry_glyph="@",
    warn_glyph="!",
    bullet_glyph="-",
    spinner_frames=("|", "/", "-", "\\"),
)


def _unicode_supported() -> bool:
    """Best-effort check that the active stdout encoding handles our glyphs."""
    enc = getattr(sys.stdout, "encoding", None) or ""
    try:
        "⏺⎿›↻▸↺⚠·⠋⠙".encode(enc or "ascii")
        return True
    except Exception:
        return False


THEME: Theme = Theme() if _unicode_supported() else _ASCII_THEME


# ── Helpers ─────────────────────────────────────────────────────────────────

_MAX_ARG_PREVIEW = 200
_MAX_RESULT_PREVIEW = 600
_MAX_RESULT_LINES = 8

# Short pet-bubble lines triggered when a specific tool fires. Tools without
# an entry get a generic ``using <tool>…`` bubble. Mirrors the frontend
# table in stores/system.js so both surfaces stay in sync.
_TOOL_BUBBLES: dict[str, str] = {
    "shell_exec":             "running a command…",
    "bg_shell_exec":          "spawning a process…",
    "shell_kill":             "stopping that process…",
    "shell_get_output":       "checking the output…",
    "python_run":             "launching a desktop app…",
    "file_read":              "reading…",
    "file_write":             "writing a file…",
    "file_edit_lines":        "editing…",
    "file_replace":           "replacing text…",
    "file_append":            "appending…",
    "file_search":            "grepping…",
    "dir_list":               "listing files…",
    "web_search":             "searching the web…",
    "web_fetch":              "fetching a page…",
    "web_head":               "probing a URL…",
    "verify_url":             "checking a link…",
    "git_status":             "looking at git…",
    "git_diff":               "diffing…",
    "git_commit":             "committing…",
    "git_push":               "pushing…",
    "git_pull":               "pulling…",
    "git_log":                "reading history…",
    "memory_persist":         "remembering…",
    "memory_recall":          "recalling…",
    "memory_forget":          "forgetting…",
    "browser_navigate":       "navigating…",
    "browser_screenshot":     "taking a screenshot…",
    "browser_click":          "clicking…",
    "browser_fill_input":     "typing into a form…",
    "browser_get_active_tab": "peeking at your tab…",
    "browser_get_text":       "reading the page…",
    "skill_load":             "loading a skill doc…",
    "skill_query":            "querying a skill doc…",
    "plan_set":               "drafting a plan…",
    "plan_update":            "updating the plan…",
    "plan_add":               "adding to the plan…",
    "plan_remove":            "removing a task…",
    "ask_user":               "asking the user…",
    "live_server":            "starting the dev server…",
    "scaffold_web_app":       "scaffolding the project…",
    "spotify_play":           "queueing music…",
    "spotify_search":         "searching Spotify…",
}


def _shorten(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _fmt_args(args: dict[str, Any]) -> Text:
    """Inline ``key=value`` rendering for tool args, truncated."""
    parts = Text()
    for i, (k, v) in enumerate(args.items()):
        if i:
            parts.append(", ", style=THEME.dim)
        parts.append(k, style=THEME.muted)
        parts.append("=", style=THEME.dim)
        if isinstance(v, str):
            preview = _shorten(v.replace("\n", " "), 80)
            parts.append(json.dumps(preview), style=THEME.text)
        else:
            try:
                rendered = json.dumps(v, default=str)
            except Exception:
                rendered = repr(v)
            parts.append(_shorten(rendered, 80), style=THEME.text)
        if parts.cell_len > _MAX_ARG_PREVIEW:
            parts.append(" …", style=THEME.dim)
            break
    return parts


def _fmt_result(result: Any) -> str:
    """Compact preview of a tool result for inline display."""
    if isinstance(result, str):
        text = result
    else:
        try:
            text = json.dumps(result, indent=2, default=str)
        except Exception:
            text = repr(result)
    lines = text.splitlines()
    if len(lines) > _MAX_RESULT_LINES:
        head = lines[: _MAX_RESULT_LINES]
        text = "\n".join(head) + f"\n… (+{len(lines) - _MAX_RESULT_LINES} more lines)"
    if len(text) > _MAX_RESULT_PREVIEW:
        text = text[: _MAX_RESULT_PREVIEW] + "\n…"
    return text


# ── Renderer ────────────────────────────────────────────────────────────────


class Renderer:
    """Stateful event renderer that owns a :class:`rich.console.Console`.

    Streaming assistant text uses a single ``Live`` block per turn so tokens
    fold in without flicker; tool calls / structural events print between
    turns of the live block.
    """

    def __init__(self, console: Console | None = None, *,
                 show_thinking: bool = True, pet=None,
                 plan_provider=None) -> None:
        self.console = console or Console(highlight=False, soft_wrap=True)
        self.show_thinking = show_thinking

        # Pet companion — animated in real time during a turn.
        self.pet = pet
        self._pet_state: str = "idle"
        self._pet_speech: str = ""
        self._pet_speech_at: float = 0.0
        self._pet_speech_ttl: float = 4.0   # seconds before bubble fades
        self._tick: int = 0
        self._anim_stop = threading.Event()
        self._anim_thread: threading.Thread | None = None

        # Live plan checklist. ``plan_provider`` is an optional callable that
        # returns the current plan dict (``{tasks: [...], updated_at: ...}``)
        # whenever the renderer wants to repaint. Falls back to None — the
        # checklist panel is just hidden when no plan is active.
        self._plan_provider = plan_provider
        # Plan panel visibility window: only show the panel during plan
        # mutations + briefly afterwards so it doesn't flicker on every
        # token frame. Driven by ``_show_plan_for(seconds)`` from the
        # plan_* event handlers.
        self._plan_visible_until: float = 0.0
        self._last_plan_signature: str = ""

        # In-flight tool — set on tool_call, cleared on matching tool_result.
        # Drives the spinner row in the Live region so the user sees what's
        # actually running and how long it's been running.
        self._running_tool: dict | None = None

        # A turn is rendered in three phases — "thinking", "tools", "answer".
        # Each phase is committed to scrollback when the next one begins so
        # the on-screen order matches the chronological event order.
        self._phase: str = "idle"
        self._answer_buf: list[str] = []
        self._thinking_buf: list[str] = []
        self._live: Live | None = None

        # State indicator timestamps. ``_state_started_at`` is set when
        # a turn opens; cleared when the first token/tool event arrives
        # (so the inline ``◣ ▲ ◢   Thinking… 2.3s`` only appears in the
        # dead air between user input and the first sign of life).
        # Mirrors the in-line activity indicator pattern from Claude
        # Code.
        self._state_started_at: float = 0.0
        # Optional context-aware verbs, populated by an LLM in a
        # background thread (see ``state_verbs.py``). Empty list = use
        # the static defaults from ``mark.INLINE_VERBS``.
        self._state_verbs: list[str] = []

    # ── Pet API ────────────────────────────────────────────────────────────

    def set_pet(self, pet) -> None:
        self.pet = pet
        self._tick = 0

    def update_pet_state(self, state: str, speech: str = "") -> None:
        """Switch animation state and (optionally) raise a speech bubble."""
        self._pet_state = state
        if speech:
            self._pet_speech = speech
            self._pet_speech_at = time.time()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start_turn(self) -> None:
        """Reset state and open the bottom-pinned Live with the animated pet."""
        self._phase = "idle"
        self._answer_buf = []
        self._thinking_buf = []
        self._tick = 0
        self._pet_state = "working"
        self._pet_speech = ""
        # Open the state-indicator window — inline indicator shown
        # while we're between user input and first signal of activity.
        self._state_started_at = time.time()
        # Each new turn starts fresh — clear stale LLM-generated verbs
        # from the previous turn. Caller may then call
        # ``prime_state_verbs`` to kick off a fresh background fetch.
        self._state_verbs = []

    def prime_state_verbs(self, engine, user_text: str) -> None:
        """Fire a background LLM call to fetch context-aware verbs for the
        inline indicator. Result lands in ``self._state_verbs`` once
        the call returns; until then the indicator uses static defaults.

        Cosmetic — never blocks the turn, never raises. Respects the
        ``state_verbs`` setting (off → never calls LLM) and uses
        ``state_verbs_tokens`` as the per-call token budget.
        """
        # Settings gate — when off, leave _state_verbs empty and the
        # indicator falls back to the static defaults.
        try:
            import api.settings_store as _settings
            mode = _settings.get("state_verbs", "on")
            if mode != "on":
                return
            tokens = int(_settings.get("state_verbs_tokens", 80))
        except Exception:
            tokens = 80

        try:
            from chika._cli import state_verbs as _sv
        except Exception:
            return
        history_tail = list(getattr(engine, "_history", []) or [])[-6:]

        def _on_done(verbs: list[str]) -> None:
            # Only adopt the LLM list if it returned a sensible number of
            # verbs — otherwise stay on the static defaults.
            if verbs and len(verbs) >= 3:
                self._state_verbs = verbs

        _sv.fire_and_forget(
            engine, user_text, history_tail, _on_done,
            max_tokens=tokens,
        )
        # Open a Live block immediately so the pet renders before any event
        # arrives. The renderable composes (thinking | answer) ABOVE the
        # animated pet panel; tool blocks print as scrollback above the Live.
        self._ensure_live(self._render_view())
        # Background animator: ticks frames + expires the speech bubble.
        self._anim_stop = threading.Event()
        self._anim_thread = threading.Thread(
            target=self._animate, daemon=True, name="chika-pet-animator",
        )
        self._anim_thread.start()

    def end_turn(self) -> None:
        """Stop the animator, close the Live, and clean up trailing whitespace."""
        self._state_started_at = 0.0
        self._anim_stop.set()
        if self._anim_thread is not None:
            self._anim_thread.join(timeout=0.8)
            self._anim_thread = None
        # Commit the streamed answer to scrollback BEFORE stopping the
        # Live region. Live runs in transient=True mode (so we don't
        # leak duplicate plan/pet frames), which means the answer text
        # also evaporates on stop unless we persist it ourselves.
        if self._answer_buf:
            body = "".join(self._answer_buf)
            try:
                self.console.print(Markdown(body, code_theme="monokai"))
            except Exception:
                self.console.print(Text(body, style=THEME.text))
        elif self._thinking_buf:
            # Turn ended with thinking but no answer (model timeout, hard
            # cancel, or explicit "thinking only" tool result). Surface
            # the reasoning block so the user sees what the agent
            # got to before bailing — otherwise the turn looks blank.
            body = "".join(self._thinking_buf).rstrip()
            if body:
                self._print_block(Panel(
                    Text(body, style=THEME.thinking),
                    title="thinking (no answer)",
                    title_align="left",
                    border_style=THEME.dim,
                    padding=(0, 1),
                    expand=False,
                ))
        # Pet returns to idle for the post-turn frame committed to scrollback.
        if self._pet_state not in ("celebrate", "sad"):
            self._pet_state = "idle"
        # Make sure no stale spinner survives into the next prompt — a turn
        # might end before a parallel tool's result event arrived.
        self._running_tool = None
        self._stop_live()
        if self._answer_buf:
            self.console.print()
        # Persist the plan checklist into scrollback so the conversation
        # history shows progression turn-by-turn instead of vanishing with
        # the Live region. This is the user-facing "task list persists in
        # chat" contract.
        plan_panel = self._render_plan_panel()
        if plan_panel is not None:
            self.console.print(plan_panel)
        self._phase = "idle"
        self._answer_buf = []
        self._thinking_buf = []

    # ── Animation loop ─────────────────────────────────────────────────────

    def _animate(self) -> None:
        """Tick the frame counter and fade the speech bubble in a daemon thread.

        Repaint cadence is faster while a tool is in flight (so the spinner
        glyph + elapsed-time counter feels alive) and slower when idle (so
        the pet bobbing doesn't burn CPU).
        """
        while not self._anim_stop.is_set():
            self._tick += 1
            # Speech bubble lifetime
            if self._pet_speech and (time.time() - self._pet_speech_at) > self._pet_speech_ttl:
                self._pet_speech = ""
            if self._live is not None:
                try:
                    self._live.update(self._render_view())
                except Exception:
                    pass  # Live may be stopping; safe to drop one frame
            interval = 0.12 if self._running_tool else 0.32
            self._anim_stop.wait(interval)

    # ── Event dispatch ─────────────────────────────────────────────────────

    def handle(self, event: dict) -> None:
        """Route an engine event to the right renderer method."""
        etype = event.get("type", "")
        method = getattr(self, f"_on_{etype}", None)
        if method is not None:
            method(event)
        # Unknown events are intentionally silent — most are internal.

    # ── Pet quote helper ──────────────────────────────────────────────────

    def _pet_quote(self, kind: str) -> str:
        """Pick a static personality line for ``kind`` from the active pet."""
        if self.pet is None:
            return ""
        try:
            quotes = self.pet.quotes.get(kind) or []
        except Exception:
            quotes = []
        if not quotes:
            return ""
        # Tick-driven rotation so repeated kinds cycle through options.
        return quotes[self._tick % len(quotes)]

    def _stop_live(self) -> None:
        if self._live is None:
            return
        try:
            self._live.update(self._render_view())
        finally:
            self._live.stop()
            self._live = None
        # rich.Live.stop() commits the last frame but leaves the cursor on
        # its closing row — print a blank line so the next renderable starts
        # on a fresh line.
        self.console.print()

    def _ensure_live(self, renderable) -> None:
        if self._live is None:
            # transient=True so when the Live stops, its last frame is
            # ERASED rather than baked into scrollback. Without this,
            # every _print_block (which stops + restarts the Live)
            # leaves a copy of the in-progress plan panel + pet panel
            # in the terminal history — so a 20-task plan with 10 tool
            # calls drops 10 redundant copies of the plan into the
            # user's scrollback. Tool blocks themselves commit
            # explicitly via console.print, so we don't lose anything.
            self._live = Live(
                renderable,
                console=self.console,
                refresh_per_second=12,
                transient=True,
                vertical_overflow="visible",
            )
            self._live.start()
        else:
            self._live.update(renderable)

    # ── Renderables ────────────────────────────────────────────────────────

    def _render_view(self):
        """Compose every active layer of the Live block in chronological order:
        thinking (if buffered) → answer (if streaming) → animated pet panel.
        Tool blocks are printed to scrollback ABOVE the Live by ``_print_block``.
        """
        parts: list[Any] = []

        if self.show_thinking and self._thinking_buf:
            txt = "".join(self._thinking_buf).rstrip()
            if txt:
                parts.append(Panel(
                    Text(txt, style=THEME.thinking),
                    title="thinking",
                    title_align="left",
                    border_style=THEME.dim,
                    padding=(0, 1),
                ))

        if self._answer_buf:
            body = "".join(self._answer_buf)
            try:
                parts.append(Markdown(body, code_theme="monokai"))
            except Exception:
                parts.append(Text(body, style=THEME.text))

        spinner_row = self._render_running_tool_row()
        if spinner_row is not None:
            parts.append(spinner_row)
        else:
            # State indicator only when nothing else is taking visual
            # responsibility — tool spinner (above) wins, streaming text
            # wins, but otherwise the state row fills the dead air.
            state_row = self._render_state_row()
            if state_row is not None:
                parts.append(state_row)

        plan_panel = self._render_plan_panel()
        if plan_panel is not None:
            parts.append(plan_panel)

        # Pet panel intentionally NOT rendered in the CLI — the pet
        # was clogging the vertical space inside the Live block. The
        # pet system still ships in the frontend (PetCompanion.vue);
        # the CLI surface keeps it minimal: state row + plan + tools.

        if not parts:
            parts.append(Text("", style=THEME.dim))
        return Group(*parts)

    def _show_plan_for(self, seconds: float) -> None:
        """Open the plan-panel visibility window for ``seconds`` more seconds.

        Called by plan_* event handlers so the panel surfaces briefly
        when the plan changes — and stays out of the way during plain
        token streaming, search results, etc. Pinning the window with a
        timer (instead of a boolean) makes long-running plan tools (e.g.
        an LLM-driven plan_reconcile) keep the panel visible for the
        entire duration without flicker.
        """
        deadline = time.time() + max(0.0, seconds)
        if deadline > self._plan_visible_until:
            self._plan_visible_until = deadline

    def _render_plan_panel(self):
        """Render the live plan checklist (with goal, requirements, and
        nested sub-tasks), or None when:

        - no plan is active
        - the visibility window is closed (no recent plan_* event)
        - the plan tool isn't running right now

        The window is opened by plan_* tool_call events and held open for
        a short tail after each tool_result, so the user sees the panel
        update + sees its final state, but doesn't get re-painted with
        the full plan on every token tick.
        """
        if self._plan_provider is None:
            return None
        running_plan_tool = (
            self._running_tool is not None
            and self._running_tool.get("tool", "").startswith("plan_")
        )
        # Visible iff the panel was recently opened OR a plan tool is
        # mid-flight right now.
        if not running_plan_tool and time.time() > self._plan_visible_until:
            return None
        try:
            plan = self._plan_provider()
        except Exception:
            return None
        if not isinstance(plan, dict):
            return None
        tasks = plan.get("tasks") or []
        if not tasks:
            return None

        # Glyphs by status — keep ASCII-safe so the fallback theme works.
        glyphs = {
            "done":        ("[x]", THEME.success),
            "in_progress": ("[…]", THEME.accent),
            "pending":     ("[ ]", THEME.muted),
        }

        body = Text()

        # Goal banner
        goal = (plan.get("goal") or "").strip()
        if goal:
            body.append("goal: ", style=THEME.muted)
            body.append(goal, style=f"bold {THEME.text}")
            body.append("\n")

        # Requirements list
        reqs = plan.get("requirements") or []
        if isinstance(reqs, list) and reqs:
            for req in reqs:
                body.append("  • ", style=THEME.muted)
                body.append(str(req), style=THEME.text)
                body.append("\n")
            body.append("\n")

        # Tasks (with sub-tasks indented). Use a flat counter for the
        # "done / total" summary that walks every leaf in the tree.
        leaves: list[tuple[dict, int]] = []

        def _emit(items: list, depth: int):
            for i, t in enumerate(items):
                if not isinstance(t, dict):
                    continue
                status = t.get("status") or "pending"
                glyph, glyph_style = glyphs.get(status, ("[ ]", THEME.muted))
                text_style = THEME.dim if status == "done" else THEME.text
                indent = "  " * depth
                body.append(indent)
                body.append(glyph, style=glyph_style)
                body.append("  ")
                text = (t.get("text") or "").strip() or "(empty)"
                if status == "done":
                    body.append(text, style=f"strike {text_style}")
                else:
                    body.append(text, style=text_style)
                body.append("\n")
                subs = t.get("subtasks") or []
                if subs:
                    _emit(subs, depth + 1)
                else:
                    leaves.append((t, depth))

        _emit(tasks, 0)

        # Trim final newline so the panel doesn't have a blank tail row.
        if body.plain.endswith("\n"):
            body.right_crop(1)

        done_leaves = sum(1 for t, _ in leaves if t.get("status") == "done")
        total_leaves = len(leaves) or len(tasks)

        title = Text()
        title.append("plan", style=f"bold {THEME.accent}")
        title.append(f"  ({done_leaves}/{total_leaves})", style=THEME.dim)

        return Panel(
            body,
            title=title,
            title_align="left",
            border_style=THEME.muted,
            padding=(0, 1),
            expand=False,
        )

    def _render_running_tool_row(self):
        """Single-line "running" indicator for the tool currently in flight.

        Drawn in the Live region so it updates every animator tick — gives
        the user a visible signal during long npm-create / scaffold /
        web-fetch waits where the engine would otherwise look frozen.
        """
        rt = self._running_tool
        if not rt:
            return None
        frames = THEME.spinner_frames or ("|",)
        glyph = frames[self._tick % len(frames)]
        elapsed = time.time() - rt.get("started_at", time.time())
        # Format: 0.4s, 1.2s, 12.4s, then 1m 23s once we cross a minute
        if elapsed < 60:
            elapsed_str = f"{elapsed:0.1f}s"
        else:
            mins, secs = divmod(int(elapsed), 60)
            elapsed_str = f"{mins}m {secs:02d}s"
        line = Text("  ")
        line.append(glyph, style=f"bold {THEME.accent}")
        line.append(" ", style=THEME.dim)
        line.append(rt.get("tool", "?"), style=f"bold {THEME.text}")
        # An optional 1-line hint about what the tool is doing — we set this
        # in _on_tool_call from the speech-bubble table so the user gets
        # plain English alongside the tool name.
        hint = rt.get("hint", "")
        if hint:
            line.append("  ", style=THEME.dim)
            line.append(hint, style=THEME.muted)
        line.append(f"  · {elapsed_str}", style=THEME.dim)
        return line

    def _render_state_row(self):
        """Inline animated state indicator — Claude Code's activity-line pattern.

        Renders a single line with the trefoil glyph (three triangle
        leaves at the trefoil's three petal positions, one highlighted
        per frame) followed by a present-continuous verb and an
        elapsed-time counter:

            ◣ ▲ ◢   Thinking…   2.3s

        Only visible while ``_state_started_at`` is set — i.e. between
        a user message and the first sign of activity (token, tool, or
        thinking event). Once activity arrives, the relevant handler
        clears the timestamp and this row disappears.
        """
        if not self._state_started_at:
            return None
        if self._answer_buf or self._thinking_buf:
            return None
        from chika._cli import mark as _mark

        elapsed = time.time() - self._state_started_at
        elapsed_str = (
            f"{elapsed:0.1f}s" if elapsed < 60
            else f"{int(elapsed) // 60}m {int(elapsed) % 60:02d}s"
        )

        # Inline trefoil — three triangle glyphs at the three leaf
        # positions (lower-left ◣, top ▲, lower-right ◢) so the
        # silhouette echoes the SVG mark.  Highlight rotates through
        # the leaves the same way the SVG streaming wave does.
        # ``_mark.inline_frame`` returns a logical leaf index 0..2
        # (top / right / left); we map that to display slots.
        _, _, _, hl_leaf = _mark.inline_frame(self._tick)
        # Slot order on screen: ◣(left=2) ▲(top=0) ◢(right=1)
        slot_to_leaf = {0: 2, 1: 0, 2: 1}
        slot_glyph   = ("◣", "▲", "◢")
        verbs = self._state_verbs or _mark.INLINE_VERBS
        verb = verbs[(self._tick // 18) % len(verbs)]

        line = Text("  ")
        for slot in range(3):
            leaf = slot_to_leaf[slot]
            style = (
                f"bold {THEME.accent}" if leaf == hl_leaf
                else THEME.dim
            )
            line.append(slot_glyph[slot], style=style)
            if slot < 2:
                line.append(" ", style=THEME.dim)
        line.append("   ", style=THEME.dim)
        line.append(f"{verb}…", style=f"italic {THEME.text}")
        line.append(f"   {elapsed_str}", style=THEME.dim)
        return line

    def _render_pet_panel(self):
        """Pet panel with optional speech bubble and a bobbing offset.

        The bobbing offset is purely visual: every other frame we prepend a
        single space, which (with rounded panel borders) reads as a gentle
        breathe-in / breathe-out motion.
        """
        pet = self.pet
        frame = pet.frame_for(self._pet_state, self._tick)
        # Bob: shift right by one space every other tick.
        if self._tick % 2 == 1:
            frame = "\n".join(" " + line for line in frame.splitlines())

        body_text = Text()
        if self._pet_speech:
            elapsed = time.time() - self._pet_speech_at
            opacity = max(0.0, 1.0 - (elapsed / self._pet_speech_ttl))
            bubble_style = THEME.text if opacity > 0.4 else THEME.muted
            body_text.append(f"  “ {self._pet_speech} ”\n\n",
                             style=bubble_style)
        body_text.append(frame, style=THEME.text)

        title = Text()
        title.append(pet.name, style=f"bold {pet.accent}")
        if self._pet_state and self._pet_state != "idle":
            title.append(f"  ({self._pet_state})", style=THEME.dim)

        return Panel(
            body_text,
            title=title,
            title_align="left",
            border_style=pet.accent,
            padding=(0, 1),
            expand=False,
        )

    # ── Token + thinking ───────────────────────────────────────────────────

    def _on_token(self, event: dict) -> None:
        text = event.get("text", "")
        if not text:
            return
        # First sign of life — close the state-indicator window so it
        # stops shadowing the streamed answer.
        self._state_started_at = 0.0
        # Token streaming = "answer" phase. The Live is already open and the
        # animator will repaint within ~300ms; we also push an immediate
        # update so streaming feels responsive.
        if self._phase != "answer":
            self._phase = "answer"
        self._answer_buf.append(text)
        if self._live is not None:
            self._live.update(self._render_view())

    def _on_thinking(self, event: dict) -> None:
        if not self.show_thinking:
            return
        text = event.get("text", "")
        if not text:
            return
        if self._phase != "thinking":
            self._phase = "thinking"
            self.update_pet_state("thinking", speech=self._pet_quote("thinking"))
        self._thinking_buf.append(text)
        if self._live is not None:
            self._live.update(self._render_view())

    def _on_thinking_end(self, _event: dict) -> None:
        # Commit the thinking text to scrollback BEFORE clearing the
        # buffer — the rich.Live region runs in transient mode, so its
        # last frame is erased on stop. Without an explicit print here
        # the panel disappears as soon as the next phase begins, and a
        # turn that ends with thinking-only (model timeout, hard cancel)
        # leaves no visible record at all.
        if self._phase == "thinking":
            body = "".join(self._thinking_buf).rstrip()
            self._stop_live()
            if body:
                self.console.print(Panel(
                    Text(body, style=THEME.thinking),
                    title="thinking",
                    title_align="left",
                    border_style=THEME.dim,
                    padding=(0, 1),
                    expand=False,
                ))
            self._thinking_buf = []
            self._phase = "idle"
            self._ensure_live(self._render_view())

    # ── Workflow / step events ────────────────────────────────────────────

    def _print_block(self, *renderables: Any) -> None:
        """Commit the current Live, print to scrollback, then reopen the Live.

        Reopening keeps the pet animating while subsequent tool blocks land
        between the streamed content. Without the reopen the pet would
        vanish for the rest of the turn after the first tool call.
        """
        was_live = self._live is not None
        if was_live:
            self._stop_live()
        # Clear the thinking buffer once thinking is committed to scrollback,
        # so it doesn't redraw inside the next Live frame.
        if self._phase == "thinking":
            self._thinking_buf = []
            self._phase = "idle"
        self.console.print(*renderables)
        if was_live:
            self._ensure_live(self._render_view())

    def _on_workflow_start(self, event: dict) -> None:
        name = event.get("name") or event.get("workflow_id") or "workflow"
        self.update_pet_state("working", speech=self._pet_quote("working"))
        # Workflow header carries the chika brand: a small trefoil leaf
        # glyph next to the name. Single ▲ (top leaf) keeps it
        # readable without crowding the rule.
        title = Text()
        title.append(" ▲ ", style=f"bold {THEME.accent}")
        title.append(f"{name} ", style=f"bold {THEME.accent}")
        self._print_block(Rule(title, style=THEME.dim, characters="─"))

    def _on_workflow_done(self, _event: dict) -> None:
        if self._pet_state != "sad":
            self.update_pet_state("celebrate", speech=self._pet_quote("celebrate"))
        self._print_block(Rule(style=THEME.dim, characters="─"))

    def _on_step_start(self, event: dict) -> None:
        step_type = event.get("step_type", "")
        step_id = event.get("step_id", "")
        if step_type in ("sequential", "parallel", "pipeline", "fan_out",
                         "conditional", "loop", "map", "retry", "sub_workflow"):
            # Chevron + step type in muted, id in dim — reads as a
            # quiet structural marker, not a label.
            line = Text("  ", end="")
            line.append("▸ ", style=THEME.muted)
            line.append(step_type, style=f"bold {THEME.muted}")
            line.append(f"  {step_id}", style=THEME.dim)
            self._print_block(line)

    # ── Tools ──────────────────────────────────────────────────────────────

    def _on_tool_call(self, event: dict) -> None:
        tool = event.get("tool", "?")
        args = event.get("args", {}) or {}

        # Tool firing = activity — close the state-indicator window so
        # the spinner row takes over visual responsibility.
        self._state_started_at = 0.0

        # Pet narrates which tool is firing — short, in-character bubble.
        bubble = _TOOL_BUBBLES.get(tool, f"using {tool}…")
        self.update_pet_state("working", speech=bubble)

        # Track the in-flight call so the spinner row in the Live region
        # can show a live elapsed-time counter while the tool runs.
        self._running_tool = {
            "tool":       tool,
            "step_id":    event.get("step_id", ""),
            "started_at": time.time(),
            "hint":       _TOOL_BUBBLES.get(tool, ""),
        }

        # Plan-mutating tools open the plan-panel visibility window so
        # the user actually sees the change land.
        if tool.startswith("plan_"):
            self._show_plan_for(8.0)

        # Distinct treatment for skill_load so the user can audit how
        # often the agent is consulting SKILL.md docs vs. winging it.
        if tool == "skill_load":
            skill_name = args.get("skill", "?")
            header = Text("  ")
            header.append("📚 ", style=THEME.accent)
            header.append("skill_load", style=f"bold {THEME.accent}")
            header.append("  → ", style=THEME.dim)
            header.append(skill_name, style=f"bold {THEME.text}")
            self._print_block(header)
            return

        header = Text()
        header.append(f"{THEME.tool_glyph} ", style=THEME.accent)
        header.append(tool, style=f"bold {THEME.text}")
        header.append("  ", style=THEME.dim)
        header.append(_fmt_args(args))
        self._print_block(header)

    def _on_tool_result(self, event: dict) -> None:
        tool = event.get("tool", "")
        err = event.get("error")
        result = event.get("result", "")
        duration_ms = event.get("duration_ms", 0)

        # Clear the in-flight indicator if this result matches the tracked
        # call. Match on step_id (preferred — survives parallel workflows)
        # and fall back to tool name when step_id is missing.
        rt = self._running_tool
        if rt is not None:
            same_step = rt.get("step_id") and rt["step_id"] == event.get("step_id")
            same_tool_no_step = (not rt.get("step_id")) and rt.get("tool") == tool
            if same_step or same_tool_no_step:
                self._running_tool = None

        # Plan tool finished — keep the panel visible briefly so the user
        # sees the update land, then let it fade out of the live view.
        if tool.startswith("plan_"):
            self._show_plan_for(4.0)

        if err:
            self.update_pet_state("sad", speech=self._pet_quote("sad") or "that broke")

        # Distinct rendering for skill_load result — a bordered audit panel
        # so the user can SEE that the doc was read and how big it was.
        if tool == "skill_load" and not err and isinstance(result, dict):
            self._print_block(self._render_skill_load_panel(result, duration_ms))
            return

        body = Text("  ", end="")
        body.append(f"{THEME.result_glyph} ", style=THEME.dim)
        if err:
            body.append("x ", style=f"bold {THEME.error}")
            body.append(_shorten(str(err), 200), style=THEME.error)
            # Surface known structured-error hints so the user (and
            # operator reading scrollback) sees what to actually do
            # next, instead of a single opaque error name.
            if isinstance(result, dict):
                hint = result.get("hint")
                fix_command = result.get("fix_command")
                tried = result.get("tried") or []
                log_tail = result.get("log_tail")
                if fix_command:
                    body.append("\n     fix: ", style=THEME.dim)
                    body.append(str(fix_command), style=f"bold {THEME.warn}")
                if tried:
                    body.append("\n     tried: ", style=THEME.dim)
                    body.append(", ".join(map(str, tried)), style=THEME.muted)
                if hint:
                    body.append("\n     hint: ", style=THEME.dim)
                    body.append(_shorten(str(hint), 240), style=THEME.muted)
                if log_tail:
                    body.append("\n     log: ", style=THEME.dim)
                    body.append(_shorten(str(log_tail), 240), style=THEME.muted)
        else:
            # Per-tool compact summary first; fall back to JSON dump if
            # no formatter is registered or the formatter declines.
            from chika._cli import tool_summaries as _summaries
            summary = _summaries.summarise(tool, result)
            if summary:
                body.append(summary, style=THEME.text)
            else:
                preview = _fmt_result(result)
                first, _, rest = preview.partition("\n")
                body.append(first, style=THEME.text)
                if rest:
                    rest_text = Text("\n" + "\n".join(
                        "    " + line for line in rest.splitlines()
                    ), style=THEME.muted)
                    body.append(rest_text)
        if duration_ms:
            body.append(f"  ({duration_ms}ms)", style=THEME.dim)
        self._print_block(body)

    def _render_skill_load_panel(self, result: dict, duration_ms: int):
        """Bordered audit panel showing that a SKILL.md was loaded."""
        skill_name = result.get("skill", "?")
        chars = result.get("char_count", 0)
        condensed = result.get("condensed", False)
        path = result.get("path", "")

        body = Text()
        body.append("path:        ", style=THEME.muted)
        body.append(f"{path}\n", style=THEME.text)
        body.append("size:        ", style=THEME.muted)
        body.append(f"{chars:,} chars", style=THEME.text)
        if condensed:
            body.append("  (condensed via 2nd LLM call)\n",
                        style=f"italic {THEME.warn}")
        else:
            body.append("  (verbatim)\n", style=THEME.dim)
        if duration_ms:
            body.append("duration:    ", style=THEME.muted)
            body.append(f"{duration_ms}ms\n", style=THEME.text)

        title = Text()
        title.append("📚 SKILL.md  ", style=f"bold {THEME.accent}")
        title.append(skill_name, style=f"bold {THEME.text}")

        return Panel(
            body,
            title=title,
            title_align="left",
            border_style=THEME.accent,
            padding=(0, 1),
            expand=False,
        )

    # ── Variables / loops / approvals / misc ──────────────────────────────

    def _on_variable_set(self, event: dict) -> None:
        name = event.get("name", "?")
        var_type = event.get("var_type", "?")
        size = event.get("size_bytes", 0)
        # Visual hierarchy: chevron + $name in accent + type/size dim.
        # Reads like a "stored" annotation, not a debug log line.
        line = Text("  ", end="")
        line.append("▸ ", style=f"bold {THEME.accent}")
        line.append(f"${name}", style=f"bold {THEME.text}")
        line.append(f"  {var_type}", style=THEME.muted)
        line.append(f" · {size}B", style=THEME.dim)
        self._print_block(line)

    def _on_loop_iteration(self, event: dict) -> None:
        i = event.get("iteration", 0)
        m = event.get("max", 0)
        self._print_block(Text(
            f"  {THEME.loop_glyph} loop {i}/{m}", style=THEME.muted,
        ))

    def _on_map_item(self, event: dict) -> None:
        i = event.get("index", 0) + 1
        m = event.get("total", 0)
        self._print_block(Text(
            f"  {THEME.map_glyph} map {i}/{m}", style=THEME.muted,
        ))

    def _on_retry_attempt(self, event: dict) -> None:
        a = event.get("attempt", 0)
        m = event.get("max", 0)
        reason = event.get("reason") or ""
        line = Text(f"  {THEME.retry_glyph} retry {a}/{m}", style=THEME.warn)
        if reason:
            line.append("  ")
            line.append(_shorten(reason, 60), style=THEME.dim)
        self._print_block(line)

    def _on_condition_eval(self, event: dict) -> None:
        """Show conditional branch decisions inline so the user sees
        which path the workflow took (true/false or named branch).
        """
        result = event.get("result")
        expr = event.get("expression") or event.get("step_id") or ""
        if result is True:
            glyph, style = "✓", THEME.success
            label = "true"
        elif result is False:
            glyph, style = "✗", THEME.error
            label = "false"
        else:
            glyph, style = "⑂", THEME.muted
            label = str(result)
        line = Text(f"  {glyph} ", style=style)
        line.append(label, style=f"bold {style}")
        if expr:
            line.append("  ")
            line.append(_shorten(str(expr), 60), style=THEME.dim)
        self._print_block(line)

    def _on_compaction(self, event: dict) -> None:
        removed = event.get("removed", 0)
        kept = event.get("kept", 0)
        self._print_block(Text(
            f"  {THEME.bullet_glyph} compacted history (-{removed}, kept {kept})",
            style=THEME.muted,
        ))

    def _on_auto_continue(self, event: dict) -> None:
        # Commit the current turn's answer to scrollback BEFORE the next
        # turn starts streaming. Without this, the next turn's tokens
        # append to the same _answer_buf and the live view repaints
        # the previous answer + the new one merged together — exactly
        # the "messages duplicating" symptom the user reported.
        self._commit_answer_to_scrollback()

        depth = event.get("depth", 1)
        cap = event.get("max", 10)
        line = Text("  ", end="")
        line.append("↻ ", style=THEME.accent)
        line.append("auto-continue", style=f"bold {THEME.accent}")
        line.append(f"  ({depth}/{cap}) — agent promised more work, firing another turn",
                    style=THEME.muted)
        self._print_block(line)

    def _commit_answer_to_scrollback(self) -> None:
        """Flush the streamed answer buffer to the terminal scrollback
        and reset for the next turn.

        Called between auto-continue turns so the previous turn's text
        doesn't visually concatenate with the next turn's stream. Mirrors
        the same logic ``end_turn`` runs at end-of-chat.
        """
        if not self._answer_buf:
            return
        body = "".join(self._answer_buf)
        was_live = self._live is not None
        if was_live:
            self._stop_live()
        try:
            self.console.print(Markdown(body, code_theme="monokai"))
        except Exception:
            self.console.print(Text(body, style=THEME.text))
        self._answer_buf = []
        self._phase = "idle"
        if was_live:
            self._ensure_live(self._render_view())

    def _on_auto_continue_blocked(self, event: dict) -> None:
        """Visible diagnostic when the agent promised more work but the
        engine refused to fire another turn (cap hit, setting off, etc.).
        Without this the conversation just stops with no signal — the
        user thinks the agent is broken when it's actually waiting."""
        reason = event.get("reason", "blocked")
        line = Text("  ", end="")
        line.append(f"{THEME.warn_glyph} ", style=THEME.warn)
        line.append("auto-continue blocked", style=f"bold {THEME.warn}")
        line.append(f" — {reason}", style=THEME.muted)
        self._print_block(line)

    def _on_chat_title(self, event: dict) -> None:
        title = event.get("title", "")
        if title:
            self._print_block(Text(
                f"  {THEME.bullet_glyph} title: {title}", style=THEME.dim,
            ))

    def _on_validation_warning(self, event: dict) -> None:
        msg = event.get("message", "ungrounded claim detected")
        self._print_block(Text(
            f"  {THEME.warn_glyph} {msg}", style=THEME.warn,
        ))

    def _on_retry_notice(self, event: dict) -> None:
        msg = event.get("message", "")
        self._print_block(Text(
            f"  {THEME.retry_glyph} {msg}", style=THEME.warn,
        ))

    def _on_error(self, event: dict) -> None:
        msg = event.get("message", "unknown error")
        self.update_pet_state("sad", speech=self._pet_quote("sad") or "something broke")
        was_live = self._live is not None
        if was_live:
            self._stop_live()
        self.console.print(Panel(
            Text(msg, style=THEME.error),
            title="error",
            title_align="left",
            border_style=THEME.error,
            padding=(0, 1),
        ))
        if was_live:
            self._ensure_live(self._render_view())

    def _on_cancelled(self, _event: dict) -> None:
        self._stop_live()
        # Filled square = stop, gives the cancel state real weight
        # rather than a thin bullet that reads like normal output.
        line = Text("  ", end="")
        line.append("■ ", style=f"bold {THEME.warn}")
        line.append("stopped", style=THEME.warn)
        self.console.print(line)

    # ── Approvals / questions ─────────────────────────────────────────────

    def _on_approval_required(self, event: dict) -> None:
        # In the WS path the server sends this; in CLI we don't see it because
        # the engine is owned locally and approvals are wired elsewhere.
        # Render as a notice for visibility.
        tool = event.get("tool", "?")
        msg = event.get("message", f"Approve {tool}?")
        # Diamond glyph + accent label gives approval prompts visual
        # weight so the user immediately notices an action is needed.
        line = Text("  ", end="")
        line.append("◇ ", style=f"bold {THEME.accent}")
        line.append("approval  ", style=f"bold {THEME.text}")
        line.append(msg, style=THEME.muted)
        self._print_block(line)

    # ── Browser / extension events ────────────────────────────────────────

    def _on_browser_watch_trigger(self, event: dict) -> None:
        """A registered DOM watcher fired — surface what changed."""
        name = event.get("event_name") or "watch"
        data = event.get("data") or {}
        sel  = data.get("selector") or ""
        cur  = data.get("current")
        prev = data.get("previous")
        line = Text()
        line.append(f"  {THEME.warn_glyph} watch fired: ", style=THEME.warn)
        line.append(name, style=f"bold {THEME.text}")
        if sel:
            line.append("  ")
            line.append(_shorten(sel, 60), style=THEME.dim)
        if cur is not None or prev is not None:
            line.append("  ")
            if prev is not None:
                line.append(_shorten(str(prev), 28), style=THEME.dim)
                line.append(" → ", style=THEME.muted)
            line.append(_shorten(str(cur), 28), style=THEME.text)
        self._print_block(line)

    def _on_extension_status(self, event: dict) -> None:
        """Show when the Chrome extension pairs / unpairs."""
        ok = bool(event.get("connected"))
        glyph = "●" if ok else "○"
        text = "extension paired" if ok else "extension disconnected"
        style = THEME.accent if ok else THEME.dim
        self._print_block(Text(f"  {glyph} {text}", style=style))


# ── One-off renderers (used by slash commands) ─────────────────────────────


def render_banner(console: Console, *, version: str, provider: str, model: str) -> None:
    """Welcome banner shown at startup.

    The chika brand mark renders at the top — same trefoil as the SVG
    in ``frontend/src/components/ChikaMark.vue``, rasterised to
    half-block characters by ``chika._cli.mark``. Single static frame:
    terminal grids don't carry the SVG's per-leaf flip animation
    meaningfully, but the static silhouette is in faithful parity.
    """
    from chika._cli.mark import get_frame as _mark_frame

    mark = Text(_mark_frame("idle"), style=f"bold {THEME.accent}")

    title = Text()
    title.append("chika ", style=f"bold {THEME.accent}")
    title.append(f"v{version}", style=THEME.muted)

    body = Text()
    body.append("\nThe agentic AI assistant — ", style=THEME.text)
    body.append("Chika CLI", style=f"italic {THEME.accent}")
    body.append(".\n\n", style=THEME.text)
    body.append("type ", style=THEME.muted)
    body.append("/help", style=f"bold {THEME.accent}")
    body.append(" for commands · ", style=THEME.muted)
    body.append("/quit", style=f"bold {THEME.accent}")
    body.append(" to exit\n", style=THEME.muted)
    body.append("\nprovider: ", style=THEME.dim)
    body.append(provider, style=THEME.text)
    body.append("   model: ", style=THEME.dim)
    body.append(model, style=THEME.text)

    console.print(Panel(
        Group(mark, Text(""), title, body),
        border_style=THEME.accent,
        padding=(1, 2),
    ))


def render_status_line(console: Console, **fields: str) -> None:
    """Compact one-line status footer printed before the next prompt."""
    parts: list[str] = []
    for k, v in fields.items():
        if not v:
            continue
        parts.append(f"[dim]{k}[/dim] [white]{v}[/white]")
    console.print("  · ".join(parts), style=THEME.muted, soft_wrap=True)


def render_pet(console: Console, pet, state: str = "idle",
               tick: int = 0, speech: str = "") -> None:
    """Print a small pet panel — used between turns and in /pet output.

    Optional ``speech`` text shows above the frame as a tiny speech bubble.
    """
    frame = pet.frame_for(state, tick)
    title = Text()
    title.append(pet.name, style=f"bold {pet.accent}")
    if state and state != "idle":
        title.append(f"  ({state})", style=THEME.dim)

    body_lines: list[str] = []
    if speech:
        # Render as a simple bubble with leading quote dash.
        bubble = f'  ❝ {speech} ❞'.replace("❝", '"').replace("❞", '"')
        body_lines.append(bubble)
        body_lines.append("")
    body_lines.append(frame)
    console.print(Panel(
        Text("\n".join(body_lines), style=THEME.text),
        title=title,
        title_align="left",
        border_style=pet.accent,
        padding=(0, 1),
        expand=False,
    ))


def render_kv_table(console: Console, title: str, rows: list[tuple[str, str]],
                    *, value_style: str | None = None) -> None:
    """Print a two-column table of key → value (used by /settings, /env etc)."""
    table = Table(
        title=Text(title, style=f"bold {THEME.accent}"),
        title_justify="left",
        show_header=False,
        box=None,
        padding=(0, 2),
    )
    table.add_column(style=THEME.muted, no_wrap=True)
    table.add_column(style=value_style or THEME.text, overflow="fold")
    for k, v in rows:
        table.add_row(k, v)
    console.print(table)


def render_json_block(console: Console, data: Any, *, lang: str = "json") -> None:
    """Pretty-print JSON / data with syntax highlighting."""
    try:
        text = json.dumps(data, indent=2, default=str)
    except Exception:
        text = str(data)
    console.print(Syntax(text, lang, theme="monokai", background_color="default"))
