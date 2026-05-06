#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
#  Chika — macOS .pkg builder
# ─────────────────────────────────────────────────────────────────────
#
# Run from the repo root:
#
#   ./installers/macos/build_pkg.sh
#
# Builds:
#
#   1. A wheel via ``python -m build --wheel``
#   2. A staged payload tree at ``build/installer-macos/payload/``
#      (the file layout the .pkg will lay down at install time)
#   3. A component .pkg via ``pkgbuild`` (with our pre/postinstall
#      scripts attached)
#   4. A distribution .pkg via ``productbuild`` (gives a real wizard
#      with welcome / readme / install screens, the kind of thing
#      Mac users expect)
#
# Output: ``installers/dist/Chika-<version>.pkg``
#
# Pass --version to override the version detected from pyproject.toml.
# Pass --skip-wheel to use an existing dist/*.whl.
#
# The .pkg is unsigned by default. To sign + notarise for distribution
# (required for Gatekeeper to allow it without warnings), set:
#
#   export CHIKA_DEVELOPER_ID="Developer ID Installer: Your Name (TEAMID)"
#   export CHIKA_NOTARY_PROFILE="<keychain profile name>"
#
# We'll then run productsign + xcrun notarytool. Without these, the
# build still succeeds — users just get a Gatekeeper warning the
# first time they double-click the .pkg.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALLER_DIR="${REPO_ROOT}/installers/macos"
BUILD_DIR="${REPO_ROOT}/build/installer-macos"
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
    # Read from pyproject.toml — same source of truth as the Windows
    # build script. Stays in sync without manual coordination.
    VERSION="$(grep -E '^[[:space:]]*version[[:space:]]*=' "${REPO_ROOT}/pyproject.toml" \
        | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi
[[ -z "$VERSION" ]] && { echo "could not determine version" >&2; exit 1; }
echo "Building Chika ${VERSION}..."

# ── Step 1: wheel ────────────────────────────────────────────────────

if [[ $SKIP_WHEEL -eq 0 ]]; then
    echo "  · building wheel..."
    cd "$REPO_ROOT"
    python3 -m pip install --upgrade build --quiet
    python3 -m build --wheel --outdir "$WHEEL_DIR" >/dev/null
fi
WHEEL="$(ls -t "${WHEEL_DIR}"/chika-${VERSION}-*.whl 2>/dev/null | head -1 || true)"
[[ -z "$WHEEL" ]] && { echo "no wheel found at ${WHEEL_DIR}/chika-${VERSION}-*.whl" >&2; exit 1; }
echo "  · wheel: $(basename "$WHEEL")"

# ── Step 2: stage payload ────────────────────────────────────────────
# .pkg payloads are filesystem trees rooted at ``/``. We install to
# ``/Library/Application Support/Chika/`` (system-wide; works for
# multi-user macs without a user profile dance) — but the postinstall
# script then symlinks ``chika`` into ``/usr/local/bin/`` so it lands
# on PATH for every user.

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/payload/Library/Application Support/Chika"
mkdir -p "$BUILD_DIR/scripts"

# The wheel + the source archive go to the install dir. We don't bake
# a venv into the .pkg because virtualenvs aren't relocatable across
# installs reliably; the postinstall builds it on the user's machine
# against their actual Python.
cp "$WHEEL" "$BUILD_DIR/payload/Library/Application Support/Chika/"
cp "${INSTALLER_DIR}/chika" "$BUILD_DIR/payload/Library/Application Support/Chika/"
chmod +x "$BUILD_DIR/payload/Library/Application Support/Chika/chika"

# Drop the install marker so ``chika update`` knows we're macos_installer.
cat > "$BUILD_DIR/payload/Library/Application Support/Chika/install_marker.json" <<JSON
{
  "kind": "macos_installer",
  "version": "${VERSION}",
  "wheel": "$(basename "$WHEEL")",
  "installed_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
JSON

# Pre/postinstall scripts.
cp "${INSTALLER_DIR}/scripts/preinstall" "$BUILD_DIR/scripts/preinstall"
cp "${INSTALLER_DIR}/scripts/postinstall" "$BUILD_DIR/scripts/postinstall"
chmod +x "$BUILD_DIR/scripts/"*

# ── Step 3: component .pkg ──────────────────────────────────────────

mkdir -p "$DIST_DIR"
COMPONENT_PKG="$BUILD_DIR/Chika-component.pkg"
pkgbuild \
    --root "$BUILD_DIR/payload" \
    --scripts "$BUILD_DIR/scripts" \
    --identifier "com.chika.app" \
    --version "$VERSION" \
    --install-location "/" \
    "$COMPONENT_PKG"

# ── Step 4: distribution .pkg ───────────────────────────────────────

DIST_XML="$BUILD_DIR/distribution.xml"
cat > "$DIST_XML" <<XML
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
  <title>Chika</title>
  <organization>com.chika</organization>
  <domains enable_localSystem="true"/>
  <options customize="never" require-scripts="true" rootVolumeOnly="true"/>
  <choices-outline>
    <line choice="default">
      <line choice="com.chika.app"/>
    </line>
  </choices-outline>
  <choice id="default"/>
  <choice id="com.chika.app" visible="false">
    <pkg-ref id="com.chika.app"/>
  </choice>
  <pkg-ref id="com.chika.app" version="${VERSION}" onConclusion="none">Chika-component.pkg</pkg-ref>
</installer-gui-script>
XML

OUTPUT="$DIST_DIR/Chika-${VERSION}.pkg"
productbuild \
    --distribution "$DIST_XML" \
    --package-path "$BUILD_DIR" \
    --version "$VERSION" \
    "$OUTPUT"

# ── Step 5 (optional): sign + notarise ──────────────────────────────

if [[ -n "${CHIKA_DEVELOPER_ID:-}" ]]; then
    echo "  · signing with ${CHIKA_DEVELOPER_ID}..."
    SIGNED="$DIST_DIR/Chika-${VERSION}-signed.pkg"
    productsign --sign "$CHIKA_DEVELOPER_ID" "$OUTPUT" "$SIGNED"
    mv "$SIGNED" "$OUTPUT"

    if [[ -n "${CHIKA_NOTARY_PROFILE:-}" ]]; then
        echo "  · submitting for notarisation..."
        xcrun notarytool submit "$OUTPUT" \
            --keychain-profile "$CHIKA_NOTARY_PROFILE" \
            --wait
        xcrun stapler staple "$OUTPUT"
    fi
fi

echo ""
echo "✓ installer ready: $OUTPUT"
ls -lh "$OUTPUT" | awk '{print "  size:", $5}'
