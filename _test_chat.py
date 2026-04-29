"""
Interactive Chika test harness — REPL for manual testing and iteration.

Usage:
    python _test_chat.py                    # fresh session, default profile
    python _test_chat.py --profile zoe      # fresh session, specific profile
    python _test_chat.py --resume           # resume last session
    python _test_chat.py "hello" "do X"     # non-interactive: run these prompts and exit
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from api.session_manager import SessionManager
from chika.core.compactor import estimate_tokens

_TRACE_DIR = Path("data/test_traces")
_TRACE_DIR.mkdir(parents=True, exist_ok=True)

# ── Colors ────────────────────────────────────────────────────────────────────

C_USER    = "\033[36m"
C_CHIKA   = "\033[35m"
C_TOOL    = "\033[33m"
C_OK      = "\033[32m"
C_ERR     = "\033[31m"
C_DIM     = "\033[90m"
C_BOLD    = "\033[1;37m"
C_RESET   = "\033[0m"


async def chat_turn(engine, user_text: str) -> dict:
    """Send one message and collect all events into a trace dict."""
    print(f"\n{C_USER}━━━ YOU ━━━{C_RESET}  {user_text}")
    trace = {
        "user": user_text,
        "thinking": "",
        "tokens": "",
        "tool_calls": [],
        "tool_results": [],
        "warnings": [],
        "errors": [],
        "workflows": [],
        "duration_sec": 0.0,
        "history_tokens": estimate_tokens(engine._history),
    }
    t0 = time.time()

    async for event in engine.chat(user_text):
        etype = event.get("type", "")

        if etype == "thinking":
            trace["thinking"] += event.get("text", "")
        elif etype == "token":
            txt = event.get("text", "")
            trace["tokens"] += txt
            print(txt, end="", flush=True)
        elif etype == "tool_call":
            tc = {
                "tool": event.get("tool"),
                "args_preview": json.dumps(event.get("args", {}), default=str)[:200],
            }
            trace["tool_calls"].append(tc)
            print(f"\n  {C_TOOL}-> {tc['tool']}{C_RESET}  {tc['args_preview']}")
        elif etype == "tool_result":
            r = event.get("result")
            tr = {
                "tool": event.get("tool"),
                "error": event.get("error"),
                "preview": (json.dumps(r, default=str)[:200] if r is not None else ""),
            }
            trace["tool_results"].append(tr)
            mark = f"{C_ERR}x" if tr["error"] else f"{C_OK}ok"
            print(f"  {mark} {tr['tool']}{C_RESET}  {tr['preview'][:120]}")
        elif etype == "workflow_start":
            trace["workflows"].append(event.get("name", event.get("workflow_id", "")))
            print(f"  {C_DIM}[workflow: {event.get('name', '')}]{C_RESET}")
        elif etype == "validation_warning":
            trace["warnings"].append({"reason": event.get("reason"), "urls": event.get("urls")})
            print(f"  {C_ERR}! {event.get('reason', 'warning')}{C_RESET}")
        elif etype == "error":
            trace["errors"].append(event.get("message", ""))
            print(f"\n  {C_ERR}ERROR: {event.get('message', '')}{C_RESET}")
        elif etype == "compaction":
            print(f"  {C_DIM}[compacted {event.get('removed', '?')} messages]{C_RESET}")
        elif etype == "chat_title":
            print(f"  {C_DIM}[title: {event.get('title', '')}]{C_RESET}")
        elif etype == "done":
            break

    trace["duration_sec"] = round(time.time() - t0, 2)

    if trace["tokens"] and not trace["tokens"].endswith("\n"):
        print()

    if trace["thinking"]:
        print(f"{C_DIM}[thinking: {len(trace['thinking'])} chars]{C_RESET}")

    post_tokens = estimate_tokens(engine._history)
    print(
        f"{C_DIM}[{trace['duration_sec']}s | "
        f"{len(trace['tool_calls'])} tools | "
        f"history: {trace['history_tokens']} -> {post_tokens} tokens]{C_RESET}"
    )
    return trace


def save_trace(traces: list[dict], session_id: str) -> Path:
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = _TRACE_DIR / f"trace_{session_id}_{ts}.json"
    path.write_text(json.dumps(traces, indent=2, default=str), encoding="utf-8")
    return path


async def interactive_loop(engine, session_id: str):
    """REPL loop: read user input, chat, repeat."""
    traces: list[dict] = []
    print(f"\n{C_BOLD}Chika Test Harness{C_RESET}")
    print(f"{C_DIM}Session: {session_id}")
    print(f"Profile: {engine._active_profile.name if engine._active_profile else '?'}")
    print(f"History: {len(engine._history)} messages")
    print(f"Type 'quit' to exit, 'reset' to clear history, 'save' to save trace{C_RESET}\n")

    while True:
        try:
            user_input = input(f"{C_USER}> {C_RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            break
        if user_input.lower() == "reset":
            engine.reset()
            engine._history.clear()
            traces.clear()
            print(f"{C_DIM}[reset]{C_RESET}")
            continue
        if user_input.lower() == "save":
            p = save_trace(traces, session_id)
            print(f"{C_DIM}[saved {len(traces)} turns to {p}]{C_RESET}")
            continue

        trace = await chat_turn(engine, user_input)
        traces.append(trace)

    if traces:
        p = save_trace(traces, session_id)
        print(f"\n{C_DIM}[auto-saved {len(traces)} turns to {p}]{C_RESET}")


async def main():
    parser = argparse.ArgumentParser(description="Chika interactive test harness")
    parser.add_argument("prompts", nargs="*", help="Non-interactive prompts to run")
    parser.add_argument("--profile", default=None, help="Profile to use")
    parser.add_argument("--resume", action="store_true", help="Resume last session")
    parser.add_argument("--session", default=None, help="Session ID to use")
    args = parser.parse_args()

    sm = SessionManager()
    session_id = args.session or ("iter_session" if args.resume else f"test_{int(time.time())}")
    engine = sm.get_or_create(session_id)

    if not args.resume:
        engine._history = []
        engine._vars.clear()

    if args.profile:
        from chika.core.profile_manager import ProfileManager
        pm = ProfileManager(Path("data/profiles"))
        profile = pm.get_or_create(args.profile)
        engine.switch_profile(profile)

    if args.prompts:
        traces = []
        for p in args.prompts:
            traces.append(await chat_turn(engine, p))
        path = save_trace(traces, session_id)
        print(f"\n{C_BOLD}━━━ SUMMARY ━━━{C_RESET}")
        for i, t in enumerate(traces, 1):
            status = f"{C_ERR}ERRORS" if t["errors"] else f"{C_OK}OK"
            print(
                f"  [{i}] '{t['user'][:60]}' -> "
                f"{len(t['tool_calls'])} tools, "
                f"{len(t['warnings'])} warns, "
                f"{t['duration_sec']}s "
                f"{status}{C_RESET}"
            )
        print(f"{C_DIM}[trace: {path}]{C_RESET}")
    else:
        await interactive_loop(engine, session_id)


if __name__ == "__main__":
    asyncio.run(main())
