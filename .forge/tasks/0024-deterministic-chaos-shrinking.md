---
id: 0024
title: Add deterministic chaos and schedule-shrinking harness
status: done
agent: test-engineer
model: sonnet
depends_on: [0019, 0020]
issue: 66
---

## Goal

Explore durable runtime interleavings with seedable schedules and shrink failures to minimal,
offline-replayable counterexamples.

## Acceptance criteria

- [x] A schedule DSL covers commit crashes, duplicate delivery, stale workers, lease expiry,
      wait/signal races, checkpoint corruption, cursor gaps, compaction, provider timeout, and
      ambiguous commit.
- [x] The same schedule runs against every backend and compares history, outcome, receipts, and
      privacy evidence.
- [x] Invariants cover hash chains, event/effect atomicity, fencing, dedupe, cancellation,
      recovery, replay, and privacy.
- [x] Shrinking emits a digest-only minimal schedule that preserves failure classification.
- [x] CI runs a bounded deterministic seed corpus without wall-clock or network dependence.
- [x] CLI supports generate, run, shrink, replay, and inspect.
- [x] Regression schedules are promoted into conformance and release evidence.

## Research decisions

- Retry and replay behavior must assume repeated operations and stable idempotency keys.
- A deterministic schedule is high-signal coverage, not a claim of exhaustive interleavings.
- Failure artifacts must omit raw prompts, credentials, provider bodies, and host-specific paths.

## Verification

Track implementation and release evidence on GitHub issue #66. Preserve the seed and contract
digest for every promoted regression.

Implementation and release evidence:

- `forge-chaos.py` defines the `forge-chaos-v1` schedule contract and digest-only result projection.
- The generated schedule passes on all three facades: SQLite/WAL `11/13` plus two explicit
  distributed degradations, memory-fault `11/13` plus the same degradations, and etcd-first `13/13`.
- Cross-backend canonical history, state, effect, receipt, outcome, and privacy projections compare
  with zero mismatches.
- Backend-scoped `expected_failure` predicates fail closed when a classified regression disappears
  or changes failure class.
- Seeds `6601`, `6602`, and `6603` pass the bounded corpus with no network or wall-clock reads.
- The focused chaos suite passes six tests; shrink tests preserve the `terminal_outcome_mismatch`
  failure class while removing two irrelevant actions.
