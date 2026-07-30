#!/usr/bin/env bash
# Forge for Zed — idempotent install script
#
# Installs Forge's skills, profiles, and global instructions into the right
# Zed locations. Safe to re-run after pulling updates.
#
# Usage:
#   ./install.sh            # symlink (default)
#   ./install.sh --copy     # copy files instead
#   ./install.sh --dry-run  # preview without making changes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_SRC="$REPO_ROOT/plugins/forge/skills"
ZED_SRC="$SCRIPT_DIR"

SKILLS_DEST="$HOME/.agents/skills"
ZED_CONFIG="$HOME/.config/zed"

DRY_RUN=false
USE_COPY=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --copy)    USE_COPY=true ;;
  esac
done

log() { echo "  $1"; }
run() {
  if $DRY_RUN; then
    echo "  [dry-run] $*"
  else
    "$@"
  fi
}

install_skill() {
  local src="${1%/}"
  local name
  name="$(basename "$src")"
  local dest="$SKILLS_DEST/$name"

  run mkdir -p "$dest"
  while IFS= read -r -d '' f; do
    local relative
    local target
    relative="${f:${#src}+1}"
    target="$dest/$relative"
    run mkdir -p "$(dirname "$target")"
    if $USE_COPY; then
      run cp "$f" "$target"
      log "✓  $name/$relative (copied)"
    else
      run ln -sf "$f" "$target"
      log "✓  $name/$relative (linked)"
    fi
  done < <(find "$src" -type f -print0)
}

install_zed_skill() {
  local name="$1"
  local src_file="$2"
  local dest_dir="$SKILLS_DEST/$name"

  run mkdir -p "$dest_dir"
  if $USE_COPY; then
    run cp "$src_file" "$dest_dir/SKILL.md"
    log "✓  $name/SKILL.md (copied)"
  else
    run ln -sf "$src_file" "$dest_dir/SKILL.md"
    log "✓  $name/SKILL.md (linked)"
  fi
}

echo ""
echo "Forge for Zed — Install"
echo "======================="
echo ""

# ── 1. Methodology skills (from plugins/forge/skills/) ──────────────────────
methodology_count="$(find "$SKILLS_SRC" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
echo "Installing $methodology_count methodology skills..."
for skill_dir in "$SKILLS_SRC"/*/; do
  [ -d "$skill_dir" ] || continue
  install_skill "$skill_dir"
done
echo ""

# ── 2. Agent skills (from zed/skills/agents/) ───────────────────────────────
agent_count="$(find "$ZED_SRC/skills/agents" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')"
echo "Installing $agent_count specialist agent skills..."
for skill_file in "$ZED_SRC/skills/agents/"*.md; do
  [ -f "$skill_file" ] || continue
  name="$(basename "$skill_file" .md)"
  install_zed_skill "$name" "$skill_file"
done
echo ""

# ── 3. Command skills (from zed/skills/commands/) ───────────────────────────
command_count="$(find "$ZED_SRC/skills/commands" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')"
echo "Installing $command_count slash command skills..."
for skill_file in "$ZED_SRC/skills/commands/"*.md; do
  [ -f "$skill_file" ] || continue
  name="$(basename "$skill_file" .md)"
  install_zed_skill "$name" "$skill_file"
done
echo ""

# ── 4. Global AGENTS.md ─────────────────────────────────────────────────────
echo "Installing global AGENTS.md..."
mkdir -p "$ZED_CONFIG"
if $USE_COPY; then
  run cp "$ZED_SRC/AGENTS.md" "$ZED_CONFIG/AGENTS.md"
  log "✓  ~/.config/zed/AGENTS.md (copied)"
else
  run ln -sf "$ZED_SRC/AGENTS.md" "$ZED_CONFIG/AGENTS.md"
  log "✓  ~/.config/zed/AGENTS.md (linked)"
fi
echo ""

# ── 5. Profiles ──────────────────────────────────────────────────────────────
echo "Profiles: add to ~/.config/zed/settings.json manually if not already present."
echo "  See: $ZED_SRC/settings/profiles.json"
echo "  Merge the contents under: agent.profiles"
echo ""

echo "Done! Forge for Zed is installed."
echo ""
echo "Next steps:"
echo "  • Restart or reload Zed — skills are discovered automatically."
echo "  • Select 'Forge: Concise Engineer' or 'Forge: Mentor' in the agent panel."
echo "  • Type /forge-cmd- to see all $command_count slash commands."
