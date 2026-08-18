---
id: 0049
title: Validate signed A2A Agent Cards as bounded delegation evidence
status: in_progress
agent: security-engineer
model: standard
depends_on: [0048]
issue: 93
---

## Goal

Add an offline A2A 1.0 Agent Card verifier that turns untrusted discovery metadata
into digest-only interoperability evidence bound to an explicit Forge execution context.

## Acceptance criteria

- [ ] The verifier validates required A2A card fields, secure interfaces, protocol versions,
      skills, security requirements, extensions, and forward-compatible unknown fields.
- [ ] Optional JWS cards receive shape validation, while cryptographic verification remains
      an external host or trust-service responsibility.
- [ ] Credential-shaped values, insecure URLs, legacy extended-card declarations, and
      context/card digest drift fail closed.
- [ ] The report is strict, deterministic, digest-only, and never grants authority.
- [ ] A deterministic threat corpus, tests, release projection, and local gate are wired.

## Research decisions

- A2A 1.0 defines Agent Cards, secure service interfaces, optional JWS signatures, and
  authenticated extended cards for discovery and interoperability.
- RFC 8785 and RFC 7515 govern the external canonicalization and signature boundary.
- Discovery metadata is not authorization; Forge must bind any later effect to its own
  authority, policy, lease, provenance, and host-admission contracts.

## Scope boundary

Do not fetch `.well-known` cards, operate a live registry, obtain credentials, verify
cryptographic signatures, or execute remote A2A tasks in this slice.

## Verification

Record the exact local gate, commit, and stacked PR here after the implementation is
committed and pushed.

## Primary sources

- [A2A 1.0 specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)
- [A2A agent discovery](https://github.com/a2aproject/A2A/blob/main/docs/topics/agent-discovery.md)
- [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)
- [RFC 7515 JSON Web Signature](https://www.rfc-editor.org/rfc/rfc7515)
