#!/usr/bin/env bash
#
# drivekit installer — puts `drivekit` (and the short alias `dk`) on your PATH
# and installs the free NTFS/ext driver stack.
# Usage:  ./install.sh    (run from the drivekit folder)
#
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
src="$here/drivekit"
[[ -f "$src" ]] || { echo "error: drivekit script not found next to install.sh" >&2; exit 1; }
chmod +x "$src" 2>/dev/null || true

[[ "$(uname)" == "Darwin" ]] || { echo "error: the driver stack is macOS-only (recovery works on Linux too)" >&2; exit 1; }

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install it first:"
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  exit 1
fi

# Prefer Homebrew's bin (already on PATH, user-writable); fall back to /usr/local/bin.
bindir="$(brew --prefix)/bin"
SUDO=""
if [[ ! -w "$bindir" ]]; then
  bindir="/usr/local/bin"
  sudo mkdir -p "$bindir"
  SUDO="sudo"
fi
$SUDO ln -shf "$src" "$bindir/drivekit"
$SUDO ln -shf "$src" "$bindir/dk"
echo "✔ Linked $bindir/{drivekit,dk} -> $src"

echo
echo "Installing drivers (macFUSE + ntfs-3g + ext4fuse + e2fsprogs)..."
"$src" setup

echo
echo "Done. Try:  dk list    (or the long form: drivekit list)"
