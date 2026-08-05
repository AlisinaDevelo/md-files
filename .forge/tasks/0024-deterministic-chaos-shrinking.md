---
id: 0024
title: Add deterministic chaos and schedule-shrinking harness
status: planned
agent: test-engineer
model: sonnet
depends_on: [0019, 0020]
issue: 66
---

## Goal

Explore durable runtime interleavings with seedable schedules and shrink failures to minimal,
offline-replayable counterexamples.

## Acceptance criteria

- [ ] A schedule DSL covers commit crashes, duplicate delivery, stale workers, lease expiry,
      wait/signal races, checkpoint corruption, cursor gaps, compaction, provider timeout, and
      ambiguous commit.
- [ ] The same schedule runs against every backend and compares history, outcome, receipts, and
      privacy evidence.
- [ ] Invariants cover hash chains, event/effect atomicity, fencing, dedupe, cancellation,
      recovery, replay, and privacy.
- [ ] Shrinking emits a digest-only minimal schedule that preserves failure classification.
- [ ] CI runs a bounded deterministic seed corpus without wall-clock or network dependence.
- [ ] CLI supports generate, run, shrink, replay, and inspect.
- [ ] Regression schedules are promoted into conformance and release evidence.

## Research decisions

- Retry and replay behavior must assume repeated operations and stable idempotency keys.
- A deterministic schedule is high-signal coverage, not a claim of exhaustive interleavings.
- Failure artifacts must omit raw prompts, credentials, provider bodies, and host-specific paths.

## Verification

Track implementation and release evidence on GitHub issue #66. Preserve the seed and contract
digest for every promoted regression.
