---
id: 0012
title: Derive release surfaces from the capability graph
status: done
agent: devops-engineer
model: sonnet
depends_on: [0007, 0008, 0010, 0011]
---

## Goal

Make release archives consume graph-rendered host trees and resolved metadata instead of
packaging separately maintained host instruction surfaces.

## Acceptance criteria

- [x] Claude, Codex, Agent Skills, and Zed-compatible host trees are rendered first.
- [x] Catalogs, bundles, workflows, manifests, schemas, licenses, and install inputs are
      included in the rendered release surface.
- [x] Release archives consume generated paths and preserve executable modes.
- [x] SPDX and offline verification remain valid with shared archive path namespaces.
- [x] Repeated release builds remain byte-identical.

## Context

The implementation extends `scripts/render_capabilities.py` with the release-surface
projection and makes `scripts/build_release.py` archive that output. Existing authored Zed
files remain source inputs for global install configuration; generated capability shims are
what enter the release archive.

## Notes

Implemented on `feat/compiler-release-surfaces`; release and Codex archive tests are green.
