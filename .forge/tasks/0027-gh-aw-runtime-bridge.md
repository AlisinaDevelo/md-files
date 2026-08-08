---
id: 0027
title: Bind gh-aw episodes to the durable Forge runtime
status: in-progress
agent: orchestration-specialist
model: sonnet
depends_on: [0018, 0019, 0021, 0026]
issue: 21
---

## Goal

Make the gh-aw adapter consume the existing Forge runtime contract for episode identity,
dispatcher/worker tasks, safe-output effects, receipts, replay, and cancellation.

## Acceptance criteria

- [ ] One deterministic episode ID binds the gh-aw manifest, runtime definition, worker tasks,
      outbox effects, provider receipts, and GitHub object references.
- [ ] Dispatch and safe-output operations are staged in the transactional outbox with policy
      evidence and stable idempotency keys; the adapter never calls GitHub directly.
- [ ] Worker completion, partial failure, replay, and cancellation are represented by existing
      runtime lifecycle events and do not duplicate accepted effects.
- [ ] Receipt validation requires the bridge revision, approval reference, episode/workflow/output
      identity, and bounded provider references; inspection is privacy-safe.
- [ ] Episode schema, CLI, docs, release projections, focused tests, full validation, and hosted
      CI pass under `AlisinaDevelo`.

## Scope boundary

This slice stages and verifies provider operations locally. A future live provider worker may
claim the outbox and call GitHub, but it must preserve the lease, approval, idempotency, and
receipt contracts.

## Verification

Record focused/full tests, release reproducibility, and the hosted CI run when complete.
