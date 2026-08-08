---
id: 0026
title: Add bounded GitHub Agentic Workflows compiler adapter
status: done
agent: devops-engineer
model: sonnet
depends_on: [0018, 0020, 0024, 0025]
issue: 21
---

## Goal

Project Forge orchestration metadata into a deterministic, pinned GitHub Agentic Workflows
contract while preserving read-only agent execution, staged safe outputs, policy evidence, and
durable runtime boundaries.

## Acceptance criteria

- [x] A versioned schema and canonical workflow spec pin the upstream gh-aw version, commit,
      action SHAs, engines, triggers, dispatch graph, safe outputs, and protected paths.
- [x] Compilation validates capability references, dispatch cycles, fan-out, protected files,
      secret boundaries, and policy decisions before writing artifacts.
- [x] The default lock is an honest offline preview that stops before mutation; the pinned
      official compiler can produce native locks with source-to-lock evidence.
- [x] Checks detect spec drift, artifact drift, agent write permissions, and unknown upstream
      secret references without committing secret values.
- [x] Focused tests, release projections, documentation, full validation, and hosted CI pass
      under `AlisinaDevelo`.

## Scope boundary

This slice does not make GitHub workflow locks the canonical runtime history. Live dispatch,
worker episode correlation, safe-output receipts, and replay integration remain follow-up work
on issue #21.

## Verification

Implementation and release evidence:

- `forge-gh-aw.py` validates the `forge-gh-aw-v1` schema, canonical capability references,
  bounded dispatch graph, protected paths, secret references, action pins, and `gh-aw` policy
  effects; it emits deterministic preview locks and can replace them with native `gh aw v0.85.4`
  locks from commit `53843da968225dc56e1590978a7ed6407a8438ac`.
- Focused adapter, renderer, IR, and capability tests pass (`17 passed`); the full repository
  suite passes (`256 passed`). Ruff 0.16.2, Python compilation, `scripts/validate.sh`, and
  Markdown lint pass.
- Static evals pass `312/313` with one existing warning and zero failures; all 12 cross-host
  scenarios, backend conformance, and the bounded chaos corpus pass.
- Forge 3.6.0 release artifacts verify offline and are byte-identical across two local builds;
  hosted release packaging and Claude/Codex/Agent Skills validation pass.
- Hosted CI run [31233866794](https://github.com/AlisinaDevelo/md-files/actions/runs/31233866794)
  is green for commit `46165a1`; OpenSSF Scorecard is skipped by the workflow.

Issue #21 remains open for live dispatch, worker episode correlation, safe-output receipts, and
replay integration with the durable runtime.
