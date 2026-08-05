---
id: 0023
title: Add distributed revision and watch recovery adapter
status: planned
agent: concurrency-engineer
model: sonnet
depends_on: [0020]
issue: 67
---

## Goal

Add an etcd-first distributed adapter that preserves Forge ordering, fencing, recovery, and privacy
contracts across revisions, watches, leases, snapshots, reconnects, and compaction.

## Acceptance criteria

- [ ] The adapter negotiates consistency, revision, watch, lease, snapshot, and compaction
      capabilities before a run starts.
- [ ] Required state transitions use strict-serializable transactions; observations cannot mutate
      canonical state unless their cursor is verified.
- [ ] Gaps, stale cursors, reconnects, and compaction recover from a verified snapshot plus replay
      or fail closed with evidence.
- [ ] Duplicate and out-of-order notifications preserve one canonical history.
- [ ] Remote IDs, revisions, and CloudEvents remain reference-only adapter evidence.
- [ ] Offline fault simulation and the full shared conformance matrix pass.
- [ ] Snapshot retention, quorum loss, compaction windows, and operator recovery are documented.

## Research decisions

- etcd strict-serializable writes and monotonic revisions are useful guarantees, while watch
  cursors and compaction require explicit recovery logic.
- Remote revisions never replace Forge event identity or hash-chain ordering.
- Provider execution remains at-least-once and idempotency-bound.

## Verification

Track implementation and release evidence on GitHub issue #67. A live cluster is optional for the
first test pass; deterministic local watch faults are required.
