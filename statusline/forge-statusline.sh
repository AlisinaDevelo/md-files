#!/usr/bin/env bash
# Forge status line for Claude Code.
#
# Reads the session JSON on stdin and prints a single line:
#   <model> · <dir> · <git branch+dirty> · <context%> · <session cost>
#
# Wire it up in settings.json (see statusline/README.md):
#   "statusLine": { "type": "command", "command": "/abs/path/to/forge-statusline.sh", "padding": 1 }
#
# Degrades gracefully: uses jq if present, falls back to python3, and shows what it can.

set -euo pipefail
input="$(cat)"

# Extract a dotted JSON path from the payload (jq, then python3 fallback).
get() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null || true
  else
    printf '%s' "$input" | python3 -c "
import json,sys
d=json.load(sys.stdin)
cur=d
for k in '''$2'''.split('.'):
    cur=(cur or {}).get(k) if isinstance(cur,dict) else None
print('' if cur is None else cur)
" 2>/dev/null || true
  fi
}

model="$(get '.model.display_name' 'model.display_name')"
dir="$(get '.workspace.current_dir' 'workspace.current_dir')"
ctx="$(get '.context_window.used_percentage' 'context_window.used_percentage')"
cost="$(get '.cost.total_cost_usd' 'cost.total_cost_usd')"

dir_base="$(basename "${dir:-$PWD}")"

# Git branch + dirty marker, computed from the session's working directory.
branch=""
if git -C "${dir:-$PWD}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  b="$(git -C "${dir:-$PWD}" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [ -n "$(git -C "${dir:-$PWD}" status --porcelain 2>/dev/null)" ]; then
    branch=" ⎇ ${b}*"
  else
    branch=" ⎇ ${b}"
  fi
fi

out="${model:-?}"
out="${out} · ${dir_base}${branch}"
[ -n "$ctx" ] && out="${out} · ctx ${ctx}%"
if [ -n "$cost" ]; then
  out="$(printf '%s · $%.3f' "$out" "$cost" 2>/dev/null || printf '%s · $%s' "$out" "$cost")"
fi

printf '%s' "$out"
