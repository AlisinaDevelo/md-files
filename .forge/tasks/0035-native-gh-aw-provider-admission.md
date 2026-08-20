---
id: 0035
title: Consume native gh-aw admission in the fenced provider
status: done
agent: security-engineer
model: sonnet
depends_on: [0034]
issue: 21
---

## Goal

Make the fenced gh-aw provider consume the native execution admission certificate before
planning or approving an effect, and revalidate the same certificate after authentication before
any GitHub request or reconciliation lookup.

## Acceptance criteria

- [x] Native plan, approval, execution, and reconciliation require a verified admission certificate;
      preview mode remains compatible without one.
- [x] Verification binds the certificate to the current native manifest/artifacts, deterministic
      episode and request identity, runtime definition, and a verified history prefix while allowing
      the expected runtime suffix after dispatch.
- [x] The admission ID is bound into native policy approval and execution evidence, and tampering
      after login fails before the provider transport is called.
- [x] The CLI exposes `--admission`; provider persistence remains digest-only for certificate data.
- [x] Focused tests, full local validation, and hosted CI pass for the pushed branch.

## Context

Task 0034 creates the read-only native admission certificate but deliberately leaves consumption to
the worker integration. This task closes that boundary without enabling a live GitHub dispatch in
tests; the provider still requires the explicit execute/reconcile acknowledgement and the expected
`gh` login.

## Verification

- Focused gh-aw/runtime/provider tests pass (`22 passed`); full pytest passes (`295 passed`).
- Ruff, Python compilation, `scripts/validate.sh`, capability graph/projection checks,
  Markdownlint (`0` issues across `200` files), ShellCheck, static eval (`312/313`, one existing
  warning), and cross-host scenarios (`12/12`) pass.
- Hosted CI run [31287082957](https://github.com/AlisinaDevelo/md-files/actions/runs/31287082957)
  passes all applicable jobs, including native compiler/reproducibility, provider tests, and
  release-surface validation; OpenSSF Scorecard is skipped on the feature branch.
