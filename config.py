"""
Multi-provider LLM client factory.
Set CHIKA_PROVIDER=azure|anthropic|openai|ollama in .env
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# override=True so the project's .env always wins over any stale/empty
# ANTHROPIC_API_KEY or CHIKA_* vars that may be set in the OS environment.
load_dotenv(Path(__file__).parent / ".env", override=True)


import logging as _logging


def _bool(val: str | None, default: bool = False) -> bool:
    """Parse a boolean environment variable. Accepts: 1/true/yes/on (case-insensitive)."""
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int_env(key: str, default: int) -> int:
    """Parse an integer environment variable, falling back to default on bad values."""
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        _logging.warning("Config: %s=%r is not a valid integer; using default %d", key, val, default)
        return default


PROVIDER = os.getenv("CHIKA_PROVIDER", "anthropic").lower()

# Azure OpenAI
AZURE_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_API_KEY    = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "2024-10-21")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# Messages API max output tokens (raise CHIKA_ANTHROPIC_* if the model truncates long replies).
ANTHROPIC_MAX_TOKENS = _int_env("CHIKA_ANTHROPIC_MAX_TOKENS", 16384)
# With extended thinking, output + thinking must fit under max_tokens — default higher ceiling.
ANTHROPIC_MAX_TOKENS_THINKING = _int_env("CHIKA_ANTHROPIC_MAX_TOKENS_THINKING", 32768)
# Non-streaming paths (e.g. compaction, meta completions).
ANTHROPIC_COMPLETE_MAX_TOKENS = _int_env("CHIKA_ANTHROPIC_COMPLETE_MAX_TOKENS", 8192)

# OpenAI / Azure OpenAI
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL      = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_MAX_TOKENS = _int_env("CHIKA_OPENAI_MAX_TOKENS", 16384)

# Ollama (local)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3.1")

# Engine settings
MAX_HISTORY_TOKENS   = _int_env("CHIKA_MAX_HISTORY_TOKENS", 10000)
COMPACT_KEEP_FIRST   = _int_env("CHIKA_COMPACT_KEEP_FIRST", 2)
COMPACT_KEEP_LAST    = _int_env("CHIKA_COMPACT_KEEP_LAST", 4)
MAX_TOOL_TURNS       = _int_env("CHIKA_MAX_TOOL_TURNS", 20)
MAX_WORKFLOW_STEPS        = _int_env("CHIKA_MAX_WORKFLOW_STEPS", 8)
MAX_FILE_WRITES_PER_WF    = _int_env("CHIKA_MAX_FILE_WRITES_PER_WF", 3)
MAX_MEMORY_TOKENS    = _int_env("CHIKA_MAX_MEMORY_TOKENS", 2000)

# Grounding / hallucination controls
# When true, the engine runs a lightweight post-response validator that
# flags factual claims in the final reply that aren't supported by the
# $facts ledger. Emits a "validation_warning" event the frontend can show.
GROUNDING_VALIDATE_RESPONSE = _bool(os.getenv("CHIKA_VALIDATE_RESPONSE"), default=True)
# Minimum response length (chars) to bother running the validator
GROUNDING_MIN_LENGTH        = _int_env("CHIKA_GROUNDING_MIN_LENGTH", 160)

# Extended thinking (Anthropic only).
# When enabled, Claude runs a hidden reasoning pass before its response and
# the tokens are streamed to the frontend as {type: "thinking", text: ...}
# events so the user can see the agent's reasoning.
THINKING_ENABLED        = _bool(os.getenv("CHIKA_THINKING"), default=True)
THINKING_BUDGET_TOKENS  = _int_env("CHIKA_THINKING_BUDGET", 4000)

# Autonomy mode — controls whether tool calls require user approval.
# "supervised" (default): approval dialogs shown for each tool call.
# "autonomous": AI runs freely without approval popups.
# The runtime value can be overridden via PATCH /api/settings.
AUTONOMY_MODE = os.getenv("CHIKA_AUTONOMY", "supervised")

# API server
API_HOST    = os.getenv("CHIKA_HOST", "0.0.0.0")
API_PORT    = _int_env("CHIKA_PORT", 8000)
CHIKA_API_KEY = os.getenv("CHIKA_API_KEY", "")   # empty = auth disabled
# Comma-separated list of allowed CORS origins. Defaults to localhost dev servers.
# Set to "*" only for fully public APIs with no credentials.
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv(
        "CHIKA_CORS_ORIGINS",
        "http://localhost:5173,http://localhost:8000,http://127.0.0.1:5173,http://127.0.0.1:8000",
    ).split(",")
    if o.strip()
]


@dataclass
class ProviderConfig:
    provider: str
    model: str
    extra: dict = field(default_factory=dict)


def get_provider_config() -> ProviderConfig:
    if PROVIDER == "azure":
        return ProviderConfig(
            provider="azure",
            model=AZURE_DEPLOYMENT,
            extra={"endpoint": AZURE_ENDPOINT, "api_key": AZURE_API_KEY, "api_version": AZURE_API_VERSION},
        )
    elif PROVIDER == "anthropic":
        return ProviderConfig(provider="anthropic", model=ANTHROPIC_MODEL, extra={"api_key": ANTHROPIC_API_KEY})
    elif PROVIDER == "openai":
        return ProviderConfig(provider="openai", model=OPENAI_MODEL, extra={"api_key": OPENAI_API_KEY})
    elif PROVIDER == "ollama":
        return ProviderConfig(
            provider="ollama",
            model=OLLAMA_MODEL,
            extra={"base_url": OLLAMA_BASE_URL},
        )
    else:
        raise ValueError(f"Unknown CHIKA_PROVIDER: {PROVIDER!r}. Use anthropic, openai, azure, or ollama.")


def make_client():
    """Return the async LLM client for the configured provider."""
    cfg = get_provider_config()
    if cfg.provider == "azure":
        from openai import AsyncAzureOpenAI
        return AsyncAzureOpenAI(
            azure_endpoint=cfg.extra["endpoint"],
            api_key=cfg.extra["api_key"],
            api_version=cfg.extra["api_version"],
        )
    elif cfg.provider == "anthropic":
        import anthropic
        return anthropic.AsyncAnthropic(api_key=cfg.extra["api_key"])
    elif cfg.provider == "openai":
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=cfg.extra["api_key"])
    elif cfg.provider == "ollama":
        from openai import AsyncOpenAI
        # Ollama speaks the OpenAI API — no real key needed
        return AsyncOpenAI(base_url=cfg.extra["base_url"], api_key="ollama")


def reload_from_env() -> None:
    """Re-read ``.env`` and refresh every PROVIDER/MODEL/API-KEY global.

    Hot-reload entry point: call after ``.env`` has been edited (via
    ``/provider``, ``/model``, ``PATCH /api/provider``, or any path
    that writes the .env file) so the next ``make_client()`` and the
    engine's per-call provider checks see the new values without a
    process restart.

    Why we mutate module globals instead of computing per-call:
    callers throughout the engine read ``config.PROVIDER`` /
    ``config.ANTHROPIC_MODEL`` etc. directly — refactoring every
    callsite to read through a function would touch dozens of files.
    The module-globals + reload_from_env() pattern is one tight
    function, no callsite churn, and the refresh is atomic enough
    in practice (settings changes are rare; in-flight LLM calls
    already captured the old values into local request kwargs by
    the time they fire).
    """
    global PROVIDER
    global AZURE_ENDPOINT, AZURE_API_KEY, AZURE_DEPLOYMENT, AZURE_API_VERSION
    global ANTHROPIC_API_KEY, ANTHROPIC_MODEL
    global ANTHROPIC_MAX_TOKENS, ANTHROPIC_MAX_TOKENS_THINKING, ANTHROPIC_COMPLETE_MAX_TOKENS
    global OPENAI_API_KEY, OPENAI_MODEL, OPENAI_MAX_TOKENS
    global OLLAMA_BASE_URL, OLLAMA_MODEL
    global THINKING_ENABLED, THINKING_BUDGET_TOKENS
    global GROUNDING_VALIDATE_RESPONSE, GROUNDING_MIN_LENGTH
    global AUTONOMY_MODE

    load_dotenv(Path(__file__).parent / ".env", override=True)

    PROVIDER = os.getenv("CHIKA_PROVIDER", "anthropic").lower()

    AZURE_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_API_KEY     = os.getenv("AZURE_OPENAI_KEY", "")
    AZURE_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "2024-10-21")

    ANTHROPIC_API_KEY              = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL                = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    ANTHROPIC_MAX_TOKENS           = _int_env("CHIKA_ANTHROPIC_MAX_TOKENS", 16384)
    ANTHROPIC_MAX_TOKENS_THINKING  = _int_env("CHIKA_ANTHROPIC_MAX_TOKENS_THINKING", 32768)
    ANTHROPIC_COMPLETE_MAX_TOKENS  = _int_env("CHIKA_ANTHROPIC_COMPLETE_MAX_TOKENS", 8192)

    OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL      = os.getenv("OPENAI_MODEL", "gpt-4o")
    OPENAI_MAX_TOKENS = _int_env("CHIKA_OPENAI_MAX_TOKENS", 16384)

    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3.1")

    THINKING_ENABLED       = _bool(os.getenv("CHIKA_THINKING"), default=True)
    THINKING_BUDGET_TOKENS = _int_env("CHIKA_THINKING_BUDGET", 4000)

    GROUNDING_VALIDATE_RESPONSE = _bool(os.getenv("CHIKA_VALIDATE_RESPONSE"), default=True)
    GROUNDING_MIN_LENGTH        = _int_env("CHIKA_GROUNDING_MIN_LENGTH", 160)

    AUTONOMY_MODE = os.getenv("CHIKA_AUTONOMY", "supervised")
