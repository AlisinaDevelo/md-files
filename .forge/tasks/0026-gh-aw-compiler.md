---
id: 0026
title: Add bounded GitHub Agentic Workflows compiler adapter
status: in-progress
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

- [ ] A versioned schema and canonical workflow spec pin the upstream gh-aw version, commit,
      action SHAs, engines, triggers, dispatch graph, safe outputs, and protected paths.
- [ ] Compilation validates capability references, dispatch cycles, fan-out, protected files,
      secret boundaries, and policy decisions before writing artifacts.
- [ ] The default lock is an honest offline preview that stops before mutation; the pinned
      official compiler can produce native locks with source-to-lock evidence.
- [ ] Checks detect spec drift, artifact drift, agent write permissions, and unknown upstream
      secret references without committing secret values.
- [ ] Focused tests, release projections, documentation, full validation, and hosted CI pass
      under `AlisinaDevelo`.

## Scope boundary

This slice does not make GitHub workflow locks the canonical runtime history. Live dispatch,
worker episode correlation, safe-output receipts, and replay integration remain follow-up work
on issue #21.

## Verification

Record focused and full test counts, static evals, release reproducibility, and the hosted CI run
here when the implementation is complete.
