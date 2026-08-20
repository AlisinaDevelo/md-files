---
id: 0031
title: Gate pinned native gh-aw compilation
status: done
agent: devops-engineer
model: sonnet
depends_on: [0026, 0030]
issue: 21
---

## Goal

Make the optional native `gh-aw` compiler path a continuously verified integration rather
than a locally documented command. Native locks must remain bound to their Forge source,
definition, pinned compiler metadata, and action manifest without granting the agent job a
write boundary.

## Acceptance criteria

- [x] Native artifact checks require Forge source and definition evidence, the exact pinned
      upstream version/schema, strict compiler metadata, and SHA-pinned upstream actions.
- [x] Manifest checks reject source drift even when a generated artifact hash is rewritten,
      reject inventory/definition drift, and preserve preview-versus-native mode semantics.
- [x] Hosted CI installs `gh-aw` `v0.85.4`, compiles all five workflows with `--strict`, runs
      the Forge verifier, and performs no workflow dispatch or repository mutation.
- [x] Focused tests, full validation, documentation, and hosted CI pass under `AlisinaDevelo`.

## Context

This is the next issue #21 slice after the durable provider and operator-confirmed dispatch
reconciliation. The upstream compiler runs in a temporary fixture and is not canonical Forge
history; the native output is verification evidence only. Keep the agent read-only and keep
safe-output execution behind the existing approval, lease, and provider boundaries.

## Notes

The verifier intentionally binds exact `v0.85.4` metadata and the pinned workflow schema. A
future upstream compiler requires a reviewed spec/version update rather than silently changing
the native output contract.

## Verification

- `check_artifacts` now validates manifest identity and inventory, source digests, Forge native
  evidence, strict upstream metadata, action-manifest SHA pins, read-only agent permissions, and
  known secret references. Focused gh-aw tests pass (`9 passed`); the full suite passes (`281
  passed`).
- Local Ruff, Python compilation, `scripts/validate.sh`, Markdownlint (196 files), ShellCheck,
  `git diff --check`, and all 12 cross-host scenarios pass.
- Hosted CI run
  [31282192271](https://github.com/AlisinaDevelo/md-files/actions/runs/31282192271) is green for
  the pushed implementation; the native compiler job installs `gh-aw v0.85.4`, compiles and
  verifies all five workflows, and OpenSSF Scorecard is skipped on this feature branch.
