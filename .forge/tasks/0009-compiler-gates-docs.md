---
id: 0009
title: Integrate compiler gates and update capability docs
status: done
agent: docs-writer
model: sonnet
depends_on: [0007, 0008]
---

## Goal

Document the v2 compiler workflow and ensure local, CI, and release validation exercise
the graph and renderer together.

## Acceptance criteria

- [ ] `validate.sh`, `justfile`, CI Ruff scope, and release packaging invoke the renderer.
- [ ] Capability IR docs describe v2 bodies, adapter contracts, migration, and current
      release boundaries accurately.
- [ ] README evidence counts and links match the verified suite.
- [ ] The focused feature is ready for a reviewable PR with follow-up boundaries stated.

## Context

Keep release versioning separate from this feature branch. Full bundle/workflow derivation
and semantic migration reports remain follow-up work under issue #42 unless completed and
verified in this task.

## Notes

Docs, README evidence counts, validation, CI Ruff scope, and release packaging integration
are complete on `feat/capability-renderer`. Follow-up work is recorded in issue #42 rather
than hidden behind this focused change.
