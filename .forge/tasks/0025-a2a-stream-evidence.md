---
id: 0025
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
- [x] The verifier accepts message-only and task streams with ordered terminal closure.
- [x] Bounded concurrent task streams require equivalent event references.
- [x] Push metadata is bound to the task, context, stream, event, and payload kind.
- [x] Credentials, raw content, and authority grants fail closed.
- [x] A deterministic JSONL corpus and focused tests cover valid and hostile cases.
- [ ] The change is reviewed and merged through the public release workflow.

## Research decisions

- A2A v1 permits a first `Task` or a single `Message`, then ordered updates; the
  verifier models this as evidence rather than implementing a transport.
- Multiple subscriptions are represented as bounded equivalent streams. Delivery
  endpoints and payloads remain digest references.
- Forge's canonical runtime history remains authoritative; A2A identifiers do not
  replace Forge event identity or authority policy.

## Verification

Run `python3 scripts/forge-a2a-stream.py evaluate --corpus
tests/fixtures/a2a-stream/v1.jsonl --json`, the focused pytest module, and the
repository validation gate. Track release review on GitHub issue #97.
