---
id: 0002
title: Build the stack engine
status: done
agent: devops-engineer
model: sonnet
depends_on: [0001]
---

## Goal

Provide a safe, vendor-neutral command-line engine for defining, inspecting, validating,
and planning submission of stacked branches.

## Acceptance criteria

- [x] A versioned `.forge/stack.json` manifest models provider, trunk, remote, and branches.
- [x] The engine supports init, add, link, status, check, plan, and PR-body generation.
- [x] Mutating GitHub or Git operations are never performed by the default path.
- [x] Unit tests cover valid stacks, invalid graphs, git ancestry, adapters, and plans.

## Context

The executable must use Python's standard library and ship inside the plugin.

## Notes

Prefer explicit commands and recovery instructions over hidden git rewrites.

Twenty new stack workflow and guard tests pass.
