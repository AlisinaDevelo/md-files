# Identity and Delegated Authority

Forge authority is a portable evidence contract for agents, workflows, workers, providers,
and human approvals. It is not an identity provider, token issuer, secret store, or proof
that a model is trustworthy.

## Contract

`forge-authority-v1` contains a bundle of:

- identity descriptors with issuer, subject, build, audience, workspace, scopes, resources,
  tools, intended-goal digests, expiry, nonce, revocation reference, and generation;
- an ordered delegation chain whose child scopes, resources, tools, goals, lifetime, audience,
  and workspace can only narrow the parent;
- an action bound to the final actor and authority, with digest-only capability, resource,
  tool, effect, intent, policy, approval, lease, runtime, provider, and provenance references;
- policy-decision and approval evidence that must bind to the same action, actor, authority,
  audience, workspace, capability, resource, policy revision, lease, and generation.

Action references intentionally exclude the policy and approval back-references. Those
references point to the operation digest, producing an acyclic evidence graph; the action
proof still covers the complete action envelope.

## Proof boundary

Proofs have two explicit profiles:

- `external-reference` records the algorithm, key identifier, payload digest, and opaque proof
  reference supplied by a host or identity system. Forge validates the contract and trust-key
  status but does not impersonate that external verifier.
- `local` supports HMAC-SHA256 with key material supplied only through an external trust policy.
  The key never enters the bundle, receipt, fixture, or release artifact.

The design leaves room for Ed25519, DPoP, SPIFFE SVID, or another host-bound proof without
making one provider a Forge dependency. Audience checks and short-lived authority are required
at the Forge boundary; a connected adapter must perform its own host authentication as well.

## Verification

```bash
python3 scripts/forge-authority.py evaluate \
  --corpus tests/fixtures/authority/v1.jsonl --json
```

The offline corpus covers a valid chain, goal hijack, tool poisoning, privilege escalation,
rogue delegation, nonce replay, expiry, revocation, audience drift, generation change, and
the explicit legacy-principal profile. The release oracle is deterministic. A model judge,
provider, or live identity service cannot replace these checks.

## Threat boundaries

Forge fails closed when:

- a child delegation adds a scope, resource, tool, goal, or lifetime;
- the expected audience or workspace differs from the authority claim;
- the actor, approval, policy decision, policy revision, lease, runtime, provider, or provenance
  digest drifts;
- an identity or delegation is expired, revoked, stale, or replayed;
- a tool or intended-goal digest is outside the delegated set;
- a legacy principal is used without the explicit migration profile.

The contract follows the current direction of [NIST's AI Agent Standards Initiative](https://www.nist.gov/artificial-intelligence/ai-agent-standards-initiative),
the [NIST identity and authority concept paper](https://www.nist.gov/news-events/news/2026/02/new-concept-paper-identity-and-authority-software-agents),
the [OWASP Agentic Skills security checklist](https://owasp.org/www-project-agentic-skills-top-10/checklist.html),
and [OAuth 2.0 Security Best Current Practice](https://www.rfc-editor.org/rfc/rfc9700). MCP-connected
adapters must additionally honor resource-specific audience validation and the authorization
requirements in the [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).
