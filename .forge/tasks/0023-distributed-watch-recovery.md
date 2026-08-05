---
id: 0023
title: Add distributed revision and watch recovery adapter
status: done
agent: concurrency-engineer
model: sonnet
depends_on: [0020]
issue: 67
---

## Goal

Add an etcd-first distributed adapter that preserves Forge ordering, fencing, recovery, and privacy
contracts across revisions, watches, leases, snapshots, reconnects, and compaction.

## Acceptance criteria

- [x] The adapter negotiates consistency, revision, watch, lease, snapshot, and compaction
      capabilities before a run starts.
- [x] Required state transitions use strict-serializable transactions; observations cannot mutate
      canonical state unless their cursor is verified.
- [x] Gaps, stale cursors, reconnects, and compaction recover from a verified snapshot plus replay
      or fail closed with evidence.
- [x] Duplicate and out-of-order notifications preserve one canonical history.
- [x] Remote IDs, revisions, and CloudEvents remain reference-only adapter evidence.
- [x] Offline fault simulation and the full shared conformance matrix pass.
- [x] Snapshot retention, quorum loss, compaction windows, and operator recovery are documented.

## Research decisions

- etcd strict-serializable writes and monotonic revisions are useful guarantees, while watch
  cursors and compaction require explicit recovery logic.
- Remote revisions never replace Forge event identity or hash-chain ordering.
- Provider execution remains at-least-once and idempotency-bound.

## Verification

Implementation and release evidence:

- PR [#72](https://github.com/AlisinaDevelo/md-files/pull/72), merged at
  `0232e453fd6e70bc2407b403fc57306e762a3f1b`.
- The etcd-first facade advertises and negotiates strict serializability, remote revisions, watch
  delivery, fenced leases, snapshot recovery, and compaction recovery before use.
- The shared backend matrix passes `12/12`; the distributed matrix passes `6/6` for ordering and
  deduplication, cursor gaps, compaction recovery, stale watches, privacy rejection, and reconnect
  fencing.
- The repository suite passes `230` tests; `ruff`, `validate.sh`, deterministic host projections,
  reproducible release packaging, and hosted CI all pass. Static evals remain `312/313` with one
  existing situational-warning result and zero failures.
- The implementation is deterministic and offline. A live provider integration must scope its key
  range, distinguish unrelated cluster-wide revisions from dropped Forge events, and preserve the
  same fail-closed recovery rules.
