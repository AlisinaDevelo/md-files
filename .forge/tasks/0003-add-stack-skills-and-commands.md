---
id: 0003
title: Add stack skills and commands
status: done
agent: tech-lead
model: sonnet
depends_on: [0001]
---

## Goal

Teach Claude, Codex, and `.agents` clients to design, author, review, restack, and land
stacked changes safely.

## Acceptance criteria

- [x] A progressive-disclosure skill covers stack design, tool adapters, review, CI,
      merge order, and recovery.
- [x] `/stack` and `/stack-review` commands expose author and reviewer workflows.
- [x] Pull-request authoring and orchestration route large changes into stacks when useful.
- [x] Codex/Zed command shims expose both commands.

## Context

Keep the core method vendor-neutral and move tool-specific commands into a reference.

## Notes

Each PR must remain independently understandable and reviewable.
