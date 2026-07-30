---
name: task-ledger
description: >-
  Use when turning a plan into trackable tasks and working them to done — a
  lightweight issue tracker for an orchestrated run. Covers the task format
  (acceptance criteria, status, dependencies, assigned agent + model) and three
  backends: local markdown files (default), GitHub issues via gh, or Jira/Linear via
  MCP. See TEMPLATE.md for the issue format.
---

# Task Ledger

A task ledger is the shared state of an orchestrated run: the list of concrete pieces of
work, each with a definition of done, so the conductor knows what's left, what's blocked,
and what's verified. It's the Jira/GitHub-issue layer of Forge — but starts with zero
external dependencies.

## Each task is a small, verifiable unit

A good task has a **stable id**, a one-line title, an explicit **acceptance criteria** (how
you'll know it's done — the test that passes, the behavior observed), a **status**, its
**dependencies**, and its routing (**assigned agent + model tier**). If a task's acceptance
criteria is vague ("make it better"), it isn't ready — sharpen it first. See
[TEMPLATE.md](TEMPLATE.md) for the exact shape.

**Status lifecycle:** `backlog → ready → in-progress → review → done` (plus `blocked`). A
task is `ready` only when its dependencies are `done`. It reaches `done` only when its
acceptance criteria is *verified*, not just attempted.

## Three backends — pick per project

- **Local markdown (default, zero-dep):** one file per task under `.forge/tasks/`, committed
  with the code. Works in any repo, offline, reviewable in a PR, no auth. This is the default
  and what `/tasks` writes.
- **GitHub issues (via `gh`):** when the team lives in GitHub, mirror tasks to real issues —
  `gh issue create`, `gh issue list`, `gh issue close`. The ledger and the issues stay in
  sync; the acceptance criteria goes in the issue body.
- **Jira / Linear (via MCP):** if a Jira or Linear MCP server is connected, create and
  transition tickets through it. Forge doesn't bundle those integrations (they need
  credentials and an MCP server) — it targets whatever issue MCP you've connected. See
  `mcp/` for how to wire one.

Keep one backend as the source of truth per project; don't split state across two.

## Working the ledger

The conductor (see the `orchestration` skill) reads the ledger, dispatches each `ready` task
to its assigned specialist at its model tier, moves it through the lifecycle, and verifies
acceptance criteria before `done`. The `iterate-to-done` skill covers the loop that drains
the ledger and its stop conditions.

For stacked delivery, a task may record an optional `change` id that points to a branch in
`.forge/stack.json`. This is traceability only: `depends_on` controls task readiness;
stack `parent` controls Git/PR ancestry. Never infer one graph from the other.

## Discipline

- **One source of truth.** The ledger reflects reality — update status as work happens, don't
  let it drift from the actual state of the code.
- **Verify before done.** "Attempted" is `review`, not `done`. `done` means the acceptance
  criteria was checked.
- **Keep tasks small.** A task that needs "and" in its title is probably two tasks. Small
  tasks parallelize and verify cleanly.
- **Never put secrets or findings in task files** that get committed — reference them, don't
  paste them.
