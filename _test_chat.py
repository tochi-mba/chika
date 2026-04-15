"""Live chika chat harness — keep iterating."""
import sys, asyncio, json, time
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from api.session_manager import SessionManager


async def chat(engine, user_text: str) -> dict:
    print(f"\n\033[36m━━━ YOU ━━━\033[0m  {user_text}")
    trace = {"user": user_text, "thinking": "", "tokens": "",
             "tool_calls": [], "tool_results": [], "warnings": [], "duration_sec": 0.0}
    t0 = time.time()
    async for event in engine.chat(user_text):
        t = event.get("type", "")
        if t == "thinking":
            trace["thinking"] += event.get("text", "")
        elif t == "token":
            trace["tokens"] += event.get("text", "")
        elif t == "tool_call":
            trace["tool_calls"].append({
                "tool": event.get("tool"),
                "args_preview": json.dumps(event.get("args", {}), default=str)[:140],
            })
        elif t == "tool_result":
            r = event.get("result")
            trace["tool_results"].append({
                "tool": event.get("tool"),
                "error": event.get("error"),
                "preview": (json.dumps(r, default=str)[:180] if r is not None else ""),
            })
        elif t == "validation_warning":
            trace["warnings"].append({"reason": event.get("reason"), "urls": event.get("urls")})
        elif t == "done":
            break
    trace["duration_sec"] = round(time.time() - t0, 2)
    if trace["thinking"]:
        print(f"\033[90m[thinking {len(trace['thinking'])} chars]\033[0m")
    for tc in trace["tool_calls"]:
        print(f"  \033[33m→ {tc['tool']}\033[0m  {tc['args_preview']}")
    for tr in trace["tool_results"]:
        mark = "✗" if tr["error"] else "✓"
        print(f"  \033[32m{mark} {tr['tool']}\033[0m  {tr['preview']}")
    for w in trace["warnings"]:
        print(f"  \033[31m⚠ {w['reason']}\033[0m")
    print(f"\033[35m━━━ CHIKA ━━━\033[0m  {trace['tokens']}")
    print(f"\033[90m[{trace['duration_sec']}s | {len(trace['tool_calls'])} tools]\033[0m")
    return trace


async def main():
    sm = SessionManager()
    engine = sm.get_or_create("iter_session")
    engine._history = []
    engine._vars.clear()
    prompts = sys.argv[1:] if len(sys.argv) > 1 else ["hi"]
    traces = [await chat(engine, p) for p in prompts]
    print("\n\033[1;37m━━━━━━ SUMMARY ━━━━━━\033[0m")
    for i, t in enumerate(traces, 1):
        print(f"[{i}] '{t['user'][:60]}' → {len(t['tool_calls'])} tools, "
              f"{len(t['warnings'])} warns, {t['duration_sec']}s")


if __name__ == "__main__":
    asyncio.run(main())
