---
id: 0006
title: Design and import body-aware capability IR v2
status: done
agent: architect
model: opus
depends_on: []
---

## Goal

Extend the canonical capability graph from a digest inventory into a body-aware,
semantically typed intermediate representation that can drive multiple host projections.

## Acceptance criteria

- [x] The graph schema is versioned as v2 and embeds canonical Markdown instructions.
- [x] Components expose identity, trigger, tool, permission, input, output, resource,
      script, eval, and host-extension fields.
- [x] Import remains deterministic and rejects source drift.
- [x] Existing components and eval scenarios are migrated without losing coverage.

## Context

The source contract remains `plugins/forge/{agents,skills,commands}`. Preserve existing
digests, risk labels, projection semantics, and Python 3.9-compatible stdlib-only tooling.
Issue #42 is the broader capability-renderer milestone; this task is its IR foundation.

## Notes

Implemented on `feat/capability-renderer`; the v2 graph imports all 67 components and
embeds canonical bodies, semantic fields, resources, scripts, eval links, and host
extensions. Full repository gates are green.
