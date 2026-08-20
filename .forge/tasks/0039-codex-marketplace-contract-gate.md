---
id: 0039
title: Add strict Codex marketplace contract validation
status: done
agent: test-engineer
model: sonnet
depends_on: [0038]
issue: 82
---

## Goal

Turn the current OpenAI Codex marketplace policy and local source requirements into a
dependency-free validator that runs locally and in hosted CI.

## Acceptance criteria

- [x] Marketplace name, interface, plugin entries, local source paths, policy values, and
      categories are validated against the current Codex contract.
- [x] Local source resolution is checked without allowing paths outside the marketplace root.
- [x] Valid and invalid policy fixtures have focused tests.
- [x] `scripts/validate.sh` and the hosted host-validation job run the gate.

## Context

Forge already has a strict plugin manifest validator and a Codex marketplace smoke test, but
the marketplace JSON was previously checked only for parseability and source existence.

## Notes

The gate intentionally validates the skills-only local/repository marketplace shape. Public
directory submission, publisher verification, and any remote catalog state remain external.
