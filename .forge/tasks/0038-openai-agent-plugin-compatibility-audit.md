---
id: 0038
title: Audit OpenAI universal Agent Plugin compatibility
status: done
agent: architect
model: opus
depends_on: [0037]
issue: 82
---

## Goal

Record the current OpenAI universal Agent Plugin contract and map it honestly to Forge's
Claude, Codex, and Agent Skills surfaces. This prevents the repository marketplace from
being mistaken for public directory approval.

## Acceptance criteria

- [x] Official OpenAI architecture, packaging, marketplace, guidelines, and submission
      sources are recorded with review date.
- [x] Forge's skills-only shape, manifest, assets, marketplace, and non-goals are audited.
- [x] The public submission boundary and required evidence are explicit.
- [x] Follow-up implementation and submission tasks are recorded in the local ledger and
      GitHub issue plan.

## Context

OpenAI now describes plugins as universal ChatGPT and Codex packages. Skills-only plugins are
valid; MCP servers and UI are optional and should only be added for a real workflow need.

## Notes

See [OpenAI Agent Plugins compatibility](../../docs/openai-agent-plugins.md) and the
[marketplace readiness](../../docs/marketplace-readiness.md) checklist.
