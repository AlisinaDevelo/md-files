---
id: 0031
title: Gate pinned native gh-aw compilation
status: in-progress
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

- [ ] Native artifact checks require Forge source and definition evidence, the exact pinned
      upstream version/schema, strict compiler metadata, and SHA-pinned upstream actions.
- [ ] Manifest checks reject source drift even when a generated artifact hash is rewritten,
      reject inventory/definition drift, and preserve preview-versus-native mode semantics.
- [ ] Hosted CI installs `gh-aw` `v0.85.4`, compiles all five workflows with `--strict`, runs
      the Forge verifier, and performs no workflow dispatch or repository mutation.
- [ ] Focused tests, full validation, documentation, and hosted CI pass under `AlisinaDevelo`.

## Context

This is the next issue #21 slice after the durable provider and operator-confirmed dispatch
reconciliation. The upstream compiler runs in a temporary fixture and is not canonical Forge
history; the native output is verification evidence only. Keep the agent read-only and keep
safe-output execution behind the existing approval, lease, and provider boundaries.

## Notes

The verifier intentionally binds exact `v0.85.4` metadata and the pinned workflow schema. A
future upstream compiler requires a reviewed spec/version update rather than silently changing
the native output contract.
