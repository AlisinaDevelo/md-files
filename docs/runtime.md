# Durable Runtime Foundation

Forge's durable runtime starts with a local-first execution history. The history is the
source of truth for a run; receipts remain privacy-safe observability evidence and the
task ledger remains planning state. Provider sessions, MCP Tasks, and GitHub workflows
are adapters that will consume this contract rather than replace it.

## Local store

The standard-library runtime uses SQLite in WAL mode by default:

```bash
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 start \
  --run-id run-demo \
  --workflow-id feature-flow \
  --definition-version workflow-v1 \
  --policy-revision policy-v1

python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 append \
  --run-id run-demo \
  --event-type task.scheduled \
  --idempotency-key task-build-scheduled \
  --payload-json '{"task_id":"build","depends_on":[]}'

python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 append \
  --run-id run-demo \
  --event-type task.scheduled \
  --idempotency-key task-test-scheduled \
  --payload-json '{"task_id":"test","depends_on":["build"]}' \
  --effect-json '{"effect_type":"github.issue.create","task_id":"test","activity_id":"github-issue","attempt":1,"effect_definition_revision":"effect-v1","payload":{"target_ref":"github:issues/1","request_digest":"sha256:request"}}'

python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 state --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 verify --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 outbox --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 inbox --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 lease-events \
  --effect-id EFFECT_ID
```

The database schemas are versioned in [`data/runtime-events.schema.json`](../data/runtime-events.schema.json),
[`data/runtime-state.schema.json`](../data/runtime-state.schema.json),
[`data/runtime-outbox.schema.json`](../data/runtime-outbox.schema.json), and
[`data/runtime-inbox.schema.json`](../data/runtime-inbox.schema.json), and
[`data/runtime-lease-events.schema.json`](../data/runtime-lease-events.schema.json). A store
refuses an unknown schema version rather than guessing at a migration.

## Execution contract

- Every run has a pinned workflow, definition, and policy revision.
- Events receive a monotonic per-run sequence and a deterministic event identifier derived
  from the idempotency key.
- Each event hashes its canonical JSON plus the previous event hash. Reopening a database
  replays the complete prefix and rejects sequence gaps, transition violations, or tampering.
- Duplicate idempotency keys return the original event without another write. Reusing a key
  with different event data fails closed.
- Runtime payloads accept identifiers, references, and digests. Prompts, raw content,
  tool arguments/results, credentials, and tokens are rejected from durable state.
- SQLite `BEGIN IMMEDIATE`, WAL, and a bounded busy timeout serialize local writers without
  requiring a hosted service.

The lifecycle supports start, pause, resume, cancellation request, cancellation, completion,
failure, and bounded task scheduling/start/completion/failure/cancellation.

## External effect protocol

Pass an effect descriptor when appending the event that schedules an external operation. Forge
derives a stable `effect_id` and provider `idempotency_key` from the run, task, activity,
activity attempt, effect-definition revision, and effect type. The event and pending outbox
intent commit in one SQLite transaction, so a failed outbox insert cannot leave a replayable
event with no effect intent.

Workers claim pending or retryable intents with a bounded lease. Each claim advances a
monotonic lease generation and returns a provider-facing context containing the worker,
generation, expiry, deadline, and idempotency key. An expired lease can be reclaimed by
another worker, but the old generation cannot heartbeat, authorize submission, acknowledge,
or fail the effect, even if the same worker identifier is reused. `heartbeat_outbox` extends
only the current lease and only up to its persisted maximum deadline. Heartbeats, claims,
and lease loss are reference-only evidence in `runtime_outbox_lease_events`, separate from
the canonical event history.

A worker either acknowledges with a reference-only receipt or records a retryable/non-
retryable failure; delivery attempt rows preserve claim, generation, and outcome metadata
without rewriting the canonical event history. The inbox is keyed by the derived provider
idempotency key: an identical duplicate returns the original receipt, while a conflicting
reuse fails closed. Lease, heartbeat, activity-timeout, cancellation, and retry policy
revisions are pinned when the first claim is made.

Adapters must make the external operation idempotent and return status, references, digests,
and provider request IDs. Prompts, raw content, tool arguments/results, credentials, tokens,
and provider response bodies are rejected at the persistence boundary. The effect hash also
makes direct outbox tampering detectable before inspection or delivery.

Snapshots/migrations, human-input waits, adaptive routing, and distributed backends remain
follow-up work under [#19](https://github.com/AlisinaDevelo/md-files/issues/19).

## Boundary

This is durable history plus an at-least-once external-effect protocol, not exactly-once
provider execution. SQLite can atomically persist the intent and receipt; only the adapter and
provider can make a retry harmless. A worker crash after a provider accepts an operation but
before Forge records the receipt is expected to produce a retry, which is why the stable
provider idempotency key is mandatory.
