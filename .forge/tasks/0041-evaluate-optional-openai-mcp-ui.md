---
id: 0041
title: Evaluate optional OpenAI MCP and UI extension
status: done
agent: architect
model: opus
depends_on: [0038]
issue: 83
---

## Goal

Decide whether Forge has a workflow that justifies an OpenAI MCP server or optional UI
resource, while preserving the current skills-first and host-neutral design.

## Acceptance criteria

- [x] Concrete Forge workflows were evaluated; none currently requires server-backed tools
      or visual inspection beyond existing skills and host tools.
- [x] The decision record covers authentication, data boundaries, tool annotations, retries,
      and external side effects.
- [x] The decision records an evidence-backed deferral and explicit reopen criteria.
- [x] Any future implementation is split into separate reviewed tasks with their own tests
      and submission requirements.

## Context

OpenAI's current plugin architecture makes MCP and custom UI optional. Adding either one
would expand the trust and publication surface, so this is a decision task rather than a
default feature request.

## Decision

Forge remains skills-only for the current release line. See
[`docs/openai-mcp-ui-decision.md`](../../docs/openai-mcp-ui-decision.md) for the workflow
inventory, threat model, evidence, and criteria for reopening the decision.
