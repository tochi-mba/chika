"""Verify the chika trefoil renders identically across surfaces.

Per ADR-27, the canonical SVG petal path is duplicated by hand on
five surfaces (Vue, popup, manifest-icon-render, terminal art,
landing page). The contract is "all five carry the same path bytes."
This script enforces it.

Run:

    python scripts/check_brand_parity.py             # exit 0 if parity, 1 if drift
    python scripts/check_brand_parity.py --verbose   # print each surface's path

The canonical path (single source of truth) is read from the Vue
component. Every other surface is checked for byte-identical
appearance of that path string.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The Vue component is the canonical source.
VUE_CANONICAL = REPO_ROOT / "frontend" / "src" / "components" / "ChikaMark.vue"

# Every file that must contain the canonical path. Ordered by audience:
# frontend → extension → CLI rasteriser → manifest icon renderer → landing.
SURFACES: list[Path] = [
    REPO_ROOT / "frontend" / "src" / "components" / "ChikaMark.vue",
    REPO_ROOT / "extension" / "popup" / "popup.html",
    REPO_ROOT / "extension" / "icons" / "_render.html",
    REPO_ROOT / "chika" / "_cli" / "mark.py",
    REPO_ROOT / "docs" / "index.html",
    REPO_ROOT / "docs" / "favicon.svg",
]

# Pattern that matches the petal cubic-bezier:
# M 0,-58 C 13,-44 19,-22 0,-6 C -19,-22 -13,-44 0,-58 Z
# We extract the numeric coordinates so cosmetic spacing differences
# (single space vs double, comma-space vs space-only) don't false-positive.
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def extract_petal_signature(text: str) -> str | None:
    """Return a normalised signature of the canonical petal path, or None.

    The signature is the sequence of numeric coordinates as strings —
    independent of inter-token whitespace. So:

       M 0,-58 C 13,-44 19,-22 0,-6 C -19,-22 -13,-44 0,-58 Z
       M 0,-58 C  13,-44  19,-22  0,-6 C -19,-22 -13,-44 0,-58 Z

    both produce ``"0,-58,13,-44,19,-22,0,-6,-19,-22,-13,-44,0,-58"``.

    For the CLI rasteriser (``mark.py``) the path lives as Python
    constants (``_TIP_Y = -58.0``, ``_CP1 = (13.0, -44.0)``, etc.).
    We match the numeric tuple directly.
    """
    # Grab a window around the canonical "M 0,-58 C" so we don't pick up
    # unrelated numbers elsewhere in the file.
    m = re.search(r"M\s*0\s*,\s*-58.*?Z", text, re.DOTALL)
    if m:
        nums = _NUM_RE.findall(m.group(0))
        return ",".join(nums)

    # mark.py form — look for the constants block.
    if "_TIP_Y" in text and "-58" in text:
        # Pull the numeric values from the canonical declarations
        # ``_TIP_Y     = -58.0``
        # ``_INNER_Y   = -6.0``
        # ``_CP1       = (13.0, -44.0)``
        # ``_CP2       = (19.0, -22.0)``
        tip = re.search(r"_TIP_Y\s*=\s*(-?\d+(?:\.\d+)?)", text)
        inner = re.search(r"_INNER_Y\s*=\s*(-?\d+(?:\.\d+)?)", text)
        cp1 = re.search(r"_CP1\s*=\s*\((-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\)", text)
        cp2 = re.search(r"_CP2\s*=\s*\((-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\)", text)
        if all((tip, inner, cp1, cp2)):
            # Build the same numeric sequence the SVG path produces
            # M 0,tip C cp1 cp2 0,inner C -cp2 -cp1 0,tip Z
            tip_v = _strip_trailing_zero(tip.group(1))
            inner_v = _strip_trailing_zero(inner.group(1))
            cp1x = _strip_trailing_zero(cp1.group(1))
            cp1y = _strip_trailing_zero(cp1.group(2))
            cp2x = _strip_trailing_zero(cp2.group(1))
            cp2y = _strip_trailing_zero(cp2.group(2))
            mirror_cp2x = _flip_sign(cp2x)
            mirror_cp1x = _flip_sign(cp1x)
            return ",".join([
                "0", tip_v,
                cp1x, cp1y, cp2x, cp2y, "0", inner_v,
                mirror_cp2x, cp2y, mirror_cp1x, cp1y, "0", tip_v,
            ])

    return None


def _strip_trailing_zero(s: str) -> str:
    """``-58.0`` → ``-58``, ``13.5`` → ``13.5``."""
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _flip_sign(s: str) -> str:
    if s.startswith("-"):
        return s[1:]
    if s == "0":
        return "0"
    return f"-{s}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    if not VUE_CANONICAL.is_file():
        print(f"canonical source missing: {VUE_CANONICAL}", file=sys.stderr)
        return 1

    canonical = extract_petal_signature(VUE_CANONICAL.read_text(encoding="utf-8"))
    if canonical is None:
        print(f"could not extract canonical petal from {VUE_CANONICAL}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"canonical: {canonical}")

    drift = []
    for surface in SURFACES:
        if not surface.is_file():
            drift.append((surface, "MISSING"))
            continue
        sig = extract_petal_signature(surface.read_text(encoding="utf-8"))
        if sig is None:
            drift.append((surface, "NO_PATH_FOUND"))
        elif sig != canonical:
            drift.append((surface, f"MISMATCH ({sig})"))
        elif args.verbose:
            print(f"  ✓ {surface.relative_to(REPO_ROOT)}")

    if drift:
        print("\nbrand-mark drift detected (ADR-27 parity violation):", file=sys.stderr)
        for path, reason in drift:
            print(f"  ✗ {path.relative_to(REPO_ROOT)} — {reason}", file=sys.stderr)
        print(
            "\nThe canonical path is in frontend/src/components/ChikaMark.vue.\n"
            "Update every surface to match. See ADR-27 in DECISIONS.md.",
            file=sys.stderr,
        )
        return 1

    print(f"all {len(SURFACES)} surfaces match the canonical petal path.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
