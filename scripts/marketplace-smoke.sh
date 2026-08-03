#!/usr/bin/env bash
# Exercise isolated Claude and Codex marketplace install, upgrade, resource, and removal paths.

set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
VERSION="$(jq -r '.version' "$ROOT/plugins/forge/.claude-plugin/plugin.json")"
TMP_ROOT="$(mktemp -d -t forge-marketplace-smoke)"

printf 'Running marketplace smoke for Forge %s from %s\n' "$VERSION" "$ROOT"

export CLAUDE_CONFIG_DIR="$TMP_ROOT/claude-config"
export CLAUDE_CODE_PLUGIN_CACHE_DIR="$TMP_ROOT/claude-cache"
mkdir -p "$CLAUDE_CONFIG_DIR" "$CLAUDE_CODE_PLUGIN_CACHE_DIR"
claude plugin marketplace add "$ROOT" --scope user >/dev/null
claude plugin install forge@forge --scope user >/dev/null
claude_listing="$(claude plugin list)"
grep -q "Version: $VERSION" <<<"$claude_listing"
CLAUDE_CACHE_ROOT="$CLAUDE_CODE_PLUGIN_CACHE_DIR/cache/forge/forge/$VERSION"
test -f "$CLAUDE_CACHE_ROOT/skills/orchestration/SKILL.md"
test -f "$CLAUDE_CACHE_ROOT/assets/icon.png"
claude plugin install forge@forge --scope user >/dev/null
claude plugin uninstall forge@forge --scope user
claude_listing="$(claude plugin list)"
if grep -q "forge@forge" <<<"$claude_listing"; then
  printf 'Claude uninstall left Forge installed\n' >&2
  exit 1
fi

export CODEX_HOME="$TMP_ROOT/codex-home"
mkdir -p "$CODEX_HOME"
codex plugin marketplace add "$ROOT" --json >/dev/null
codex plugin add forge@forge --json >/dev/null
codex plugin list --json --available \
  | jq -e --arg version "$VERSION" 'any(.installed[]?; .pluginId == "forge@forge" and .version == $version and .enabled == true)' \
  >/dev/null
test -f "$CODEX_HOME/plugins/cache/forge/forge/$VERSION/skills/orchestration/SKILL.md"
test -f "$CODEX_HOME/plugins/cache/forge/forge/$VERSION/assets/logo.png"
codex plugin add forge@forge --json >/dev/null
codex plugin remove forge@forge --json >/dev/null
if codex plugin list --json --available | jq -e 'any(.installed[]?; .pluginId == "forge@forge")' >/dev/null; then
  printf 'Codex uninstall left Forge installed\n' >&2
  exit 1
fi

printf 'Marketplace smoke passed; isolated state is at %s\n' "$TMP_ROOT"
