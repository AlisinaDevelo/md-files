# Runtime Roadmap

Last reviewed: 2026-08-18.

The cross-project frontier priorities are tracked in the [frontier roadmap](frontier-roadmap.md).
This document remains the durable runtime plan; protocol, identity, evaluation, and release
attestation work must integrate through explicit adapters rather than replace runtime history.

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
- The wait-aware runtime now uses database schema v4; v2/v3 checkpoints remain readable evidence
  but are excluded from restore until a v4 checkpoint is created after migration. v3-to-v4 adds
  deterministic legacy definition descriptors without rewriting canonical event rows.
- The current release candidate is 3.7.0. The transactional effect boundary is documented
  under its release heading and must remain covered by the local release gate.
- The current stack delivery path already records head/base SHAs, guards mutations, handles
  Merge Queue observation, and receives `merge_group` CI checks. Stacked delivery is a
  maintained strength, not a missing parallel abstraction.

## Research decisions

| Area | Industry signal | Forge decision |
| --- | --- | --- |
| Activities and effects | Temporal and AWS assume retries or duplicate delivery and require idempotent activities, stable keys, and an atomic outbox boundary. | Keep at-least-once delivery explicit; make adapter idempotency and provider request references mandatory. |
| Worker ownership | Chubby uses a lock generation sequencer that protected services validate, closing the stale-client write window. | A lease claim must issue a monotonic generation or fencing token; owner and generation are required for heartbeat, completion, failure, and protected effect submission. |
| Recovery | LangGraph, Microsoft Agent Framework, and Dapr persist checkpoints and durable retry state, including successful work that can be resumed after a sibling failure. | Add hashed checkpoints, suffix replay, crash recovery, and reviewed fail-closed migrations before calling the runtime durable at scale. |
| Human interaction | The final MCP 2026-07-28 specification makes the core stateless and places long-running work in the Tasks extension, including `input_required`, TTL, polling hints, cancellation, and authorization expectations. | Keep waits and signals in Forge history; the versioned, digest-only adapter in [#85](https://github.com/AlisinaDevelo/md-files/issues/85) is now locally verified. |
| Evidence | OpenTelemetry provides versioned agent/workflow/tool vocabulary; W3C Trace Context carries portable correlation; SLSA and in-toto bind evidence to immutable subjects and resolved inputs. | Add a privacy-safe, digest-bound episode lineage and receipt verifier with pinned mappings, without replacing canonical history or GitHub release attestations. |
| GitHub delivery | GitHub Merge Queue validates checks on the latest target plus queued changes and requires `merge_group` reporting. | Preserve SHA-bound stack plans, queue-event correlation, explicit approval, and indeterminate stop states. |
| Definition rollout | AWS durable execution pins qualified versions and requires deterministic replay; Temporal uses worker-version compatibility and reachability signals. | Pin every run to an immutable definition/build digest; aliases affect new runs only, and incompatible replay fails closed or crosses an explicit continue-as-new boundary. |
| Distributed recovery | etcd separates strict-serializable transactions from watch delivery, revisions, and compaction behavior; revisions are cluster-wide and watches may be range-scoped. | Treat remote revisions as adapter evidence, define the watched Forge stream, persist cursors, recover from verified snapshots plus replay, and fail closed on unexplained gaps, cursor loss, or ambiguous boundaries. |
| Reliability testing | [FoundationDB simulation](https://apple.github.io/foundationdb/testing.html) makes entropy and faults replayable; [Jepsen linearizability](https://jepsen.io/consistency/models/linearizable) provides a correctness oracle for concurrent histories. | Add deterministic schedules, minimized counterexamples, invariant checks, and a bounded seed corpus before claiming backend portability at scale. |

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

4. [#57 Human-input waits, signals, and cancellation](https://github.com/AlisinaDevelo/md-files/issues/57)
   This slice adds checkpoint-before-input waits, digest-bound submissions and signals, explicit
   expiry outcomes, sticky cancellation evidence, and an MCP Tasks projection over Forge state.

5. [#58 Portable backend adapter and conformance](https://github.com/AlisinaDevelo/md-files/issues/58)
   This slice makes backend portability a negotiated semantic contract rather than a shared CRUD
   interface. Both the SQLite/WAL reference backend and deterministic in-memory fault backend pass
   the same 12-case matrix, including ambiguous commits, adapter evidence, restore, migration,
   and privacy boundaries.

6. [#68 Workflow definition versioning and replay compatibility](https://github.com/AlisinaDevelo/md-files/issues/68)
   This slice pins workflow code/schema, worker builds, policy and feature-flag decisions to an
   immutable descriptor. Replay, restore, migration, and effect retry fail closed unless the
   candidate declares compatibility; aliases affect new runs only, with offline canary, redirect,
   rollback, retirement, and continue-as-new evidence.

7. [#67 Distributed revision/watch recovery](https://github.com/AlisinaDevelo/md-files/issues/67)
   This slice adds an etcd-first backend facade with explicit remote revision, watch, snapshot,
   and compaction capabilities. It verifies watch identity and CloudEvent metadata, rejects gaps,
   stale cursors, conflicting duplicates, raw payloads, and compaction ambiguity, and recovers
   from digest-verified snapshots plus contiguous replay. The shared backend matrix remains
   `12/12`, and the distributed matrix adds `6/6` deterministic cases.

8. [#65 Signed trace-context and provenance bridge](https://github.com/AlisinaDevelo/md-files/issues/65)
   This slice adds stable W3C trace correlation, pinned OpenTelemetry mappings, digest-only
   privacy defaults, an offline HMAC-signed in-toto/SLSA-shaped subject envelope, trust-policy
   rotation and revocation, and tamper/reproducibility fixtures without mutating runtime state.

9. [#66 Deterministic chaos and schedule shrinking](https://github.com/AlisinaDevelo/md-files/issues/66)
   This slice adds a seedable, digest-only schedule DSL and offline runner for the SQLite/WAL,
   memory-fault, and etcd-first facades. It exercises commit crashes, ambiguous commits, duplicate
   delivery, fencing, waits/signals, cancellation, checkpoint corruption, provider timeouts,
   privacy boundaries, replay, cursor gaps, and compaction recovery. Delta-debugging preserves a
   classified failure while removing irrelevant actions, and the bounded corpus promotes seeds
   `6601`, `6602`, and `6603` into CI evidence.

### Next runtime slices

These issues are the minimum credible v4 runtime contract. They are intentionally separate:
recovery, evidence, interaction, and backend portability have different failure modes and
must remain independently reviewable.

The currently tracked runtime slices are complete; the later integrations below remain
intentionally separate from the local-first runtime contract.

### Frontier handoff

The next release lane is deliberately outside the completed runtime baseline:

- [#85 MCP Tasks adapter](https://github.com/AlisinaDevelo/md-files/issues/85) is locally complete,
  including v2 per-request capability admission
  at the reference-only contract boundary. A live protocol claim still requires separate hosted
  transport and discovery evidence.
- [#86 release attestations](https://github.com/AlisinaDevelo/md-files/issues/86) now verifies
  portable DSSE/SLSA v1.2 statements with explicit public-key, local-HMAC, and GitHub evidence
  profiles without overstating local HMAC evidence as public-key provenance.
- [#87 trajectory evaluations](https://github.com/AlisinaDevelo/md-files/issues/87) now has a
  verified digest-only corpus contract; deterministic safety and replay checks stay ahead of
  optional model-based judging.
- [#88 delegated authority](https://github.com/AlisinaDevelo/md-files/issues/88) now has a locally
  verified `forge-authority-v1` contract binding identity, policy revision, approval, worker
  lease, action, runtime, provider, and provenance. Connected execution remains opt-in until a
  host adapter supplies and verifies its authentication/proof-of-possession boundary.

No hosted MCP server or external control plane is required for the current runtime release.

### Later integrations

- [#21 GitHub Agentic Workflows](https://github.com/AlisinaDevelo/md-files/issues/21) now has a
  pinned `forge-gh-aw-v1` adapter with deterministic sources, preview locks, policy-gated
  effects, protected-path validation, a hosted gate for pinned native upstream compilation and
  byte-identical reruns, structural permission and supply-chain admission, a pinned native job
  graph, a digest-only native execution admission certificate, a fenced provider worker, and
  operator-confirmed dispatch reconciliation, certificate-bound worker handoff, and
  generation-fenced provider lease supervision. Live execution remains opt-in; the remaining
  work is production deployment and an external durable control plane rather than treating the
  workflow lock as canonical history.
- [#22 Adaptive model routing](https://github.com/AlisinaDevelo/md-files/issues/22) now has a
  deterministic capability filter, digest-only decision contract, pins/budgets/fallbacks, and
  offline replay gate. Live adaptive activation and provider integrations remain gated follow-up
  work after this foundation is reviewed.
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
