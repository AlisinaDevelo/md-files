---
id: 0025
title: Add deterministic adaptive-routing policy and offline replay foundation
status: in_progress
agent: data-engineer
model: sonnet
depends_on: [0018, 0019, 0020, 0021]
issue: 22
---

## Goal

Make model routing capability-aware, deterministic, privacy-safe, and reviewable offline before
any provider integration or online adaptation is enabled.

## Acceptance criteria

- [ ] Capability, pin, data-policy, replay-safety, latency, concurrency, and token/cost budgets
      filter ineligible routes before scoring.
- [ ] Decisions record candidate status, exclusion reasons, score source, fallback plan, budget
      state, policy revision, request digest, and outcome evidence digests.
- [ ] Static and disabled modes are deterministic; live adaptive decisions fail closed until an
      offline replay satisfies sample, confidence, regression, cost, failure, approval, and
      replay-budget gates.
- [ ] Replay compares quality, cost, latency, failure rate, and approval burden over a shared
      episode set without persisting raw content or treating agent confidence as ground truth.
- [ ] Versioned policy, decision, and replay schemas ship through Claude, Codex, and Agent Skills
      release surfaces.
- [ ] Focused and full validation, release rendering, and hosted CI pass under `AlisinaDevelo`.

## Scope boundary

This slice does not activate online self-modification or connect to a provider. A future rollout
slice must add reviewed evidence windows, approval policy, provider adapters, and staged rollback.

## Verification

Update this ledger with the focused test count, full validation result, release artifact result,
and hosted CI run after the branch is pushed.
