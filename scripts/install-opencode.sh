#!/usr/bin/env bash
# Install Forge's Agent Skills projection for OpenCode.
#
# Usage:
#   ./scripts/install-opencode.sh              # copy skills and instructions
#   ./scripts/install-opencode.sh --symlink    # link to this checkout
#   ./scripts/install-opencode.sh --dry-run    # preview the copy
#   ./scripts/install-opencode.sh --force      # replace conflicting files

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_DEST="${OPENCODE_SKILLS_DIR:-$HOME/.agents/skills}"
CONFIG_DEST="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
SKILLS_SRC="$REPO_ROOT/plugins/forge/skills"
AGENTS_SRC="$REPO_ROOT/zed/skills/agents"
COMMANDS_SRC="$REPO_ROOT/zed/skills/commands"
INSTRUCTIONS_SRC="$REPO_ROOT/AGENTS.md"

MODE="copy"
DRY_RUN=false
FORCE=false

usage() {
  sed -n '2,10p' "$0"
}

fail() {
  printf 'install-opencode: %s\n' "$1" >&2
  exit 1
}

run() {
  if $DRY_RUN; then
    printf '  [dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

install_file() {
  local source="$1"
  local target="$2"

  if [[ -L "$target" ]] && [[ "$(readlink "$target")" == "$source" ]]; then
    return 0
  fi
  if [[ -f "$target" ]] && cmp -s "$source" "$target"; then
    return 0
  fi
  if [[ -e "$target" || -L "$target" ]]; then
    $FORCE || fail "refusing to replace existing file: $target (use --force)"
    run rm -f "$target"
  fi

  run mkdir -p "$(dirname "$target")"
  if [[ "$MODE" == "copy" ]]; then
    run cp "$source" "$target"
  else
    run ln -s "$source" "$target"
  fi
}

install_tree() {
  local source_root="$1"
  local target_root="$2"
  local file relative

  [[ -d "$source_root" ]] || fail "missing source directory: $source_root"
  while IFS= read -r -d '' file; do
    relative="${file#"$source_root"/}"
    install_file "$file" "$target_root/$relative"
  done < <(find "$source_root" -type f -print0 | sort -z)
}

install_flat_skills() {
  local source_root="$1"
  local file name

  [[ -d "$source_root" ]] || fail "missing source directory: $source_root"
  while IFS= read -r -d '' file; do
    name="$(basename "$file" .md)"
    install_file "$file" "$SKILLS_DEST/$name/SKILL.md"
  done < <(find "$source_root" -maxdepth 1 -type f -name '*.md' -print0 | sort -z)
}

while (($#)); do
  case "$1" in
    --copy) MODE="copy" ;;
    --symlink) MODE="symlink" ;;
    --dry-run) DRY_RUN=true ;;
    --force) FORCE=true ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; fail "unknown option: $1" ;;
  esac
  shift
done

[[ -f "$INSTRUCTIONS_SRC" ]] || fail "missing OpenCode instructions: $INSTRUCTIONS_SRC"

methodology_count="$(find "$SKILLS_SRC" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
agent_count="$(find "$AGENTS_SRC" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')"
command_count="$(find "$COMMANDS_SRC" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')"
surface_count=$((methodology_count + agent_count + command_count))

printf 'Installing Forge Agent Skills for OpenCode (%s)\n' "$MODE"
install_tree "$SKILLS_SRC" "$SKILLS_DEST"
install_flat_skills "$AGENTS_SRC"
install_flat_skills "$COMMANDS_SRC"
install_file "$INSTRUCTIONS_SRC" "$CONFIG_DEST/AGENTS.md"
printf 'Installed %s Forge skill surfaces under %s\n' "$surface_count" "$SKILLS_DEST"
printf 'Installed OpenCode instructions at %s/AGENTS.md\n' "$CONFIG_DEST"
