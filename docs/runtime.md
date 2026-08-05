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
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 checkpoint --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 checkpoints --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 restore --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 migrations --dry-run
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 migrate --dry-run
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 outbox --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 inbox --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 lease-events \
  --effect-id EFFECT_ID
```

The database schemas are versioned in [`data/runtime-events.schema.json`](../data/runtime-events.schema.json),
[`data/runtime-state.schema.json`](../data/runtime-state.schema.json),
[`data/runtime-outbox.schema.json`](../data/runtime-outbox.schema.json),
[`data/runtime-inbox.schema.json`](../data/runtime-inbox.schema.json),
[`data/runtime-lease-events.schema.json`](../data/runtime-lease-events.schema.json),
[`data/runtime-checkpoints.schema.json`](../data/runtime-checkpoints.schema.json),
[`data/runtime-restore.schema.json`](../data/runtime-restore.schema.json), and
[`data/runtime-migrations.schema.json`](../data/runtime-migrations.schema.json). A store
uses only the reviewed migration registry for an older database and refuses an unknown
schema version rather than guessing at a transformation.

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

## Checkpointed recovery

`checkpoint_run` captures reducer state at a verified event boundary. The checkpoint binds the
run, workflow, definition, policy, database schema, event sequence, event hash, and state
digest; its state passes the same reference-only payload boundary as event data. Repeating a
checkpoint request for the same boundary returns the existing deterministic checkpoint.

`restore_state` selects the newest valid checkpoint, verifies its metadata, state digest, and
event head, then applies only the verified event suffix. A corrupt checkpoint is skipped. A
corrupt event suffix stops at the last verified prefix and returns a recovery report with a
privacy-safe error reference; unsafe state is never used. Full `state` and `history` remain
strict verification APIs and fail closed on any corruption.

Database upgrades are explicit and append migration evidence with source and target versions,
preconditions, result digest, status, and restore guidance. Use `migrations --dry-run` to
inspect a legacy database and `migrate` only after preserving a verified backup. Interrupted
migrations remain resumable; canonical event rows are not rewritten by the checkpoint schema
upgrade. Checkpoints are retained as evidence and no compaction command deletes history needed
to verify active runs or external effects.

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

Human-input waits, adaptive routing, and distributed backends remain follow-up work under
[#19](https://github.com/AlisinaDevelo/md-files/issues/19).

## Boundary

This is durable history plus an at-least-once external-effect protocol, not exactly-once
provider execution. SQLite can atomically persist the intent and receipt; only the adapter and
provider can make a retry harmless. A worker crash after a provider accepts an operation but
before Forge records the receipt is expected to produce a retry, which is why the stable
provider idempotency key is mandatory.
