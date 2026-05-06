#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
#  Chika — universal Linux/Unix installer (curl | bash)
# ──────────────────────────────────────────────────────────────────────
#
# Run via:
#
#   curl -fsSL https://raw.githubusercontent.com/tochi-mba/chika/main/installers/linux/install.sh | bash
#
# Or download + inspect first (recommended):
#
#   curl -fsSL https://raw.githubusercontent.com/tochi-mba/chika/main/installers/linux/install.sh -o install-chika.sh
#   less install-chika.sh
#   bash install-chika.sh
#
# What it does:
#
#   1. Verifies Python 3.11+ is available
#   2. Downloads the latest chika wheel from GitHub Releases
#   3. Creates a venv at ``~/.local/share/chika/venv`` (XDG-compliant)
#   4. pip installs the wheel into that venv
#   5. Drops a launcher at ``~/.local/bin/chika`` (already on PATH on
#      most distros; user is told to add it if not)
#   6. Writes ``~/.local/share/chika/install_marker.json`` so
#      ``chika update`` recognises us as ``linux_universal``
#
# Designed to be **idempotent**: re-running upgrades in place. Same
# uninstall story:
#
#   ~/.local/share/chika/uninstall.sh
#
# Or just delete the launcher + dir manually.
#
# Per-user install only — never asks for sudo. If you want a system-
# wide install, use the .deb (Debian/Ubuntu) or build it yourself
# with --prefix=/opt/chika and adjust paths.

set -euo pipefail

OWNER="tochi-mba"
REPO="chika"

# XDG-compliant per-user install location.
INSTALL_DIR="${CHIKA_INSTALL_DIR:-$HOME/.local/share/chika}"
BIN_DIR="${CHIKA_BIN_DIR:-$HOME/.local/bin}"

VERSION="${CHIKA_VERSION:-}"

# ── Helpers ──────────────────────────────────────────────────────────

c_red()    { printf '\033[31m%s\033[0m\n' "$1"; }
c_green()  { printf '\033[32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[33m%s\033[0m\n' "$1"; }
c_dim()    { printf '\033[2m%s\033[0m\n' "$1"; }

step() { echo; printf '\033[1m▸ %s\033[0m\n' "$1"; }
ok()   { c_green "  ✓ $1"; }
warn() { c_yellow "  ⚠ $1"; }
err()  { c_red "  ✗ $1" >&2; exit 1; }

# Pick an HTTP fetcher. curl is more common; wget is the fallback.
download() {
    local url="$1" dest="$2"
    if command -v curl >/dev/null 2>&1; then
        curl --proto '=https' --tlsv1.2 -fsSL -o "$dest" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget --quiet --output-document="$dest" "$url"
    else
        err "neither curl nor wget found — install one and re-run"
    fi
}

http_get() {
    local url="$1"
    if command -v curl >/dev/null 2>&1; then
        curl --proto '=https' --tlsv1.2 -fsSL "$url"
    else
        wget --quiet -O - "$url"
    fi
}

# ── Step 1: Python ───────────────────────────────────────────────────

step "Checking for Python 3.11+"
PY=""
for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1; then
        v="$("$c" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true)"
        major="${v%%.*}"
        minor="${v##*.}"
        if [ "$major" = "3" ] && [ "${minor:-0}" -ge 11 ] 2>/dev/null; then
            PY="$c"
            ok "$c (Python $v)"
            break
        fi
    fi
done
[ -z "$PY" ] && err "Python 3.11+ not found — install via your distro's package manager"

# ── Step 2: resolve version ──────────────────────────────────────────

step "Resolving latest version"
if [ -z "$VERSION" ]; then
    LATEST="$(http_get "https://api.github.com/repos/${OWNER}/${REPO}/releases/latest" \
        | grep -E '"tag_name"' | head -1 | sed -E 's/.*"v?([^"]+)".*/\1/' || true)"
    [ -z "$LATEST" ] && err "couldn't resolve latest version from GitHub"
    VERSION="$LATEST"
fi
ok "version: $VERSION"

# ── Step 3: download wheel ───────────────────────────────────────────

step "Downloading wheel"
WHEEL_URL="https://github.com/${OWNER}/${REPO}/releases/download/v${VERSION}/chika-${VERSION}-py3-none-any.whl"
WHEEL_DIR="$(mktemp -d)"
trap "rm -rf $WHEEL_DIR" EXIT
WHEEL_PATH="$WHEEL_DIR/chika-${VERSION}-py3-none-any.whl"
download "$WHEEL_URL" "$WHEEL_PATH"
ok "downloaded $(du -h "$WHEEL_PATH" | cut -f1)"

# ── Step 4: venv + pip install ───────────────────────────────────────

step "Installing into $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
if [ ! -d "$INSTALL_DIR/venv" ]; then
    "$PY" -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip --quiet
"$INSTALL_DIR/venv/bin/pip" install --upgrade --force-reinstall "$WHEEL_PATH" --quiet
ok "installed into $INSTALL_DIR/venv"

# ── Step 5: launcher shim ────────────────────────────────────────────

mkdir -p "$BIN_DIR"
LAUNCHER="$BIN_DIR/chika"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Chika launcher (installed by install.sh)
set -e
: "\${CHIKA_DATA_DIR:=\$HOME/.chika/data}"
: "\${CHIKA_SETTINGS_PATH:=\$CHIKA_DATA_DIR/settings.json}"
export CHIKA_DATA_DIR CHIKA_SETTINGS_PATH
mkdir -p "\$CHIKA_DATA_DIR" 2>/dev/null || true
exec "$INSTALL_DIR/venv/bin/chika" "\$@"
EOF
chmod 0755 "$LAUNCHER"
ok "launcher at $LAUNCHER"

# ── Step 6: install marker for chika update ──────────────────────────

cat > "$INSTALL_DIR/install_marker.json" <<JSON
{
  "kind": "linux_universal",
  "version": "$VERSION",
  "installed_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "install_dir": "$INSTALL_DIR",
  "bin_dir": "$BIN_DIR"
}
JSON

# ── Step 7: ship an uninstaller ──────────────────────────────────────

cat > "$INSTALL_DIR/uninstall.sh" <<EOF
#!/usr/bin/env bash
set -e
echo "Uninstalling Chika..."
rm -f "$LAUNCHER"
rm -rf "$INSTALL_DIR"
echo "  · removed $INSTALL_DIR + $LAUNCHER"
echo "  · user data preserved at \$HOME/.chika/  (delete manually to wipe)"
echo "✓ Chika uninstalled"
EOF
chmod 0755 "$INSTALL_DIR/uninstall.sh"

# ── Step 8: PATH check ───────────────────────────────────────────────

step "Done"
case ":$PATH:" in
    *":$BIN_DIR:"*)
        ok "$BIN_DIR is on PATH — try: chika --help"
        ;;
    *)
        warn "$BIN_DIR is not on your PATH"
        c_dim "  add this to your ~/.bashrc or ~/.zshrc:"
        c_dim "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        c_dim "  or run chika directly: $LAUNCHER --help"
        ;;
esac
echo
c_dim "  Uninstall: $INSTALL_DIR/uninstall.sh"
c_dim "  Update:    chika update  (auto-downloads next release)"
