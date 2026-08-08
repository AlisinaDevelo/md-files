---
id: 0027
title: Bind gh-aw episodes to the durable Forge runtime
status: done
agent: orchestration-specialist
model: sonnet
depends_on: [0018, 0019, 0021, 0026]
issue: 21
---

## Goal

Make the gh-aw adapter consume the existing Forge runtime contract for episode identity,
dispatcher/worker tasks, safe-output effects, receipts, replay, and cancellation.

## Acceptance criteria

- [x] One deterministic episode ID binds the gh-aw manifest, runtime definition, worker tasks,
      outbox effects, provider receipts, and GitHub object references.
- [x] Dispatch and safe-output operations are staged in the transactional outbox with policy
      evidence and stable idempotency keys; the adapter never calls GitHub directly.
- [x] Worker completion, partial failure, replay, and cancellation are represented by existing
      runtime lifecycle events and do not duplicate accepted effects.
- [x] Receipt validation requires the bridge revision, approval reference, episode/workflow/output
      identity, and bounded provider references; inspection is privacy-safe.
- [x] Episode schema, CLI, docs, release projections, focused tests, full validation, and hosted
      CI pass under `AlisinaDevelo`.

## Scope boundary

This slice stages and verifies provider operations locally. A future live provider worker may
claim the outbox and call GitHub, but it must preserve the lease, approval, idempotency, and
receipt contracts.

## Verification

Implementation and verification evidence:

- The `forge-gh-aw-runtime-v1` bridge pins the compiled manifest and runtime definition, derives
  deterministic `gh-aw:` episode IDs, stages dispatcher and safe-output effects through the
  transactional outbox, validates bounded approval/provider receipts, and exposes a digest-only
  inspection projection. It supports replay-safe worker lifecycle transitions and durable
  cancellation without calling GitHub.
- Focused bridge/compiler tests pass (`11 passed`); the full repository suite passes (`261 passed`).
  Ruff 0.16.2, Python compilation, `scripts/validate.sh`, Markdown lint (192 files), and
  ShellCheck pass.
- Static evals pass `312/313` with one existing warning and zero failures; all 12 cross-host
  scenarios, backend conformance, and the bounded chaos corpus pass.
- Forge 3.6.0 release artifacts verify offline and are byte-identical across two local builds;
  hosted release packaging and Claude/Codex/Agent Skills validation pass.
- Hosted CI run [31234543180](https://github.com/AlisinaDevelo/md-files/actions/runs/31234543180)
  is green for commit `24de93d`; OpenSSF Scorecard is skipped by the workflow.

The bridge remains local-first. A future provider worker may perform live GitHub operations only
after claiming the fenced outbox lease, verifying approval, using the provider idempotency key,
and acknowledging a reference-only receipt.
