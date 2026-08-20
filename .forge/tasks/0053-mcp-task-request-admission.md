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

- Focused adapter suite: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_forge_mcp_tasks.py -q -ra` -> 8 passed, including a negative matrix for every task operation entrypoint.
- Full local release gate passed on implementation/test commit `913bb3e630d360e6e1f8019c78c6c7256a2a07f4`: 416 tests; static evals `333/334` with one warning and zero failures; trajectory, authority, host-admission, A2A card/task, cross-host, backend, and deterministic chaos checks passed.
- Python compilation, Ruff, Markdown lint, skills-ref, strict Claude validation, and ShellCheck passed; 7 release artifacts were byte-identical across two builds.
- Offline release, Codex archive, OpenAI skills-only ZIP, marketplace, and attestation validation passed.
- Installed candidate replay passed with 2 identical attempts over 8 cases; `forge-3.7.0-openai.zip` SHA-256 `c3549d31fc9ecf34af6acbae77ccdc089ae8e64b4273ed6393cb76f09a85b381`, 119 installed files, 25 installed skills.
- The implementation was previously reviewed in stacked PR [#102](https://github.com/AlisinaDevelo/md-files/pull/102), which merged into its feature parent. Mainline reconciliation is [#111](https://github.com/AlisinaDevelo/md-files/pull/111).
