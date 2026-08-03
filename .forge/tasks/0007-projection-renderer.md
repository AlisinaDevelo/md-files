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

- [x] Built-in renderers cover native and omitted/shimmed component kinds.
- [x] Claude-only command substitutions are removed or adapted at the shim boundary.
- [x] Native skill resources and host manifests are copied deterministically.
- [x] Repeated renders compare byte-for-byte and are exercised by release gates.

## Context

The renderer is `scripts/render_capabilities.py`; output is an explicit caller-selected
directory and never a tracked generated tree. Release packaging now consumes its generated
surface, while hand-authored Zed files remain reviewed source inputs for install config.

## Notes

Implemented on `feat/capability-renderer`; focused renderer tests, deterministic snapshots,
and the release-packager dry run are green. Bundle/workflow derivation landed in task 0012.
