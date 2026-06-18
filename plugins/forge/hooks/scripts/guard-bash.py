#!/usr/bin/env python3
"""PreToolUse(Bash) guard — block irrecoverably destructive shell commands.

Reads the Claude Code hook payload from stdin. If the proposed Bash command
matches a high-confidence destructive pattern, exit 2 to block it and explain
why on stderr (which Claude sees). Otherwise exit 0 to allow.

This is a safety net, not a sandbox: it targets a small set of catastrophic,
unambiguous commands. It deliberately fails OPEN on parse errors so it never
bricks the session — pair it with proper permissions for real isolation.
"""
import json
import re
import sys

# (compiled pattern, human explanation). Keep these high-precision to avoid
# false positives that would erode trust in the guard.
RULES = [
    (r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(/|~|/\*|\$HOME)(\s|$)",
     "recursive force-delete of a root/home path"),
    (r"\brm\s+-[a-z]*f[a-z]*r[a-z]*\s+(/|~|/\*|\$HOME)(\s|$)",
     "recursive force-delete of a root/home path"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
     "fork bomb"),
    (r"\bmkfs(\.\w+)?\s+/dev/",
     "formatting a block device"),
    (r"\bdd\b[^\n]*\bof=/dev/(disk|sd|nvme|hd)",
     "raw write to a disk device"),
    (r">\s*/dev/(sd|nvme|hd|disk)\w*",
     "redirect over a raw disk device"),
    (r"\bchmod\s+-R\s+0?777\s+/(\s|$)",
     "recursive world-writable on root"),
    (r"\bgit\s+push\b[^\n]*\s(--force|-f)\b[^\n]*\b(origin\s+)?(main|master|prod)\b",
     "force-push to a protected branch (main/master/prod)"),
    (r"\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(sh|bash|zsh)\b",
     "piping a remote script straight into a shell"),
    (r"\bgit\s+reset\s+--hard\b[^\n]*&&[^\n]*\bpush\b",
     "hard reset chained into a push"),
]

COMPILED = [(re.compile(p), why) for p, why in RULES]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # fail open: never block on a malformed payload

    if payload.get("tool_name") != "Bash":
        return 0

    command = payload.get("tool_input", {}).get("command", "")
    if not isinstance(command, str):
        return 0

    for pattern, why in COMPILED:
        if pattern.search(command):
            sys.stderr.write(
                f"⛔ Blocked by Forge guard: {why}.\n"
                f"   Command: {command}\n"
                "   This is a high-risk, hard-to-reverse operation. If you truly\n"
                "   intend it, run it manually outside Claude or narrow the command.\n"
            )
            return 2  # exit code 2 = block the tool call

    return 0


if __name__ == "__main__":
    sys.exit(main())
