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

python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 state --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 verify --run-id run-demo
```

The database schema is versioned in [`data/runtime-events.schema.json`](../data/runtime-events.schema.json)
and [`data/runtime-state.schema.json`](../data/runtime-state.schema.json). A store refuses
an unknown schema version rather than guessing at a migration.

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

The current lifecycle supports start, pause, resume, cancellation request, cancellation,
completion, failure, and bounded task scheduling/start/completion/failure/cancellation.
Worker leases, heartbeats, snapshots, migrations, human-input waits, outbox/inbox effects,
and distributed backends remain follow-up work under [#19](https://github.com/AlisinaDevelo/md-files/issues/19).

## Boundary

This is durable history and deterministic projection, not exactly-once external execution.
An external write still needs an idempotency key and a policy-approved outbox/inbox adapter.
That boundary is deliberately separate so a retry cannot be mistaken for a transaction across
SQLite and a provider API.
