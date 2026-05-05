"""Sync each skill's SKILL.md ``Tool reference`` appendix from the live
registry. Run once after touching any skill's tool definitions. The
appendix is fenced by the markers below — content outside the markers is
preserved exactly so manual prose / patterns aren't clobbered.

    <!-- chika:tool-reference:auto-start -->
    ...auto-generated...
    <!-- chika:tool-reference:auto-end -->

CI runs the same generator under ``--check`` to fail when source drifts
from the doc.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from api.session_manager import session_manager  # noqa: E402

START = "<!-- chika:tool-reference:auto-start -->"
END   = "<!-- chika:tool-reference:auto-end -->"


def _format_tool_block(tool) -> str:
    params = tool.parameters or {}
    props = params.get("properties", {})
    required = set(params.get("required", []) or [])

    lines = []
    approval = " · **requires approval**" if getattr(tool, "requires_approval", False) else ""
    lines.append(f"### `{tool.name}`{approval}")
    lines.append("")
    desc = (tool.description or "").strip()
    if desc:
        # First sentence ish for compactness, then a blank line.
        lines.append(desc)
        lines.append("")

    if props:
        lines.append("**Args**:")
        lines.append("")
        for name, spec in props.items():
            ptype = spec.get("type", "any")
            if isinstance(ptype, list):
                ptype = " | ".join(t for t in ptype if t != "null") + " | null"
            tag = "**required**" if name in required else "optional"
            doc = (spec.get("description") or "").strip()
            line = f"- `{name}` ({ptype}, {tag})"
            if doc:
                line += f" — {doc}"
            lines.append(line)
    else:
        lines.append("*No parameters.*")

    lines.append("")
    return "\n".join(lines)


def _generate_appendix(skill_name: str, tools: list) -> str:
    body = [
        START,
        "",
        "<!-- This block is auto-generated from the live tool registry by",
        "     scripts/sync_skill_docs.py. Don't hand-edit between the",
        "     start/end markers — your changes will be overwritten.    -->",
        "",
        "## Tool reference",
        "",
        f"_{len(tools)} tool{'s' if len(tools) != 1 else ''} registered with the `{skill_name}` skill._",
        "",
    ]
    for tool in sorted(tools, key=lambda t: t.name):
        body.append(_format_tool_block(tool))
    body.append(END)
    return "\n".join(body)


def _splice(existing: str, appendix: str) -> str:
    """Replace any existing auto-generated appendix; otherwise append it."""
    if START in existing and END in existing:
        before = existing.split(START)[0].rstrip() + "\n\n"
        after_block = existing.split(END, 1)[1]
        return before + appendix + after_block
    if existing and not existing.endswith("\n"):
        existing += "\n"
    return f"{existing}\n---\n\n{appendix}\n"


def _walk_skills():
    eng = session_manager.get_or_create("__skill_doc_sync__")
    skills_dir = _REPO / "chika" / "skills"
    for skill_name, skill in eng._skills._skills.items():
        # Find the SKILL.md path. Try both ``<name>_skill`` and ``<name>``.
        for cand in (f"{skill_name}_skill", skill_name):
            md = skills_dir / cand / "SKILL.md"
            if md.is_file():
                yield skill_name, md, list(skill.tools)
                break


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="Exit non-zero if any SKILL.md is out of date.")
    args = parser.parse_args()

    drift = []
    written = 0
    for skill_name, md_path, tools in _walk_skills():
        existing = md_path.read_text(encoding="utf-8")
        appendix = _generate_appendix(skill_name, tools)
        target = _splice(existing, appendix)
        if target == existing:
            continue
        if args.check:
            drift.append(skill_name)
        else:
            md_path.write_text(target, encoding="utf-8")
            written += 1
            print(f"updated {md_path.relative_to(_REPO)}")

    if args.check:
        if drift:
            print("SKILL.md drift detected for: " + ", ".join(drift))
            print("Run: python scripts/sync_skill_docs.py")
            return 1
        print("all SKILL.md tool references are in sync")
        return 0

    if written == 0:
        print("all SKILL.md tool references already in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
