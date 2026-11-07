#!/usr/bin/env bash
#
# drivekit installer — puts `drivekit` (and the short alias `dk`) on your PATH
# and installs its stack: the NTFS/ext driver stack on macOS, the disk toolkit
# (e2fsprogs/ntfs-3g/exfatprogs/...) on Linux.
# Usage:  ./install.sh    (run from the drivekit folder)
#
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
src="$here/drivekit"
[[ -f "$src" ]] || { echo "error: drivekit script not found next to install.sh" >&2; exit 1; }
chmod +x "$src" 2>/dev/null || true

os="$(uname)"
if [[ "$os" == "Darwin" ]]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required. Install it first:"
    # shellcheck disable=SC2016  # literal install command for the user to copy
    echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    exit 1
  fi
  # Prefer Homebrew's bin (already on PATH, user-writable); fall back to /usr/local/bin.
  bindir="$(brew --prefix)/bin"
  lnflags="-shf"
else
  bindir="/usr/local/bin"
  lnflags="-sfn"
fi

SUDO=""
if [[ ! -w "$bindir" ]]; then
  [[ "$os" == "Darwin" ]] && bindir="/usr/local/bin"
  SUDO="sudo"
  $SUDO mkdir -p "$bindir"
fi
# shellcheck disable=SC2086  # lnflags is intentionally word-split
$SUDO ln $lnflags "$src" "$bindir/drivekit"
# shellcheck disable=SC2086
$SUDO ln $lnflags "$src" "$bindir/dk"
echo "✔ Linked $bindir/{drivekit,dk} -> $src"

echo
if [[ "$os" == "Darwin" ]]; then
  echo "Installing drivers (macFUSE + ntfs-3g + ext4fuse + e2fsprogs)..."
else
  echo "Installing the Linux toolkit stack..."
fi
"$src" setup

echo
echo "Done. Try:  dk list    (or the long form: drivekit list)"
