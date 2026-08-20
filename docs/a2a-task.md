# A2A Task Handoff Evidence

Forge can validate one bounded A2A 1.0 task lifecycle after an Agent Card has been
admitted. The verifier produces a strict, deterministic, digest-only
`forge-a2a-task-v1` report. It is a local evidence adapter, not an A2A client.

## What it checks

- A2A 1.0 protocol version, task and context identity, and the full Forge context binding.
- Ordered lifecycle events from send/submitted through a terminal state.
- Allowed transitions for working, input-required, and auth-required interruptions.
- Message identity drift and repeated idempotency-key effect drift.
- Idempotent cancellation acknowledgements.
- Optional stream positions and first/terminal markers.
- Optional push notification configuration with HTTPS, task/context binding, digest-only
  authentication, and rejection of local, private, link-local, or credential-bearing URLs.
- Strict exclusion of prompts, message parts, artifacts, provider bodies, tokens, and raw
  webhook credentials.

AUTH_REQUIRED is an interruption state, not an authorization grant. Authority, host
admission, lease, runtime episode, provider operation, and provenance are required as
references from the surrounding Forge context; cryptographic authentication and remote
execution remain provider responsibilities.

## Verify one handoff

From the repository root:

~~~bash
python3 scripts/forge-a2a-task.py verify --input TASK-ENVELOPE.json
~~~

The envelope binds the task to the admitted Agent Card and carries only opaque identifiers
and SHA-256 references. It does not contact the remote agent, fetch artifacts, resolve DNS,
send a webhook, acquire credentials, or persist A2A message parts.

## Run the deterministic corpus

~~~bash
python3 scripts/forge-a2a-task.py evaluate --corpus tests/fixtures/a2a-task/v1.jsonl --json
~~~

The checked-in corpus expects eight cases and five explicit threat cases. It covers
auth-required recovery, cancel retry, secure push configuration, terminal reopening,
sequence gaps, message-content drift, private push targets, and raw message-body rejection.

## Boundary

Forge intentionally does not implement a live A2A client, streaming transport, push
delivery, registry discovery, credential exchange, artifact download, or provider
authorization in this slice. A provider adapter must verify its own authentication and
bind every effect to the report references before execution.

## Sources

- [A2A 1.0 specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)
- [A2A agent discovery](https://github.com/a2aproject/A2A/blob/main/docs/topics/agent-discovery.md)
- [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)
- [RFC 7515 JSON Web Signature](https://www.rfc-editor.org/rfc/rfc7515)
