---
name: forge-cmd-tasks
description: Create, list, or update the Forge task ledger for an orchestrated run
disable-model-invocation: true
---

Manage the Forge task ledger.

Use the `task-ledger` skill. Default to local markdown tasks under `.forge/tasks/`, with
one file per task and an optional `.forge/tasks/README.md` board. Supported actions:
list the board, add a task with acceptance criteria and agent/model routing, mark a task
done only after verification, mark a task blocked with a concrete reason, or mirror the
ledger to GitHub issues with `gh` when GitHub should be the source of truth.

Keep one backend as the source of truth, and never put secrets in committed task files.
