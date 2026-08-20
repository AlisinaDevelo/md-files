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
  --policy-revision policy-v1 \
  --worker-build-id worker-v1 \
  --workflow-code-digest sha256:1111111111111111111111111111111111111111111111111111111111111111 \
  --workflow-schema-digest sha256:2222222222222222222222222222222222222222222222222222222222222222

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
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 definition --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 compatibility \
  --run-id run-demo --operation migration \
  --candidate-json '{"workflow_id":"feature-flow","definition_version":"workflow-v2","worker_build_id":"worker-v2","policy_revision":"policy-v1","compatible_definition_digests":["sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]}'
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 migrations --dry-run
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 migrate --dry-run
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 outbox --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 inbox --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 lease-events \
  --effect-id EFFECT_ID

python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 wait \
  --run-id run-demo --task-id approval --wait-id approval-1 \
  --input-schema-digest sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --authorization-context-digest sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  --resume-contract workflow-v1 --ttl-seconds 3600 --poll-interval-ms 1000
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 waits --run-id run-demo
python3 scripts/forge-runtime.py --db .forge/runtime.sqlite3 submit-input \
  --run-id run-demo --wait-id approval-1 --submission-id response-1 \
  --input-digest sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc \
  --input-schema-digest sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --authorization-context-digest sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
python3 scripts/forge-mcp-tasks.py --db .forge/runtime.sqlite3 get \
  --run-id run-demo --wait-id approval-1 \
  --authorization-context-digest sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb

python3 scripts/forge-lineage.py export \
  --db .forge/runtime.sqlite3 --output .forge/lineage.json
python3 scripts/forge-lineage.py verify --manifest .forge/lineage.json

python3 scripts/forge-backends.py describe --backend sqlite
python3 scripts/forge-backends.py negotiate --backend memory \
  --requirements-json '{"capabilities":["fenced_leases"],"consistency_level":"strict_serializable"}'
python3 scripts/forge-backends.py conformance --backend all
python3 scripts/forge-backends.py describe --backend etcd
python3 scripts/forge-backends.py negotiate --backend etcd \
  --requirements-json '{"required_capabilities":["remote_revisions","watch_delivery","snapshot_recovery","compaction_recovery","fenced_leases"],"consistency_level":"strict_serializable"}'
python3 scripts/forge-backends.py watch-conformance --backend etcd
```

The database schemas are versioned in [`data/runtime-events.schema.json`](../data/runtime-events.schema.json),
[`data/runtime-state.schema.json`](../data/runtime-state.schema.json),
[`data/runtime-outbox.schema.json`](../data/runtime-outbox.schema.json),
[`data/runtime-inbox.schema.json`](../data/runtime-inbox.schema.json),
[`data/runtime-lease-events.schema.json`](../data/runtime-lease-events.schema.json),
[`data/runtime-checkpoints.schema.json`](../data/runtime-checkpoints.schema.json),
[`data/runtime-restore.schema.json`](../data/runtime-restore.schema.json), and
[`data/runtime-migrations.schema.json`](../data/runtime-migrations.schema.json), and
[`data/runtime-waits.schema.json`](../data/runtime-waits.schema.json),
[`data/runtime-mcp-tasks.schema.json`](../data/runtime-mcp-tasks.schema.json),
[`data/runtime-backend.schema.json`](../data/runtime-backend.schema.json), and
[`data/runtime-backend-evidence.schema.json`](../data/runtime-backend-evidence.schema.json), and
[`data/runtime-conformance.schema.json`](../data/runtime-conformance.schema.json),
[`data/runtime-distributed.schema.json`](../data/runtime-distributed.schema.json),
[`data/runtime-definitions.schema.json`](../data/runtime-definitions.schema.json), and
[`data/runtime-compatibility.schema.json`](../data/runtime-compatibility.schema.json). A store
uses only the reviewed migration registry for an older database and refuses an unknown
schema version rather than guessing at a transformation.

For an offline, privacy-safe evidence view of this history, use the lineage exporter and
verifier described in [`docs/receipts.md`](receipts.md). The manifest is derived from the
canonical database and does not replace event verification, inbox receipts, or release
artifact attestations. A signed trace projection is described in
[`docs/provenance.md`](provenance.md); it remains an evidence adapter rather than runtime state.

## Execution contract

- Every run has a pinned workflow, digest-addressed definition, worker build, policy revision,
  policy digest, feature-flag digest, compatibility revision, and stable-step identity revision.
- A definition alias can select only new runs. In-flight runs retain their descriptor digest until
  an explicit continue-as-new boundary or a reviewed migration.
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
failure, bounded task scheduling/start/completion/failure/cancellation, and durable
human-input waits with signals.

## Human interaction

`create_wait` captures a verified checkpoint before appending `wait.created`. The wait stores
only an input-schema digest, authorization-context digest, policy revision, absolute expiry,
polling hint, expiration outcome, and bounded resume contract. `submit_input` accepts one
schema- and authorization-matched digest; duplicate delivery with the same idempotency key
returns the original event, while a conflicting or late response fails closed.

Signals are reference-only, ordered events. A signal targeted at a wait must use the wait's
authorization-context digest, and each run is bounded to a finite signal count. Expiry is
serialized in the event history and applies the wait's persisted `fail_run` or `cancel_run`
policy; no wall-clock read can silently change the outcome.

Cancellation records request, acknowledgement, and terminal cancellation evidence. A
terminal cancellation is sticky: late task completion, input, expiry, or provider callbacks
cannot resurrect the run.

### MCP Tasks 2026-07-28 adapter

The reference-only adapter in `scripts/forge-mcp-tasks.py` exposes the final
`2026-07-28` protocol revision and the `io.modelcontextprotocol/tasks` extension as the
versioned `forge-mcp-tasks-v2` contract. It projects canonical Forge history through
`tasks/get`, `tasks/update`, and `tasks/cancel`; it is not a hosted MCP server, does not
implement `server/discover`, and does not persist raw `inputResponses`.

Inspect the negotiated profile before using the adapter:

```bash
python3 scripts/forge-mcp-tasks.py profile \
  --protocol-version 2026-07-28 \
  --extension io.modelcontextprotocol/tasks
```

Every read and mutation proves the wait's authorization-context digest. `tasks/get` returns an
opaque, authorization-bound `forge-task-v2` handle. Before any task view or task mutation is
returned, the caller must pass the exact MCP request `_meta` capability object. The adapter
requires `io.modelcontextprotocol/clientCapabilities.extensions.io.modelcontextprotocol/tasks`
to be present as an object; missing or malformed request capabilities fail closed. If a caller
supplies a request-identity digest, the handle is stable across reconnects; without one, the
adapter adds a random nonce so handles cannot be enumerated. `inputRequests` contains only a
schema digest and a digest-only input-request key. Submit a digest reference, never raw input:

```json
{
  "io.modelcontextprotocol/clientCapabilities": {
    "extensions": {
      "io.modelcontextprotocol/tasks": {}
    }
  }
}
```

```bash
python3 scripts/forge-mcp-tasks.py --db .forge/runtime.sqlite3 update-by-id \
  --task-id TASK_HANDLE \
  --request-meta-json REQUEST_META_JSON \
  --authorization-context-digest sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  --input-digest sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc \
  --input-schema-digest sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --input-request-id INPUT_REQUEST_ID
```

The update and cancellation acknowledgements are empty results, as required by the Tasks
extension. Poll the same handle with `get-by-id`; repeated updates are idempotent only when the
persisted event payload matches exactly. A later input round receives a new request key, so a
stale response fails closed. Notifications remain a best-effort legacy convenience and are not
the canonical history. The adapter profile advertises `requestNegotiation: "per-request"` and
the machine-readable contract is `data/runtime-mcp-tasks.schema.json` (v2).

This boundary follows the [MCP 2026-07-28 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/),
the [Tasks extension](https://modelcontextprotocol.io/extensions/tasks/overview), and the
[TypeScript SDK migration guidance](https://ts.sdk.modelcontextprotocol.io/v2/migration/support-2026-07-28).

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
upgrade. The v2-to-v3 wait migration retains v2 checkpoints as legacy evidence, excludes them
from v3 restore, and allows a fresh v3 checkpoint at the same event boundary. The v3-to-v4
definition migration adds deterministic legacy descriptors without rewriting old event payloads;
legacy checkpoints remain evidence until a fresh v4 checkpoint is created. Checkpoints are
retained as evidence and no compaction command deletes history needed to verify active runs or
external effects.

## Definition pinning and rollout

`start_run` records a canonical definition descriptor in the run-definition table and repeats its
identity in `run.started`, so both metadata and the hash chain must agree. The descriptor digest
covers workflow identity, definition version, workflow code/schema digests, worker build, policy
and feature-flag digests,
compatibility and step-identity revisions, and an explicit list of previously reviewed compatible
definition digests. Raw workflow code, prompts, credentials, and tool content are never persisted.

Use `definition` to inspect the pinned descriptor and `compatibility` to produce a deterministic,
digest-bound decision. Exact definitions are accepted; a candidate is accepted for replay, restore,
migration, or effect retry only when it declares the pinned digest as compatible under the same
workflow and compatibility revision. `continue_as_new` is the explicit boundary for a new
definition. Workers claiming effects can pass their candidate descriptor to the runtime so retries
fail closed before lease ownership changes. The offline `DefinitionRegistry` supports active,
canary, redirected, rollback, and retired rollout states: redirecting or rolling back an alias
affects new runs, while resolving a retired digest remains possible for in-flight history. Use the
`rollout --registry-json REGISTRY --reference stable` command to inspect that alias state without
connecting to a provider.

## Distributed revision and watch recovery

The etcd-first adapter extends the portable backend descriptor with `remote_revisions`,
`watch_delivery`, `snapshot_recovery`, and `compaction_recovery`. Negotiate those capabilities and
`strict_serializable` consistency before creating a run. The implementation in
`scripts/forge-distributed.py` is a deterministic offline model: it proves the safety contract
without requiring a live etcd cluster, credentials, or provider payloads.

Canonical Forge history remains the source of truth. Remote revisions, transaction references,
watch cursors, compaction markers, and CloudEvents are reference-only evidence; CloudEvent payloads
must be represented by a `data_ref`. Notifications are normalized, verified against their watch
identity, ordered by revision, and deduplicated by canonical event reference. A missing revision,
conflicting duplicate, stale cursor, foreign watch, or tampered reference fails closed before it
can affect canonical state.

The offline contract models a dedicated Forge event stream in which every accepted revision is
expected. A live etcd integration must define its watched key range explicitly: etcd revisions are
cluster-wide, so unrelated writes can create numeric gaps in a filtered watch. Use the watch's
progress/revision evidence to distinguish an unrelated revision from a dropped Forge event; never
silently assume that a gap is harmless.

When a watch cursor is older than the compaction boundary, do not guess or replay an incomplete
history. Retain a digest-verified snapshot with its state reference and remote revision, then
replay only the contiguous notification suffix. If the snapshot is older than compaction, the
watch identity changes, or the suffix contains a gap, stop and require operator recovery. The
adapter's `watch-conformance` command covers ordering/deduplication, cursor gaps, compaction
recovery, stale watches, privacy rejection, and reconnect fencing:

```bash
python3 scripts/forge-backends.py watch-conformance --backend etcd
```

Operationally, snapshot retention must cover the longest expected reconnect and compaction
window. Quorum loss pauses remote observation and effect dispatch; it must not rewrite canonical
history or advance a cursor. After quorum returns, verify the persisted snapshot/cursor references
and replay from the last accepted revision. Keep provider-specific watch code behind the adapter
boundary and consult the [etcd API guarantees](https://etcd.io/docs/v3.7/learning/api_guarantees/),
[etcd watch/compaction guidance](https://etcd.io/docs/v3.7/dev-guide/interacting_v3/), and the
[CloudEvents specification](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md)
when implementing a live provider.

## Deterministic chaos and schedule shrinking

Runtime conformance fixtures prove selected contracts; the chaos harness explores replayable
interleavings around those contracts. A schedule is a seed, an ordered list of symbolic actions,
and an optional expected failure predicate. It never carries prompts, credentials, provider
bodies, absolute paths, or wall-clock values. The schedule reference and every result are
SHA-256 references over canonical JSON.

Generate, inspect, run, replay, and shrink schedules offline:

```bash
python3 scripts/forge-chaos.py generate --seed 6601 --output /tmp/forge-schedule.json
python3 scripts/forge-chaos.py inspect --schedule /tmp/forge-schedule.json
python3 scripts/forge-chaos.py run --schedule /tmp/forge-schedule.json --backend all
python3 scripts/forge-chaos.py replay --schedule /tmp/forge-schedule.json --backend etcd
python3 scripts/forge-chaos.py shrink --schedule /tmp/failing-schedule.json --backend memory
```

The generated schedule covers pre- and post-commit crashes, ambiguous commits, duplicate
delivery, lease expiry and stale-worker mutation, wait/signal ordering, cancellation, checkpoint
corruption, provider timeout, privacy rejection, replay verification, cursor gaps, and
compaction recovery. SQLite/WAL and memory explicitly report distributed-only actions as
unsupported degradation; etcd must execute those actions. Backend comparison checks canonical
history, terminal state, effect and receipt projections, action outcomes, and privacy evidence.

The bounded release corpus is the promoted seed set `6601`, `6602`, and `6603`:

```bash
python3 scripts/forge-chaos.py corpus --output /tmp/forge-chaos-corpus.json
```

When a schedule fails, retain the schedule JSON and its digest-only result as regression evidence.
Run `shrink` against the failing backend, review the minimized schedule, then promote its seed or
schedule reference into the corpus and conformance evidence. A minimized schedule must preserve
the same failure class. An `expected_failure` predicate can scope a regression to a backend and
failure class; a missing or changed failure is reported as `expected_failure_mismatch` with
digest-only evidence. CI remains bounded and deterministic; the corpus is high-signal coverage,
not a claim of exhaustive interleavings. See
[`data/runtime-chaos-schedule.schema.json`](../data/runtime-chaos-schedule.schema.json),
[`data/runtime-chaos-result.schema.json`](../data/runtime-chaos-result.schema.json), and
[`data/runtime-chaos-corpus.schema.json`](../data/runtime-chaos-corpus.schema.json).

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

Deterministic model routing is documented in [`docs/routing.md`](routing.md) and exposed through
`scripts/forge-routing.py`. Capability and policy constraints filter routes before scoring;
static decisions remain the live default, and adaptive decisions fail closed until an offline
replay satisfies its sample, confidence, regression, cost, failure, approval, and budget gates.
The portable backend contract is executable: `forge-backends.py` negotiates capabilities and
consistency, keeps Forge history canonical, normalizes remote metadata through a reference-only
evidence envelope, runs the same 12-case fixture matrix against the SQLite/WAL reference,
in-memory fault, and etcd-first facades, and adds a six-case distributed revision/watch matrix.

## Boundary

This is durable history plus an at-least-once external-effect protocol, not exactly-once
provider execution. SQLite can atomically persist the intent and receipt; only the adapter and
provider can make a retry harmless. A worker crash after a provider accepts an operation but
before Forge records the receipt is expected to produce a retry, which is why the stable
provider idempotency key is mandatory.
