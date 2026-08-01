---
description: Create, list, or update the task ledger (local files, or GitHub issues via gh)
argument-hint: "[list | add <title> | done <id> | block <id> <reason> | sync-gh]"
allowed-tools: Read, Grep, Glob, Bash(ls:*), Bash(gh issue:*), Edit, Write
model: sonnet
---

Manage the task ledger. Use the `task-ledger` skill for the format and lifecycle.

- Current ledger: !`ls .forge/tasks/ 2>/dev/null || echo "(none)"`
- Board: !`cat .forge/tasks/README.md 2>/dev/null || echo "(no board yet)"`

Action: $ARGUMENTS

- **list** (default) — show the status board (id, title, status, agent, model, deps). If
  there's no ledger yet, say so.
- **add `<title>`** — create `.forge/tasks/<next-id>-<slug>.md` from the TEMPLATE with status
  `backlog`; ask for or infer the acceptance criteria, agent, and model tier. Update the
  board.
- **done `<id>`** — only after its acceptance criteria is actually verified; set status
  `done`, note the evidence, and update the board.
- **block `<id>` `<reason>`** — set status `blocked` with the reason.
- **sync-gh** — use the bundled backend at `python3 scripts/forge-tasks.py`: run `plan`
  before `apply --yes`, inspect structured conflicts, and use native sub-issue and
  blocked-by relationships. Use `--authority github import --write` only when GitHub is
  the chosen source of truth. See `docs/github-task-ledger.md` for recovery and disconnect
  behavior.

Keep the ledger honest — reflect the real state of the work, and never commit secrets or
findings into task files.
