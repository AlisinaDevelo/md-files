---
id: 0019
title: Add durable human-input waits, signals, and cancellation
status: done
agent: orchestration-specialist
model: sonnet
depends_on: [0018]
---

## Goal

Add a provider-neutral, durable protocol for pausing a run for human input, receiving signals,
and cancelling work without losing canonical history, checkpoint safety, authorization binding,
or deterministic replay.

## Acceptance criteria

- [x] A run can enter `input_required`, survive restart, accept one authorized response, and
      resume from the exact checkpoint.
- [x] Wait identity binds run/task, requested input schema digest, policy revision, TTL, polling
      hint, authorization context digest, and a bounded resume contract.
- [x] Signal and input submission are idempotent, ordered, correlation-bound, duplicate-aware,
      and deterministic under concurrent delivery.
- [x] Cancellation has requested, acknowledged, and terminal `cancelled` evidence; late worker
      completion cannot resurrect a cancelled run.
- [x] Expired waits produce an explicit policy-bound outcome and never disappear silently.
- [x] MCP Tasks maps task IDs, TTLs, polling, status notifications, result retrieval, and
      cancellation to Forge references without making MCP canonical.
- [x] Authorization binding, bounded concurrency, maximum TTL, rate limits, and audit references
      are enforced before state mutation.
- [x] Raw prompts, credentials, tool arguments/results, and provider response bodies remain out
      of durable wait and signal payloads by default.
- [x] Crash/restart, duplicate delivery, auth mismatch, timeout, cancellation races, late
      responses, adapter failure, schemas, CLI inspection, fixtures, docs, and release checks pass.

## Context

This is GitHub issue #57 after the completed runtime lineage slice in #56. The design follows
MCP Tasks state and cancellation semantics, checkpoint-before-interrupt guidance from LangGraph
and Microsoft durable agents, and Forge's existing hash-chained event, policy, lease, and
checkpoint contracts. Provider task state is an adapter view, never the source of truth.

## Contract decisions

- Canonical events are `wait.created`, `wait.input_submitted`, `wait.expired`,
  `signal.received`, `run.cancel_requested`, `cancel.acknowledged`, and `run.cancelled`.
  `wait.created` is the transition that projects the run into `input_required`.
- Waits bind a verified checkpoint, input-schema digest, authorization-context digest, policy
  revision, absolute expiry, poll interval, expiration outcome, and bounded resume contract.
  Submissions are one-shot and require both schema and authorization matches.
- Expiry is evaluated against the persisted absolute deadline and serialized as an event.
  Cancellation is sticky and serialized as request, acknowledgement, and terminal evidence.
  Late workers cannot append mutating lifecycle events after terminal status.
- MCP is an adapter view: Forge IDs are carried in `_meta`, results contain references/digests,
  polling and notifications are best-effort, and MCP task methods never become canonical state.
- Runtime database schema v3 is reached through a reviewed v2-to-v3 migration. Legacy v2
  checkpoints remain evidence but are not used for v3 restore; a fresh v3 checkpoint can coexist.

## Verification

Implemented in PR #63 and merged as `7f17f1f`. The focused runtime/MCP/lineage suite passes 30
tests; the full repository suite passes 213 tests. `bash scripts/validate.sh`, capability render
checks, schema parsing, hosted Ruff 0.16.1, reproducible release packaging, host projections,
Markdown, ShellCheck, static evals, and OpenSSF Scorecard all pass. GitHub issue #57 is closed.
