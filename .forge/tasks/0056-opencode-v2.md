---
id: 0056
title: Support OpenCode v2 profiles and safe installer conflicts
status: done
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
- [x] Pass the complete local release gate, record host discovery limits, then merge.

## Completion Evidence

PR [#139](https://github.com/AlisinaDevelo/md-files/pull/139) merged as
`96d7bf650f3af86c461f0e9b2c32b1379f8af276`. The complete local release gate passed on
`e577efbe5e4e0cc9edf0fd3eabe2e3eab25370e5`: 465 tests, including 9 focused installer
tests, plus lint, security corpora, deterministic packaging, installed contract replay,
and isolated Claude/Codex lifecycle checks. Independent review found no merge blocker.

## Evidence boundary

OpenCode 1.18.21 parsed the v1 configuration and discovered the 67 Forge surfaces on
2026-10-02. A temporary isolated OpenCode 2.0.22 parsed both configurations in memory;
the experimental v2 `skill.list` API returned zero registrations in that isolated setup,
so v2 skill discovery and activation remain unverified. It has no `debug skill`.
Focused installer tests: 9 passed. No global installation was changed during development.
