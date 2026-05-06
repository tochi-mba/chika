"""
Brand-mark helpers shared across every Python rendering surface.

The trefoil itself is duplicated across six surfaces (Vue, extension
popup, manifest icon renderer, CLI ASCII rasteriser, landing page,
favicon) — see ADR-27 + ``scripts/check_brand_parity.py`` for the
why-and-how of that. Each surface needs a different rendering shape
(CSS-animated component, ASCII art, ICO bytes, etc.), so a single
"share the SVG string" abstraction would force every surface to
re-implement what its rendering medium handles natively.

What this module DOES dedupe is the **Python-side** consumers — any
server-rendered HTML response that embeds the trefoil should pull
markup through ``trefoil_svg()`` so we don't keep growing parallel
hard-coded copies inside Python files.

The canonical bytes live at ``docs/favicon.svg``. We read them at
import time; subsequent calls just template-substitute size + color.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FAVICON_PATH = REPO_ROOT / "docs" / "favicon.svg"

# Default accent colour. Matches --accent in the design tokens; if you
# change it there, change it here too (and the parity-checker will
# remind you to update the other surfaces).
DEFAULT_ACCENT = "#6c63ff"


@lru_cache(maxsize=1)
def _read_favicon() -> str:
    """Read the canonical SVG from disk once.

    Cached so module-level callers don't re-read on every render.
    """
    if not FAVICON_PATH.exists():
        # Fallback so the module is import-safe even if the install
        # tree is partial (e.g., a wheel that didn't ship docs/).
        return _FALLBACK_SVG
    return FAVICON_PATH.read_text(encoding="utf-8").strip()


def trefoil_svg(
    *,
    size: int = 48,
    color: str = DEFAULT_ACCENT,
) -> str:
    """Return inline-ready trefoil SVG markup.

    Parameters
    ----------
    size : int
        Pixel width/height to render at. The viewBox is fixed at
        -60..60, so size just scales it; the petal stroke uses
        non-scaling-stroke wherever the rendering surface honours it.
    color : str
        CSS colour for the petals + hub dot. Defaults to the
        accent token.
    """
    base = _read_favicon()
    # Inject explicit width/height — the canonical favicon SVG
    # intentionally omits them so it scales to its container; for
    # inline embeds in HTML responses we want a fixed size.
    if "width=" not in base:
        base = base.replace(
            "<svg ", f'<svg width="{size}" height="{size}" ', 1
        )
    # Swap the canonical accent if a custom colour was requested.
    if color != DEFAULT_ACCENT:
        base = re.sub(re.escape(DEFAULT_ACCENT), color, base)
    return base


# ── Fallback (used when docs/favicon.svg isn't on disk) ──────────────
#
# Identical bytes to the canonical favicon. Kept here so this module
# is import-safe in stripped install trees. The brand-parity checker
# verifies the disk copy stays in sync with the rest of the surfaces;
# this fallback is just a soft-fail safety net, not a second source
# of truth.

_FALLBACK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="-60 -60 120 120">
  <g stroke="#6c63ff" stroke-width="3.4" fill="none" stroke-linecap="round" stroke-linejoin="round">
    <g transform="rotate(0)"><path d="M 0,-58 C 13,-44 19,-22 0,-6 C -19,-22 -13,-44 0,-58 Z"/></g>
    <g transform="rotate(120)"><path d="M 0,-58 C 13,-44 19,-22 0,-6 C -19,-22 -13,-44 0,-58 Z"/></g>
    <g transform="rotate(240)"><path d="M 0,-58 C 13,-44 19,-22 0,-6 C -19,-22 -13,-44 0,-58 Z"/></g>
  </g>
  <circle r="3.2" fill="#6c63ff"/>
</svg>"""
