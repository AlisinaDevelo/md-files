---
id: 0007
title: Render deterministic native and degraded host surfaces
status: done
agent: devops-engineer
model: sonnet
depends_on: [0006]
---

## Goal

Generate reproducible Claude, Codex, and Agent Skills-compatible trees from the canonical
graph, including nested resources, manifests, and explicit degraded shims.

## Acceptance criteria

- [ ] Built-in renderers cover native and omitted/shimmed component kinds.
- [ ] Claude-only command substitutions are removed or adapted at the shim boundary.
- [ ] Native skill resources and host manifests are copied deterministically.
- [ ] Repeated renders compare byte-for-byte and are exercised by release gates.

## Context

The renderer is `scripts/render_capabilities.py`; output is an explicit caller-selected
directory and never a tracked generated tree. Keep existing hand-authored Zed shims as
reviewed release artifacts until the bundle migration slice lands.

## Notes

Implemented on `feat/capability-renderer`; focused renderer tests, deterministic snapshots,
and the release-packager dry run are green. Full bundle/workflow derivation remains a
follow-up boundary documented in issue #42.
