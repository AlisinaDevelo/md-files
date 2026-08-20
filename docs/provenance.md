# Runtime Provenance

Forge can export a deterministic, signed evidence bundle that connects canonical runtime
history to portable traces without making telemetry the source of truth. The event history,
runtime receipts, and lineage verifier remain authoritative; a provenance bundle is a
portable projection for review, release evidence, and offline incident work.

## Export and verify

The command is local and standard-library-only. It does not contact an OpenTelemetry collector,
GitHub, a model provider, or a key server:

```bash
python3 scripts/forge-provenance.py export \
  --db .forge/runtime.sqlite3 \
  --source-revision git:HEAD \
  --policy-revision policy-v1 \
  --key-id forge-local-2026 \
  --key-file .forge/keys/forge-local-2026.key \
  --trust-policy .forge/keys/trust-policy.json \
  --output .forge/provenance.json

python3 scripts/forge-provenance.py verify \
  --bundle .forge/provenance.json \
  --trust-policy .forge/keys/trust-policy.json \
  --source-revision git:HEAD \
  --policy-revision policy-v1
```

The verifier checks the bundle digest, lineage hash chain, exact subject digest, source and
policy revisions, evidence-input digests, W3C context, pinned mapping, signature, and trust
status. Failures name the first invalid boundary and return a non-zero exit code.

## Contract

- W3C Trace Context is accepted only after strict validation. The incoming `traceparent` and
  `tracestate` are preserved as correlation metadata; invalid context is rejected, allowing a
  caller to restart with a newly derived trace instead of propagating an untrusted parent.
- Stable trace IDs derive from the incoming trace ID or the Forge run ID. Root, event, effect,
  attempt, and receipt span IDs derive from stable Forge IDs, so retries and replay produce the
  same correlation identities while each retry remains a distinct attempt span.
- `forge-otel-1`, OTel `1.59.0`, and GenAI semantic conventions `1.42.0` are recorded in the
  bundle. Workflow, agent, tool, effect, wait, receipt, and bounded GenAI usage/cost mappings
  are explicit in the mapping object.
- The signed statement is an in-toto Statement v1 with an SLSA-shaped provenance predicate.
  Its subject is the exact SHA-256 digest of the verified runtime lineage manifest. Evidence
  inputs also cover the trace projection, trace context, and mapping.
- v1 signs the DSSE pre-authenticated encoding with `hmac-sha256`. This is an offline symmetric
  trust model, not a claim of public-key or hosted SLSA attestation. The algorithm is versioned
  in the schema so a future asymmetric signer can be added without silently changing meaning.

The schema is [`data/runtime-provenance.schema.json`](../data/runtime-provenance.schema.json).
The CLI never writes to the runtime database while exporting.

## Privacy and retention

Default exports contain only stable identifiers, status values, references, and digests. Prompt,
credential, token, tool argument, tool result, response, and content keys are redacted before
they reach the bundle. Raw content requires all three controls: an explicit allowlist, an
`allow_content` policy flag, and `export_enabled`; allowed strings are bounded and carry a
digest when truncated. Secret-looking keys remain redacted even under opt-in mode.

Keep runtime databases, receipt logs, key files, and provenance bundles on encrypted storage.
Retain the smallest evidence set needed for the operational or legal purpose: usually the
verified bundle, its subject digest, the relevant policy revision, and the incident record.
Apply the repository or organization retention schedule to raw receipts and delete them after
the evidence window closes. A deleted raw receipt must not be reconstructed from a provenance
bundle because the bundle intentionally contains no raw content.

## Key custody and rotation

The trust policy contains key IDs, algorithms, statuses, and base64-encoded HMAC material. Treat
it as secret configuration; do not commit it or place it inside a bundle. The signing key file
must match the active key entry exactly. Use an encrypted secret store or a protected local
volume, restrict file permissions, and keep a separate backup under the organization's custody
rules.

To rotate, add a new active key, export new bundles with its key ID, and mark the old key
`retired`. Retired keys remain valid for verification of historical bundles. After the review
window, or immediately after suspected compromise, mark the key `revoked`; verification then
fails closed. Preserve the old bundle digest and key ID in the rotation record so an operator
can explain which trust decision was applied at verification time.

## Incident response

1. Stop exports with the affected key and revoke it in the trust policy.
2. Preserve the original bundle, subject digest, verifier output, source revision, policy
   revision, and key ID as incident evidence.
3. Verify whether the bundle signature was valid before revocation and record the trust policy
   revision used for that decision.
4. Rotate to a new key, re-export from the unchanged canonical runtime history, and compare the
   new lineage subject digest with the preserved one.
5. Investigate raw receipts and provider systems under their own access controls; do not add
   recovered prompts or tool bodies to the provenance bundle.

Export loss, collector downtime, and output reordering are observational failures. They must
never be treated as runtime transitions or used to rewrite canonical event history.
