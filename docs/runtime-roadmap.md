# Runtime Roadmap

Last reviewed: 2026-08-05.

This roadmap is the execution plan for Forge's durable runtime. The event history is the
source of truth for a run; receipts, task ledgers, provider sessions, MCP Tasks, GitHub
workflows, and telemetry remain adapters or evidence surfaces.

## Baseline

- The merged transactional effect boundary from #53 is the baseline; the generation-fenced
  heartbeat slice in #54 and checkpoint recovery slice in #55 are now implemented on top of it.
- The local SQLite/WAL runtime has hash-chained events, deterministic replay, bounded
  lifecycle transitions, an atomic event-plus-outbox write, leases, retries, dead letters,
  inbox dedupe, and reference-only payload checks.
- The verifiable lineage and receipt-integrity slice in #56 is implemented and merged; it adds
  offline evidence verification without making telemetry the source of truth.
- The wait-aware runtime uses database schema v3; v2 checkpoints remain readable evidence but
  are excluded from restore until a v3 checkpoint is created after migration.
- The current release remains 3.6.0. The transactional effect boundary is documented under
  `Unreleased`; no new tag should claim it until release validation is repeated.
- The current stack delivery path already records head/base SHAs, guards mutations, handles
  Merge Queue observation, and receives `merge_group` CI checks. Stacked delivery is a
  maintained strength, not a missing parallel abstraction.

## Research decisions

| Area | Industry signal | Forge decision |
| --- | --- | --- |
| Activities and effects | Temporal and AWS assume retries or duplicate delivery and require idempotent activities, stable keys, and an atomic outbox boundary. | Keep at-least-once delivery explicit; make adapter idempotency and provider request references mandatory. |
| Worker ownership | Chubby uses a lock generation sequencer that protected services validate, closing the stale-client write window. | A lease claim must issue a monotonic generation or fencing token; owner and generation are required for heartbeat, completion, failure, and protected effect submission. |
| Recovery | LangGraph, Microsoft Agent Framework, and Dapr persist checkpoints and durable retry state, including successful work that can be resumed after a sibling failure. | Add hashed checkpoints, suffix replay, crash recovery, and reviewed fail-closed migrations before calling the runtime durable at scale. |
| Human interaction | MCP Tasks defines `input_required`, TTL, polling hints, cancellation, authorization binding, limits, and audit expectations; provider task state is not enough. | Model waits and signals in Forge history, then expose MCP Tasks as an adapter. |
| Evidence | OpenTelemetry provides versioned agent/workflow/tool vocabulary; W3C Trace Context carries portable correlation; SLSA and in-toto bind evidence to immutable subjects and resolved inputs. | Add a privacy-safe, digest-bound episode lineage and receipt verifier with pinned mappings, without replacing canonical history or GitHub release attestations. |
| GitHub delivery | GitHub Merge Queue validates checks on the latest target plus queued changes and requires `merge_group` reporting. | Preserve SHA-bound stack plans, queue-event correlation, explicit approval, and indeterminate stop states. |

## Release sequence

### Completed runtime slices

1. [#54 Heartbeats and stale-worker fencing](https://github.com/AlisinaDevelo/md-files/issues/54)
   This slice closes the zombie-worker gap in the existing outbox lease protocol with crash and
   race tests, schemas, CLI inspection, generation fencing, and policy-pinned timeout evidence.

2. [#55 Checkpointed recovery and migrations](https://github.com/AlisinaDevelo/md-files/issues/55)
   This slice binds reducer checkpoints to verified event heads, replays only validated suffixes,
   recovers from corrupt prefixes with privacy-safe references, and applies reviewed additive
   migrations with resumable evidence.

3. [#56 Verifiable execution lineage and receipt integrity](https://github.com/AlisinaDevelo/md-files/issues/56)
   This slice derives deterministic, privacy-safe evidence from canonical history and optional
   policy/receipt stores. Offline verification binds event parents, effect attempts, lease
   generations, adapter revisions, provider references, and receipt digests.

### In progress

1. [#57 Human-input waits, signals, and cancellation](https://github.com/AlisinaDevelo/md-files/issues/57)

This slice will make human interruption and cancellation durable, authorization-bound, and
replayable across process restart. Research is focused on MCP Tasks mapping, checkpoint-before-
interrupt semantics, deterministic expiry, and late-response races.

### Next runtime slices

1. [#58 Portable backend adapter and conformance](https://github.com/AlisinaDevelo/md-files/issues/58)

These issues are the minimum credible v4 runtime contract. They are intentionally separate:
recovery, evidence, interaction, and backend portability have different failure modes and
must remain independently reviewable.

### Later integrations

- [#21 GitHub Agentic Workflows](https://github.com/AlisinaDevelo/md-files/issues/21) comes
  after the runtime can correlate dispatch, workers, safe outputs, and replay.
- [#22 Adaptive model routing](https://github.com/AlisinaDevelo/md-files/issues/22) comes
  after outcome evidence, budgets, policy gates, and offline replay are trustworthy.
- [#8 Connected Control Plane](https://github.com/AlisinaDevelo/md-files/issues/8) and
  [#9 Evidence and Trust](https://github.com/AlisinaDevelo/md-files/issues/9) remain the
  compatibility and release tracks for GitHub synchronization, policy, attestations, and
  cross-host evidence.

## Release gates

Do not call the runtime v4-ready until the following are true:

- A killed worker cannot mutate an effect after reclaim, even when a delayed request arrives.
- A checkpoint plus suffix replay matches full replay, and corrupt or incompatible state
  fails closed with a reviewed migration path.
- Human waits, signals, cancellation, and late responses are deterministic and auditable.
- At least two backend implementations pass the same conformance fixtures, or the adapter
  capability report explicitly proves why a second backend is not yet available.
- Runtime evidence verifies offline without raw prompts, credentials, tool content, or
  provider response bodies.
- The exact release archive is reproducible, validated for Claude and Codex, and its
  artifact attestations verify against the intended source ref.
