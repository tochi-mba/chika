"""Chika trefoil mark — terminal art with parity to the SVG version.

The canonical mark lives in ``frontend/src/components/ChikaMark.vue``.
Here we render the same geometry (3 leaves at 120° intervals + centre
dot) to a small bitmap by sampling the cubic-bezier petal path, then
collapse vertical pixel pairs into half-block characters so the same
shape reads in any monospace terminal.

Why bitmap-rasterise instead of hand-drawing ASCII art:

  - Hand-drawn art doesn't preserve the curve quality of the SVG.
  - The half-block trick (``▀``, ``▄``, ``█``, space) effectively
    doubles the vertical resolution of the terminal — a 12-row glyph
    only takes 6 character rows.
  - When the SVG geometry changes, regenerate by editing the
    constants below; everything else follows.

Frames for the animator: two (idle / pulse). The ``pulse`` frame
inverts the centre dot — used during streaming to read as a
heartbeat without needing rotation, which doesn't translate to a
character grid anyway.
"""
from __future__ import annotations

import math

# ── Geometry (mirrors ChikaMark.vue) ─────────────────────────────
# Petal cubic-bezier control points in viewBox space (-60..60).
# M 0,-58 C 13,-44 19,-22 0,-6 C -19,-22 -13,-44 0,-58 Z
_TIP_Y     = -58.0
_INNER_Y   = -6.0
_CP1       = (13.0, -44.0)   # outer side, near tip
_CP2       = (19.0, -22.0)   # outer side, near base
_HUB_R     = 3.2

# Render canvas in viewBox units (-W/2..W/2 in both axes).
# 20×20 is a good size for a banner: ~10 character rows tall
# (half-block paired), petal tips read crisply, total width fits
# comfortably inside an 80-col terminal panel.
_BITMAP_W  = 20   # cols (must be even)
_BITMAP_H  = 20   # rows (must be even — half-block pairs)


def _bezier_pt(t: float, p0: tuple[float, float], p1: tuple[float, float],
               p2: tuple[float, float], p3: tuple[float, float]) -> tuple[float, float]:
    """Cubic Bezier sample at ``t`` ∈ [0,1]."""
    u = 1.0 - t
    bb = u * u
    cc = t * t
    return (
        bb * u * p0[0] + 3 * bb * t * p1[0] + 3 * u * cc * p2[0] + cc * t * p3[0],
        bb * u * p0[1] + 3 * bb * t * p1[1] + 3 * u * cc * p2[1] + cc * t * p3[1],
    )


def _petal_polygon() -> list[tuple[float, float]]:
    """Return the petal as a polygon by sampling its two cubic curves.

    The path is:
        M 0,-58 C cp1, cp2, 0,-6 C -cp2, -cp1, 0,-58 Z

    Sample N points along each curve, concatenate, and return as a
    closed polygon (first point = last point).
    """
    N = 24
    tip   = (0.0, _TIP_Y)
    inner = (0.0, _INNER_Y)
    pts: list[tuple[float, float]] = []
    # Right side: tip → cp1 → cp2 → inner.
    for i in range(N + 1):
        pts.append(_bezier_pt(i / N, tip, _CP1, _CP2, inner))
    # Left side: inner → -cp2 → -cp1 → tip.
    cp1m = (-_CP2[0], _CP2[1])
    cp2m = (-_CP1[0], _CP1[1])
    for i in range(1, N + 1):
        pts.append(_bezier_pt(i / N, inner, cp1m, cp2m, tip))
    return pts


def _rotate(p: tuple[float, float], deg: float) -> tuple[float, float]:
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    x, y = p
    return (x * c - y * s, x * s + y * c)


def _point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    """Standard ray-casting point-in-polygon."""
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _rasterise(stroke_width: float = 5.0) -> list[list[bool]]:
    """Render the trefoil silhouette into a boolean grid.

    Builds the 3 rotated petals + hub disc, then for each pixel asks
    "is this pixel within ``stroke_width/2`` of any petal edge OR
    inside the hub disc?".  That gives the STROKE-ONLY look.
    """
    base = _petal_polygon()
    petals = [
        [_rotate(p, 0)   for p in base],
        [_rotate(p, 120) for p in base],
        [_rotate(p, 240) for p in base],
    ]
    half_w = stroke_width / 2.0

    # Map each grid cell to a viewBox coordinate (centred at 0,0,
    # range -60..60).  Sample at cell centre.
    vw, vh = 120.0, 120.0
    grid = [[False] * _BITMAP_W for _ in range(_BITMAP_H)]

    # Pre-compute a coarser polygon (every 2nd vertex) for distance
    # checks — exact distance to a cubic is overkill at this resolution.
    coarse_petals = [poly[::2] for poly in petals]

    for row in range(_BITMAP_H):
        # Vertical: row 0 = top of viewBox = y = -60.
        y = -vh / 2 + (row + 0.5) * (vh / _BITMAP_H)
        for col in range(_BITMAP_W):
            # Horizontal: col 0 = left of viewBox.
            x = -vw / 2 + (col + 0.5) * (vw / _BITMAP_W)

            # Hub disc.
            if math.hypot(x, y) <= _HUB_R + half_w:
                grid[row][col] = True
                continue

            # Stroke distance to any petal polygon edge.
            for poly in coarse_petals:
                if _near_polygon_edge(x, y, poly, half_w):
                    grid[row][col] = True
                    break
    return grid


def _near_polygon_edge(x: float, y: float, poly: list[tuple[float, float]],
                       d: float) -> bool:
    """True if (x,y) is within ``d`` of any edge of ``poly``."""
    d2 = d * d
    for i in range(len(poly) - 1):
        x1, y1 = poly[i]
        x2, y2 = poly[i + 1]
        # Squared distance from (x,y) to segment ((x1,y1),(x2,y2)).
        dx, dy = x2 - x1, y2 - y1
        ll = dx * dx + dy * dy
        if ll == 0:
            continue
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / ll))
        px = x1 + t * dx
        py = y1 + t * dy
        if (x - px) ** 2 + (y - py) ** 2 <= d2:
            return True
    return False


def _grid_to_halfblock(grid: list[list[bool]]) -> str:
    """Collapse pairs of rows into half-block characters.

    Each output character represents 2 vertical pixels:
        upper full, lower full → █
        upper full, lower empty → ▀
        upper empty, lower full → ▄
        both empty → space
    """
    rows = len(grid)
    cols = len(grid[0]) if grid else 0
    out: list[str] = []
    for r in range(0, rows, 2):
        line: list[str] = []
        for c in range(cols):
            top = grid[r][c]
            bot = grid[r + 1][c] if r + 1 < rows else False
            if top and bot:
                line.append("█")
            elif top:
                line.append("▀")
            elif bot:
                line.append("▄")
            else:
                line.append(" ")
        # Strip trailing spaces so the printed glyph isn't padded.
        out.append("".join(line).rstrip())
    return "\n".join(out)


# ── Cached frames ────────────────────────────────────────────────
# The bitmap is deterministic and small — compute once on import.

_FRAME_IDLE = _grid_to_halfblock(_rasterise(stroke_width=7.0))


def get_frame(state: str = "idle") -> str:
    """Return the ASCII glyph for ``state``.

    Currently a single static frame — terminal grids don't have the
    resolution to carry the SVG's per-leaf flip animation
    meaningfully. The renderer can ALTERNATE colours on the static
    glyph during streaming/thinking to convey activity (see
    ``render_banner`` in renderer.py).
    """
    return _FRAME_IDLE


# ── Inline state glyph (one row, animated) ───────────────────────
# Used in the "Vibing… 2.3s" status line during agent activity, the
# same way Claude Code shows ``✸ Vibing…`` while a turn is in flight.
# Three frames, each one "lights up" a different leaf of the trefoil
# — direct port of the SVG streaming wave to a 3-step character cycle.
#
# Each frame is a fixed-width 5-char strip:
#   col 0..1: left  leaf
#   col 2  : centre dot
#   col 3..4: right leaf  (and the top leaf is implied by the
#                          "lit" highlight cycling around)
#
# In practice we just cycle which of the 3 trefoil glyphs gets the
# bright accent colour and which two get the muted shade — the
# renderer applies the styling per character, this module only
# decides "which leaf is the bright one this frame".
INLINE_GLYPHS = ("◇", "◇", "◇")     # baseline: 3 outline diamonds
INLINE_HUB    = "•"                  # centre anchor dot

# 3-frame highlight rotation — index of the leaf to brighten this frame.
INLINE_HIGHLIGHT_CYCLE: tuple[int, ...] = (0, 1, 2)

# Verbs the inline indicator cycles through. Borrowed from Claude
# Code's bag of present-continuous "I'm working" verbs — keeps the
# user informed without claiming anything specific the agent might
# not actually be doing.
INLINE_VERBS: tuple[str, ...] = (
    "Thinking",
    "Vibing",
    "Pondering",
    "Cooking",
    "Reasoning",
    "Considering",
    "Working",
    "Brewing",
)


def inline_frame(tick: int) -> tuple[str, str, str, int]:
    """Return ``(left, centre, right, highlight_idx)`` for animator tick ``tick``.

    The renderer uses this to assemble a styled inline row:
    leaves indexed 0 (top), 1 (right), 2 (left) — only the one whose
    index matches ``highlight_idx`` should render bright; the other
    two muted. ``centre`` is the anchor dot, always rendered.
    """
    idx = INLINE_HIGHLIGHT_CYCLE[tick % len(INLINE_HIGHLIGHT_CYCLE)]
    return INLINE_GLYPHS[0], INLINE_HUB, INLINE_GLYPHS[2], idx


def inline_verb(tick: int, *, slow: int = 18) -> str:
    """Return the present-continuous verb for ``tick``.

    The verb changes every ``slow`` ticks (default ~3s at 6 fps) so
    the indicator stays readable instead of strobing word-to-word.
    """
    return INLINE_VERBS[(tick // max(1, slow)) % len(INLINE_VERBS)]


if __name__ == "__main__":
    # Visual sanity-check: ``python -m chika._cli.mark``
    print(_FRAME_IDLE)
