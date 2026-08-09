---
id: 0041
title: Evaluate optional OpenAI MCP and UI extension
status: backlog
agent: architect
model: opus
depends_on: [0038]
issue: 83
---

## Goal

Decide whether Forge has a workflow that justifies an OpenAI MCP server or optional UI
resource, while preserving the current skills-first and host-neutral design.

## Acceptance criteria

- [ ] At least one concrete workflow is shown to require server-backed tools or visual
      inspection rather than existing skills and host tools.
- [ ] A threat model covers authentication, data boundaries, tool annotations, retries, and
      external side effects.
- [ ] The decision records either a minimal MCP/UI design or an evidence-backed deferral.
- [ ] Any implementation is split into a separate reviewed task with its own tests and
      submission requirements.

## Context

OpenAI's current plugin architecture makes MCP and custom UI optional. Adding either one
would expand the trust and publication surface, so this is a decision task rather than a
default feature request.
