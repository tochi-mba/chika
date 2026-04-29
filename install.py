#!/usr/bin/env python3
"""
Chika — interactive setup wizard.
Run: python install.py
"""

import sys
import os
import subprocess
import shutil
import getpass
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent

# ── ANSI colours ──────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"

def c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"

def ok(msg: str)   -> None: print(f"  {c(GREEN,  '✓')}  {msg}")
def err(msg: str)  -> None: print(f"  {c(RED,    '✗')}  {msg}")
def info(msg: str) -> None: print(f"  {c(BLUE,   '·')}  {msg}")
def warn(msg: str) -> None: print(f"  {c(YELLOW, '!')}  {msg}")
def step(n: int, total: int, msg: str) -> None:
    print(f"\n{c(BOLD+WHITE, f'[{n}/{total}]')} {c(BOLD, msg)}")

def rule(char: str = "─", width: int = 60) -> None:
    print(c(DIM, char * width))

def banner() -> None:
    print()
    print(c(BOLD + CYAN, "  ██████╗██╗  ██╗██╗██╗  ██╗ █████╗ "))
    print(c(BOLD + CYAN, " ██╔════╝██║  ██║██║██║ ██╔╝██╔══██╗"))
    print(c(BOLD + CYAN, " ██║     ███████║██║█████╔╝ ███████║"))
    print(c(BOLD + CYAN, " ██║     ██╔══██║██║██╔═██╗ ██╔══██║"))
    print(c(BOLD + CYAN, " ╚██████╗██║  ██║██║██║  ██╗██║  ██║"))
    print(c(BOLD + CYAN, "  ╚═════╝╚═╝  ╚═╝╚═╝╚═╝  ╚═╝╚═╝  ╚═╝"))
    print()
    print(c(DIM, "  Agentic AI assistant with browser control"))
    print(c(DIM, "  github.com/tochi-mba/chika"))
    print()
    rule()
    print()

# ── Helpers ───────────────────────────────────────────────────────────────────

def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{c(DIM, default)}]" if default else ""
    val = input(f"  {c(CYAN, '?')}  {prompt}{suffix}: ").strip()
    return val or default

def ask_secret(prompt: str) -> str:
    return getpass.getpass(f"  {c(CYAN, '?')}  {prompt}: ")

def ask_choice(prompt: str, choices: list[tuple[str, str]], default: int = 1) -> str:
    """Display a numbered menu and return the chosen value."""
    print(f"\n  {c(BOLD, prompt)}")
    for i, (key, label) in enumerate(choices, 1):
        marker = c(CYAN, "▶") if i == default else " "
        print(f"    {marker} {c(BOLD, str(i))}.  {label}")
    print()
    while True:
        raw = input(f"  {c(CYAN, '?')}  Enter number [{c(DIM, str(default))}]: ").strip()
        if not raw:
            return choices[default - 1][0]
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1][0]
        warn("Please enter a valid number.")

def ask_yn(prompt: str, default: bool = True) -> bool:
    hint = c(DIM, "Y/n" if default else "y/N")
    raw = input(f"  {c(CYAN, '?')}  {prompt} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")

def run(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    kwargs: dict = {"check": True}
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return subprocess.run(cmd, **kwargs)

# ── Steps ─────────────────────────────────────────────────────────────────────

TOTAL_STEPS = 5

def check_python() -> None:
    step(1, TOTAL_STEPS, "Checking Python version")
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        err(f"Python 3.11+ required — you have {major}.{minor}")
        sys.exit(1)
    ok(f"Python {major}.{minor}")

    if not shutil.which("pip"):
        err("pip not found. Install pip and re-run.")
        sys.exit(1)
    ok("pip found")


def install_deps() -> None:
    step(2, TOTAL_STEPS, "Installing dependencies")
    req = ROOT / "requirements.txt"
    if not req.exists():
        warn("requirements.txt not found — skipping.")
        return
    print(c(DIM, f"\n  Running: pip install -r requirements.txt\n"))
    try:
        run([sys.executable, "-m", "pip", "install", "-r", str(req), "--quiet"])
        ok("All dependencies installed")
    except subprocess.CalledProcessError:
        err("pip install failed. Fix the errors above and re-run.")
        sys.exit(1)

    # Register the `chika` CLI command so users can run it from anywhere
    print(c(DIM, "\n  Running: pip install -e .  (registers the `chika` command)\n"))
    try:
        run([sys.executable, "-m", "pip", "install", "-e", str(ROOT), "--quiet"])
        ok("`chika` command registered — type `chika` anywhere to start the REPL")
    except subprocess.CalledProcessError:
        warn("Could not register `chika` command. You can still run: python chika.py")


def configure_env() -> None:
    step(3, TOTAL_STEPS, "Configuring environment")

    env_path = ROOT / ".env"
    if env_path.exists():
        warn(".env already exists.")
        if not ask_yn("Overwrite it?", default=False):
            ok("Keeping existing .env")
            return

    provider = ask_choice(
        "Which LLM provider will you use?",
        [
            ("anthropic", "Anthropic  (Claude — recommended)"),
            ("openai",    "OpenAI     (GPT-4o / GPT-4.1)"),
            ("azure",     "Azure OpenAI"),
            ("ollama",    "Ollama     (local / free — requires Ollama installed)"),
        ],
    )

    lines: list[str] = [
        "# Generated by install.py — edit anytime\n",
        f"CHIKA_PROVIDER={provider}\n",
        "\n",
    ]

    if provider == "anthropic":
        print()
        info("Get your key at: console.anthropic.com → API Keys")
        key = ask_secret("Anthropic API key (sk-ant-…)")
        model = ask("Model", default="claude-sonnet-4-6")
        lines += [
            f"ANTHROPIC_API_KEY={key}\n",
            f"ANTHROPIC_MODEL={model}\n",
        ]

    elif provider == "openai":
        print()
        info("Get your key at: platform.openai.com → API Keys")
        key = ask_secret("OpenAI API key (sk-…)")
        model = ask("Model", default="gpt-4o")
        lines += [
            f"OPENAI_API_KEY={key}\n",
            f"OPENAI_MODEL={model}\n",
        ]

    elif provider == "azure":
        print()
        key      = ask_secret("Azure OpenAI API key")
        endpoint = ask("Azure endpoint (https://…openai.azure.com/)")
        deploy   = ask("Deployment name", default="gpt-4o")
        lines += [
            f"AZURE_OPENAI_ENDPOINT={endpoint}\n",
            f"AZURE_OPENAI_KEY={key}\n",
            f"AZURE_OPENAI_DEPLOYMENT={deploy}\n",
            "AZURE_API_VERSION=2024-10-21\n",
        ]

    elif provider == "ollama":
        print()
        info("Make sure Ollama is running: ollama serve")
        info("Recommended models: llama3.1, qwen2.5, deepseek-r1")
        model    = ask("Model", default="llama3.1")
        base_url = ask("Ollama URL", default="http://localhost:11434/v1")
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
            info(f"Appended /v1 → {base_url}")
        lines += [
            f"OLLAMA_MODEL={model}\n",
            f"OLLAMA_BASE_URL={base_url}\n",
        ]
        if not shutil.which("ollama"):
            print()
            warn("ollama command not found on PATH.")
            info("Download at: ollama.com/download")
            info(f"Then run: ollama pull {model}")
        else:
            print()
            info(f"Pulling {model} (this may take a few minutes)…")
            try:
                run(["ollama", "pull", model])
                ok(f"{model} ready")
            except subprocess.CalledProcessError:
                warn(f"Could not pull {model} — run `ollama pull {model}` manually")

    lines += [
        "\n# Engine settings\n",
        "CHIKA_MAX_HISTORY_TOKENS=10000\n",
        "CHIKA_MAX_WORKFLOW_STEPS=8\n",
        "CHIKA_MAX_TOOL_TURNS=20\n",
        "CHIKA_THINKING=true\n",
        "CHIKA_VALIDATE_RESPONSE=true\n",
        "CHIKA_HOST=0.0.0.0\n",
        "CHIKA_PORT=8000\n",
        "CHIKA_API_KEY=\n",
    ]

    env_path.write_text("".join(lines), encoding="utf-8")
    ok(f".env written → {env_path}")


def build_frontend() -> None:
    frontend = ROOT / "frontend"
    dist     = frontend / "dist"

    if dist.exists():
        ok("Frontend already built")
        return

    node = shutil.which("node")
    npm  = shutil.which("npm") or shutil.which("npm.cmd")

    if not node or not npm:
        warn("Node.js not found — skipping frontend build.")
        info("Install Node 18+ from nodejs.org, then run:")
        info("  cd frontend && npm install && npm run build")
        return

    print(c(DIM, "\n  Running: npm install\n"))
    try:
        subprocess.run([npm, "install"], cwd=str(frontend), check=True)
        print(c(DIM, "\n  Running: npm run build\n"))
        subprocess.run([npm, "run", "build"], cwd=str(frontend), check=True)
        ok("Frontend built → frontend/dist/")
    except subprocess.CalledProcessError:
        err("Frontend build failed.")
        warn("Run manually: cd frontend && npm install && npm run build")


def verify_setup() -> None:
    step(4, TOTAL_STEPS, "Verifying setup")
    try:
        result = run(
            [sys.executable, "-c", "from api.session_manager import session_manager; print('ok')"],
            capture=True,
        )
        if "ok" in result.stdout:
            ok("Core imports working")
        else:
            raise RuntimeError("unexpected output")
    except Exception as e:
        err(f"Import check failed: {e}")
        warn("Try running manually: python api/server.py")


def print_extension_instructions() -> None:
    step(5, TOTAL_STEPS, "Extension setup")
    ext_path = (ROOT / "extension").resolve()
    print()
    print(c(BOLD, "  Load the Chrome extension (one-time, takes 60 seconds):"))
    print()
    steps = [
        ("Open Chrome and go to",         c(CYAN + BOLD, "chrome://extensions")),
        ("Enable",                          c(BOLD, "Developer mode") + c(DIM, "  (toggle, top-right corner)")),
        ("Click",                           c(BOLD, "Load unpacked")),
        ("Select this folder:",             c(CYAN, str(ext_path))),
        ("Click the",                       c(BOLD, "Chika") + " icon in your toolbar → " + c(BOLD, "Options")),
        ("Server URL should be",            c(CYAN + BOLD, "http://localhost:8000") + c(DIM, "  (already set)")),
        ("Click",                           c(BOLD, "Test connection") + c(DIM, "  — should show ") + c(GREEN, "Connected!")),
    ]
    for i, (label, value) in enumerate(steps, 1):
        print(f"    {c(BOLD+CYAN, str(i)+'.')}  {label} {value}")
    print()

    print(c(DIM, "  ─────────────────────────────────────────────────"))
    print()
    print(c(BOLD, "  Firefox / Edge?"))
    print(c(DIM,  "  Edge:    edge://extensions → same steps as Chrome"))
    print(c(DIM,  "  Firefox: about:debugging → This Firefox → Load Temporary Add-on"))
    print(c(DIM,  "           → select extension/manifest.json"))
    print()


def configure_spotify(env_path: Path) -> None:
    print()
    rule("─", 60)
    print()
    print(c(BOLD, "  Spotify setup"))
    print()
    print(c(DIM,  "  You'll need a free Spotify Developer app (2 minutes):"))
    print()
    steps = [
        ("Go to",       c(CYAN + BOLD, "developer.spotify.com/dashboard")),
        ("Click",       c(BOLD, "Create app")),
        ("App name:",   c(DIM, "anything, e.g. 'Chika'")),
        ("Redirect URI — add exactly:", c(CYAN, "http://localhost:8000/auth/spotify/callback")),
        ("Copy your",   c(BOLD, "Client ID") + " and " + c(BOLD, "Client Secret")),
    ]
    for i, (label, value) in enumerate(steps, 1):
        print(f"    {c(BOLD+CYAN, str(i)+'.')}  {label} {value}")
    print()

    client_id     = ask("Client ID")
    client_secret = ask_secret("Client Secret")

    if not client_id or not client_secret:
        warn("Skipping Spotify — you can add these to .env later:")
        info("CHIKA_SPOTIFY_CLIENT_ID=...")
        info("CHIKA_SPOTIFY_CLIENT_SECRET=...")
        return

    # Append to existing .env
    with env_path.open("a", encoding="utf-8") as f:
        f.write(
            "\n# Spotify\n"
            f"CHIKA_SPOTIFY_CLIENT_ID={client_id}\n"
            f"CHIKA_SPOTIFY_CLIENT_SECRET={client_secret}\n"
            "CHIKA_SPOTIFY_REDIRECT_URI=http://localhost:8000/auth/spotify/callback\n"
        )

    ok("Spotify credentials saved to .env")
    print()
    print(c(DIM, "  After the server starts, complete OAuth once:"))
    print(f"    {c(CYAN + BOLD, 'http://localhost:8000/auth/spotify')}")
    print(c(DIM, "  Tokens are saved automatically — you won't need to do this again."))


def print_start_instructions(start_now: bool) -> None:
    rule()
    print()
    print(c(BOLD + GREEN, "  Chika is ready!"))
    print()
    if not start_now:
        print(c(BOLD, "  Start the server:"))
        print()
        if sys.platform == "win32":
            print(c(CYAN, "    .\\start.ps1"))
            print(c(DIM,  "    — or —"))
            print(c(CYAN, "    python api/server.py"))
        else:
            print(c(CYAN, "    python api/server.py"))
        print()

    print(c(BOLD, "  Then open:"))
    print()
    print(c(CYAN + BOLD, "    http://localhost:8000"))
    print()
    print(c(DIM,  "  CLI mode (no browser needed):"))
    print(c(CYAN, "    chika"))
    print(c(DIM,  "  (or `python chika.py` if the command isn't on PATH yet)"))
    print()
    rule()
    print()


def start_server() -> None:
    server = ROOT / "api" / "server.py"
    if not server.exists():
        err("api/server.py not found")
        return
    print()
    info("Starting server on http://localhost:8000  (Ctrl+C to stop)")
    print()
    try:
        os.execv(sys.executable, [sys.executable, str(server)])
    except Exception as e:
        err(f"Could not start server: {e}")
        warn(f"Run manually: python {server}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Windows: enable ANSI codes
    if sys.platform == "win32":
        os.system("color")

    banner()

    check_python()
    install_deps()
    configure_env()
    verify_setup()

    if ask_yn("Build the web frontend? (requires Node 18+)", default=True):
        build_frontend()

    print_extension_instructions()

    if ask_yn("Set up Spotify integration?", default=False):
        env_path = ROOT / ".env"
        if env_path.exists():
            configure_spotify(env_path)
        else:
            warn(".env not found — run configure step first")

    start_now = ask_yn("Start Chika server now?", default=True)
    print_start_instructions(start_now)

    if start_now:
        start_server()


if __name__ == "__main__":
    main()
