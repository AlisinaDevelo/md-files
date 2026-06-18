#!/usr/bin/env bash
# Stop hook — desktop notification when Claude finishes a turn.
#
# Cross-platform best-effort: macOS (osascript/terminal-notifier), Linux
# (notify-send). Silent no-op if no notifier is available. Always exits 0 and
# never blocks. Reads and ignores the stdin payload.

set -euo pipefail
cat >/dev/null 2>&1 || true

title="Claude Code"
message="Finished — ready for your input."

if [[ "$(uname)" == "Darwin" ]]; then
  if command -v terminal-notifier >/dev/null 2>&1; then
    terminal-notifier -title "$title" -message "$message" -sound default >/dev/null 2>&1 || true
  elif command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"$message\" with title \"$title\" sound name \"Glass\"" >/dev/null 2>&1 || true
  fi
elif command -v notify-send >/dev/null 2>&1; then
  notify-send "$title" "$message" >/dev/null 2>&1 || true
fi

exit 0
