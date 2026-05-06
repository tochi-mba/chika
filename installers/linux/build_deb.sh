#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
#  Chika — Linux .deb builder
# ─────────────────────────────────────────────────────────────────────
#
# Run from the repo root:
#
#   ./installers/linux/build_deb.sh
#
# Builds:
#
#   1. A wheel via ``python -m build --wheel``
#   2. A staged .deb tree at ``build/installer-deb/chika_<v>_all/``
#   3. The .deb via ``dpkg-deb --build``
#
# Output: ``installers/dist/chika_<v>_all.deb``
#
# Architecture is ``all`` because the wheel is pure-Python (no native
# extensions). If we ever ship a native dep, switch to ``amd64`` /
# ``arm64`` and add per-arch CI jobs.
#
# Pass --version to override; --skip-wheel to reuse dist/*.whl.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALLER_DIR="${REPO_ROOT}/installers/linux"
BUILD_DIR="${REPO_ROOT}/build/installer-deb"
DIST_DIR="${REPO_ROOT}/installers/dist"
WHEEL_DIR="${REPO_ROOT}/dist"

VERSION=""
SKIP_WHEEL=0
while [[ $# -gt 0 ]]; do
    case $1 in
        --version) VERSION="$2"; shift 2 ;;
        --skip-wheel) SKIP_WHEEL=1; shift ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

if [[ -z "$VERSION" ]]; then
    VERSION="$(grep -E '^[[:space:]]*version[[:space:]]*=' "${REPO_ROOT}/pyproject.toml" \
        | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi
[[ -z "$VERSION" ]] && { echo "could not determine version" >&2; exit 1; }
echo "Building chika ${VERSION}.deb..."

# ── Step 1: wheel ────────────────────────────────────────────────────

if [[ $SKIP_WHEEL -eq 0 ]]; then
    echo "  · building wheel..."
    cd "$REPO_ROOT"
    python3 -m pip install --upgrade build --quiet
    python3 -m build --wheel --outdir "$WHEEL_DIR" >/dev/null
fi
WHEEL="$(ls -t "${WHEEL_DIR}"/chika-${VERSION}-*.whl 2>/dev/null | head -1 || true)"
[[ -z "$WHEEL" ]] && { echo "no wheel at ${WHEEL_DIR}/chika-${VERSION}-*.whl" >&2; exit 1; }

# ── Step 2: stage the .deb tree ──────────────────────────────────────

PKG_NAME="chika_${VERSION}_all"
PKG_DIR="${BUILD_DIR}/${PKG_NAME}"
rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR/DEBIAN" "$PKG_DIR/opt/chika" "$PKG_DIR/usr/bin"

# DEBIAN control + maintainer scripts
sed "s/VERSION_PLACEHOLDER/${VERSION}/" "${INSTALLER_DIR}/debian/control" > "$PKG_DIR/DEBIAN/control"
cp "${INSTALLER_DIR}/debian/postinst" "$PKG_DIR/DEBIAN/postinst"
cp "${INSTALLER_DIR}/debian/prerm"    "$PKG_DIR/DEBIAN/prerm"
chmod 0755 "$PKG_DIR/DEBIAN/postinst" "$PKG_DIR/DEBIAN/prerm"

# Wheel + launcher
cp "$WHEEL" "$PKG_DIR/opt/chika/"
cp "${INSTALLER_DIR}/chika" "$PKG_DIR/usr/bin/chika"
chmod 0755 "$PKG_DIR/usr/bin/chika"

# install_marker.json is written by postinst (so it picks up the
# resolved version from the freshly-built venv); we don't ship it
# pre-baked here.

# ── Step 3: dpkg-deb ──────────────────────────────────────────────────

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "dpkg-deb not found — install via 'apt-get install dpkg-dev' or run on a Debian-family host" >&2
    exit 1
fi

mkdir -p "$DIST_DIR"
OUTPUT="$DIST_DIR/${PKG_NAME}.deb"
dpkg-deb --build --root-owner-group "$PKG_DIR" "$OUTPUT" >/dev/null

# Sanity-check with lintian if available (it's not on every CI image
# but when present catches a class of policy violations early).
if command -v lintian >/dev/null 2>&1; then
    lintian --no-tag-display-limit --suppress-tags new-package-should-close-itp-bug "$OUTPUT" || true
fi

echo ""
echo "✓ .deb ready: $OUTPUT"
ls -lh "$OUTPUT" | awk '{print "  size:", $5}'
