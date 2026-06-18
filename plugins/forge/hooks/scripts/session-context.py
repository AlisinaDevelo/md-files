#!/usr/bin/env python3
"""SessionStart hook — inject lightweight repo context at the start of a session.

Claude Code reads the system prompt and CLAUDE.md at session start but doesn't know
your *current* working state. This hook gathers a few cheap, high-signal facts — branch,
how far ahead/behind, uncommitted file count, and the last few commits — and injects them
as `additionalContext` so Claude starts grounded in where the repo actually is.

Output contract (SessionStart, exit 0): stdout is JSON with
`hookSpecificOutput.additionalContext`. Fails silent (emits nothing) outside a git repo
or on any error — never blocks a session.
"""
from __future__ import annotations

import json
import subprocess
import sys


def git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5, check=False
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def main() -> int:
    # Consume stdin payload (unused, but drain it so the pipe closes cleanly).
    try:
        sys.stdin.read()
    except Exception:
        pass

    if git("rev-parse", "--is-inside-work-tree") != "true":
        return 0  # not a git repo — nothing to add

    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "(detached)"
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    ahead_behind = ""
    if upstream:
        counts = git("rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        if counts and "\t" in counts:
            behind, ahead = counts.split("\t")
            if ahead != "0" or behind != "0":
                ahead_behind = f" ({ahead} ahead, {behind} behind {upstream})"

    dirty = git("status", "--porcelain")
    dirty_count = len([line for line in dirty.splitlines() if line.strip()])
    recent = git("log", "-5", "--pretty=format:%h %s")

    lines = [
        "Current repository state (from the Forge session-context hook):",
        f"- Branch: {branch}{ahead_behind}",
        f"- Uncommitted changes: {dirty_count} file(s)",
    ]
    if recent:
        lines.append("- Recent commits:")
        lines += [f"    {c}" for c in recent.splitlines()]

    context = "\n".join(lines)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
