---
id: 0045
title: Add DSSE and SLSA v1.2 artifact attestation verification
status: planned
agent: security-auditor
model: opus
depends_on: [0022, 0033]
issue: 86
---

## Goal

Make release evidence portable by verifying DSSE-wrapped SLSA v1.2 provenance for Forge
archives and SBOMs without overstating local development evidence as public-key provenance.

## Acceptance criteria

- [ ] Archive and SBOM subjects bind to source ref, build definition, resolved inputs, policy,
      and exact digests.
- [ ] Offline verification supports explicit trust roots, rotation, revocation, and clear
      local-HMAC versus public-key/GitHub evidence profiles.
- [ ] Tampered subject, predicate, signature, trust-root, and binding fixtures fail closed.
- [ ] Verification results are digest-only, reproducible, and included in the local release gate.
- [ ] Documentation does not claim a SLSA build level without corresponding builder evidence.

## Scope boundary

Do not require hosted CI or change the canonical runtime history. GitHub artifact-attestation
integration remains an adapter with its own evidence boundary.

## Primary sources

- [SLSA v1.2 provenance](https://slsa.dev/spec/v1.2/provenance)
- [SLSA build provenance](https://github.com/slsa-framework/slsa/blob/main/spec/build-provenance.md)
