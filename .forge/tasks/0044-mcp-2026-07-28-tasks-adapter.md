---
id: 0044
title: Add MCP 2026-07-28 Tasks adapter contract
status: planned
agent: architect
model: opus
depends_on: [0019, 0038]
issue: 85
---

## Goal

Upgrade Forge's reference-only MCP Tasks projection to an explicit compatibility contract for
the final MCP 2026-07-28 specification without turning the plugin into a hosted service.

## Acceptance criteria

- [ ] A versioned `mcp-2026-07-28` profile rejects unsupported or ambiguous revisions.
- [ ] `tasks/get`, `tasks/update`, and `tasks/cancel` remain projections over canonical Forge
      history and bind wait, request, and authorization references by digest.
- [ ] `input_required` round trips are bounded, idempotent, replayable, and reject stale or
      mismatched responses.
- [ ] Task handles are isolated and cannot be enumerated when request identity is unavailable.
- [ ] Offline fixtures cover retries, input rounds, expiry, cancellation, isolation, and legacy
      version rejection while the existing backend gate remains green.
- [ ] Documentation distinguishes this adapter contract from live MCP server support.

## Scope boundary

Do not add a hosted MCP server, MCP Apps UI, raw input persistence, or a second source of truth.

## Primary sources

- [MCP 2026-07-28 final specification](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [MCP Tasks extension](https://modelcontextprotocol.io/extensions/tasks/overview)
- [MCP TypeScript 2026 migration](https://ts.sdk.modelcontextprotocol.io/v2/migration/support-2026-07-28)
