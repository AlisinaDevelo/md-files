---
id: 0051
title: Add A2A StreamResponse evidence and concurrent-stream checks
status: review
agent: interoperability-engineer
model: sonnet
depends_on: [0020, 0021]
issue: 97
---

## Goal

Add a local, digest-only admission and evidence contract for A2A v1 StreamResponse
message, task, concurrent subscription, and push metadata shapes.

## Acceptance criteria

- [x] A versioned runtime schema describes the report and its reference-only context.
- [x] The verifier accepts message-only and task streams with ordered transport closure.
- [x] Exact A2A 1.0 wrapper members are recorded; legacy `kind` and `final` fail closed.
- [x] Terminal and interrupted closure are distinguished, and interruption may resume.
- [x] Bounded concurrent task streams require equivalent logical response references.
- [x] Push metadata is bound to the task, context, stream, event, and wrapper member.
- [x] Credentials, raw content, and authority grants fail closed.
- [x] A deterministic JSONL corpus and focused tests cover valid and hostile cases.
- [ ] The change is reviewed and merged through the public release workflow.

## Research decisions

- A2A v1 permits a first `Task` or a single `Message`, then ordered updates; the
  verifier models this as evidence rather than implementing a transport.
- A2A 1.0 removed `kind` and `final`; Forge records the exact wrapper member and a
  transport-level `closed` observation instead.
- Multiple subscriptions are represented as bounded streams with equivalent logical
  responses. Delivery-local IDs and timestamps may differ, and closing one stream does
  not imply that another stream closed.
- Terminal states are absorbing. Interrupted states may close the observed stream or
  transition back to work when later evidence exists.
- Delivery endpoints and payloads remain digest references.
- Forge's canonical runtime history remains authoritative; A2A identifiers do not
  replace Forge event identity or authority policy.

## Verification

Run `python3 scripts/forge-a2a-stream.py evaluate --corpus
tests/fixtures/a2a-stream/v2.jsonl --json`, the focused pytest module, and the
repository validation gate. Track release review on GitHub issue #97.

Local evidence recorded 2026-08-19:

- Corpus: 6/6 expected outcomes, including 4 hostile rejections.
- Focused tests: 14 passed.
- Full tests: 244 passed.
- Static evals: 312/313 passed, 1 warning, 0 failures.
- Cross-host scenarios: 12 passed, 0 failed, 0 flaky, 12 live-host cases skipped.
- Validation, Markdown lint (188 files), Python lint, and shell lint passed.
