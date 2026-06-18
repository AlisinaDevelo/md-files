# Tests

Behavioral tests for the Forge safety hooks. They invoke each hook script as a real
subprocess, feed it a Claude Code hook payload on stdin, and assert on the exit code —
the same contract Claude Code uses (exit `2` blocks a tool call, `0` allows it).

```bash
just test          # or:
pytest tests/ -v
```

## What's covered

- **`guard-bash.py`** — 16 catastrophic commands that must be blocked (`rm -rf /`,
  fork bombs, force-push to protected branches, `curl | sh`, disk writes) and 10 safe
  commands that must pass (relative-path deletes, feature-branch pushes, quoted strings).
  Plus: non-Bash tools are ignored, and malformed input fails open (never blocks).
- **`scan-secrets.py`** — 7 real credential shapes that must be blocked (AWS keys,
  private keys, GitHub/Slack/Anthropic/Google tokens, hardcoded passwords) and 7 safe
  cases that must pass (placeholders, short values, normal code). Plus: Edit/MultiEdit
  payload extraction, non-write tools ignored, fail-open on garbage.
- **`format-file.sh` / `notify.sh`** — must always exit `0` (best-effort, non-blocking),
  including when the file path is missing.

The two guard hooks are safety-critical, so the suite emphasizes both **true positives**
(catching the dangerous thing) and **true negatives** (not crying wolf) — a guard that
false-positives gets disabled, which is worse than no guard.
