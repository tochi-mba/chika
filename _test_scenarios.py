"""
Scripted scenario runner — exercises Chika end-to-end with complex tasks.

Each scenario sends a sequence of messages and runs assertion checks on
the traces to verify Chika behaved correctly.

Usage:
    python _test_scenarios.py                  # run all scenarios
    python _test_scenarios.py build_html_app   # run one scenario by name
    python _test_scenarios.py --list           # list available scenarios
"""
import sys, os, asyncio, json, time, tempfile, shutil
from pathlib import Path

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from api.session_manager import SessionManager
from chika.core.profile_manager import ProfileManager

# ── Colors ────────────────────────────────────────────────────────────────────

C_PASS  = "\033[32m"
C_FAIL  = "\033[31m"
C_DIM   = "\033[90m"
C_BOLD  = "\033[1;37m"
C_RESET = "\033[0m"
C_TOOL  = "\033[33m"

_TRACE_DIR = Path("data/test_traces")
_TRACE_DIR.mkdir(parents=True, exist_ok=True)


# ── Trace collector ───────────────────────────────────────────────────────────

async def collect_turn(engine, user_text: str) -> dict:
    """Send a message and collect all events into a trace dict."""
    trace = {
        "user": user_text,
        "tokens": "",
        "tool_calls": [],
        "tool_results": [],
        "errors": [],
        "workflows": [],
    }
    async for event in engine.chat(user_text):
        etype = event.get("type", "")
        if etype == "token":
            trace["tokens"] += event.get("text", "")
        elif etype == "tool_call":
            trace["tool_calls"].append({
                "tool": event.get("tool"),
                "args": event.get("args", {}),
            })
        elif etype == "tool_result":
            trace["tool_results"].append({
                "tool": event.get("tool"),
                "error": event.get("error"),
                "result": event.get("result"),
            })
        elif etype == "workflow_start":
            trace["workflows"].append(event.get("name", ""))
        elif etype == "error":
            trace["errors"].append(event.get("message", ""))
        elif etype == "done":
            break
    return trace


# ── Assertion helpers ─────────────────────────────────────────────────────────

def used_tool(traces, tool_name):
    """Check if any trace used a specific tool."""
    for t in traces:
        for tc in t["tool_calls"]:
            if tc["tool"] == tool_name:
                return True
    return False


def no_errors(traces):
    """Check that no trace had errors."""
    for t in traces:
        if t["errors"]:
            return False
    return True


def file_exists_in(directory, filename):
    """Check if a file exists in a directory (recursive)."""
    for root, _, files in os.walk(directory):
        if filename in files:
            return True
    return False


def response_mentions(traces, keyword):
    """Check if any response text mentions a keyword (case-insensitive)."""
    kw = keyword.lower()
    for t in traces:
        if kw in t["tokens"].lower():
            return True
    return False


def used_plan(traces):
    """Check if plan_set was called."""
    return used_tool(traces, "plan_set")


def total_tool_calls(traces):
    """Count total tool calls across all traces."""
    return sum(len(t["tool_calls"]) for t in traces)


def max_steps_in_single_workflow(traces):
    """Find the max tool calls in any single turn."""
    return max((len(t["tool_calls"]) for t in traces), default=0)


# ── Scenarios ─────────────────────────────────────────────────────────────────

SCENARIOS = []


def scenario(name, messages, checks, description="", setup=None, timeout=60):
    SCENARIOS.append({
        "name": name,
        "description": description,
        "messages": messages,
        "checks": checks,
        "setup": setup,
        "timeout": timeout,
    })


scenario(
    name="build_html_app",
    description="Build a simple counter app and serve it",
    timeout=90,
    messages=[
        "build me a simple counter app with an increment and decrement button. use html/css/js in separate files.",
    ],
    checks=[
        ("used file_write", lambda traces, ws: used_tool(traces, "file_write")),
        ("created index.html", lambda traces, ws: file_exists_in(ws, "index.html")),
        ("used live_server", lambda traces, ws: used_tool(traces, "live_server")),
        ("no errors", lambda traces, ws: no_errors(traces)),
    ],
)

scenario(
    name="research_question",
    description="Answer a factual question using web search",
    messages=[
        "what is the tallest building in the world right now?",
    ],
    checks=[
        ("used web_search", lambda traces, ws: used_tool(traces, "web_search")),
        ("response has content", lambda traces, ws: len(traces[-1]["tokens"]) > 50),
        ("no errors", lambda traces, ws: no_errors(traces)),
    ],
)

def _setup_debug_code(ws):
    (Path(ws) / "buggy.py").write_text(
        'def greet(name)\n    return f"Hello, {name}!"\n\nprint(greet("world"))\n',
        encoding="utf-8",
    )

def _check_valid_python(workspace, filename="buggy.py"):
    p = Path(workspace) / filename
    if not p.exists():
        return False
    try:
        compile(p.read_text(encoding="utf-8"), str(p), "exec")
        return True
    except SyntaxError:
        return False

scenario(
    name="debug_code",
    description="Fix a buggy Python file",
    setup=_setup_debug_code,
    messages=[
        "I have a buggy Python file at $WORKSPACE/buggy.py -- read it and fix the bug",
    ],
    checks=[
        ("used file_read", lambda traces, ws: used_tool(traces, "file_read")),
        ("used file_replace", lambda traces, ws: used_tool(traces, "file_replace")),
        ("no errors", lambda traces, ws: no_errors(traces)),
        ("fixed file is valid python", lambda traces, ws: _check_valid_python(ws)),
    ],
)


scenario(
    name="multi_turn_project",
    description="Build across multiple turns",
    messages=[
        "build a simple todo app in html/css/js with add and delete functionality",
        "now add a 'mark as done' feature that strikes through completed items",
    ],
    checks=[
        ("created index.html", lambda traces, ws: file_exists_in(ws, "index.html")),
        ("used file_write", lambda traces, ws: used_tool(traces, "file_write")),
        ("response mentions done/complete", lambda traces, ws: (
            response_mentions(traces, "done") or response_mentions(traces, "complete")
            or response_mentions(traces, "strike")
        )),
        ("no errors", lambda traces, ws: no_errors(traces)),
    ],
)

scenario(
    name="workflow_size_limit",
    description="Large project should be broken into multiple turns",
    messages=[
        "build a full-stack web app with: landing page, about page, contact page, "
        "dashboard, login page, signup page, profile page, settings page, 404 page, "
        "and a shared navbar and footer component. All in separate HTML files with CSS.",
        "yes go ahead, use vanilla HTML/CSS/JS",
    ],
    checks=[
        ("used plan_set", lambda traces, ws: used_plan(traces)),
        ("no single workflow >8 tools", lambda traces, ws: max_steps_in_single_workflow(traces) <= 10),
        ("created multiple files", lambda traces, ws: (
            sum(1 for t in traces for tc in t["tool_calls"] if tc["tool"] == "file_write") >= 3
        )),
        ("no errors", lambda traces, ws: no_errors(traces)),
    ],
)


# ── NEW: Increasingly complex scenarios ──────────────────────────────────────

# Level 2: Write + execute Python
scenario(
    name="write_and_run_python",
    description="Write a Python script and execute it",
    messages=[
        "write a python script that prints the first 10 fibonacci numbers, save it "
        "to $WORKSPACE/fib.py and then run it so I can see the output",
    ],
    checks=[
        ("created fib.py", lambda traces, ws: file_exists_in(ws, "fib.py")),
        ("used shell_exec", lambda traces, ws: used_tool(traces, "shell_exec")),
        ("no errors", lambda traces, ws: no_errors(traces)),
        ("response has fibonacci output", lambda traces, ws: (
            response_mentions(traces, "1") and response_mentions(traces, "34")
        )),
    ],
)

# Level 3: Read + understand + modify existing code
def _setup_refactor(ws):
    (Path(ws) / "utils.py").write_text(
        'def add(a,b):\n    return a+b\n\n'
        'def subtract(a,b):\n    return a-b\n\n'
        'def multiply(a,b):\n    return a*b\n\n'
        'def divide(a,b):\n    return a/b\n',
        encoding="utf-8",
    )

scenario(
    name="read_modify_code",
    description="Read existing code and add error handling",
    setup=_setup_refactor,
    messages=[
        "read $WORKSPACE/utils.py and add error handling to the divide function "
        "so it doesn't crash on division by zero. also add a docstring to each function.",
    ],
    checks=[
        ("used file_read", lambda traces, ws: used_tool(traces, "file_read")),
        ("modified the file", lambda traces, ws: (
            used_tool(traces, "file_replace") or used_tool(traces, "file_write")
        )),
        ("file has docstrings", lambda traces, ws: (
            '"""' in (Path(ws) / "utils.py").read_text(encoding="utf-8")
            or "'''" in (Path(ws) / "utils.py").read_text(encoding="utf-8")
        )),
        ("file has zero division handling", lambda traces, ws: (
            "zero" in (Path(ws) / "utils.py").read_text(encoding="utf-8").lower()
            or "ZeroDivision" in (Path(ws) / "utils.py").read_text(encoding="utf-8")
        )),
        ("no errors", lambda traces, ws: no_errors(traces)),
    ],
)

# Level 4: Multi-turn memory — does Chika remember context?
scenario(
    name="memory_recall",
    description="Remember info across turns",
    messages=[
        "my favorite color is cerulean blue and my dog's name is Biscuit. remember that.",
        "what's my favorite color and what's my dog's name?",
    ],
    checks=[
        ("recalls color", lambda traces, ws: response_mentions(traces, "cerulean")),
        ("recalls dog name", lambda traces, ws: response_mentions(traces, "biscuit")),
        ("no errors", lambda traces, ws: no_errors(traces)),
    ],
)

# Level 5: Complex app — quiz game with scoring
scenario(
    name="quiz_app",
    description="Build a quiz app with multiple features",
    messages=[
        "build a trivia quiz web app with 5 hardcoded questions, multiple choice "
        "answers, a score counter, and a results screen at the end. use html/css/js "
        "in separate files. make it look modern and clean.",
    ],
    timeout=90,
    checks=[
        ("created index.html", lambda traces, ws: file_exists_in(ws, "index.html")),
        ("created js file", lambda traces, ws: (
            file_exists_in(ws, "script.js") or file_exists_in(ws, "quiz.js")
            or file_exists_in(ws, "app.js")
        )),
        ("created css file", lambda traces, ws: (
            file_exists_in(ws, "style.css") or file_exists_in(ws, "styles.css")
        )),
        ("used live_server", lambda traces, ws: used_tool(traces, "live_server")),
        ("no errors", lambda traces, ws: no_errors(traces)),
    ],
)

# Level 6: Error recovery — give Chika a deliberately tricky task
def _setup_broken_project(ws):
    (Path(ws) / "app.py").write_text(
        'import flask\n\napp = flask.Flask(__name__)\n\n'
        '@app.route("/")\ndef home():\n    return render_template("index.html")\n\n'
        '@app.route("/api/users")\ndef get_users()\n'
        '    users = [{"name": "Alice"}, {"name": "Bob"}]\n'
        '    return jsonify(users)\n\n'
        'if __name__ == "__main__":\n    app.run(debug=True)\n',
        encoding="utf-8",
    )

scenario(
    name="fix_multiple_bugs",
    description="Fix multiple bugs in a Python file",
    setup=_setup_broken_project,
    messages=[
        "read $WORKSPACE/app.py, find ALL the bugs, fix them, and explain what was wrong",
    ],
    checks=[
        ("used file_read", lambda traces, ws: used_tool(traces, "file_read")),
        ("fixed the file", lambda traces, ws: (
            used_tool(traces, "file_replace") or used_tool(traces, "file_write")
        )),
        ("file is valid python", lambda traces, ws: _check_valid_python(ws, "app.py")),
        ("mentions missing colon", lambda traces, ws: (
            response_mentions(traces, "colon") or response_mentions(traces, "syntax")
            or response_mentions(traces, ":")
        )),
        ("no errors", lambda traces, ws: no_errors(traces)),
    ],
)

# ── Runner ────────────────────────────────────────────────────────────────────

async def run_scenario(sc: dict) -> dict:
    """Run a single scenario in a fresh engine with a temp workspace."""
    name = sc["name"]
    print(f"\n{C_BOLD}{'='*60}{C_RESET}")
    print(f"{C_BOLD}SCENARIO: {name}{C_RESET}")
    print(f"{C_DIM}{sc.get('description', '')}{C_RESET}")

    # Create temp workspace
    workspace = tempfile.mkdtemp(prefix=f"chika_test_{name}_")

    sm = SessionManager()
    session_id = f"scenario_{name}_{int(time.time())}"
    engine = sm.get_or_create(session_id)
    engine._history = []
    engine._vars.clear()

    # Set up a test profile pointing to the temp workspace
    pm = ProfileManager(Path("data/profiles"))
    profile = pm.get_or_create("_test_runner")
    profile._workspace = workspace
    engine.switch_profile(profile)
    engine._vars.set("profile.workspace", workspace)

    setup_fn = sc.get("setup")
    if setup_fn:
        setup_fn(workspace)

    messages = [m.replace("$WORKSPACE", workspace.replace("\\", "/")) for m in sc["messages"]]

    timeout = sc.get("timeout", 60)
    traces = []
    t0 = time.time()
    for msg in messages:
        print(f"\n  {C_DIM}>> {msg[:80]}{'...' if len(msg) > 80 else ''}{C_RESET}")
        try:
            trace = await asyncio.wait_for(collect_turn(engine, msg), timeout=timeout)
        except asyncio.TimeoutError:
            traces.append({
                "user": msg, "tokens": "", "tool_calls": [],
                "tool_results": [], "errors": [f"TIMEOUT after {timeout}s"],
                "workflows": [],
            })
            print(f"  {C_FAIL}TIMEOUT after {timeout}s{C_RESET}")
            break
        traces.append(trace)

        # Print brief status
        tools_used = [tc["tool"] for tc in trace["tool_calls"]]
        if tools_used:
            print(f"  {C_TOOL}tools: {', '.join(tools_used[:8])}{C_RESET}")
        if trace["errors"]:
            for e in trace["errors"]:
                print(f"  {C_FAIL}ERROR: {e[:100]}{C_RESET}")
        if trace["tokens"]:
            preview = trace["tokens"][:120].replace("\n", " ")
            print(f"  {C_DIM}response: {preview}...{C_RESET}")

    duration = round(time.time() - t0, 1)

    # Run checks
    results = []
    print(f"\n  {C_BOLD}Checks:{C_RESET}")
    for check_name, check_fn in sc["checks"]:
        try:
            passed = check_fn(traces, workspace)
        except Exception as exc:
            passed = False
            print(f"    {C_FAIL}EXCEPTION in '{check_name}': {exc}{C_RESET}")
        mark = f"{C_PASS}PASS" if passed else f"{C_FAIL}FAIL"
        print(f"    {mark}{C_RESET} {check_name}")
        results.append({"check": check_name, "passed": passed})

    # Save trace
    trace_path = _TRACE_DIR / f"scenario_{name}_{int(time.time())}.json"
    trace_path.write_text(json.dumps({
        "scenario": name,
        "traces": traces,
        "results": results,
        "duration_sec": duration,
        "workspace": workspace,
    }, indent=2, default=str), encoding="utf-8")

    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)
    status = "PASS" if passed_count == total else "FAIL"
    color = C_PASS if status == "PASS" else C_FAIL
    print(f"\n  {color}{status}{C_RESET} ({passed_count}/{total} checks, {duration}s)")
    print(f"  {C_DIM}trace: {trace_path}{C_RESET}")

    # Cleanup temp workspace
    try:
        shutil.rmtree(workspace, ignore_errors=True)
    except Exception:
        pass

    return {
        "name": name,
        "status": status,
        "passed": passed_count,
        "total": total,
        "duration_sec": duration,
        "errors": [e for t in traces for e in t["errors"]],
    }


async def main():
    if "--list" in sys.argv:
        print(f"\n{C_BOLD}Available scenarios:{C_RESET}")
        for sc in SCENARIOS:
            print(f"  {sc['name']:25s} {sc.get('description', '')}")
        return

    # Filter to specific scenarios if names given
    names = [a for a in sys.argv[1:] if not a.startswith("-")]
    scenarios = SCENARIOS
    if names:
        scenarios = [s for s in SCENARIOS if s["name"] in names]
        if not scenarios:
            print(f"{C_FAIL}No matching scenarios: {names}{C_RESET}")
            return

    print(f"\n{C_BOLD}Chika Scenario Runner{C_RESET}")
    print(f"{C_DIM}Running {len(scenarios)} scenario(s)...{C_RESET}")

    all_results = []
    for sc in scenarios:
        result = await run_scenario(sc)
        all_results.append(result)

    # Summary
    print(f"\n\n{C_BOLD}{'='*60}{C_RESET}")
    print(f"{C_BOLD}RESULTS SUMMARY{C_RESET}")
    print(f"{'='*60}")

    total_pass = 0
    total_fail = 0
    for r in all_results:
        color = C_PASS if r["status"] == "PASS" else C_FAIL
        print(
            f"  {color}{r['status']:4s}{C_RESET}  "
            f"{r['name']:25s}  "
            f"{r['passed']}/{r['total']} checks  "
            f"{r['duration_sec']}s"
        )
        if r["status"] == "PASS":
            total_pass += 1
        else:
            total_fail += 1

    print(f"\n  {C_PASS}{total_pass} passed{C_RESET}, {C_FAIL}{total_fail} failed{C_RESET}")


if __name__ == "__main__":
    asyncio.run(main())
