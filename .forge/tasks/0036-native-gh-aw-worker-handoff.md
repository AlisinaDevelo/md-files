---
id: 0036
title: Add native gh-aw worker handoff contract
status: done
agent: reliability-engineer
model: sonnet
depends_on: [0035]
issue: 21
---

## Goal

Give a native upstream gh-aw worker a verified, digest-only handoff into the durable Forge
runtime. The handoff must bind one admission certificate to one leased effect without making
the workflow lock a second source of runtime history.

## Acceptance criteria

- [x] A native handoff command verifies the current admission certificate, claims exactly one
      requested outbox effect, and emits a strict reference-only envelope.
- [x] The envelope binds the admission, episode, dispatcher, effect, worker, request reference,
      safe-output identity, and lease generation; it contains no raw payloads, credentials, or
      absolute filesystem paths.
- [x] Replaying the envelope is idempotent for the same live lease and fails closed for a
      different worker, generation, effect, request, or certificate.
- [x] Provider plan, approval, execute, and reconcile stages can consume the envelope and
      revalidate it against the current runtime before any external effect.
- [x] The schema, CLI, docs, focused tests, and local validation are updated; hosted CI is
      verified on the pushed commit.

## Context

Tasks 0031-0035 made native compilation reproducible, admitted the pinned job graph, issued a
certificate, and taught the provider to consume that certificate. This task closes the next
boundary named in the runtime roadmap: native worker consumption. It remains deployment-gated;
the command is an offline/local runtime contract and does not dispatch GitHub or claim a live
production control plane.

## Notes

The handoff claims only the selected effect. A generic outbox claim must not accidentally lease
the other dispatcher workers when a native job is handed one target effect.

## Verification

- Focused runtime/provider tests: 26 passed.
- Full test suite: 299 passed.
- `bash scripts/validate.sh`, capability compile/render checks, Ruff, ShellCheck, and Markdownlint
  passed.
- Static eval: 312/313 passed with one pre-existing situational warning and zero failures.
- Cross-host scenarios: 12 passed, 12 skipped, zero failures.
