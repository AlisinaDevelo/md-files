---
description: Drain the current task ledger by repeatedly dispatching ready tasks, verifying results, and updating task status
argument-hint: "[optional focus, task id, or stop condition]"
allowed-tools: Read, Grep, Glob, Bash, Edit, Write
model: opus
---

Run the solve-loop over the current Forge task ledger.

- Focus / stop condition: $ARGUMENTS
- Repo state: !`git status --short 2>/dev/null | head -20`
- Current board: !`cat .forge/tasks/README.md 2>/dev/null || echo "(no task board found)"`

Use the `iterate-to-done`, `task-ledger`, and `orchestration` skills.

Loop deliberately:

1. Refresh `.forge/tasks/`: identify `done`, `blocked`, and newly `ready` tasks whose
   dependencies are satisfied.
2. If there are no ready tasks, finish if all tasks are `done`; otherwise report the
   blockers and the next human decision/access needed.
3. Pick the next ready task or independent batch. Respect each task's `agent` and `model`
   fields; override only when the routing policy clearly calls for it.
4. Dispatch independent work in parallel where the harness supports it. Give each
   specialist a self-contained brief with goal, context, files, and acceptance criteria.
5. Verify results against the task's acceptance criteria using real evidence: diff,
   tests, command output, docs rendered, or the relevant inspection.
6. Update each task file and `.forge/tasks/README.md`: `done` with evidence, `review` if
   attempted but unverified, or `blocked` with a concrete reason.
7. Continue until the ledger is done, blocked, or a full pass makes no verified progress.

Do not mark a task done from a subagent summary alone. The ledger is the source of truth.
