# Optional MCP and UI Decision

Status: deferred
Task: `0041`
Issue: [#83](https://github.com/AlisinaDevelo/md-files/issues/83)
Last reviewed: 2026-08-12

## Decision

Keep Forge as a skills-only plugin for the current release line. Do not add a remote MCP
server or custom UI until a concrete Forge workflow demonstrates that host-provided tools,
local scripts, and structured text results are insufficient.

This is a deferral, not a rejection. OpenAI's plugin architecture supports skills-only
packages and recommends starting with the smallest shape that supports the use case. MCP
and UI remain compatible future extensions, but adding either one now would create a new
authentication, data, hosting, review, and maintenance surface without closing a proven
workflow gap.

## Workflow inventory

| Workflow | Current capability | Server or UI gap | Decision |
|---|---|---|---|
| Plan and solve a feature | Skills, task ledger, local files, shell, and host Git tools | No live service is required; the output is a reviewable plan and diff | Skills only |
| Run and inspect durable orchestration | Local SQLite runtime, JSON schemas, lineage, receipts, and replay commands | A remote server would add deployment and auth without changing the local-first contract | Skills and local tools |
| Inspect or prepare GitHub stacks | `gh`, stack adapters, policy profiles, staged previews, and explicit approval | GitHub access already comes from the user's authenticated host; no second tool boundary is needed | Host tools |
| Package and install Forge | Reproducible release scripts, Claude and Codex validators, and marketplace smoke tests | The lifecycle is local and deterministic; a server cannot improve package verification | Local tools |
| Review a run, stack, policy decision, or receipt | Markdown, JSON, deterministic digests, and existing host rendering | No current workflow requires editing or navigating a visual canvas | Structured results |

The repository's MCP configuration under `mcp/` is a developer opt-in example for external
tools. It is not a Forge-hosted MCP server and is not part of the public plugin surface.

## Shape comparison

| Shape | Benefit | Cost | Current result |
|---|---|---|---|
| Skills only | Portable, local-first, no service credentials, works headlessly | Cannot provide a new remote data source by itself | Selected |
| Skills plus MCP | Could expose a controlled multi-user control plane or live external data | Requires hosting, auth, authorization, privacy policy, uptime, rate limits, and tool review | Defer until a real external dependency exists |
| MCP with UI | Could make a dense timeline, stack graph, or policy preview easier to inspect or edit | Adds iframe, bridge, CSP, asset, accessibility, and cross-host compatibility obligations | Defer until visual interaction is measured as necessary |

## Deferred threat model

If a future task adds an MCP server or UI, it must address these boundaries before
implementation is approved:

| Area | Required control |
|---|---|
| Authentication and authorization | Use an explicit, least-privilege user flow. Do not accept personal access tokens in tool arguments. Bind each request to the authenticated principal, repository, workspace, and allowed operation. |
| Data boundaries | Send only fields needed for the requested operation. Never place prompts, credentials, raw tool results, or sensitive repository content in durable runtime state or UI props. Redact logs and publish retention and deletion behavior. |
| Tool annotations | Set `readOnlyHint`, `openWorldHint`, and `destructiveHint` to match actual behavior for every tool. A read-only lookup, GitHub mutation, and release action must not share an ambiguous tool contract. |
| Retries and recovery | Make read operations bounded and retryable. Give writes idempotency keys, timeouts, backoff, lease or generation fencing, and a clear ambiguous-outcome path. Never retry a consequential write blindly. |
| External side effects | Require an explicit intent, policy evaluation, approval, immediate re-check, and privacy-safe receipt before GitHub, release, or other public mutations. Keep preview and effect execution separate. |
| UI isolation | Use the MCP Apps standard first, keep every tool useful without the component, declare a narrow CSP, avoid secrets in component state, and provide a headless fallback when the host does not render UI. |
| Supply chain and operations | Pin and review server and UI dependencies, define health and rate-limit behavior, test failure modes, and preserve a rollback path for server metadata and UI resource versions. |

These controls align with Forge's existing policy, receipt, runtime, and privacy contracts;
they are not a reason to bypass those contracts behind an MCP boundary.

## Reopen criteria

Create a new reviewed implementation task only when at least one of these is demonstrated
with reproducible evidence:

1. A supported workflow needs live data or an action from a service that the host does not
   already provide.
2. Multiple users need a shared, remote Forge control plane rather than a local runtime
   and repository state.
3. A representative evaluation set shows that users cannot reliably inspect, compare,
   edit, confirm, or navigate the result as structured text.

The implementation must be split into separate tasks: first the MCP contract and threat
model, then a minimal read-only server slice, then any write tools, and finally UI only if
the measured workflow still needs it. Each slice needs its own tests, review evidence,
submission metadata, and rollback plan. No MCP or UI implementation is part of task `0041`.

## Evidence and sources

Current Forge surfaces reviewed:

- [Runtime and MCP Tasks adapter](runtime.md)
- [Policy plane](policy-plane.md)
- [Privacy policy](privacy.md)
- [GitHub stack workflow](github-native-stacks.md)
- [MCP developer configuration](../mcp/README.md)

Official OpenAI sources reviewed on 2026-08-12:

- [Plugin architecture](https://developers.openai.com/plugins/concepts/plugins)
- [MCP server](https://developers.openai.com/plugins/concepts/mcp-server)
- [Build an MCP server](https://developers.openai.com/plugins/build/mcp-server)
- [Add UI to an MCP server](https://developers.openai.com/plugins/build/chatgpt-ui)
- [Plugin guidelines](https://developers.openai.com/plugins/app-guidelines)
- [Security and privacy](https://developers.openai.com/plugins/guides/security-privacy)
- [Submit plugins](https://developers.openai.com/plugins/deploy/submission)
- [MCP server review requirements](https://developers.openai.com/plugins/deploy/app-review)
