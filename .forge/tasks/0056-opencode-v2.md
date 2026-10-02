---
id: 0056
title: Support OpenCode v2 profiles and safe installer conflicts
status: in_progress
agent: interoperability-engineer
model: standard
depends_on: []
issue: 135
---

## Goal

Preserve OpenCode v1 discovery while providing a v2 reference profile and safe,
explicit installation behavior.

## Acceptance criteria

- [x] Retain the v1 object profile and add an opt-in v2 skill-source array profile.
- [x] Test copy, symlink, force, dry-run, and conflicting instruction behavior.
- [x] Refuse directory replacement and preserve unrelated user files.
- [x] Clarify the doctor repository-root path and keep Claude hooks out of OpenCode.
- [ ] Pass the complete local release gate, record host discovery limits, then merge.

## Evidence boundary

OpenCode 1.18.21 parsed the v1 configuration and discovered the 67 Forge surfaces on
2026-10-02. A temporary isolated OpenCode 2.0.22 parsed both configurations in memory;
v2 skill discovery and activation are separate evidence gates. It has no `debug skill`.
Focused installer tests: 9 passed. No global installation was changed during development.
