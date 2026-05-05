"""Read and write the project ``.env`` file safely.

Used by both the CLI (``/env`` command) and the API (``/api/env`` route).
Comments and blank lines are preserved; only matching keys are rewritten in
place. Sensitive values (API keys, secrets, tokens) can optionally be masked
when displayed.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from chika.core._io import atomic_write

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

# Underscore-delimited segments that mark a credential. Matched as whole
# segments so e.g. ``MAX_TOKENS`` (a token *count*) is NOT classified as a
# secret while ``ACCESS_TOKEN`` correctly is.
_SECRET_SEGMENTS = frozenset(
    ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY")
)

# A reasonably strict env-line matcher: KEY=value (no spaces around =).
# Quoted values are unwrapped on read, re-wrapped on write when needed.
_ENV_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def env_path() -> Path:
    """Return the project's .env path (whether or not it exists)."""
    return _ENV_PATH


def is_sensitive(key: str) -> bool:
    """True if a key looks like it holds a secret.

    Matches whole underscore-delimited segments — ``ACCESS_TOKEN`` is a
    secret; ``MAX_TOKENS`` (a token count) is not.
    """
    segments = key.upper().split("_")
    if any(seg in _SECRET_SEGMENTS for seg in segments):
        return True
    # Special-case: an env name that is *exactly* a secret keyword.
    if key.upper() in _SECRET_SEGMENTS:
        return True
    return False


def mask(value: str) -> str:
    """Mask a secret value for display, preserving prefix/suffix as a hint."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]}  ({len(value)} chars)"


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def read_env() -> dict[str, str]:
    """Return all non-comment KEY=VALUE pairs from the .env file."""
    if not _ENV_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for raw_line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENV_LINE_RE.match(line)
        if not m:
            continue
        key, value = m.group(1), _strip_quotes(m.group(2).strip())
        out[key] = value
    return out


def read_env_for_display(*, mask_secrets: bool = True) -> list[tuple[str, str, bool]]:
    """Return ``(key, display_value, is_secret)`` triples for UI display."""
    raw = read_env()
    rows: list[tuple[str, str, bool]] = []
    for k, v in raw.items():
        secret = is_sensitive(k)
        rows.append((k, mask(v) if (secret and mask_secrets) else v, secret))
    return rows


def write_env(updates: dict[str, str | None], *, create: bool = True) -> dict[str, str]:
    """Apply ``updates`` to .env, preserving order and comments.

    - ``key: value``  → set/replace
    - ``key: None``   → delete the line if present (no-op otherwise)

    Lines for keys not in ``updates`` are kept verbatim. New keys are appended
    at the end. Returns the post-write key/value map.
    """
    pending = dict(updates)

    if not _ENV_PATH.exists():
        if not create:
            raise FileNotFoundError(f".env not found at {_ENV_PATH}")
        _ENV_PATH.touch()

    lines = _ENV_PATH.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(raw_line)
            continue
        m = _ENV_LINE_RE.match(stripped)
        if not m:
            new_lines.append(raw_line)
            continue
        key = m.group(1)
        if key in pending:
            new_value = pending.pop(key)
            if new_value is None:
                # Deletion → drop the line
                continue
            new_lines.append(f"{key}={_quote_if_needed(new_value)}")
        else:
            new_lines.append(raw_line)

    # Append any keys that weren't already in the file
    if pending:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        for k, v in pending.items():
            if v is None:
                continue
            new_lines.append(f"{k}={_quote_if_needed(v)}")

    atomic_write(_ENV_PATH, "\n".join(new_lines) + "\n")

    # Refresh os.environ so subsequent imports of `config` see new values.
    for k, v in updates.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return read_env()


def _quote_if_needed(value: str) -> str:
    """Wrap value in double quotes only when it contains characters that
    confuse python-dotenv parsers (whitespace, ``#``, leading/trailing space).
    """
    if value == "":
        return ""
    needs_quote = (
        any(c in value for c in (" ", "\t", "#", '"', "'"))
        or value != value.strip()
    )
    if not needs_quote:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
