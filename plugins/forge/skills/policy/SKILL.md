---
name: policy
description: >-
  Use when an orchestrated run may create an external effect or mutate a protected
  resource. Defines versioned action envelopes, declarative profiles, scoped one-use
  approvals, staged previews, pre-effect re-evaluation, and privacy-safe decision
  receipts for Forge mutation adapters.
---

# Policy Plane

The policy plane is Forge's authorization boundary for effects. It is deliberately
small, readable, and standard-library-only so local runs do not depend on an
enterprise policy service.

## Required flow

1. Build a versioned action envelope with the exact tool identity, arguments, resource
   scope, principal, workspace, and intended effect.
2. Evaluate the selected profile and inspect the decision, rule, reason, constraints,
   policy revision, and action digest.
3. For a staged preview, return the decision and record `staged-preview`; do not call
   an external adapter and do not consume an approval.
4. If approval is required, issue a short-lived approval bound to the action digest,
   principal, workspace, policy revision, and one use.
5. Re-evaluate immediately before the adapter effect and consume the exact approval.
6. After the adapter returns, record the final committed effect and result digest.

The action digest includes the canonical envelope and policy revision. Any material
argument, resource, principal, workspace, branch, file, or profile change invalidates
the approval. Raw arguments, prompts, credentials, and tool payloads must never be
placed in approval records or receipts.

## Identity and delegated authority

For agent or worker effects, bind the policy action to the versioned authority contract
before the adapter runs:

```bash
python3 scripts/forge-authority.py evaluate \
  --corpus tests/fixtures/authority/v1.jsonl --json
```

The authority verifier checks the actor identity, parent delegation, audience, workspace,
capability, resource, tool, intent, expiry, revocation generation, nonce, policy revision,
policy decision, approval, worker lease, runtime episode, provider operation, and provenance
references. It accepts either
a host-authenticated proof reference or a local HMAC trust boundary; private keys and host
credentials remain outside Forge state. A legacy principal is supported only through the
explicit `legacy-principal-v1` profile and remains scope-bound.

Connected execution must call the verifier again immediately before its effect. Forge
records digest-only bindings; authentication is the host's responsibility and is not
inferred from model output or self-description.

### Host-authenticated admission

Connected hosts may provide a `forge-host-admission-v1` proof for one exact effect. The host
must validate its OAuth, DPoP, mTLS, SPIFFE, or JWS cryptography before creating the proof.
Forge validates the versioned shape and binds the host, audience, workspace, resource, request,
authority, policy decision, approval, lease, runtime episode, provider operation, provenance,
scopes, and policy revision. It also enforces a short lifetime, generation, nonce replay
protection, sender-constrained versus bearer semantics, and exclusion of raw credentials.
The proof is evidence of the host boundary, not a local cryptographic verification of the host.

The deterministic corpus exercises the positive and replay-threat paths:

```bash
python3 scripts/forge-host-admission.py evaluate \
  --corpus tests/fixtures/host-admission/v1.jsonl --json
```

## Profiles

Profiles live in `policies/` and are intentionally readable during review:

- `default` denies undeclared effects and permits safe inspection.
- `review` allows inspection and requires approval for writes or execution.
- `github-mutation` protects GitHub issue and stacked-PR mutations with scoped approval.
- `release` requires approval for publishing, tagging, and release effects.
- `production` requires approval for production or deployment effects with tighter
  cost and fan-out limits.

Protected instruction, workflow, dependency-lock, security, settings, and plugin
manifest paths are never silently allowed. A rule that would allow one of them is
upgraded to `require_approval`.

## CLI

Use the root wrapper or the skill script:

```bash
python3 scripts/forge-policy.py --profile default profiles
python3 scripts/forge-policy.py --profile github-mutation evaluate --action action.json
python3 scripts/forge-policy.py --profile github-mutation stage --action action.json
python3 scripts/forge-policy.py --profile github-mutation approve --action action.json --ttl-seconds 600
python3 scripts/forge-policy.py --profile github-mutation authorize --action action.json --approval-id APPROVAL_ID
```

Mutation adapters opt in with `--policy-profile`. Existing explicit `--yes` gates
remain in force; `--policy-staged` is the no-effect path and therefore does not need
`--yes`.

The core `PolicySession` is an adapter protocol. An enterprise implementation can wrap
or replace the session at the integration boundary without adding a dependency to the
Forge core.
