---
id: 0045
title: Add DSSE and SLSA v1.2 artifact attestation verification
status: done
agent: security-auditor
model: opus
depends_on: [0022, 0033]
issue: 86
---

## Goal

Make release evidence portable by verifying DSSE-wrapped SLSA v1.2 provenance for Forge
archives and SBOMs without overstating local development evidence as public-key provenance.

## Acceptance criteria

- [x] Archive and SBOM subjects bind to source ref, build definition, resolved inputs, policy,
      and exact digests.
- [x] Offline verification supports explicit trust roots, rotation, revocation, and clear
      local-HMAC versus public-key/GitHub evidence profiles.
- [x] Tampered subject, predicate, signature, trust-root, and binding fixtures fail closed.
- [x] Verification results are digest-only, reproducible, and included in the local release gate.
- [x] Documentation does not claim a SLSA build level without corresponding builder evidence.

## Scope boundary

Do not require hosted CI or change the canonical runtime history. GitHub artifact-attestation
integration remains an adapter with its own evidence boundary.

## Primary sources

- [SLSA v1.2 provenance](https://slsa.dev/spec/v1.2/provenance)
- [SLSA build provenance](https://github.com/slsa-framework/slsa/blob/main/spec/build-provenance.md)
- [in-toto envelope layer](https://github.com/in-toto/attestation/blob/main/spec/v1/envelope.md)
- [GitHub offline attestation verification](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline)

## Verification

The release manifest now declares `forge-release-attestation-v1`. The standard-library verifier
in `scripts/forge-attestation.py` checks canonical DSSE payloads, Ed25519 or local HMAC
signatures, explicit trust-root rotation and revocation, exact archive/SBOM subjects, source
ref, builder, policy, manifest, and resolved-input bindings. GitHub artifact attestations remain
host-verified evidence through `gh attestation verify`; the local receipt profile does not claim
to reproduce GitHub's certificate or transparency-log verification.

Verification evidence:

- `uv run --with 'pytest>=8,<9' pytest tests/test_forge_attestation.py -q -ra`: 7 passed.
- `scripts/forge-attestation.py self-test`: two positive profiles and six negative tamper cases.
- `scripts/verify_release.py`: release manifest, archives, SBOM, and attestation contract pass.
- `scripts/local-release-check.sh`: attestation verification is part of the release gate.
