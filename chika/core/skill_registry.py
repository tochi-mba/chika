from __future__ import annotations
from dataclasses import dataclass, field

from chika.core.memory_manager import MemoryManager
from chika.core.prompt_builder import PromptBuilder
from chika.core.tool_registry import ToolDefinition, ToolRegistry


@dataclass
class Skill:
    name: str
    description: str
    tools: list[ToolDefinition]
    workflow_examples: str = ""       # Markdown injected into system prompt
    memory_seeds: dict[str, str] = field(default_factory=dict)


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

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill
        for tool in skill.tools:
            self._tools.register(tool)
        if skill.workflow_examples:
            self._prompt.add_workflow_examples(skill.name, skill.workflow_examples)
        for key, value in skill.memory_seeds.items():
            self._memory.seed(key, value)

    def unregister(self, skill_name: str) -> None:
        skill = self._skills.pop(skill_name, None)
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
            }
            for s in self._skills.values()
        ]

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)
