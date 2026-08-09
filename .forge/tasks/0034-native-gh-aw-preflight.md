---
id: 0034
title: Add native gh-aw execution admission preflight
status: done
agent: reliability-engineer
model: sonnet
depends_on: [0033]
issue: 21
---

## Goal

Create a read-only admission boundary for native `gh-aw` execution. A worker must be able to
prove that its pinned native source and lock are bound to one durable Forge episode, one request,
and one verified runtime history boundary before it can consume a lease.

## Acceptance criteria

- [x] Native preflight requires verified `upstream-gh-aw` artifacts and fails closed on preview,
      stale, or mismatched output.
- [x] A deterministic episode ID is bound to the dispatcher, request digest, spec, and upstream
      contract; arbitrary supplied IDs are rejected.
- [x] The certificate binds runtime and gh-aw definition digests, source/lock hashes, upstream
      version/schema, native job roles, safe-output declarations, and the verified history head.
- [x] The certificate contains no prompts, provider content, credentials, or effect payloads and
      does not append runtime history or call GitHub.
- [x] Repeated generation is byte-stable; an existing path may only contain the same certificate.
- [x] The certificate schema is included in Claude/Codex release surfaces and documented for the
      future native worker integration.
- [x] Focused tests, full local validation, and hosted CI pass for the pushed branch.

## Context

Tasks 0031-0033 make native compilation reproducible and structurally admissible, while tasks
0027-0030 provide the durable episode and fenced provider boundaries. This task connects those
contracts without enabling live execution: the native worker integration must consume this
certificate in a later task and still revalidate the current lease immediately before effects.

## Verification

- Focused gh-aw/runtime/release tests pass (`27 passed`); full pytest passes (`292 passed`).
- Ruff, Python compilation, `scripts/validate.sh`, capability graph/projection checks,
  Markdownlint (`0` issues across `199` files), ShellCheck, static eval (`312/313`, one existing
  warning), and cross-host scenarios (`12/12`) pass.
- Real local `gh-aw v0.85.4` native compilation, admission verification, and certificate emission
  pass without dispatching a workflow or calling GitHub.
- Hosted CI run [31286286392](https://github.com/AlisinaDevelo/md-files/actions/runs/31286286392)
  passes all applicable jobs, including native compiler/reproducibility and release-surface
  validation; OpenSSF Scorecard is skipped on the feature branch.
