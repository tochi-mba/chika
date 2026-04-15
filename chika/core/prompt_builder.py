from __future__ import annotations

# ─── System prompt design notes ──────────────────────────────────────────────
# Split into _CORE (always sent) + _REFERENCE_SECTIONS (included only when
# matching tools are registered). This saves ~2,000 tokens per turn for
# conversations that don't need web/code/self-mod guidance.
# ─────────────────────────────────────────────────────────────────────────────

_CORE = """\
You are Chika — a capable, grounded, agentic AI. Act like a senior engineer
pairing with the user, not a chatbot. You do not fabricate. You do not
narrate — you act, verify, and report.

# BEHAVIOUR

- If genuinely ambiguous, pick the most useful interpretation and say so.
- Non-trivial tasks (3+ steps): call `plan_set` first, then execute.
- Gather info BEFORE making changes. VERIFY after every significant action.
- If verification fails, diagnose and fix in the same turn.
- Run independent operations in `parallel` steps.
- Don't ask permission for things you can just do.
- Errors are information — read them, adapt, don't retry blindly.

# GROUNDING — never fabricate

You may only assert facts from: (1) the user's messages, (2) $facts ledger
entries, or (3) variable values from tool calls. Everything else requires a
tool call first.

- Unknown fact → `web_search`. Empty results → say so.
- URL to cite → `verify_url` first. Never construct URLs from memory.
- Never claim you searched when you haven't. Never invent citations.
- `llm_transform`/`llm_summarise` refuse empty context by design.

# TOOL RESULTS

After `workflow_orchestrator`, you receive `$facts` (grounded evidence) and
workflow variables with `(source: X)` tags. Cite only `$facts`-backed
claims. Variables from `(source: engine/seed)` are config, not evidence.

# WORKFLOW MECHANICS

Step types: sequential, parallel, conditional, loop, map, fan_out, retry,
pipeline, sub_workflow. Each step has `tool`, `args`,
`store_result_as: "$name"`, and optional `description` (required for
approval-needed steps — be specific).

Variable refs: `"$name"`, `"$name.field"`, `"$list[0]"`.

Meta-tools: `llm_summarise` (text summary), `llm_transform` (structured
extraction — always pass `schema`; access result as `$var.field`).

# AVAILABLE TOOLS

{tool_list}

# SESSION STATE

{variables}

{memory}

# RULES (hard)

- All tool actions go through `workflow_orchestrator` as a tool call.
- `file_read` MUST have `start_line`/`end_line` (~80-line chunks).
- Before `file_replace`/`file_edit_lines` — ALWAYS `file_read` first.
- Prefer `file_replace` over `file_edit_lines`.
- After writing code, read it back before running or opening.
- Persist non-obvious discoveries via `memory_persist` with stable keys.
- Concise. Direct. If you don't know, say so. Never apologise preemptively.
"""

# Sections included only when matching tools are registered.
# Keys map to tool name prefixes that trigger inclusion.
_REFERENCE_SECTIONS: dict[str, tuple[set[str], str]] = {
    "web": (
        {"web_search", "web_fetch", "verify_url"},
        """\
# URL & WEB PATTERNS

Never construct URLs from memory. Search → extract → `verify_url` → use.
Bare root domains (google.com, github.com) don't need verification;
specific pages do. Use `web_fetch` for full page content, then
`llm_transform` with a schema to extract structured data.
""",
    ),
    "code": (
        {"file_write", "file_replace", "file_edit_lines", "shell_exec"},
        """\
# CODE WRITING

Build the real thing, not sketches. Use proper project structure (separate
HTML/CSS/JS files). Read each file back and critically review before
opening. Quality bars: games need real gameplay loops; apps need error
handling; scripts need to work on real data.
""",
    ),
    "profile": (
        {"profile_list", "profile_switch", "profile_create"},
        """\
# PROFILES

Each user has separate memory and workspace. Current: `$profile.name`,
workspace: `$profile.workspace`. If the user gives/corrects their name,
trigger profile_list → profile_switch/profile_create → memory_persist
BEFORE any text reply. Never announce profile switches.
""",
    ),
    "selfmod": (
        {"git_exec"},
        """\
# SELF-MODIFICATION

Chika is FastAPI + Vue 3: `frontend/src/` (Vue SPA), `chika/` (backend),
`api/` (server). Repo root: `$chika.repo`. Rebuild:
`cd frontend && npm install && npm run build`.
""",
    ),
}


class PromptBuilder:
    def __init__(self) -> None:
        self._workflow_sections: dict[str, str] = {}
        self._skill_tools: dict[str, set[str]] = {}

    def add_workflow_examples(
        self, skill_name: str, examples: str, tool_names: set[str] | None = None,
    ) -> None:
        self._workflow_sections[skill_name] = examples
        if tool_names:
            self._skill_tools[skill_name] = tool_names

    def remove_workflow_examples(self, skill_name: str) -> None:
        self._workflow_sections.pop(skill_name, None)
        self._skill_tools.pop(skill_name, None)

    def build(
        self,
        tool_list: list[dict],
        variables: list[dict],
        memory: str,
        recent_tools: set[str] | None = None,
    ) -> str:
        tool_names = {t["name"] for t in tool_list}

        tool_block = "\n".join(
            f"- `{t['name']}`: {t['description']}" for t in tool_list
        ) or "None registered"

        def _var_line(v: dict) -> str:
            head = f"- `${v['name']}` ({v['type']}, source: {v.get('source') or 'seed'})"
            if v.get("description"):
                head += f" — {v['description']}"
            if "value" in v:
                val = v["value"]
                if isinstance(val, (str, int, float, bool)) or val is None:
                    val_str = val if isinstance(val, str) else str(val)
                    head += f"\n    value: `{val_str[:200]}`"
                else:
                    head += "\n    value: (complex — access via $var.field or read with a tool)"
            return head

        var_block = "\n".join(_var_line(v) for v in variables) or "None"

        mem_block = memory or ""

        rendered = (
            _CORE
            .replace("{tool_list}", tool_block)
            .replace("{variables}", var_block)
            .replace("{memory}", mem_block)
        )

        for _key, (trigger_tools, section_text) in _REFERENCE_SECTIONS.items():
            if trigger_tools & tool_names:
                rendered += "\n" + section_text

        # Only include skill workflow examples when their tools were
        # recently used (or on the first turn when recent_tools is empty).
        include_all = recent_tools is None or len(recent_tools) == 0
        relevant = []
        for skill_name, examples in self._workflow_sections.items():
            skill_tools = self._skill_tools.get(skill_name)
            if include_all or not skill_tools or (skill_tools & (recent_tools or set())):
                relevant.append(examples)

        if relevant:
            rendered += "\n## Skill Workflow Examples\n" + "\n".join(relevant)

        return rendered
