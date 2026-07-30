---
id: 0005
title: Verify and release Forge 3.0
status: done
agent: test-engineer
model: opus
depends_on: [0004]
---

## Goal

Prove the release, publish it through GitHub, and refresh local Claude, Codex, and
`.agents` installations.

## Acceptance criteria

- [x] Unit tests, static evals, validators, markdown lint, shellcheck, and Python lint pass.
- [x] Plugin validators pass for Claude and Codex manifests.
- [x] The release is committed, tagged, pushed, and published on GitHub.
- [x] Claude, Codex, and `.agents` installations report the new version/capabilities.

## Context

GitHub authentication must remain the existing `AlisinaDevelo` account.

## Notes

Do not publish until every local release gate passes.

Release commit `1779cab` passed all seven GitHub CI jobs. Tags `v3.0.0` and
`forge--v3.0.0` were pushed, the GitHub release was published, Claude and Codex report
version 3.0.0 enabled, and nested `.agents` stack assets were verified.
