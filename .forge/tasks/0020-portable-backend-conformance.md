---
id: 0020
title: Define portable backend adapter and conformance contract
status: done
agent: architect
model: opus
depends_on: [0019]
---

## Goal

Define and implement a capability-negotiated backend contract that lets Forge add distributed
stores without weakening canonical replay, fencing, effects, timers, checkpoints, migrations,
privacy, or offline evidence.

## Acceptance criteria

- [x] A backend declares a contract revision, capability set, consistency level, limits, and
      degraded-mode policy before a run starts.
- [x] The SQLite/WAL backend remains the executable reference implementation and passes the
      portable contract through an adapter boundary.
- [x] A deterministic in-memory fault-injected backend passes the same golden fixtures for
      append ordering, atomic event/outbox commit, CAS/fencing, timers, checkpoints, dedupe,
      restore, migration, backup, and privacy.
- [x] Ambiguous commits, unsupported guarantees, stale revisions, compaction/cursor loss, and
      provider consistency gaps fail closed or emit explicit degraded evidence.
- [x] Remote revisions, transaction IDs, watches, and CloudEvents map to reference-only adapter
      evidence; Forge event identity and ordering remain canonical.
- [x] Conformance results classify passed, unsupported, degraded-with-evidence, and failed
      cases and are reproducible offline.
- [x] No adapter claims exactly-once provider execution without an idempotent provider contract.
- [x] Schemas, CLI inspection, docs, fixtures, and release projections pass locally.
- [x] Hosted checks pass on the PR and the merged release surface.

## Research decisions

- Temporal's event history/replay and activity idempotency make recovery and duplicate execution
  explicit; Dapr separates durable workflow timers/retries from non-durable resiliency policies.
- etcd v3.7 provides strict-serializable KV operations and monotonic revisions, but watches are
  not linearizable and can be compacted; adapters must persist cursors and detect compaction.
- CloudEvents `source + id` uniqueness, `subject`, `type`, and RFC3339 `time` are useful adapter
  envelope fields, but cannot replace Forge event IDs or hash-chain order.
- First conformance target is two local implementations: SQLite/WAL plus an in-memory backend
  with deterministic fault injection. Remote stores follow only after the semantics are proven.

## Implementation

`forge-backends.py` now exposes the contract and the SQLite/WAL plus in-memory fault-injected
adapters. The fixture matrix covers 12 deterministic cases, including the reference-only
adapter-evidence envelope and an after-commit ambiguous-write retry. Physical SQLite backup
bytes are deliberately excluded from result digests; restored canonical history is hashed instead
so results remain reproducible across SQLite page metadata changes.

## Verification

Research is recorded on GitHub issue #58. PR #64 merged as `a9d2cfb003b6a1f313c22b133a127cc961ec188a`.
Both adapters report 12/12 conformance cases, the full suite passes with 217 tests, and the
evaluation suite reports 312/313 with one pre-existing situational-description warning. Ruff,
validation, capability compilation/rendering, release projections, and the post-merge workflow
run `30974614529` all pass.
