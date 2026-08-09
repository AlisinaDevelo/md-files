---
id: 0032
title: Enforce reproducible native gh-aw output
status: in_progress
agent: devops-engineer
model: sonnet
depends_on: [0031]
issue: 21
---

## Goal

Turn the native `gh-aw` compiler's reproducibility claim into a hosted invariant and make the
permission boundary fail closed if upstream output moves a write capability onto an agent or
control-plane job.

## Acceptance criteria

- [x] The verifier requires an empty top-level permission map and a read-only `agent` job.
- [x] Every generated write permission is confined to the preview safe-output job, or to the
      pinned upstream `conclusion` and `safe_outputs` jobs in native mode.
- [x] Focused negative tests reject non-empty top-level permissions and writes outside the
      safe-output boundary.
- [x] Hosted CI compiles and verifies all five native workflows twice in isolated directories and
      fails unless the complete artifact trees are byte-identical.
- [ ] Full local validation and hosted CI pass for the pushed branch.

## Context

Issue #21 requires deterministic, version-pinned, reproducible compiler output while keeping
agent jobs read-only and writes behind declared safe outputs. Task 0031 proved pinned native
compilation and source/lock evidence; this task closes the remaining two-run reproducibility and
structural permission-boundary gaps without dispatching a workflow or approving an effect.

## Verification

- Focused gh-aw tests pass (`12 passed`).
- Local real `gh-aw v0.85.4` compilation, verification, and two-run artifact comparison pass for
  all five workflows.
- Full local pytest passes (`284 passed`); `scripts/validate.sh`, full Ruff, Markdownlint (`0`
  issues across `197` files), ShellCheck, cross-host scenarios (`12/12`), and `git diff --check`
  pass. Hosted CI is the remaining gate.
