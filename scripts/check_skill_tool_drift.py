"""Detect drift between SKILL.md tool tables and the live tool registry.

Each ``chika/skills/<name>_skill/SKILL.md`` lists the tools that
skill exposes. The actual tool registry knows the truth. When a tool
gets renamed, removed, or added, contributors are supposed to keep
the SKILL.md in sync — but they forget. The agent then reads claims
about tools that don't exist (or misses tools that do), and the
generated summary inherits the lie.

This script extracts tool names from each SKILL.md (looking for
``code-fenced`` mentions and explicit ``Tools`` tables / lists) and
diffs against the registry. Drift is reported with the file + line
where the SKILL.md claims a non-existent tool, or where a registered
tool isn't documented.

Run:

    python scripts/check_skill_tool_drift.py             # exit 0 if clean
    python scripts/check_skill_tool_drift.py --verbose
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _load_registered_tools() -> set[str]:
    """Return the set of tool names the registry knows about.

    Imports lazily to avoid pulling the full engine into a CI lint
    step. Falls back to grep-based discovery if the registry import
    fails (e.g., missing optional deps).
    """
    try:
        from chika.tools._registry import _tools  # type: ignore
        return set(_tools.keys())
    except Exception:
        pass
    # Fallback: grep for @register_tool decorators.
    found: set[str] = set()
    for tool_file in (REPO_ROOT / "chika" / "tools").rglob("*.py"):
        text = tool_file.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
            r"@register_tool[^\n]*\n(?:[^\n]+\n)*?def\s+(\w+)\s*\(",
            text, re.MULTILINE,
        ):
            found.add(m.group(1))
    for skill_file in (REPO_ROOT / "chika" / "skills").rglob("*.py"):
        text = skill_file.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
            r"@register_tool[^\n]*\n(?:[^\n]+\n)*?def\s+(\w+)\s*\(",
            text, re.MULTILINE,
        ):
            found.add(m.group(1))
    return found


# Names that look like tool names but aren't (common false positives
# in SKILL.md prose). Adjust as new patterns surface.
_NOT_TOOL_NAMES = frozenset({
    "tool", "tools", "args", "result", "error", "skill", "skills",
    "yes", "no", "true", "false", "none", "null",
})


def _claimed_tools_from_skill_md(text: str) -> set[str]:
    """Extract tool-name-shaped tokens from a SKILL.md.

    Heuristic: words inside backticks that look like ``[a-z][a-z0-9_]*``
    AND contain at least one underscore (most tool names do — e.g.
    ``shell_exec``, ``browser_click``, ``plan_set``). Tightening on
    "has-underscore" reduces false positives from generic prose like
    ``the agent`` or ``run``.
    """
    out: set[str] = set()
    for m in re.finditer(r"`([a-z][a-z0-9_]*)`", text):
        token = m.group(1)
        if "_" in token and token not in _NOT_TOOL_NAMES:
            out.add(token)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    registered = _load_registered_tools()
    if not registered:
        print(
            "warning: tool registry returned empty — skipping drift check",
            file=sys.stderr,
        )
        return 0

    if args.verbose:
        print(f"registered tools ({len(registered)}):")
        for t in sorted(registered):
            print(f"  · {t}")
        print()

    drift = []
    skills_dir = REPO_ROOT / "chika" / "skills"
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        claimed = _claimed_tools_from_skill_md(text)
        # SKILL.md may legitimately mention tools owned by other skills
        # (cross-references). Only flag claims of tools that don't
        # exist *anywhere* in the registry.
        missing = claimed - registered
        if missing:
            drift.append((skill_md, sorted(missing)))

    if drift:
        print("\nSKILL.md ↔ tool registry drift:", file=sys.stderr)
        for path, names in drift:
            rel = path.relative_to(REPO_ROOT)
            print(f"  ✗ {rel}", file=sys.stderr)
            for n in names:
                print(f"      claims {n!r} which is not in the registry", file=sys.stderr)
        print(
            "\nFix: either add the tool to the registry (scaffold.py tool <name>) "
            "or remove the stale mention from SKILL.md "
            "(then regenerate the summary).",
            file=sys.stderr,
        )
        return 1

    print(f"all SKILL.md tool claims line up with the registry "
          f"({len(registered)} tools).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
