#!/usr/bin/env bash
# Install the Forge toolkit into your user-level Claude Code config (~/.claude)
# by symlinking, so updates here flow through with a `git pull`.
#
# Usage:
#   ./scripts/install.sh            # symlink agents, skills, commands
#   ./scripts/install.sh --copy     # copy instead of symlink
#   ./scripts/install.sh --dry-run  # show what would happen
#
# This does NOT install hooks automatically — hooks run shell commands, so you
# should review hooks/hooks.json and wire them into your settings yourself, or
# install the whole thing as a plugin (recommended — see the README).

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${CLAUDE_HOME:-$HOME/.claude}"
MODE="symlink"
DRY=0

for arg in "$@"; do
  case "$arg" in
    --copy) MODE="copy" ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 1 ;;
  esac
done

echo "Repo:        $REPO"
echo "Destination: $DEST"
echo "Mode:        $MODE$([ $DRY -eq 1 ] && echo ' (dry run)')"
echo

link_dir() {
  local name="$1"
  local src="$REPO/plugins/forge/$name"
  local dst="$DEST/$name"
  [ -d "$src" ] || { echo "skip $name (not in repo)"; return; }

  if [ $DRY -eq 1 ]; then
    echo "would install $name -> $dst"
    return
  fi

  mkdir -p "$DEST"
  if [ "$MODE" = "copy" ]; then
    mkdir -p "$dst"
    cp -R "$src/." "$dst/"
    echo "copied  $name -> $dst"
  else
    # Back up an existing non-symlink directory before replacing.
    if [ -e "$dst" ] && [ ! -L "$dst" ]; then
      mv "$dst" "$dst.backup.$(date +%s)"
      echo "backed up existing $name"
    fi
    ln -sfn "$src" "$dst"
    echo "linked  $name -> $dst"
  fi
}

link_dir agents
link_dir commands
link_dir skills
link_dir output-styles

echo
echo "Done. Restart Claude Code (or run /agents) to pick up the changes."
echo "To enable hooks, install Forge as a plugin or copy hooks/hooks.json into"
echo "your settings. See the README for the recommended plugin install."
