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
  local src="$1"
  local name
  name="$(basename "$src")"
  local dest="$SKILLS_DEST/$name"

  if [ -d "$dest" ] && ! $USE_COPY; then
    log "↻  $name (already linked — skipping)"
    return
  fi

  run mkdir -p "$dest"
  for f in "$src"/*.md; do
    [ -f "$f" ] || continue
    local fname
    fname="$(basename "$f")"
    if $USE_COPY; then
      run cp "$f" "$dest/$fname"
      log "✓  $name/$fname (copied)"
    else
      run ln -sf "$f" "$dest/$fname"
      log "✓  $name/$fname (linked)"
    fi
  done
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
echo "Installing 18 methodology skills..."
for skill_dir in "$SKILLS_SRC"/*/; do
  [ -d "$skill_dir" ] || continue
  install_skill "$skill_dir"
done
echo ""

# ── 2. Agent skills (from zed/skills/agents/) ───────────────────────────────
echo "Installing 20 specialist agent skills..."
for skill_file in "$ZED_SRC/skills/agents/"*.md; do
  [ -f "$skill_file" ] || continue
  name="$(basename "$skill_file" .md)"
  install_zed_skill "$name" "$skill_file"
done
echo ""

# ── 3. Command skills (from zed/skills/commands/) ───────────────────────────
echo "Installing 14 slash command skills..."
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
echo "  • Type /forge-cmd- to see all 14 slash commands."
