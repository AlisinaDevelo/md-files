---
name: forge-cmd-solve-loop
description: Drain the current task ledger by dispatching ready tasks, verifying results, and updating status
disable-model-invocation: true
---

Run the solve-loop over the current Forge task ledger.

Use the `iterate-to-done`, `task-ledger`, and `orchestration` skills. Refresh the ledger,
find ready tasks, dispatch each to its assigned specialist and model tier, verify the
result against acceptance criteria, update task status and evidence, then repeat until all
tasks are done or the run is genuinely blocked.

Stop on done, blocked tasks that need human input/access, repeated attempts with no
verified progress, or an explicit budget/attempt cap. Do not mark work done from a
specialist summary alone.
