---
id: 0004
title: Integrate docs, catalog, and installers
status: done
agent: docs-writer
model: sonnet
depends_on: [0002, 0003]
---

## Goal

Make Forge Stacks discoverable and consistent across manifests, catalogs, workflows, and
installation targets.

## Acceptance criteria

- [x] README, getting started, usage, architecture, and workflow docs explain the feature.
- [x] Machine-readable bundle/workflow/catalog data includes the new capability.
- [x] Manifests and counts are updated for the major release.
- [x] Competitive audit records the release's durable differentiation.

## Context

Generated catalog files must be regenerated, not hand-edited.

## Notes

Use direct product language and avoid unsupported performance claims.

The `.agents` installer now preserves nested skill references and executable scripts.
