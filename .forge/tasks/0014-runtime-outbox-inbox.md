---
id: 0014
title: Add transactional runtime outbox and inbox effects
status: done
agent: concurrency-engineer
model: sonnet
depends_on: [0013]
---

## Goal

Give the local durable runtime a policy-safe, at-least-once boundary for external effects:
event and intent commit atomically, workers claim with leases, and provider receipts are
deduplicated without pretending SQLite can make a remote API exactly-once.

## Acceptance criteria

- [x] Event and outbox intent commit atomically and roll back together on conflict.
- [x] Effect and provider idempotency identifiers are deterministic across retries and
      include run, task, activity, attempt, and effect-definition revision.
- [x] Local workers can claim, expire/reclaim, acknowledge, retry, and dead-letter intents.
- [x] Inbox receipts deduplicate identical delivery and fail closed on conflicting reuse.
- [x] Attempt metadata survives retries without rewriting canonical runtime history.
- [x] Raw prompts, credentials, tool arguments/results, and provider response bodies are
      rejected at the durable boundary.
- [x] Schemas, CLI inspection, documentation, focused tests, and release-surface validation
      cover the new contract.

## Context

This is the next implementation slice of GitHub issue #52 after the event store in #50/#51.
Hosted queues, provider-specific adapters, human waits, adaptive routing, and gh-aw remain
separate follow-ups.

## Notes

Implemented against the existing standard-library SQLite/WAL store. The 194-test suite,
structure validation, static eval, cross-host scenarios, Markdown/ShellCheck, deterministic
release rendering, and offline archive verification pass. Receipts and effect delivery state
remain separate from the hash-chained event history; adapters supply references, digests,
status, and provider request IDs rather than raw response content.
