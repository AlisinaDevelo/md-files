---
id: 0048
title: Add host-authenticated admission evidence for connected effects
status: done
agent: security-engineer
model: standard
depends_on: [0047]
issue: 21
---

## Goal

Give connected Forge adapters a portable digest-only statement that a host verified the
external authentication proof for one exact effect, without hosted identity providers or
credentials.

## Acceptance criteria

- [x] Versioned `forge-host-admission-v1` schema binds host, audience, workspace, resource,
  request, authority, policy, approval, lease, runtime, provider, provenance, scope, and
  policy-revision refs.
- [x] Verifier checks canonical digest, resource/audience, scope, short lifetime, nonce replay,
  generation, and credential exclusion.
- [x] Auth schemes distinguish sender-constrained from bearer and require replay protection.
- [x] The gh-aw provider accepts an explicit host-admission file and rechecks it after login
  before an external request.
- [x] Deterministic positive/threat corpus, provider tests, release projection, and local gate
  are wired.

## Research decisions

- NIST's 2026 agent standards initiative treats authentication and identity infrastructure as
  a research priority.
- MCP authorization uses a canonical resource audience; RFC 9449 and RFC 9700 cover
  sender-constrained and replay-resistant OAuth protections.
- OpenAI Agents SDK tool guardrails provide an execution-boundary reference.
- Forge verifies shape, binding, freshness, and replay; the host owns OAuth, DPoP, mTLS, SPIFFE,
  or JWS cryptography.

## Scope boundary

Do not add a hosted identity provider, store tokens or signatures, or claim the local proof
verifies live authentication.

## Verification

Full local release gate passed after implementation and ledger closure; the exact release commit
is recorded in the release handoff.

- 355 pytest tests passed.
- Static evaluations passed 333/334 with one warning and zero failures.
- Trajectory corpus passed 4 cases with 2 threat cases.
- Authority corpus passed 11 cases with 5 threat cases.
- Host-admission corpus passed 2 cases with 1 replay threat.
- Backend conformance passed 12/12; release artifacts were byte-identical across two builds.
- Offline release, Codex archive, and marketplace validation passed.
- Installed replay passed 8 cases across 2 identical attempts.
