---
id: 0008
title: Harden adapter contract and conformance tests
status: done
agent: test-engineer
model: sonnet
depends_on: [0007]
---

## Goal

Make third-party host projection behavior explicit, safe, and independently verifiable.

## Acceptance criteria

- [ ] The v1 adapter schema validates identifiers, component-kind partitions, paths, and
      projection naming fields.
- [ ] Unsafe paths, overlapping native/shim kinds, and unsupported kinds fail closed.
- [ ] A representative third-party adapter renders native skills and agent/command shims.
- [ ] Deterministic output and existing cross-host scenarios remain green.

## Context

Use `data/host-adapter.schema.json`, `render_adapter`, and the repository's existing
`evals/run_scenarios.py` contracts. Do not require live Claude or Codex credentials.

## Notes

The v1 schema and executable contract checks are present in `data/host-adapter.schema.json`,
`scripts/render_capabilities.py`, and `tests/test_capability_renderer.py`; unsafe paths and
overlapping kind partitions fail closed.
