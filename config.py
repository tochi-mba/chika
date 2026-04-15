"""
Multi-provider LLM client factory.
Set CHIKA_PROVIDER=azure|anthropic|openai in .env
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# override=True so the project's .env always wins over any stale/empty
# ANTHROPIC_API_KEY or CHIKA_* vars that may be set in the OS environment.
load_dotenv(Path(__file__).parent / ".env", override=True)

PROVIDER = os.getenv("CHIKA_PROVIDER", "anthropic").lower()

# Azure OpenAI
AZURE_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_API_KEY    = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "2024-10-21")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o")

# Engine settings
MAX_HISTORY_TOKENS   = int(os.getenv("CHIKA_MAX_HISTORY_TOKENS", "80000"))
COMPACT_KEEP_FIRST   = int(os.getenv("CHIKA_COMPACT_KEEP_FIRST", "2"))
COMPACT_KEEP_LAST    = int(os.getenv("CHIKA_COMPACT_KEEP_LAST", "4"))
MAX_TOOL_TURNS       = int(os.getenv("CHIKA_MAX_TOOL_TURNS", "20"))
MAX_MEMORY_TOKENS    = int(os.getenv("CHIKA_MAX_MEMORY_TOKENS", "2000"))

# Grounding / hallucination controls
# When true, the engine runs a lightweight post-response validator that
# flags factual claims in the final reply that aren't supported by the
# $facts ledger. Emits a "validation_warning" event the frontend can show.
GROUNDING_VALIDATE_RESPONSE = os.getenv("CHIKA_VALIDATE_RESPONSE", "true").lower() == "true"
# Minimum response length (chars) to bother running the validator
GROUNDING_MIN_LENGTH        = int(os.getenv("CHIKA_GROUNDING_MIN_LENGTH", "160"))

# API server
API_HOST    = os.getenv("CHIKA_HOST", "0.0.0.0")
API_PORT    = int(os.getenv("CHIKA_PORT", "8000"))
CHIKA_API_KEY = os.getenv("CHIKA_API_KEY", "")   # empty = auth disabled


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
    else:
        raise ValueError(f"Unknown CHIKA_PROVIDER: {PROVIDER!r}. Use azure, anthropic, or openai.")


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
