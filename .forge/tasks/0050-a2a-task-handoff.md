---
id: 0050
title: Add bounded A2A task handoff and lifecycle evidence
status: done
agent: interoperability-engineer
model: standard
depends_on: [0049, 0047, 0048]
issue: 95
---

## Goal

Add a strict, offline A2A 1.0 task lifecycle verifier that turns one admitted task
handoff into digest-only evidence bound to the Agent Card and Forge execution context.

## Acceptance criteria

- [x] Validate protocol version, task/context identity, required Forge references, and
      bounded event ordering.
- [x] Validate input-required and auth-required interruptions without treating either state
      as authority.
- [x] Validate terminal closure, message identity, cancellation idempotency, and effect
      drift for repeated idempotency keys.
- [x] Validate optional stream ordering and safe HTTPS push configuration without DNS,
      network, credential, or artifact access.
- [x] Emit a strict digest-only report, deterministic threat corpus, focused tests, and
      release-surface wiring.
- [x] Run the full local release gate, publish one stacked draft PR, and record exact
      evidence.

## Research decisions

- A2A 1.0 task state includes submitted, working, input-required, auth-required, and
  terminal states; streams begin with the current task and close at terminal state.
- Send Message may use messageId for idempotency; Cancel is idempotent and repeated effects
  must not mutate the task into a different result.
- Push notification targets must be HTTPS, bound to the expected task/context, and must not
  expose credentials or target local/private networks.
- AUTH_REQUIRED is an authentication interruption, not a Forge authorization decision.

## Scope boundary

Do not implement a live A2A client, transport, registry discovery, push delivery, credential
exchange, artifact download, signature verification, provider authorization, or remote
execution in this slice.

## Verification

Implementation commit: f183738db6014e8f00e23bb528461e4b41726c83.
Draft PR: [#96](https://github.com/AlisinaDevelo/md-files/pull/96).

- Clean local release gate: passed.
- Full pytest suite: 381 passed.
- Static evaluations: 333/334 passed, 1 warning, 0 failures.
- A2A task corpus: 8 cases, 5 threat cases, deterministic, passed.
- Trajectory, authority, host-admission, and A2A Agent Card corpora: 4/2, 11/5, 2/1,
  and 4/3 cases/threats, respectively; all passed.
- Backend conformance: 12/12; six release artifacts were byte-identical.
- Offline release, DSSE/SLSA attestation, Codex archive, and marketplace validation:
  passed.
- Candidate archive SHA-256:
  1d3ef8cb636040c8d964e19d8bf06f77fbd06d19c22860c6c20e06881e134611.
- Installed candidate replay: 8 cases across 2 identical attempts; passed. The isolated
  install contained 110 files and 25 skills.

## Primary sources

- [A2A 1.0 specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)
- [A2A agent discovery](https://github.com/a2aproject/A2A/blob/main/docs/topics/agent-discovery.md)
- [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)
- [RFC 7515 JSON Web Signature](https://www.rfc-editor.org/rfc/rfc7515)
