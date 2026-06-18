#!/usr/bin/env bash
# PostToolUse(Write|Edit) auto-formatter.
#
# Reads the hook payload from stdin, finds the file that was just written or
# edited, and runs the matching formatter IF it is installed. Silent no-op when
# the tool isn't present, so it never blocks or errors the session. Output on
# stderr is informational only; this hook always exits 0.

set -euo pipefail

payload="$(cat)"

# Extract the file path without requiring jq (fall back to python3).
if command -v jq >/dev/null 2>&1; then
  file="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')"
else
  file="$(printf '%s' "$payload" | python3 -c \
    'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' \
    2>/dev/null || true)"
fi

[ -z "${file:-}" ] && exit 0
[ -f "$file" ] || exit 0

run() { command -v "$1" >/dev/null 2>&1 && "$@" >/dev/null 2>&1 || true; }

case "$file" in
  *.js|*.jsx|*.ts|*.tsx|*.json|*.css|*.scss|*.html|*.md|*.yaml|*.yml)
    if command -v prettier >/dev/null 2>&1; then
      run prettier --write "$file"
    elif command -v npx >/dev/null 2>&1; then
      npx --no-install prettier --write "$file" >/dev/null 2>&1 || true
    fi
    ;;
  *.py)
    run ruff format "$file" || run black "$file"
    ;;
  *.go)
    run gofmt -w "$file"
    run goimports -w "$file"
    ;;
  *.rs)
    run rustfmt "$file"
    ;;
  *.rb)
    run rubocop -A "$file"
    ;;
  *.php)
    run php-cs-fixer fix "$file"
    ;;
  *.sh|*.bash)
    run shfmt -w "$file"
    ;;
  *.lua)
    run stylua "$file"
    ;;
  *.tf)
    run terraform fmt "$file"
    ;;
esac

exit 0
