---
name: iterate-to-done
description: >-
  Use when running a solve-loop over a task ledger — repeatedly pick the next ready
  task, dispatch it, verify against acceptance criteria, update the ledger, and repeat
  until done or blocked. Covers the loop, its stop conditions, and how to drive it
  recurring or in the background with the harness (/loop, the scheduler, background
  agents).
---

# Iterate to Done

The solve-loop drains a task ledger: it keeps working the next available piece until the goal
is met. This is the engine underneath `/orchestrate` — and the thing you want driven on a
recurring or background cadence for long-running work.

## The loop

```text
loop:
  1. Refresh the ledger. What's `done`? What's now `ready` (deps satisfied)?
  2. If no `ready` tasks: if all `done` → finish; if some `blocked` → stop and report why.
  3. Pick the ready task(s). Independent ones can run in parallel this turn.
  4. Dispatch each to its assigned specialist at its model tier (see `orchestration`).
  5. Verify the result against the task's acceptance criteria — not the subagent's word.
  6. Update the ledger: `done` if verified, `review`/`blocked` with a note otherwise.
  7. Go to 1.
```

## Stop conditions — end the loop deliberately

- **Done:** every task is `done` and the top-level goal's definition of done is met. Report
  the outcome and the evidence.
- **Blocked:** a task can't proceed without something only the user can provide (a decision,
  a credential, access, a clarification that changes the work). Stop and ask — don't spin.
- **Budget/attempt cap:** bound retries on a stuck task (~3 attempts), then mark it `blocked`
  with what you tried, rather than looping on it forever.
- **No progress:** if a full pass produces no verified progress, stop and reassess the plan
  instead of repeating it.

Never fake progress to keep the loop alive: audit each "done" against a real result. A loop
that reports success it can't point to is worse than one that stops and asks.

## Driving it recurring or in the background

Forge supplies the *loop's content*; the *cadence* comes from the Claude Code harness. Wire
it up depending on the horizon:

- **Within one session:** run `/solve-loop` (or `/orchestrate`, which loops internally) and it
  iterates until a stop condition.
- **Recurring on an interval:** drive it with the harness `/loop` skill —
  `/loop 10m /solve-loop` runs the loop every 10 minutes (or omit the interval to let the
  model self-pace). Useful for "keep chipping at the backlog" or watching CI.
- **Scheduled / autonomous:** use the harness scheduler (a cron-scheduled cloud agent) to
  fire `/solve-loop` on a cadence — e.g. a nightly pass over the ready backlog.
- **Long parallel work:** dispatch independent tasks as background agents and collect their
  results on a later pass.

Be honest about which mode you're in: the plugin can't self-schedule — it provides the
command the scheduler runs. Match the cadence to how fast the underlying state actually
changes, and give a recurring loop a clear stop/idle condition so it doesn't burn cost
spinning on an empty or blocked ledger.
