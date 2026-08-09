---
id: 0033
title: Verify native gh-aw supply-chain and job-graph admission
status: done
agent: security-engineer
model: sonnet
depends_on: [0032]
issue: 21
---

## Goal

Make the native `gh-aw` lock a reviewable admission artifact: emitted actions must be covered by
the upstream SHA manifest, container images must be digest-bound, and the compiler's control-flow
roles must retain the pinned activation and safe-output topology.

## Acceptance criteria

- [x] Every external `uses` reference is SHA-pinned and covered by the upstream action manifest.
- [x] Upstream container entries require a valid `sha256` digest, a matching `pinned_image`, and
      a reference outside the manifest header in the generated lock.
- [x] Native locks require activation, agent, detection, safe-output, and conclusion roles; the
      optional `pre_activation` role is allowed only as activation's predecessor.
- [x] Native job dependencies reject undeclared jobs, cycles, and drift from the pinned role
      contract.
- [x] Focused fixtures cover unlisted actions, unbound containers, list-form `uses`, and graph
      dependency drift.
- [x] Full local validation and hosted CI pass for the pushed branch.

## Context

Task 0032 proved byte-identical native output and the write-permission boundary. This task closes
the remaining admission gap before live worker integration: a pinned version is not enough if a
lock can introduce an unlisted action, unbound image, or changed control-flow edge. The check stays
offline and does not dispatch, approve, or execute a workflow.

## Verification

- Focused gh-aw tests pass (`16 passed`).
- Local real `gh-aw v0.85.4` compilation, admission verification, and two-run artifact comparison
  pass for all five workflows.
- Full local pytest passes (`288 passed`); `scripts/validate.sh`, full Ruff, Markdownlint (`0`
  issues across `198` files), ShellCheck, cross-host scenarios (`12/12`), and `git diff --check`
  pass.
- Hosted CI run [31285705892](https://github.com/AlisinaDevelo/md-files/actions/runs/31285705892)
  passes all applicable jobs, including native admission and reproducible release gates; OpenSSF
  Scorecard is skipped on the feature branch.
