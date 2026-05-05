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

__all__ = ["WEB_APP_SKILL", "list_stacks"]


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
