---
id: 0050
title: Add bounded A2A task handoff and lifecycle evidence
status: in_progress
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
- [ ] Run the full local release gate, publish one stacked draft PR, and record exact
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

Pending the final clean-tree release gate and stacked PR publication.

## Primary sources

- [A2A 1.0 specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)
- [A2A agent discovery](https://github.com/a2aproject/A2A/blob/main/docs/topics/agent-discovery.md)
- [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)
- [RFC 7515 JSON Web Signature](https://www.rfc-editor.org/rfc/rfc7515)
