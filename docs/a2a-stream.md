# A2A StreamResponse Evidence

Forge records a provider-neutral, digest-only evidence bundle for the A2A v1
`StreamResponse` contract. The adapter verifies the first response shape, ordered
terminal closure, task state transitions, bounded concurrent subscriptions, and
push-delivery metadata without contacting a provider or storing message bodies.

The supported evidence modes are:

- **Message-only**: one `message` event, first and terminal.
- **Task**: one or more equivalent streams beginning with a `task` event and closing
  with a terminal `status_update`. Concurrent streams must carry the same event
  references in the same order.
- **Push metadata**: an external endpoint and payload are represented by digest
  references, with the delivery bound to the task, context, stream, and event.

The envelope requires Forge host, audience, workspace, resource, authority,
admission, lease, runtime episode, provider operation, and provenance references.
It never accepts credentials, authorization headers, raw content, prompts, or
provider bodies, and its `authority_grant` result is always `false`.

Run the deterministic corpus from the repository root:

```bash
python3 scripts/forge-a2a-stream.py evaluate \
  --corpus tests/fixtures/a2a-stream/v1.jsonl --json
```

Verify one envelope and emit the digest-only report:

```bash
python3 scripts/forge-a2a-stream.py verify --input envelope.json --json
```

This is an evidence and admission adapter, not an A2A client, server, webhook
sender, authentication mechanism, or replacement for Forge canonical event history.
The protocol reference is the [A2A specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md).
