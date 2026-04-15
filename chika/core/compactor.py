"""
Conversation history compaction.
When the estimated token count exceeds the threshold, the middle section of
history is summarised into a single dense block via an LLM call.
"""
from __future__ import annotations
from typing import Any


CHARS_PER_TOKEN = 4  # rough estimate


def estimate_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        total += len(str(content)) // CHARS_PER_TOKEN
    return total


class Compactor:
    def __init__(
        self,
        llm_caller: "LLMCaller",
        max_tokens: int = 80_000,
        keep_first: int = 2,
        keep_last: int = 4,
    ) -> None:
        self._llm = llm_caller
        self._max_tokens = max_tokens
        self._keep_first = keep_first
        self._keep_last = keep_last

    def needs_compaction(self, messages: list[dict]) -> bool:
        return estimate_tokens(messages) > self._max_tokens

    async def compact(self, messages: list[dict]) -> tuple[list[dict], dict]:
        """
        Returns (compacted_messages, event).
        event has type "compaction" with counts.
        """
        if len(messages) <= self._keep_first + self._keep_last + 1:
            return messages, {}

        head = messages[: self._keep_first]
        tail = messages[-self._keep_last :]
        middle = messages[self._keep_first : -self._keep_last]

        summary_text = await self._summarise(middle)
        summary_msg = {
            "role": "system",
            "content": f"[Conversation summary — {len(middle)} messages condensed]\n{summary_text}",
        }

        compacted = head + [summary_msg] + tail
        event = {
            "type": "compaction",
            "removed": len(middle),
            "kept": len(compacted),
            "summary_preview": summary_text[:200],
        }
        return compacted, event

    async def _summarise(self, messages: list[dict]) -> str:
        text_parts = []
        for m in messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            text_parts.append(f"{role.upper()}: {content[:500]}")

        prompt = (
            "Summarise the following conversation segment into a dense, factual paragraph. "
            "Preserve all key decisions, tool results, variable values, and conclusions. "
            "Be concise but complete.\n\n"
            + "\n\n".join(text_parts)
        )
        return await self._llm.complete(prompt)
