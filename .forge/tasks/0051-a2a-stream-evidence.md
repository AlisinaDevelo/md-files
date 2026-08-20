---
id: 0051
title: Add A2A StreamResponse evidence and concurrent-stream checks
status: done
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
- [x] The change is reviewed and merged through the public release workflow.

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

Local evidence recorded 2026-08-20:

- Corpus: 6/6 expected outcomes, including 4 hostile rejections.
- Focused tests: 15 passed.
- Full tests: 398 passed.
- Static evals: 333/334 passed, 1 warning, 0 failures.
- Cross-host scenarios: 12 passed, 0 failed, 0 flaky, 12 live-host cases skipped.
- Validation, Markdown lint, Python lint, ShellCheck, skills-ref, plugin validation, and release checks passed.
- Reproducible release builds produced 6 byte-identical artifacts; offline release, Codex,
  marketplace, and attestation checks passed.
- Installed candidate replay passed twice with identical results across 8 cases (111 files, 25 skills).
- Public release: PR #99 merged at `c046dc39528ea37bef69f3e2d928af1927c5fbc7` from tested head
  `6001ab2e6b4fe04c2cbbe0c901f612278c9e9675`.
