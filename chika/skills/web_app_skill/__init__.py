"""web_app_skill — scaffold any browser-based web app stack.

Bundles the ``scaffold_web_app`` tool plus workflow examples that the
prompt builder injects into the system prompt. Deeper guidance on
*choosing* a stack lives in ``SKILL.md`` — the agent should call
``skill_load(skill="web_app")`` before starting a non-trivial web build.
"""
from __future__ import annotations

from chika.core.skill_registry import Skill
from chika.skills.web_app_skill.scaffold_tool import (
    SCAFFOLD_WEB_APP_TOOL,
    list_stacks,
)

__all__ = ["WEB_APP_SKILL", "SKILL_NAME", "list_stacks"]

# Canonical name used by the engine's skill registry.
SKILL_NAME = "web_app"


WEB_APP_SKILL = Skill(
    name="web_app",
    description=(
        "Scaffold and run any browser-based web app — vanilla, Vite "
        "(Vue/React/Svelte/Solid/Preact/Lit/Qwik), Next, Nuxt, Astro, "
        "SvelteKit, Remix, Three.js, p5, Phaser, or any other npm-create "
        "package. Deep stack-picking guidance in SKILL.md (load via "
        "skill_load)."
    ),
    tools=[SCAFFOLD_WEB_APP_TOOL],
    workflow_examples="",
)


def build_skill(_context):
    """Auto-discovery entry point. The web_app skill is stateless — it
    returns the module-level ``WEB_APP_SKILL`` constant unchanged."""
    return WEB_APP_SKILL


INTENT_CASES: dict = {
    "plan": {
        "positive": [
            "make me a powder toy clone in vanilla JS + canvas",
            "build a Vue 3 dashboard with three charts and a sidebar",
            "scaffold a small Next.js site with auth + a blog route",
            "create a Three.js scene with a rotating orbital diagram",
        ],
        "negative": [
            "what's the difference between Vite and Webpack",
            "list the available scaffold templates",
            "what stack should I use for a real-time chat app",
        ],
    },
    "ask": {
        "positive": [
            "make me a UI",
            "build something cool",
            "scaffold a frontend for that idea",
        ],
        "negative": [
            "scaffold a Vue 3 dashboard with Pinia",
            "create a vanilla JS canvas app called particles",
            "build a Next.js blog at ./my-blog",
        ],
    },
}
