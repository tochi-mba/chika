#!/bin/bash
# ──────────────────────────────────────────────────────────────────────
#  Chika — macOS uninstaller
# ──────────────────────────────────────────────────────────────────────
#
# macOS doesn't have an Add/Remove Programs equivalent for .pkg's.
# Users uninstall via:
#
#   sudo /Library/Application\ Support/Chika/uninstall.sh
#
# Or with the --keep-data flag to preserve ~/.chika/ (the default).
# Pass --remove-data to wipe user settings + profiles + chat history.

set -e

INSTALL_DIR="/Library/Application Support/Chika"
SYMLINK="/usr/local/bin/chika"
PKG_RECEIPT="com.chika.app"

REMOVE_DATA=0
while [[ $# -gt 0 ]]; do
    case $1 in
        --remove-data) REMOVE_DATA=1; shift ;;
        --keep-data) REMOVE_DATA=0; shift ;;
        --help) echo "usage: $0 [--keep-data | --remove-data]"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "uninstall requires sudo (we have files in /Library and /usr/local/bin)" >&2
    exit 1
fi

echo "Uninstalling Chika..."

# ── Browser-extension reminder (advisory) ─────────────────────────────
# Run detection BEFORE removing the venv so we can read it.
VENV_PY="$INSTALL_DIR/venv/bin/python"
if [[ -x "$VENV_PY" ]]; then
    DETECT="$("$VENV_PY" -c "from chika._cli.extension_detect import detect_extension; r = detect_extension(); print(r.confidence)" 2>/dev/null || true)"
    if [[ "$DETECT" == "confirmed_active" ]] || [[ "$DETECT" == "present_in_chrome_profile" ]]; then
        REMINDER_USER="${SUDO_USER:-$USER}"
        REMINDER_HOME="${HOME}"
        if [[ -n "$SUDO_USER" ]]; then
            REMINDER_HOME="/Users/$SUDO_USER"
        fi
        REMINDER_DIR="$REMINDER_HOME/.chika"
        mkdir -p "$REMINDER_DIR" 2>/dev/null || true
        cat > "$REMINDER_DIR/uninstall_reminder.txt" <<EOF
The Chika browser extension was detected as still loaded in your
browser. The .pkg uninstaller cannot reach inside Chrome's profile
to remove it.

To finish the uninstall:
  1. Open chrome://extensions/
  2. Find "Chika Browser Agent"
  3. Click Remove
EOF
        echo "  · note: extension still loaded in your browser; see"
        echo "          $REMINDER_DIR/uninstall_reminder.txt to finish"
    fi
fi

if [[ -L "$SYMLINK" ]] || [[ -f "$SYMLINK" ]]; then
    rm -f "$SYMLINK"
    echo "  · removed $SYMLINK"
fi

if [[ -d "$INSTALL_DIR" ]]; then
    rm -rf "$INSTALL_DIR"
    echo "  · removed $INSTALL_DIR"
fi

# ``pkgutil --forget`` clears the receipt so a future reinstall is
# treated as a fresh one. Without this, a reinstall would think the
# package is already present and skip preinstall.
if pkgutil --pkg-info "$PKG_RECEIPT" >/dev/null 2>&1; then
    pkgutil --forget "$PKG_RECEIPT"
    echo "  · forgot package receipt $PKG_RECEIPT"
fi

if [[ $REMOVE_DATA -eq 1 ]]; then
    USER_DATA="${SUDO_USER:+/Users/$SUDO_USER}/.chika"
    if [[ -z "$SUDO_USER" ]]; then
        USER_DATA="$HOME/.chika"
    fi
    if [[ -d "$USER_DATA" ]]; then
        rm -rf "$USER_DATA"
        echo "  · removed user data at $USER_DATA"
    fi
else
    echo "  · user data preserved at ~/.chika/  (re-run with --remove-data to wipe)"
fi

echo "✓ Chika uninstalled"
