---
id: 0028
title: Add a fenced gh-aw GitHub provider worker
status: in_progress
agent: security-engineer
model: sonnet
depends_on: [0027]
issue: 21
---

## Goal

Close the provider-side gap between a leased gh-aw outbox effect and a bounded GitHub API
operation without weakening Forge's approval, privacy, replay, or idempotency contracts.

## Acceptance criteria

- [x] A versioned request envelope binds repository, episode, workflow, safe-output type, and
      operation payload to the existing `request_digest` or `output_ref`.
- [x] Planning is offline and no-effect by default; it validates compiled allowlists, title and
      label policy, comment limits, PR file scope, dispatch targets, and secret-free content.
- [x] Live execution requires an explicit flag, expected authenticated GitHub login, current
      worker and lease generation, matching compiled policy action digest, and one-use approval.
- [x] Provider calls use bounded REST endpoints, stable idempotency evidence, current workflow
      dispatch run details, and reference-only receipts; stale leases and ambiguous retries fail
      closed rather than duplicating effects.
- [x] Issue, comment, PR, and workflow-dispatch paths have transport-mocked tests; no test or
      verification step mutates GitHub.
- [ ] CLI, schema, docs, capability graph, release projections, focused tests, full validation,
      and hosted CI pass under `AlisinaDevelo`.

## Scope boundary

This worker executes only the four safe-output types compiled by `forge-gh-aw-v1`. It does not
grant agents write credentials, infer undeclared targets, push commits, or claim exactly-once
provider delivery.

## Verification

Local implementation evidence:

- The secret-free request schema and provider CLI bind each leased effect to the compiled
  repository, workflow, output type, operation digest, policy action digest, and exact runtime
  lease. Planning has no provider transport; execution requires `--execute`, the expected
  `gh` login, a consumed one-use approval, a running episode, and a current lease generation.
- The provider supports dispatch, issue, comment, and pull-request safe outputs with configured
  target/label/title/file limits, content sanitization, bounded REST requests, pagination-aware
  marker recovery, append-only 0600 hash-chained evidence, and reference-only receipts. It
  fails closed on ambiguous dispatch or partial provider outcomes and does not claim exactly-once
  delivery.
- Focused provider/runtime tests pass (`9 + 28 passed`); the full repository suite passes
  (`271 passed`). Ruff, Python compilation, `scripts/validate.sh`, Markdown lint (193 files),
  and ShellCheck pass.
- Static evals pass `312/313` with one existing warning and zero failures; all 12 cross-host
  scenarios, both backend conformance adapters, and the bounded chaos corpus pass.
