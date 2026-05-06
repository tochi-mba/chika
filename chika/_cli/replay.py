"""``chika replay <session_id>`` — replay a recorded session.

Reads the NDJSON at ``data/sessions/<id>.jsonl`` and dispatches each
event to a chosen surface handler. Useful for:

  - Debugging a session a user reported (run their session through
    your CLI without re-calling the LLM)
  - Demos (the "look how the surfaces stay in sync" pitch becomes
    a one-line repro)
  - Regression testing — record a real session, replay it as a fixture
    in the test suite

Surface modes
-------------
- ``cli`` (default) — dispatch through ``chika._cli.renderer.Renderer.handle``
- ``raw`` — print each event as JSON to stdout (good for grep / piping)
- ``count`` — just count events by type (sanity check the recording)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from api.event_log import list_sessions, load_events, replay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chika replay",
        description="Replay a recorded session.",
    )
    parser.add_argument(
        "session_id", nargs="?",
        help="Session id to replay. Omit to list known sessions.",
    )
    parser.add_argument(
        "--surface", choices=("cli", "raw", "count"), default="cli",
        help="Where to dispatch events (default: cli).",
    )
    parser.add_argument(
        "--root", type=Path, default=None,
        help="Override sessions/ root (tests).",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List known session ids and exit.",
    )
    args = parser.parse_args(argv)

    if args.list or not args.session_id:
        sessions = list_sessions(args.root)
        if not sessions:
            print("no recorded sessions yet (run a chat turn first).")
            return 0
        print("recorded sessions:")
        for s in sessions:
            print(f"  · {s}")
        return 0

    events = load_events(args.session_id, args.root)
    if not events:
        print(f"no events recorded for session {args.session_id!r}.", file=sys.stderr)
        return 1

    if args.surface == "raw":
        return _replay_raw(events)
    if args.surface == "count":
        return _replay_count(events)
    return _replay_cli(events)


def _replay_raw(events: list[dict[str, Any]]) -> int:
    n = 0
    for ev in events:
        print(json.dumps(ev, separators=(",", ":")))
        n += 1
    return 0


def _replay_count(events: list[dict[str, Any]]) -> int:
    counts: dict[str, int] = {}
    for ev in events:
        etype = str(ev.get("type", "?"))
        counts[etype] = counts.get(etype, 0) + 1
    width = max((len(t) for t in counts), default=0)
    for etype in sorted(counts):
        print(f"  {etype:<{width}}  {counts[etype]}")
    print(f"  total: {sum(counts.values())} events / {len(counts)} types")
    return 0


def _replay_cli(events: list[dict[str, Any]]) -> int:
    """Dispatch through the CLI Renderer."""
    try:
        from rich.console import Console

        from chika._cli.renderer import Renderer
    except Exception as exc:
        print(f"chika replay --surface cli requires rich: {exc}", file=sys.stderr)
        return 2
    console = Console(highlight=False, soft_wrap=True)
    renderer = Renderer(console=console, show_thinking=True, pet=None, plan_provider=None)
    renderer.start_turn()
    try:
        n = replay(events, renderer.handle, skip_internal=True)
    finally:
        renderer.end_turn()
    print(f"  · replayed {n} events", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
