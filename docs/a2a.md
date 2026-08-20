# A2A Agent Card Evidence

Forge can inspect an A2A 1.0 Agent Card as untrusted interoperability input. The
verifier produces a versioned, digest-only `forge-a2a-card-v1` report for a specific
host, audience, workspace, and resource.

## What it checks

- Required Agent Card fields and bounded values.
- HTTPS or WSS service endpoints and safe custom binding URIs.
- Protocol-version compatibility.
- Skill identity, required skills, input/output modes, and forward-compatible fields.
- Declared security schemes and requirements, including secure nested URLs.
- Required extension support.
- Optional JWS shape, including a protected header with `alg` and `kid`.
- Credential-shaped values and legacy unauthenticated extended-card declarations.

The report contains references and counts, not card descriptions, examples, tokens,
signatures, or provider response bodies. An Agent Card is metadata, not authorization:
`authority_grant` is always `false`.

## Verify one card

From the repository root:

```bash
python3 scripts/forge-a2a-card.py verify \
  --input CARD.json \
  --host-ref host:codex \
  --audience audience:a2a \
  --workspace workspace:md-files \
  --resource resource:repo/md-files \
  --protocol-version 1.0 \
  --required-skill route-plan \
  --required-security-scheme oauth \
  --supported-extension https://example.test/extensions/trace/v1
```

The command does not fetch the card, contact a registry, obtain credentials, or verify
cryptographic signatures. A host or a separately configured trust service must verify
JWS signatures using RFC 8785 canonicalization and RFC 7515 rules before treating the
external signature reference as authenticated.

## Run the deterministic corpus

```bash
python3 scripts/forge-a2a-card.py evaluate \
  --corpus tests/fixtures/a2a-card/v1.jsonl \
  --json
```

The corpus covers a valid signed card, an insecure endpoint, an unsupported required
extension, and a card-reference mismatch. The checked-in release gate expects four
cases and three explicit threat cases.

## Task handoff

After card admission, use [A2A Task Handoff Evidence](a2a-task.md) to validate one
bounded task lifecycle and bind it to the Agent Card, authority, host admission, lease,
runtime, provider, and provenance references. The task adapter keeps interruptions,
idempotency, cancellation, stream ordering, and push safety explicit without becoming
a live A2A client.

## Boundary

Forge intentionally does not implement a live A2A client, `.well-known` discovery,
registry integration, credential acquisition, signature verification, or remote
execution in this slice. Those are provider integrations that must bind their own
identity, policy, host admission, lease, and runtime evidence before any effect.

## Sources

- [A2A 1.0 specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)
- [A2A agent discovery](https://github.com/a2aproject/A2A/blob/main/docs/topics/agent-discovery.md)
- [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)
- [RFC 7515 JSON Web Signature](https://www.rfc-editor.org/rfc/rfc7515)
