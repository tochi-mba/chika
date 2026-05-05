"""``skill_load`` tool — fetch a skill's SKILL.md doc into the LLM's context.

A skill folder may contain ``SKILL.md`` with deep usage notes / patterns
that don't belong in the system prompt (would balloon every turn). When the
LLM realises it needs a skill's full reference (e.g. before a complex git
operation), it calls ``skill_load("git")`` to pull the doc.

If the doc is over a configurable token budget the tool runs a second LLM
call to **condense** it for *this* turn — the condensation prompt sees the
skill doc PLUS the most recent few messages of the chat, so it picks the
parts that are actually relevant.

The tool refuses to fabricate when no SKILL.md exists — it returns a
structured ``not_found`` error so the agent can decide how to proceed.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from chika.core.tool_registry import ToolDefinition
from chika.tools.skill_query_index import query as _skill_query

if TYPE_CHECKING:
    from chika.core.engine import ChikaEngine


_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# Approximate tokens via 4 chars/token. Below this threshold the doc is
# returned verbatim; above it we run a condensation pass.
#
# Tuned so the canonical SKILL.md docs fit verbatim — the plan SKILL.md
# alone is ~8.6KB after the verbose-template addition, and condensing it
# was adding ~30s of latency to the skill gate (ADR-11). Real giant docs
# (browser_skill ≈ 28KB after migrated workflow_examples) still trigger
# the condense pass; common skills load instantly.
_DEFAULT_BUDGET_CHARS = 12000

# Hard cap on input to the condense LLM call — we don't want to ship the
# whole conversation history if it's huge. Last ~8 messages is usually
# enough to know what's relevant.
_MAX_CONTEXT_MSGS = 8


def _resolve_skill_dir(name: str) -> Path | None:
    """Find the folder for a skill by name. Accepts ``git``, ``git_skill``,
    or any case combination — we normalise internally.
    """
    candidates = {name, f"{name}_skill", name.lower(), f"{name.lower()}_skill"}
    for cand in candidates:
        path = _SKILLS_DIR / cand
        if path.is_dir():
            return path
    return None


def _read_skill_doc(skill_dir: Path) -> tuple[Path | None, str]:
    """Look for SKILL.md (case-insensitive). Return (path_or_None, content)."""
    for entry in skill_dir.iterdir():
        if entry.is_file() and entry.name.lower() == "skill.md":
            try:
                return entry, entry.read_text(encoding="utf-8")
            except Exception:
                return entry, ""
    return None, ""


def _last_messages(history: list[dict], n: int) -> str:
    """Render the last ``n`` user/assistant message pairs as plain text."""
    pairs = history[-n:] if history else []
    out: list[str] = []
    for msg in pairs:
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        snippet = content.strip().replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"
        out.append(f"[{role}] {snippet}")
    return "\n".join(out)


async def _condense(engine: ChikaEngine, doc: str, history: list[dict]) -> str:
    """Run a second LLM call to summarise ``doc`` for this conversation."""
    ctx = _last_messages(history, _MAX_CONTEXT_MSGS) or "(no prior turns)"
    prompt = (
        "You are a documentation condenser. Given a skill reference doc and "
        "the recent chat history, return the parts of the doc that are "
        "relevant for the next turn. Keep code blocks, command syntax, and "
        "exact tool names verbatim. Cut anything not needed for the user's "
        "current task.\n\n"
        "## Recent chat\n"
        f"{ctx}\n\n"
        "## Skill doc\n"
        f"{doc}\n\n"
        "Return ONLY the condensed Markdown — no preamble, no closing notes."
    )
    try:
        return (await engine._llm_complete(prompt)).strip()
    except Exception as exc:
        # Fall back to a simple head-truncation rather than failing.
        head = doc[:_DEFAULT_BUDGET_CHARS].rstrip() + "\n\n…(truncated; condense failed)"
        return f"[condense_failed: {type(exc).__name__}]\n\n{head}"


def make_skill_doc_tool(engine: ChikaEngine) -> ToolDefinition:
    """Build the ``skill_load`` tool, closing over the engine for LLM access."""
    async def handler(
        skill: str,
        max_chars: int | None = None,
        force_full: bool = False,
    ) -> Any:
        if not isinstance(skill, str) or not skill.strip():
            return {"error": "skill name must be a non-empty string"}

        skill_dir = _resolve_skill_dir(skill.strip())
        if skill_dir is None:
            return {
                "error": "not_found",
                "skill": skill,
                "hint": (
                    f"No skill folder named {skill!r}. Folders found: "
                    f"{sorted(p.name for p in _SKILLS_DIR.iterdir() if p.is_dir())}"
                ),
            }

        doc_path, doc = _read_skill_doc(skill_dir)
        if doc_path is None:
            return {
                "error": "no_doc",
                "skill": skill,
                "hint": (
                    f"{skill_dir.name} has no SKILL.md yet. Suggest creating "
                    f"{skill_dir / 'SKILL.md'} with usage notes."
                ),
            }

        budget = int(max_chars or _DEFAULT_BUDGET_CHARS)
        budget = max(1000, min(budget, 50_000))
        condensed = False
        rendered = doc

        if not force_full and len(doc) > budget:
            history = list(getattr(engine, "_history", []) or [])
            rendered = await _condense(engine, doc, history)
            condensed = True

        return {
            "skill":     skill_dir.name,
            "path":      str(doc_path),
            "char_count": len(doc),
            "condensed": condensed,
            "doc":       rendered,
        }

    return ToolDefinition(
        name="skill_load",
        description=(
            "Load a skill's SKILL.md reference doc into context. The doc lives "
            "in chika/skills/<name>/SKILL.md and contains deep usage notes "
            "that aren't always in the system prompt. If the doc exceeds the "
            "char budget (default 6000) the tool runs a *second* LLM call to "
            "condense the doc against the last few chat messages — so you get "
            "the parts you actually need for the current turn. "
            "Set force_full=true to skip the condense pass."
        ),
        parameters={
            "type": "object",
            "properties": {
                "skill":      {"type": "string", "description": "Skill name (e.g. 'git', 'browser', 'web')."},
                "max_chars":  {"type": "integer", "description": "Hard char budget before auto-condense kicks in. Default 6000."},
                "force_full": {"type": "boolean", "description": "Return the doc untouched (no condensation pass)."},
            },
            "required": ["skill"],
        },
        handler=handler,
    )


# ── skill_query — focused retrieval over chunked SKILL.md ──────────────────


async def _skill_query_handler(
    skill: str | None = None,
    query: str | None = None,
    k: int = 3,
    **_kw,
):
    # Tolerate common LLM kwarg slips
    skill = skill or _kw.get("name") or _kw.get("skill_name")
    query = query or _kw.get("q") or _kw.get("question") or _kw.get("text")
    return _skill_query(skill or "", query or "", k=k)


SKILL_QUERY_TOOL = ToolDefinition(
    name="skill_query",
    description=(
        "Ask a focused question against a skill's SKILL.md and get back the "
        "top-k matching markdown sections (BM25-ranked, no embeddings or "
        "external services). Use this instead of skill_load when you only "
        "need a slice of the doc — e.g. \"how do I call plan_set?\" or "
        "\"what selector should I use for YouTube history?\". Cheaper than "
        "loading the full doc and faster than re-reading it. The skill "
        "must already be on disk as chika/skills/<name>_skill/SKILL.md. "
        "Returns chunks with their heading + body + relevance score."
    ),
    parameters={
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "Skill name (e.g. 'git', 'browser', 'plan').",
            },
            "query": {
                "type": "string",
                "description": "Natural-language question or keyword phrase.",
            },
            "k": {
                "type": "integer",
                "description": "Top-k chunks to return (1–10). Default 3.",
            },
        },
        "required": ["skill", "query"],
    },
    handler=_skill_query_handler,
)
