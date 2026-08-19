---
id: 0053
title: Enforce MCP Tasks per-request capability admission
status: done
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

- [x] Version the adapter contract and opaque task handles without changing Forge runtime history.
- [x] Require the exact request `_meta` capability object on get, result, update, and cancel paths.
- [x] Reject missing, absent, malformed, or non-object Tasks capabilities before state access.
- [x] Keep request metadata and input responses outside durable state; preserve digest-only evidence.
- [x] Update the CLI, schema, skill documentation, and offline tests with a valid request fixture.
- [x] Run the full local release gate and publish one ready stacked PR.

## Research decisions

- The current MCP Tasks guidance says servers advertise the extension in server capabilities and
  check the client's extension in each request before returning a `CreateTaskResult`.
- The adapter accepts the request's `_meta` object, not a constructor-only capability, so a caller
  cannot accidentally reuse a stale session-level opt-in.
- This remains a local projection over canonical Forge history; it does not add a hosted MCP
  server, `server/discover`, raw input persistence, or live transport.

## Primary source

- [MCP Tasks extension overview](https://modelcontextprotocol.io/extensions/tasks/overview)

## Verification

- Focused adapter suite: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_forge_mcp_tasks.py -q -ra` -> 7 passed.
- Full local release gate at implementation commit `86b2fb59b4da8205337c3832c9c0dcbc9626b3c9`: `395 passed`; static evals `333/334` with one warning and zero failures; 12 cross-host scenarios and all contract corpora passed; Ruff, Markdown lint, skills-ref, Claude validation, and ShellCheck passed.
- Release builds were byte-identical; offline archive, marketplace, and attestation validation passed.
- Installed candidate replay passed with 2 identical attempts over 8 cases; candidate `forge-3.6.0-codex.tar.gz` SHA-256 `c614852a8d470ddfcb9a925690e3d42b65c1d3b7f01deeb01209f52c022971cd`, 112 installed files, 25 installed skills.
- Evidence file: `/tmp/forge-mcp-task-admission-evidence.json`.
