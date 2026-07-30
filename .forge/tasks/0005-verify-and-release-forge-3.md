---
id: 0005
title: Verify and release Forge 3.0
status: in-progress
agent: test-engineer
model: opus
depends_on: [0004]
---

## Goal

Prove the release, publish it through GitHub, and refresh local Claude, Codex, and
`.agents` installations.

## Acceptance criteria

- [ ] Unit tests, static evals, validators, markdown lint, shellcheck, and Python lint pass.
- [ ] Plugin validators pass for Claude and Codex manifests.
- [ ] The release is committed, tagged, pushed, and published on GitHub.
- [ ] Claude, Codex, and `.agents` installations report the new version/capabilities.

## Context

GitHub authentication must remain the existing `AlisinaDevelo` account.

## Notes

Do not publish until every local release gate passes.
