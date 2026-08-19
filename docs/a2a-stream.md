# A2A StreamResponse Evidence

Forge records a provider-neutral, digest-only evidence bundle for the A2A v1
`StreamResponse` contract. The adapter verifies the v1 wrapper member, first response
shape, transport closure, task state transitions, bounded concurrent subscriptions,
and push-delivery metadata without contacting a provider or storing message bodies.

Each normalized event records `response_member` as exactly one of the v1 wrapper
members: `task`, `message`, `statusUpdate`, or `artifactUpdate`. This field belongs to
Forge evidence; it is not the legacy A2A `kind` discriminator. The v1 `kind` and
`final` fields fail closed because A2A 1.0 removed both of them.

The supported evidence modes are:

- **Message-only**: one `message` response followed by verified transport closure.
- **Task**: one or more streams beginning with a `task` response, followed by ordered
  `statusUpdate` or `artifactUpdate` responses, and closed in a terminal or interrupted
  state. An interrupted state may later resume; when later evidence exists, Forge
  validates the transition and the eventual closure state.
- **Concurrent subscriptions**: streams must carry the same logical response references
  in the same order. Stream IDs, local event IDs, and observation timestamps may differ,
  and each stream has independent closure evidence.
- **Push metadata**: an external endpoint and payload are represented by digest
  references, with the delivery bound to the task, context, stream, event, and exact
  wrapper member.

The envelope requires Forge host, audience, workspace, resource, authority,
admission, lease, runtime episode, provider operation, and provenance references.
It never accepts credentials, authorization headers, raw content, prompts, or
provider bodies, and its `authority_grant` result is always `false`.

Run the deterministic corpus from the repository root:

```bash
python3 scripts/forge-a2a-stream.py evaluate \
  --corpus tests/fixtures/a2a-stream/v2.jsonl --json
```

Verify one envelope and emit the digest-only report:

```bash
python3 scripts/forge-a2a-stream.py verify --input envelope.json --json
```

This is an evidence and admission adapter, not an A2A client, server, webhook
sender, authentication mechanism, or replacement for Forge canonical event history.
The protocol references are the [A2A specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md),
[A2A 1.0 migration notes](https://github.com/a2aproject/A2A/blob/main/docs/whats-new-v1.md),
and [streaming and asynchronous operations](https://github.com/a2aproject/A2A/blob/main/docs/topics/streaming-and-async.md).
