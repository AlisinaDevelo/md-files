---
id: 0011
title: Add fail-closed v1-to-v2 capability migration
status: done
agent: migration-specialist
model: sonnet
depends_on: [0006]
---

## Goal

Provide a reversible, source-parity-checked path from the inventory graph v1 to the
body-aware graph v2.

## Acceptance criteria

- [x] Unchanged v1 graphs migrate to the canonical v2 graph.
- [x] Unsupported schema versions, missing components, and changed digests stop with
      actionable errors.
- [x] Migration fixtures cover successful and failure paths.
- [x] The workflow is documented and uses the current compiler import as its target.

## Context

The implementation is `scripts/migrate_capabilities.py`. It refuses to synthesize bodies
from stale data and instead requires every v1 component to match the current source
contract before returning v2.

## Notes

Implemented on `feat/capability-diff-migrations`; full repository gates passed and the
change landed in PR #47.
