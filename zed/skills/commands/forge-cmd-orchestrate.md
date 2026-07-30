---
name: forge-cmd-orchestrate
description: Plan a big goal at a high tier, decompose it into a task ledger, and solve it with routed specialist work
disable-model-invocation: true
---

Orchestrate the user's goal end to end.

Use the `orchestration`, `task-ledger`, and `iterate-to-done` skills. You are the conductor
in the main conversation: plan first, write a ledger under `.forge/tasks/`, route each task
to an agent and model tier, dispatch independent work in parallel where available, verify
against acceptance criteria, and update the ledger until done or genuinely blocked.
When the implementation has several dependent, independently reviewable slices, also use
`stacked-changes` and keep branch ancestry in `.forge/stack.json`.

For model routing: use Opus or Fable for planning, architecture, security design, and
gnarly debugging; Sonnet for implementation, tests, and docs; Haiku for mechanical or
wide parallel work. Keep the ledger as the source of truth.
