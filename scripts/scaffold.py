"""Project-aware code scaffolders.

Adding a new skill / tool / event type / ADR all touch multiple files
in conventional patterns. ``scripts/scaffold.py`` collapses each into
a single command, with the templates kept consistent with whatever
the latest convention is.

Subcommands:

    python scripts/scaffold.py skill <name>        — new chika/skills/<name>_skill/
    python scripts/scaffold.py tool <name>         — new tool stub + registration
    python scripts/scaffold.py event <name>        — new EventType + Pydantic model + routing
    python scripts/scaffold.py adr <title>         — new ADR template appended to DECISIONS.md

Each generates real, runnable code (not just an empty file) and
prints a short next-steps message. Idempotent: re-running with the
same name aborts with a clear error rather than overwriting.

DX rule
-------
Every scaffolder produces test-passing code from the moment it's
generated. The contributor's first run after scaffolding should be
``pytest`` and it should pass. We add a smoke-test stub for every
new artefact so the suite size goes up, not down, with new
contributions.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Skill scaffolder ─────────────────────────────────────────────────


_SKILL_INIT_TEMPLATE = '''"""{title} — chika skill bundle.

Brief one-line summary of what this skill does. The agent reads
``SKILL.md`` for the full picture; this docstring is for human
contributors browsing the package.
"""
from __future__ import annotations

# Tools live alongside this file. Register them with the engine via
# the standard pattern in chika/tools/__init__.py:
#
#   from chika.skills.{name}_skill.{name}_tool import {pascal}_tool
#   register_tool({pascal}_tool)
#
# See any shipped skill's __init__.py for a working example.
'''

_SKILL_MD_TEMPLATE = '''# {title}

<!--
  This SKILL.md is the deep doc the agent loads on demand via
  ``skill_load("{name}_skill")`` or ``skill_query``. The committed
  one-paragraph summary at ``data/skill_summaries/{name}_skill.json``
  is what lives in the agent's system prompt every turn.

  After editing this file, regenerate the summary:
      python scripts/regenerate_skill_summaries.py --skill {name}_skill
-->

## Purpose

One-sentence description of what this skill does in active voice.

## When to use

- Concrete scenario where this skill is the right tool.
- Another scenario.
- A third scenario.

## Tools

| Tool | What it does |
|---|---|
| (todo) | (todo) |

## When NOT to use

- Boundary case where a sibling skill is better.

## Examples

```
(todo: real example call shapes the agent will produce)
```
'''

_SKILL_TEST_TEMPLATE = '''"""Tests for the {name}_skill package."""
from __future__ import annotations

import importlib


def test_skill_package_imports():
    """Smoke: the skill package imports without errors."""
    importlib.import_module("chika.skills.{name}_skill")


def test_skill_md_present():
    """Every skill must ship a SKILL.md (the agent reads it)."""
    from pathlib import Path

    p = Path(__file__).resolve().parent.parent / "chika" / "skills" / "{name}_skill" / "SKILL.md"
    assert p.is_file()
    assert p.stat().st_size > 0
'''


def scaffold_skill(name: str) -> int:
    name = _slug(name)
    if not name:
        print("skill name must contain at least one letter", file=sys.stderr)
        return 2
    pkg_name = f"{name}_skill"
    pkg_dir = REPO_ROOT / "chika" / "skills" / pkg_name
    if pkg_dir.exists():
        print(f"already exists: {pkg_dir}", file=sys.stderr)
        return 1

    title = name.replace("_", " ").title()
    pascal = "".join(p.title() for p in name.split("_"))

    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text(
        _SKILL_INIT_TEMPLATE.format(title=title, name=name, pascal=pascal),
        encoding="utf-8",
    )
    (pkg_dir / "SKILL.md").write_text(
        _SKILL_MD_TEMPLATE.format(title=title, name=name),
        encoding="utf-8",
    )
    test_path = REPO_ROOT / "tests" / f"test_{pkg_name}.py"
    if not test_path.exists():
        test_path.write_text(
            _SKILL_TEST_TEMPLATE.format(name=name),
            encoding="utf-8",
        )

    print(f"✓ created {pkg_dir.relative_to(REPO_ROOT)}/")
    print("  · __init__.py")
    print("  · SKILL.md")
    print(f"  · tests/test_{pkg_name}.py")
    print()
    print("Next steps:")
    print(f"  1. Edit chika/skills/{pkg_name}/SKILL.md")
    print("  2. Add tools (see any shipped skill folder for the pattern)")
    print("  3. Skills auto-register via the discovery walk — no edits to "
          "api/session_manager.py needed.")
    print(f"  4. python scripts/regenerate_skill_summaries.py --skill {pkg_name}")
    return 0


# ── Tool scaffolder ──────────────────────────────────────────────────


_TOOL_TEMPLATE = '''"""{title} tool."""
from __future__ import annotations

from typing import Any

from chika.tools._registry import register_tool


@register_tool
def {name}(arg: str = "") -> dict[str, Any]:
    """{title} — replace this docstring with what the tool actually does.

    The first line is what the LLM sees in the tool catalogue. Be
    crisp and concrete. Bad: "Helps with X." Good: "Returns the SHA
    of HEAD as a 7-char hex string."
    """
    # TODO: implement
    return {{"ok": True, "echo": arg}}
'''

_TOOL_TEST_TEMPLATE = '''"""Tests for the ``{name}`` tool."""
from __future__ import annotations


def test_{name}_smoke():
    from chika.tools.{name}_tool import {name}
    out = {name}("hello")
    assert isinstance(out, dict)
    assert out.get("ok") is True
'''


def scaffold_tool(name: str) -> int:
    name = _slug(name)
    if not name:
        print("tool name must contain at least one letter", file=sys.stderr)
        return 2
    title = name.replace("_", " ").title()

    tool_path = REPO_ROOT / "chika" / "tools" / f"{name}_tool.py"
    if tool_path.exists():
        print(f"already exists: {tool_path}", file=sys.stderr)
        return 1

    tool_path.write_text(
        _TOOL_TEMPLATE.format(title=title, name=name),
        encoding="utf-8",
    )
    test_path = REPO_ROOT / "tests" / f"test_{name}_tool.py"
    if not test_path.exists():
        test_path.write_text(
            _TOOL_TEST_TEMPLATE.format(name=name),
            encoding="utf-8",
        )

    print(f"✓ created {tool_path.relative_to(REPO_ROOT)}")
    print(f"  · tests/test_{name}_tool.py")
    print()
    print("Next steps:")
    print(f"  1. Implement chika/tools/{name}_tool.py")
    print("  2. Add to TOOL_CATEGORY_MAP in api/settings_store.py if it needs a permission category")
    print("  3. Add to the relevant skill's SKILL.md (and regenerate the summary)")
    return 0


# ── EventType scaffolder ─────────────────────────────────────────────


def scaffold_event(name: str) -> int:
    """Add a new event type to api/models.py + event_routing.py.

    The contract is enforced by tests/test_event_contract.py — every
    EventType must be in at least one routing set. This scaffolder
    keeps you on the happy path: new enum entry + a no-op
    registration in CLI + frontend + extension routes (you adjust
    afterwards) + an empty Pydantic model template at the right
    place in the file.
    """
    name = _slug(name)
    if not name:
        print("event name must contain at least one letter", file=sys.stderr)
        return 2

    upper = name.upper()
    pascal = "".join(p.title() for p in name.split("_")) + "Event"

    models_path = REPO_ROOT / "api" / "models.py"
    routing_path = REPO_ROOT / "api" / "event_routing.py"
    if not models_path.is_file() or not routing_path.is_file():
        print("api/models.py or api/event_routing.py missing", file=sys.stderr)
        return 1

    models_text = models_path.read_text(encoding="utf-8")
    routing_text = routing_path.read_text(encoding="utf-8")

    if f'"{name}"' in models_text:
        print(f"event '{name}' already in api/models.py", file=sys.stderr)
        return 1

    # 1. Insert a new enum member just before the closing of EventType.
    enum_re = re.compile(
        r"(class EventType\(str, Enum\)[^\n]*\n(?:    .+\n)+)",
        re.MULTILINE,
    )
    m = enum_re.search(models_text)
    if not m:
        print("could not locate EventType enum block", file=sys.stderr)
        return 1
    enum_block = m.group(1)
    last_member_indent = "    "
    new_line = f'{last_member_indent}{upper} = "{name}"\n'
    new_enum_block = enum_block + new_line
    models_text = models_text.replace(enum_block, new_enum_block)

    # 2. Add a Pydantic model stub just above the
    #    ``# Map from EventType value → strict Pydantic model.`` line.
    pyd_template = (
        f'\nclass {pascal}(BaseModel):\n'
        f'    type: str = "{name}"\n'
        f'    # TODO: add typed fields\n'
    )
    anchor = "# Map from EventType value → strict Pydantic model."
    if anchor in models_text:
        models_text = models_text.replace(anchor, pyd_template + "\n\n" + anchor)
    else:
        # Fall back to appending at end-of-file.
        models_text = models_text.rstrip() + "\n\n" + pyd_template

    models_path.write_text(models_text, encoding="utf-8")

    # 3. Add to CLI_EVENTS in event_routing.py. Caller picks where the
    #    event should also go (frontend / extension / drops) by hand —
    #    we don't guess.
    cli_anchor = "CLI_EVENTS: frozenset[str] = frozenset({"
    if cli_anchor in routing_text:
        addition = f"    EventType.{upper}.value,\n"
        routing_text = routing_text.replace(
            cli_anchor,
            cli_anchor + "\n" + addition,
            1,
        )
        # Fix the duplicate "{\n" by tightening:
        routing_text = routing_text.replace(
            cli_anchor + "\n\n    EventType",
            cli_anchor + "\n    EventType",
        )
    routing_path.write_text(routing_text, encoding="utf-8")

    print(f"✓ added EventType.{upper} = \"{name}\"")
    print(f"  · api/models.py            (enum + {pascal} model stub)")
    print("  · api/event_routing.py     (added to CLI_EVENTS)")
    print()
    print("Next steps:")
    print(f"  1. Fill in {pascal}'s typed fields in api/models.py")
    print("  2. If the model is strict, register it in _TYPED_MODELS in api/models.py")
    print("  3. Decide if the event also goes to FRONTEND_EVENTS / EXTENSION_EVENTS")
    print("     or EXTENSION_DROPS_ON_PURPOSE in api/event_routing.py")
    print("  4. python scripts/gen_event_types.py        # regen TS + JSDoc")
    print("  5. python -m pytest tests/test_event_contract.py -v")
    return 0


# ── ADR scaffolder ───────────────────────────────────────────────────


_ADR_TEMPLATE = '''
## ADR-{num}: {title}

**Status:** Proposed ({date})

**Context**

What's the problem or constraint forcing this decision? Who is
affected? What signals from the audit / reviewer / users prompted
this work?

**Decision**

What did we decide to do? State it crisply, then expand on the
mechanics. Include file paths for the new modules + the existing
ones modified.

**Consequences**

- What gets better
- What new costs / tradeoffs we accept
- What this enables for the next round
- What we explicitly chose NOT to do (and why)
'''


def scaffold_adr(title: str) -> int:
    decisions = REPO_ROOT / "DECISIONS.md"
    if not decisions.is_file():
        print(f"missing: {decisions}", file=sys.stderr)
        return 1
    text = decisions.read_text(encoding="utf-8")
    # Find the highest existing ADR-N
    nums = [int(m.group(1)) for m in re.finditer(r"^## ADR-(\d+):", text, re.MULTILINE)]
    next_num = (max(nums) + 1) if nums else 1
    today = datetime.now(UTC).date().isoformat()

    appendage = _ADR_TEMPLATE.format(num=next_num, title=title.strip(), date=today)
    text = text.rstrip() + "\n\n---\n" + appendage
    decisions.write_text(text, encoding="utf-8")

    print(f"✓ added ADR-{next_num}: {title}")
    print("  · DECISIONS.md (appended template)")
    print()
    print("Next steps:")
    print("  1. Fill in Context / Decision / Consequences in DECISIONS.md")
    print(f"  2. Update ARCHITECTURE.md to reference ADR-{next_num} where relevant")
    return 0


# ── Helpers ──────────────────────────────────────────────────────────


def _slug(name: str) -> str:
    """Normalise a user-supplied identifier to ``[a-z][a-z0-9_]*``."""
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_").lower()
    if s and s[0].isdigit():
        s = "_" + s
    return s


# ── CLI ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="kind", required=True)

    sk = sub.add_parser("skill", help="new skill package + SKILL.md + test stub")
    sk.add_argument("name")

    tl = sub.add_parser("tool", help="new tool module + registration + test stub")
    tl.add_argument("name")

    ev = sub.add_parser("event", help="new EventType + Pydantic model + routing entry")
    ev.add_argument("name")

    ad = sub.add_parser("adr", help="append an ADR template to DECISIONS.md")
    ad.add_argument("title")

    args = parser.parse_args(argv)
    if args.kind == "skill":
        return scaffold_skill(args.name)
    if args.kind == "tool":
        return scaffold_tool(args.name)
    if args.kind == "event":
        return scaffold_event(args.name)
    if args.kind == "adr":
        return scaffold_adr(args.title)
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
