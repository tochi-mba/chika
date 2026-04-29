"""Tests for Compactor — needs_compaction, compact, estimate_tokens."""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio

from chika.core.compactor import Compactor, estimate_tokens


def run(coro):
    return asyncio.run(coro)


class FakeLLM:
    def __init__(self, response="This is a summary."):
        self.response = response
        self.calls = []

    async def complete(self, prompt):
        self.calls.append(prompt)
        return self.response


def make_messages(n, role="user", content_template="Message number {}"):
    return [{"role": role, "content": content_template.format(i)} for i in range(n)]


# ── estimate_tokens ───────────────────────────────────────────────────────────

def test_estimate_tokens_empty():
    assert estimate_tokens([]) == 0


def test_estimate_tokens_single_message():
    msgs = [{"role": "user", "content": "a" * 400}]
    assert estimate_tokens(msgs) == 100


def test_estimate_tokens_multiple_messages():
    msgs = [
        {"role": "user",      "content": "a" * 400},
        {"role": "assistant", "content": "b" * 800},
    ]
    assert estimate_tokens(msgs) == 300


def test_estimate_tokens_list_content():
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "a" * 400},
        {"type": "text", "text": "b" * 400},
    ]}]
    assert estimate_tokens(msgs) == 200


def test_estimate_tokens_none_content():
    msgs = [{"role": "user", "content": None}]
    assert estimate_tokens(msgs) == 0


# ── needs_compaction ──────────────────────────────────────────────────────────

def test_needs_compaction_false_when_small():
    llm = FakeLLM()
    c = Compactor(llm, max_tokens=1000)
    msgs = make_messages(3, content_template="short message {}")
    assert c.needs_compaction(msgs) is False


def test_needs_compaction_true_when_large():
    llm = FakeLLM()
    c = Compactor(llm, max_tokens=10)
    msgs = [{"role": "user", "content": "a" * 1000}]
    assert c.needs_compaction(msgs) is True


def test_needs_compaction_exactly_at_threshold():
    llm = FakeLLM()
    # Content of 40 chars = 10 tokens exactly
    c = Compactor(llm, max_tokens=10)
    msgs = [{"role": "user", "content": "a" * 40}]
    assert c.needs_compaction(msgs) is False  # Not > threshold


def test_needs_compaction_just_over_threshold():
    llm = FakeLLM()
    c = Compactor(llm, max_tokens=10)
    msgs = [{"role": "user", "content": "a" * 44}]  # 11 tokens
    assert c.needs_compaction(msgs) is True


# ── compact ───────────────────────────────────────────────────────────────────

def test_compact_too_few_messages_returns_unchanged():
    llm = FakeLLM()
    c = Compactor(llm, max_tokens=1000, keep_first=2, keep_last=4)
    msgs = make_messages(5)
    compacted, event = run(c.compact(msgs))
    assert compacted == msgs
    assert event is None


def test_compact_summarises_middle():
    llm = FakeLLM("Summary of middle messages.")
    c = Compactor(llm, max_tokens=1000, keep_first=2, keep_last=2)
    msgs = make_messages(10)
    compacted, event = run(c.compact(msgs))
    # head(2) + summary(1) + tail(2) = 5
    assert len(compacted) == 5


def test_compact_preserves_head_and_tail():
    llm = FakeLLM("summary")
    c = Compactor(llm, max_tokens=1000, keep_first=2, keep_last=2)
    msgs = make_messages(8)
    head = msgs[:2]
    tail = msgs[-2:]
    compacted, _ = run(c.compact(msgs))
    assert compacted[0] == head[0]
    assert compacted[1] == head[1]
    assert compacted[-1] == tail[-1]
    assert compacted[-2] == tail[-2]


def test_compact_summary_message_has_system_role():
    llm = FakeLLM("compact summary")
    c = Compactor(llm, max_tokens=1000, keep_first=1, keep_last=1)
    msgs = make_messages(5)
    compacted, _ = run(c.compact(msgs))
    summary_msg = compacted[1]  # between head and tail
    # Summary is injected as a "user" message so it's valid mid-conversation
    # for all LLM providers (some reject "system" outside position 0).
    assert summary_msg["role"] == "user"
    assert "compact summary" in summary_msg["content"]


def test_compact_event_has_correct_type():
    llm = FakeLLM("summary text")
    c = Compactor(llm, max_tokens=1000, keep_first=2, keep_last=2)
    msgs = make_messages(10)
    _, event = run(c.compact(msgs))
    assert event["type"] == "compaction"


def test_compact_event_has_removed_count():
    llm = FakeLLM("summary text")
    c = Compactor(llm, max_tokens=1000, keep_first=2, keep_last=2)
    msgs = make_messages(10)
    _, event = run(c.compact(msgs))
    # middle = 10 - 2 - 2 = 6 messages removed
    assert event["removed"] == 6


def test_compact_event_has_kept_count():
    llm = FakeLLM("summary text")
    c = Compactor(llm, max_tokens=1000, keep_first=2, keep_last=2)
    msgs = make_messages(10)
    _, event = run(c.compact(msgs))
    # head(2) + summary(1) + tail(2) = 5 kept
    assert event["kept"] == 5


def test_compact_event_has_summary_preview():
    llm = FakeLLM("This is the summary preview text.")
    c = Compactor(llm, max_tokens=1000, keep_first=2, keep_last=2)
    msgs = make_messages(10)
    _, event = run(c.compact(msgs))
    assert "summary_preview" in event
    assert "summary" in event["summary_preview"].lower()


def test_compact_calls_llm_with_middle_messages():
    llm = FakeLLM("summary")
    c = Compactor(llm, max_tokens=1000, keep_first=1, keep_last=1)
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "middle_one"},
        {"role": "user", "content": "middle_two"},
        {"role": "assistant", "content": "last"},
    ]
    run(c.compact(msgs))
    assert len(llm.calls) == 1
    prompt = llm.calls[0]
    assert "middle_one" in prompt
    assert "middle_two" in prompt
    # Head and tail should NOT be in the summarised block
    assert "first" not in prompt
    assert "last" not in prompt


def test_compact_with_list_content_messages():
    llm = FakeLLM("summary")
    c = Compactor(llm, max_tokens=1000, keep_first=1, keep_last=1)
    msgs = [
        {"role": "user", "content": "start"},
        {"role": "assistant", "content": [{"type": "text", "text": "middle list content"}]},
        {"role": "user", "content": "end"},
    ]
    # Should not crash with list content
    run(c.compact(msgs))


def test_compact_reduces_token_count():
    llm = FakeLLM("s")
    c = Compactor(llm, max_tokens=1000, keep_first=2, keep_last=2)
    # Make messages with lots of tokens
    msgs = [{"role": "user", "content": "a" * 400} for _ in range(10)]
    original_tokens = estimate_tokens(msgs)
    compacted, _ = run(c.compact(msgs))
    compacted_tokens = estimate_tokens(compacted)
    assert compacted_tokens < original_tokens
