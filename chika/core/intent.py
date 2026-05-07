"""Lightweight intent heuristics for nudging the agent's strategy.

Currently exports one detector:

    detect_planning_intent(user_input: str) -> str | None

When the user's message looks like a build/create request (e.g.
"make me a Vue dashboard", "build a CLI tool that…", "scaffold a
landing page"), it returns a one-paragraph hint to inject into the
agent's per-turn system prompt. The agent uses that hint to decide
whether to call the plan skill BEFORE jumping to other tools.

When the message looks like a question, a one-shot command, or a
quick fix, it returns ``None`` — the agent should respond directly
without the overhead of planning.

Why heuristics, not an LLM call?
    - Zero added latency on every turn (regex matching is microseconds)
    - Zero added LLM cost
    - Deterministic — the same input always gets the same hint, so
      tests can pin behavior

The trade-off: regex misses nuance an LLM would catch. We accept
false negatives (missed planning opportunities) over false positives
(unnecessary plan-then-replan churn). The agent itself can still
choose to plan even without the hint; we just nudge for the obvious
build-shaped requests.
"""
from __future__ import annotations

import re

# The hint we inject into the system prompt when planning intent is
# detected. Kept short so it doesn't dominate the per-turn prompt
# budget — it's a nudge, not a directive.
_PLAN_HINT = (
    "\n\n## Planning hint\n"
    "The user's latest request seems to maybe look like a build/create task that "
    "involves multiple steps or files. Strongly consider calling the "
    "`plan_set` tool first to break the work into a checklist the "
    "user can review and edit, THEN execute the steps. Skip planning "
    "only if the work is a single trivial action (one file edit, one "
    "shell command, etc.). When in doubt, plan — the user can always "
    "say 'just do it' and you can call `plan_clear` and proceed."
)


# Question-shaped openings — these mean "explain / show me", NOT
# "build me". Always skip the planning hint for these.
#
# Notably absent: "can " / "could " / "would " / "should ". Those
# are ambiguous ("can you tell me about X" vs "can you build me X")
# and would create false negatives on legitimate build requests.
# The build patterns below will catch the build cases; questions
# starting with "can" without a build verb fall through and get no
# hint, which is the correct outcome.
_QUESTION_OPENERS: tuple[str, ...] = (
    "what ", "what's ", "whats ", "why ", "why's ", "whys ",
    "how do ", "how does ", "how should ", "how can ",
    "is ", "are ", "was ", "were ", "do ", "does ", "did ",
    "where ", "when ", "who ", "which ",
    "explain ", "show me ", "tell me ", "describe ",
    "list ", "find ", "search for ", "look up ", "look for ",
    "give me a list ",
)


# Build-shaped patterns. Each is a regex tested case-insensitively
# against the trimmed user message. Ordered roughly by likelihood:
# the most common phrasings first so we short-circuit early.
# Nouns the user is likely to "add" when they're describing a
# feature-scoped change worth planning around. Adding a "settings tab"
# or an "endpoint" or a "feature" all benefit from a plan; adding a
# "comma" doesn't. Listed verbosely so the regex stays readable.
_FEATURE_NOUNS = (
    "feature", "component", "page", "view", "endpoint", "route",
    "tool", "skill", "test", "fixture", "button", "tab", "input",
    "form", "menu", "dialog", "modal", "panel", "card", "widget",
    "chart", "graph", "table", "list", "section", "integration",
    "setting", "toggle", "notification", "alert", "api", "service",
    "library", "module", "plugin", "extension", "hook", "store",
    "model", "schema", "migration", "command", "subcommand",
    "screen", "flow", "wizard", "stepper", "field",
)
_FEATURE_NOUN_RE = "|".join(_FEATURE_NOUNS)


_BUILD_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        # "make me a X", "build me a X", "create me a X"
        r"\b(?:make|build|create|generate|scaffold|spin\s+up|set\s+up)\s+(?:me\s+)?(?:a|an|the)\s+\w+",

        # "I want to build a X", "I need to make a X"
        r"\b(?:i\s+)?(?:want|need|would\s+like)\s+(?:to\s+)?(?:build|make|create|generate|scaffold|spin\s+up|set\s+up|design|implement)\s+",

        # "i want a X", "i need a X" — the noun-direct form (no
        # explicit verb between need/want and the article).
        r"\bi\s+(?:want|need|would\s+like)\s+(?:a|an|the)\s+\w",

        # "Help me build/make/design/refactor X"
        r"\b(?:can\s+you\s+)?help\s+(?:me\s+)?(?:build|make|create|design|implement|refactor|scaffold|set\s+up)\b",

        # "refactor X to use Y", "rewrite X in Y"
        r"\b(?:refactor|rewrite|migrate|port|convert)\s+\w",

        # "add a feature for X", "add a settings tab", etc.
        # The (?:\w+\s+)* part lets adjectives slip in:
        # "add a NEW SMALL endpoint" matches.
        rf"\badd\s+(?:a|an|the)\s+(?:\w+\s+)*?(?:{_FEATURE_NOUN_RE})\b",

        # "implement X", "design X" (when X is a noun phrase, not a question)
        r"\b(?:implement|design|architect)\s+(?:a|an|the)\s+\w",

        # "let's build X" / "lets make X"
        r"\blet'?s\s+(?:build|make|create|design|implement|scaffold|set\s+up)\b",

        # "I'm trying to build X"
        r"\bi'?m\s+trying\s+to\s+(?:build|make|create|implement|design)\b",

        # Direct imperative: "build a Vue dashboard", "create a CLI tool"
        # (without "me" — first word is the verb)
        r"^\s*(?:build|create|make|generate|scaffold|implement|design)\s+(?:a|an|the)\s+\w",
    )
)


# Patterns that LOOK build-shaped but are actually fix-shaped or
# one-shot. These take precedence — if any match, skip the hint.
# (e.g. "fix this" contains no build verb but better safe than sorry.)
_OVERRIDE_NO_PLAN: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        # Quick fixes — usually one file, one bug
        r"^\s*(?:fix|repair|patch|debug)\s+",
        # One-shot lookups
        r"^\s*(?:run|execute|invoke)\s+",
        # Style / typo / cosmetic — too small to plan. ``\w*`` after
        # the noun catches plurals: ``typos``, ``commas``, etc.
        r"\b(?:typo|spelling|grammar|formatting|whitespace|indent|comma|semicolon)\w*\b",
        # Reverting / undoing
        r"\b(?:revert|undo|rollback|restore)\b",
    )
)


def detect_planning_intent(user_input: str) -> str | None:
    """Return a planning-hint string if the message looks build-shaped.

    Returns ``None`` for questions, one-shots, fixes, and short
    commands.

    Examples that return a hint:
        "make me a vue dashboard"
        "build a CLI tool that monitors a folder"
        "I want to scaffold a Next.js app with auth"
        "help me refactor the auth module"
        "add a settings tab for keyboard shortcuts"

    Examples that return None:
        "what does git rebase do?"
        "fix the bug in oauth.py"
        "show me the current settings"
        "list every tool"
        "run the tests"
        "ty"  (too short to be meaningful)
    """
    text = (user_input or "").strip()
    if not text:
        return None

    # Very short messages are never build requests — they're commands,
    # acknowledgements, or back-and-forth chatter.
    if len(text.split()) < 3:
        return None

    lower = text.lower()

    # Question patterns — the agent should answer, not plan.
    for opener in _QUESTION_OPENERS:
        if lower.startswith(opener):
            return None

    # Quick-fix / one-shot overrides win even if a build pattern
    # also matches (e.g. "fix the build script" contains "build" but
    # is a fix request).
    for pat in _OVERRIDE_NO_PLAN:
        if pat.search(text):
            return None

    # Now check the build patterns.
    for pat in _BUILD_PATTERNS:
        if pat.search(text):
            return _PLAN_HINT

    return None
