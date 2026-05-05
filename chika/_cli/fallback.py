"""Plain-text CLI fallback used when ``rich`` isn't installed.

Mirrors the original Chika v2 CLI behaviour bit-for-bit so existing scripts
that pipe stdin/stdout into ``chika`` keep working.
"""
from __future__ import annotations

import json


def _fmt_event(event: dict) -> str | None:
    t = event.get("type", "")
    if t == "token":
        return event["text"]
    if t == "workflow_start":
        return f"\n[workflow: {event['name']}]\n"
    if t == "step_start":
        return f"  [{event['step_type']}] {event['step_id']}\n"
    if t == "tool_call":
        args_str = json.dumps(event.get("args", {}))[:80]
        return f"  → {event['tool']}({args_str}…)\n"
    if t == "tool_result":
        result_str = str(event.get("result", ""))[:120]
        err = event.get("error")
        tag = "✗" if err else "✓"
        return f"  {tag} {event['tool']}: {err or result_str}\n"
    if t == "variable_set":
        return f"  ${event['name']} = {event['var_type']} ({event['size_bytes']}B)\n"
    if t == "loop_iteration":
        return f"  ↻ loop iter {event['iteration']}/{event['max']}\n"
    if t == "workflow_done":
        return "[workflow done]\n"
    if t == "compaction":
        return f"\n[history compacted: -{event['removed']} msgs]\n"
    if t == "error":
        return f"\n[error: {event['message']}]\n"
    if t == "done":
        return "\n"
    return None


async def run_plain() -> None:
    from api.session_manager import session_manager

    engine = session_manager.get_or_create("cli")
    print("Chika v2 — type to chat, Ctrl+C to quit\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break
        if not user_input:
            continue

        print("Chika: ", end="", flush=True)
        try:
            async for event in engine.chat(user_input):
                etype = event.get("type", "")
                if etype.startswith("_"):
                    continue
                if etype == "cancelled":
                    print("\n[stopped]", end="")
                    continue
                out = _fmt_event(event)
                if out:
                    print(out, end="", flush=True)
        except (RuntimeError, KeyboardInterrupt) as e:
            if isinstance(e, KeyboardInterrupt):
                engine.cancel()
                print("\n[stopped]")
            else:
                print(f"\n\n[error] {e}\n")
            continue

        print()
