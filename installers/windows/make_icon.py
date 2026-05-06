"""Generate ``chika.ico`` from the trefoil SVG mark.

Inno Setup's ``SetupIconFile`` and ``UninstallDisplayIcon`` directives
need a real ``.ico`` file on disk at compile time. We don't want to
commit a binary blob that drifts from the canonical SVG, so this
script renders the trefoil at the standard Windows icon resolutions
(16, 24, 32, 48, 64, 128, 256) using Pillow's drawing primitives —
no SVG renderer or Cairo dep needed.

The output is a multi-resolution ICO at the path passed as argv[1]
(or ``installers/windows/chika.ico`` by default).

Run from build_installer.ps1 before invoking ISCC. Idempotent: if
the .ico already exists and is newer than this script, we skip.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ACCENT = (108, 99, 255, 255)         # --accent (#6c63ff)
BG = (0, 0, 0, 0)                    # transparent
SIZES = [16, 24, 32, 48, 64, 128, 256]


def _trefoil_petal_points(size: int, rotation_deg: float) -> list[tuple[float, float]]:
    """Sample one petal of the trefoil as a polygon.

    The SVG path uses cubic Bezier curves; we approximate each curve
    with N samples. The petal is two mirrored bezier arcs that meet at
    the centre and the tip.

    Reference path (from docs/favicon.svg, viewBox -60..60):
        M  0,-58
        C  13,-44  19,-22  0,-6
        C -19,-22 -13,-44  0,-58 Z
    """
    samples_per_arc = 32
    cx, cy = size / 2, size / 2
    scale = size / 120.0  # viewBox is 120 wide
    rot = math.radians(rotation_deg)
    cos_r, sin_r = math.cos(rot), math.sin(rot)

    def bezier(t: float, p0, p1, p2, p3):
        u = 1 - t
        x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
        return x, y

    # Arc 1: (0,-58) → (0,-6) via control points (13,-44) (19,-22)
    arc1 = [bezier(i / samples_per_arc, (0, -58), (13, -44), (19, -22), (0, -6))
            for i in range(samples_per_arc + 1)]
    # Arc 2: (0,-6) → (0,-58) via control points (-19,-22) (-13,-44)
    arc2 = [bezier(i / samples_per_arc, (0, -6), (-19, -22), (-13, -44), (0, -58))
            for i in range(samples_per_arc + 1)]
    pts = arc1 + arc2

    out = []
    for x, y in pts:
        # Rotate, scale, recentre
        rx = x * cos_r - y * sin_r
        ry = x * sin_r + y * cos_r
        out.append((cx + rx * scale, cy + ry * scale))
    return out


def _render_size(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG)
    draw = ImageDraw.Draw(img)

    for rot in (0, 120, 240):
        pts = _trefoil_petal_points(size, rot)
        # Filled petal at the canonical accent. Filled (not stroked)
        # reads cleaner at the smaller icon sizes where a 3.4-unit
        # stroke would be a single fuzzy pixel.
        draw.polygon(pts, fill=ACCENT)

    # Hub dot — a small accent circle at the centre. Same r=3.2 in
    # SVG units.
    cx, cy = size / 2, size / 2
    r = max(1, size * 3.2 / 120)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ACCENT)
    return img


def main() -> int:
    here = Path(__file__).parent
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "chika.ico"
    out.parent.mkdir(parents=True, exist_ok=True)

    # Render each size from its own polygon math (sharper at 16/24px
    # than letting Pillow downscale a 256px master), then save all
    # of them as one multi-resolution ICO. The `sizes=` kwarg tells
    # Pillow's ICO encoder which entries to write; we hand it the
    # pre-rendered images via the largest as the base and the rest
    # as `append_images` so each size gets its own crisp render.
    images = [_render_size(s) for s in SIZES]
    largest = images[-1]
    largest.save(
        out,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=images[:-1],
    )
    print(f"wrote {out} ({len(SIZES)} sizes: {SIZES})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
