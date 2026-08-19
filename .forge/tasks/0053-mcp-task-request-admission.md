---
id: 0053
title: Enforce MCP Tasks per-request capability admission
status: in-progress
agent: interoperability-engineer
model: standard
depends_on: [0044]
issue: 85
---

## Goal

Align Forge's reference-only MCP Tasks adapter with the current extension boundary: advertise
server support, but require the client's `io.modelcontextprotocol/clientCapabilities.extensions`
entry in every task request before returning a task view or acknowledging a task operation.

## Acceptance criteria

- [ ] Version the adapter contract and opaque task handles without changing Forge runtime history.
- [ ] Require the exact request `_meta` capability object on get, result, update, and cancel paths.
- [ ] Reject missing, absent, malformed, or non-object Tasks capabilities before state access.
- [ ] Keep request metadata and input responses outside durable state; preserve digest-only evidence.
- [ ] Update the CLI, schema, skill documentation, and offline tests with a valid request fixture.
- [ ] Run the full local release gate and publish one ready stacked PR.

## Research decisions

- The current MCP Tasks guidance says servers advertise the extension in server capabilities and
  check the client's extension in each request before returning a `CreateTaskResult`.
- The adapter accepts the request's `_meta` object, not a constructor-only capability, so a caller
  cannot accidentally reuse a stale session-level opt-in.
- This remains a local projection over canonical Forge history; it does not add a hosted MCP
  server, `server/discover`, raw input persistence, or live transport.

## Primary source

- [MCP Tasks extension overview](https://modelcontextprotocol.io/extensions/tasks/overview)
