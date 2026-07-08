---
description: Plan a big goal at a high tier, decompose into a task ledger, and solve it by delegating each task to the right specialist and model
argument-hint: "<the goal to drive end to end>"
allowed-tools: Read, Grep, Glob, Bash, Edit, Write
model: opus
---

Orchestrate this goal end to end: $ARGUMENTS

You are the conductor, running in the main conversation (so you can delegate to subagents —
a subagent could not). Use the `orchestration`, `task-ledger`, and `iterate-to-done` skills.

- Repo state: !`git status --short 2>/dev/null | head -20`
- Existing ledger: !`ls .forge/tasks/ 2>/dev/null || echo "(none yet — create .forge/tasks/)"`

Run the conductor loop:

1. **Plan at this tier.** Restate the goal and its definition of done, surface hidden
   requirements and risks, and decide the approach. If the goal is ambiguous in a way that
   changes the work, ask before decomposing.
2. **Decompose into a task ledger** under `.forge/tasks/` (see the `task-ledger` TEMPLATE):
   small, independently-verifiable tasks, each with explicit acceptance criteria,
   dependencies, and a routed **agent + model tier** (per `MODEL-ROUTING.md`:
   Opus/Fable for design & hard reasoning, Sonnet for implementation/tests/docs, Haiku for
   mechanical/parallel work). Write a `.forge/tasks/README.md` status board.
3. **Solve the ledger** with the iterate-to-done loop: dispatch each `ready` task to its
   specialist **with an explicit `model` override**, running independent tasks in parallel in
   a single turn. Brief each subagent like a colleague who just walked in — goal, what's
   ruled out, exact files/acceptance criteria — never delegate understanding.
4. **Verify against acceptance criteria** before marking a task `done` — confirm the real
   diff/tests/output, not the subagent's summary. Keep the pieces coherent.
5. **Iterate** until the ledger is drained or genuinely blocked; then report the outcome
   mapped back to the definition of done, with the evidence.

Keep the ledger the single source of truth and update it as you go. If the goal is small
enough that a plan/ledger is overkill (a single-file change, under ~3 steps), say so and just
do it directly instead of orchestrating.
