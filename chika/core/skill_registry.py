from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from chika.core.memory_manager import MemoryManager
from chika.core.prompt_builder import PromptBuilder
from chika.core.tool_registry import ToolDefinition, ToolRegistry

# Skills folder — used to detect whether a skill has a SKILL.md and
# therefore can skip prompt-injection of its workflow_examples.
_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def _has_skill_doc(skill_name: str) -> bool:
    """True if ``chika/skills/<name>_skill/SKILL.md`` exists.

    SKILL.md is the canonical reference doc the agent loads on demand via
    ``skill_load``. When a skill has one, the prompt builder must NOT also
    inject the same content as ``workflow_examples`` — that's duplicate
    context every turn even when the skill isn't being used.
    """
    candidates = (
        _SKILLS_DIR / f"{skill_name}_skill" / "SKILL.md",
        _SKILLS_DIR / skill_name / "SKILL.md",
    )
    return any(p.is_file() for p in candidates)


@dataclass
class Skill:
    name: str
    description: str
    tools: list[ToolDefinition]
    # Markdown injected into the system prompt ONLY when the skill lacks a
    # ``SKILL.md`` file. Skills with SKILL.md are the canonical source —
    # the agent loads them on demand via ``skill_load`` instead of paying
    # for the content on every turn.
    workflow_examples: str = ""
    memory_seeds: dict[str, str] = field(default_factory=dict)

    # Optional dynamic-context contributor. Called once per system-prompt
    # build with no arguments (the skill closes over whatever state it
    # needs at construction — variable store, profile manager, etc.) and
    # returns a small markdown block to splice in, OR an empty string
    # when there's nothing to add this turn.
    #
    # Use this for state the agent should know turn-by-turn but that
    # doesn't belong in SKILL.md (which is static). The pet skill, for
    # example, surfaces its companion's name + mood + current frame
    # so the agent can respond naturally to "look at my cat!".
    #
    # Keep these blocks SHORT — they're paid every turn. ≤ ~600 chars
    # is the budget. Skills that want to ship a lot of static reference
    # belong in SKILL.md, loaded on demand.
    prompt_section: object = None  # Callable[[], str] | None


class SkillRegistry:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        memory_manager: MemoryManager,
        prompt_builder: PromptBuilder,
    ) -> None:
        self._skills: dict[str, Skill] = {}
        self._tools = tool_registry
        self._memory = memory_manager
        self._prompt = prompt_builder
        # Skill names that ship a SKILL.md — the prompt builder uses this
        # to render the SKILL INDEX so the agent knows what's loadable.
        self._skills_with_docs: set[str] = set()

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill
        for tool in skill.tools:
            self._tools.register(tool)

        has_doc = _has_skill_doc(skill.name)
        if has_doc:
            self._skills_with_docs.add(skill.name)

        # Inject workflow_examples ONLY when the skill has no SKILL.md.
        # Otherwise the agent gets the same content twice (in the system
        # prompt every turn, AND on demand via skill_load). The
        # SKILL.md is the source of truth — keep the system prompt slim.
        if skill.workflow_examples and not has_doc:
            skill_tool_names = {t.name for t in skill.tools}
            self._prompt.add_workflow_examples(
                skill.name, skill.workflow_examples, tool_names=skill_tool_names,
            )
        for key, value in skill.memory_seeds.items():
            self._memory.seed(key, value)

    def unregister(self, skill_name: str) -> None:
        skill = self._skills.pop(skill_name, None)
        self._skills_with_docs.discard(skill_name)
        if skill:
            for tool in skill.tools:
                self._tools.unregister(tool.name)
            self._prompt.remove_workflow_examples(skill_name)

    def list_skills(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "tools": [t.name for t in s.tools],
                "workflow_examples": s.workflow_examples,
                "has_doc": s.name in self._skills_with_docs,
            }
            for s in self._skills.values()
        ]

    def skill_index(self) -> list[dict]:
        """Compact index for the system prompt: name, description, has_doc."""
        return [
            {
                "name":        s.name,
                "description": s.description.split("\n")[0],
                "has_doc":     s.name in self._skills_with_docs,
            }
            for s in self._skills.values()
        ]

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def prompt_sections(self) -> list[str]:
        """Render every registered skill's dynamic prompt section.

        Each skill that supplies a ``prompt_section`` callable contributes
        a short markdown block to the system prompt. We collect them in
        registration order and let the prompt builder splice them in
        after the structural body.

        Errors raised by individual contributors are swallowed (with a
        comment-style fallback line) so a buggy skill can't take the
        whole prompt build offline.
        """
        out: list[str] = []
        for skill in self._skills.values():
            section_fn = getattr(skill, "prompt_section", None)
            if not callable(section_fn):
                continue
            try:
                section = section_fn() or ""
            except Exception as exc:
                section = (
                    f"<!-- {skill.name}_skill prompt_section raised "
                    f"{type(exc).__name__}: {exc} -->"
                )
            section = (section or "").strip()
            if section:
                out.append(section)
        return out
