---
id: 0013
title: Add local runtime event store and deterministic replay
status: done
agent: architect
model: opus
depends_on: []
---

## Goal

Give the durable-runtime work a local source of truth: a SQLite/WAL event history and pure
state reducer that can be reopened, verified, and replayed after a process failure.

## Acceptance criteria

- [x] Run lifecycle and bounded task lifecycle events are append-only and sequence-ordered.
- [x] Idempotency retries return the original event; conflicting reuse fails closed.
- [x] Canonical event hashes make sequence or payload tampering detectable.
- [x] Reopen, invalid-transition, raw-payload, and concurrent-writer tests pass.
- [x] CLI, schemas, docs, and the orchestration capability expose the local contract.

## Context

This is the first implementation slice of GitHub issue #19 and child issue #50. Receipts
remain observability evidence; this store owns execution history. Outbox effects, leases,
snapshots, migrations, and gh-aw compilation stay separate follow-up tasks.

## Notes

Implemented in `plugins/forge/skills/orchestration/scripts/forge-runtime.py` with the
root CLI shim, runtime schemas, generated release metadata, and focused recovery tests.
The full 188-test suite, all repository gates, and offline archive verification pass.
