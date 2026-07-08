---
name: orchestration
description: >-
  Use when driving a large, multi-part task end to end with multiple models —
  planning at a high tier, decomposing into a task ledger, and delegating each piece
  to the right specialist at the right model (plan with Opus/Fable, implement with
  Sonnet, mechanical work with Haiku). Covers the conductor loop and how to delegate.
  See MODEL-ROUTING.md for the tier policy.
---

# Orchestration

Orchestration is running a big goal as a *conductor*: you plan and decompose at a strong
model, then hand each concrete piece to the specialist and model tier that fits it, run the
pieces (in parallel where they're independent), and integrate the results. The win is using
an expensive model only where it pays and a cheap fast one everywhere else.

## The one architectural fact that shapes everything

**Only the main conversation can spawn subagents; a subagent cannot spawn its own
subagents.** So orchestration is driven from the *main loop* — via `/orchestrate` or by you
acting as the conductor directly — not by delegating "be the orchestrator" to one subagent
(that subagent could only work sequentially by itself). Plan at the main model's tier (set
it to Opus or Fable for hard planning), then delegate outward.

## The conductor loop

1. **Plan at a high tier.** Restate the goal and definition of done, surface hidden
   requirements, and design the approach. This is the expensive thinking — do it once, well,
   at Opus/Fable.
2. **Decompose into a task ledger.** Break the goal into concrete, independently-verifiable
   tasks with explicit acceptance criteria and dependencies. Use the `task-ledger` skill for
   the format (local issue files, or `gh`/MCP-backed issues).
3. **Route each task to a tier + specialist.** Assign per the `MODEL-ROUTING.md` policy:
   architecture/gnarly debugging → Opus/Fable; implementation, tests, docs → Sonnet;
   mechanical/parallel-cheap (renames, boilerplate, wide search) → Haiku. Match the task to
   the specialist agent (`test-engineer`, `refactoring-specialist`, `security-auditor`, …).
4. **Dispatch — parallel where independent.** Spawn each ready task as a subagent with an
   explicit `model` override and a self-contained brief (see below). Independent tasks go in
   one turn so they run concurrently; dependent tasks wait for their blocker.
5. **Integrate and verify against acceptance criteria.** A subagent's summary is its
   *intent*, not proof — confirm each result against the actual diff/tests/output before
   marking the task done. Keep the pieces coherent (consistent conventions, interfaces line
   up).
6. **Iterate to done.** Update the ledger, pick the next ready tasks, repeat until the
   ledger is empty or genuinely blocked. See the `iterate-to-done` skill for the loop and
   stop conditions.

## How to delegate well (this makes or breaks it)

When you spawn a specialist subagent, set two things deliberately:

- **The model** — pass a `model` override on the delegation (`haiku`/`sonnet`/`opus`/
  `fable`) chosen from the routing policy, so the tier matches the task, not the default.
- **The brief** — write it for a colleague who just walked in: the goal and *why*, what
  you've ruled out, the exact files/lines and acceptance criteria, and the response length
  you want. Never delegate understanding ("based on your findings, fix it" produces shallow
  work). Give lookups the exact command; give investigations the question.

Run independent specialists **in parallel** (multiple delegations in one turn) and **trust
but verify** every summary.

## When NOT to orchestrate

Orchestration has overhead (planning, ledger, delegation round-trips). For a single-file
change or a task under ~3 steps, just do it directly. Reach for the conductor loop when the
work is genuinely multi-part, spans specialties, or benefits from parallelism and mixed
model tiers.
