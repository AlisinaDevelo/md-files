---
id: 0025
title: Add deterministic adaptive-routing policy and offline replay foundation
status: done
agent: data-engineer
model: sonnet
depends_on: [0018, 0019, 0020, 0021]
issue: 22
---

## Goal

Make model routing capability-aware, deterministic, privacy-safe, and reviewable offline before
any provider integration or online adaptation is enabled.

## Acceptance criteria

- [x] Capability, pin, data-policy, replay-safety, latency, concurrency, and token/cost budgets
      filter ineligible routes before scoring.
- [x] Decisions record candidate status, exclusion reasons, score source, fallback plan, budget
      state, policy revision, request digest, and outcome evidence digests.
- [x] Static and disabled modes are deterministic; live adaptive decisions fail closed until an
      offline replay satisfies sample, confidence, regression, cost, failure, approval, and
      replay-budget gates.
- [x] Replay compares quality, cost, latency, failure rate, and approval burden over a shared
      episode set without persisting raw content or treating agent confidence as ground truth.
- [x] Versioned policy, decision, and replay schemas ship through Claude, Codex, and Agent Skills
      release surfaces.
- [x] Focused and full validation, release rendering, and hosted CI pass under `AlisinaDevelo`.

## Scope boundary

This slice does not activate online self-modification or connect to a provider. A future rollout
slice must add reviewed evidence windows, approval policy, provider adapters, and staged rollback.

## Verification

Verification:

- Focused routing/release/schema coverage: `14 passed`.
- Full repository suite: `236 passed`; `scripts/validate.sh`, Ruff, Markdown lint, static evals
  (`312/313`, one existing warning, zero failures), and all-adapter scenarios (`12/12`) pass.
- Forge 3.6.0 release artifacts verify offline and are byte-identical across two local builds;
  hosted release packaging and Claude/Codex/Agent Skills validation pass.
- Hosted CI run [31136906946](https://github.com/AlisinaDevelo/md-files/actions/runs/31136906946)
  is green for commit `3d1ec52`.

The scope remains offline and fail-closed: provider adapters and online self-modification are
future rollout work.
