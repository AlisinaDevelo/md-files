---
id: 0037
title: Add native gh-aw provider lease supervision
status: review
agent: reliability-engineer
model: sonnet
depends_on: [0036]
issue: 21
---

## Goal

Keep a native gh-aw provider worker fenced for the whole external-call window. A handoff
generation is not enough if authentication, recovery, or a GitHub request outlives its
heartbeat lease before the receipt is acknowledged.

## Acceptance criteria

- [x] The gh-aw runtime exposes an explicit heartbeat transition bound to one episode effect,
      worker, and lease generation.
- [x] Provider authentication and every transport request heartbeat before and after the call;
      a lost lease fails closed and prevents later provider calls.
- [x] Existing journal and reconciliation paths preserve recovery evidence when a lease is lost
      after an external call returns but before acknowledgement.
- [x] Tests cover heartbeat evidence, stale-owner/generation rejection, pre-call fencing, and
      post-call lease loss without recording raw provider responses.
- [ ] The roadmap, provider docs, capability projections, local validation, and hosted CI remain
      current under the `AlisinaDevelo` GitHub identity. Hosted CI is pending the review push.

## Context

Task 0036 made native worker admission consumable through a strict handoff. The next failure
window is temporal rather than structural: the existing provider can hold a lease while its
authenticated login, recovery lookup, or mutation runs, but it did not renew or recheck the
lease around those calls. This slice reuses the generation-fenced runtime heartbeat and keeps
production deployment explicitly gated.

## Scope boundary

The guard does not claim exactly-once GitHub execution. A provider call that returns after lease
loss remains ambiguous and must be recovered through the existing journal/reconcile protocol.

## Local verification

- Focused runtime/provider tests: 29 passed.
- Full test suite: 302 passed.
- `bash scripts/validate.sh`, capability compile/render checks, Ruff, ShellCheck, and Markdownlint
  passed.
- Static eval: 312/313 passed with one pre-existing situational warning and zero failures.
- Cross-host scenarios: 12 passed, 12 skipped, zero failures.
