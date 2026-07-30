# Tests

Behavioral tests for Forge's safety hooks and deterministic stack engine. Hook tests invoke
each script as a real Claude Code subprocess; stack tests create real temporary Git
repositories and verify manifests, ancestry, plans, adapters, and CLI exit behavior.

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
- **`forge-stack.py`** — accepts valid ordered stacks; rejects unknown parents, duplicates,
  self-parenting, missing/diverged branches, and empty ranges; verifies provider-native and
  vanilla plans remain plan-only and use force-with-lease; renders stack navigation; and
  exercises init/add/status/check as real CLI subprocesses.

The two guard hooks are safety-critical, so the suite emphasizes both **true positives**
(catching the dangerous thing) and **true negatives** (not crying wolf) — a guard that
false-positives gets disabled, which is worse than no guard.
