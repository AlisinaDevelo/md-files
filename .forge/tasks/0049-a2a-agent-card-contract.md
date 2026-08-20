---
id: 0049
title: Validate signed A2A Agent Cards as bounded delegation evidence
status: done
agent: security-engineer
model: standard
depends_on: [0048]
issue: 93
---

## Goal

Add an offline A2A 1.0 Agent Card verifier that turns untrusted discovery metadata
into digest-only interoperability evidence bound to an explicit Forge execution context.

## Acceptance criteria

- [x] The verifier validates required A2A card fields, secure interfaces, protocol versions,
      skills, security requirements, extensions, and forward-compatible unknown fields.
- [x] Optional JWS cards receive shape validation, while cryptographic verification remains
      an external host or trust-service responsibility.
- [x] Credential-shaped values, insecure URLs, legacy extended-card declarations, and
      context/card digest drift fail closed.
- [x] The report is strict, deterministic, digest-only, and never grants authority.
- [x] A deterministic threat corpus, tests, release projection, and local gate are wired.

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

The implementation commit is `99b10a96ea7a2f0fa0788074cb44df9bce11435d`.

- `./scripts/validate.sh`: passed.
- Full pytest suite: 368 passed.
- Static evaluations: 333/334 passed, 1 warning, 0 failures.
- A2A corpus: 4 cases, 3 threat cases, deterministic, passed.
- Trajectory, authority, and host-admission corpora: 4/2, 11/5, and 2/1 cases/threats,
  respectively; all passed.
- Backend conformance: 12/12; six release artifacts were byte-identical across two builds.
- Offline release, DSSE/SLSA attestation, Codex archive, and marketplace validation: passed.
- Installed candidate replay: 8 cases across 2 identical attempts; passed.
- Candidate archive SHA-256: `76dd59b32044437900c6eeafd8d313b6f196c046e91a6be3c82229ad498d6a93`.

## Primary sources

- [A2A 1.0 specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)
- [A2A agent discovery](https://github.com/a2aproject/A2A/blob/main/docs/topics/agent-discovery.md)
- [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)
- [RFC 7515 JSON Web Signature](https://www.rfc-editor.org/rfc/rfc7515)
