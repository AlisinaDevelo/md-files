---
name: orchestration
description: >-
  Use when driving a large, multi-part task end to end with multiple models —
  planning at a high tier, decomposing into a task ledger, and delegating each piece
  to the right specialist at the right model (plan with Opus/Fable, implement with
  Sonnet, mechanical work with Haiku). Covers the conductor loop and how to delegate.
  See MODEL-ROUTING.md for the tier policy.
---

# Orchestration

Orchestration is running a big goal as a *conductor*: you plan and decompose at a strong
model, then hand each concrete piece to the specialist and model tier that fits it, run the
pieces (in parallel where they're independent), and integrate the results. The win is using
an expensive model only where it pays and a cheap fast one everywhere else.

## The one architectural fact that shapes everything

**Only the main conversation can spawn subagents; a subagent cannot spawn its own
subagents.** So orchestration is driven from the *main loop* — via `/orchestrate` or by you
acting as the conductor directly — not by delegating "be the orchestrator" to one subagent
(that subagent could only work sequentially by itself). Plan at the main model's tier (set
it to Opus or Fable for hard planning), then delegate outward.

## The conductor loop

1. **Plan at a high tier.** Restate the goal and definition of done, surface hidden
   requirements, and design the approach. This is the expensive thinking — do it once, well,
   at Opus/Fable.
2. **Decompose into a task ledger.** Break the goal into concrete, independently-verifiable
   tasks with explicit acceptance criteria and dependencies. Use the `task-ledger` skill for
   the format (local issue files, or `gh`/MCP-backed issues).
3. **Choose the review topology.** If the implementation is too large for one reviewable
   PR and has a clean dependency order, design a stacked change with the `stacked-changes`
   skill. Keep task dependencies in the ledger and branch ancestry in `.forge/stack.json`.
4. **Route each task to a tier + specialist.** Assign per the `MODEL-ROUTING.md` policy:
   architecture/gnarly debugging → Opus/Fable; implementation, tests, docs → Sonnet;
   mechanical/parallel-cheap (renames, boilerplate, wide search) → Haiku. Match the task to
   the specialist agent (`test-engineer`, `refactoring-specialist`, `security-auditor`, …).
5. **Dispatch — parallel where independent.** Spawn each ready task as a subagent with an
   explicit `model` override and a self-contained brief (see below). Independent tasks go in
   one turn so they run concurrently; dependent tasks wait for their blocker.
6. **Integrate and verify against acceptance criteria.** A subagent's summary is its
   *intent*, not proof — confirm each result against the actual diff/tests/output before
   marking the task done. Keep the pieces coherent (consistent conventions, interfaces line
   up).
7. **Iterate to done.** Update the ledger, pick the next ready tasks, repeat until the
   ledger is empty or genuinely blocked. See the `iterate-to-done` skill for the loop and
   stop conditions.

## Durable execution history

When an orchestration run must survive a process boundary, use the local runtime store at
`scripts/forge-runtime.py`. Start with a pinned workflow definition and policy revision,
append lifecycle events with idempotency keys, and query state by replaying the verified
event history. The store is SQLite/WAL and local-first; its hash chain detects tampering and
its reducer rejects impossible transitions.

Keep the boundaries distinct: `scripts/forge-receipts.py` is privacy-safe observability,
`.forge/tasks/` is planning state, and the runtime database is execution state. Do not put
prompts, raw tool arguments/results, credentials, or tokens in runtime payloads; persist
references and digests instead. Append an effect descriptor with the event that schedules an
external operation when possible: the local runtime commits the event and outbox intent
atomically, derives stable effect/provider idempotency identifiers, and records leases,
attempts, retries, dead letters, and deduplicated inbox receipts. Each lease claim carries a
monotonic generation; heartbeat, provider submission authorization, acknowledgement, and
failure must present the current worker plus generation. Delivery is at-least-once; the
adapter must make the provider operation idempotent, and durable history never claims
exactly-once provider execution. Inspect lease evidence with the runtime `lease-events`
command when diagnosing stale workers or reclaim races. At verified workflow boundaries,
persist a checkpoint and use `restore` to validate it and replay only the verified event
suffix. Treat unknown runtime, workflow, definition, policy, or checkpoint revisions as
migration errors; inspect with `migrations --dry-run` and preserve a verified backup before
applying a reviewed migration. To pause for human input, use the runtime `wait` command: it
checkpoints before `wait.created`, binds the input schema and authorization context by digest,
and persists TTL, polling, expiry policy, and a bounded resume contract. Accept only one
matching `submit-input`; use `signal` for ordered reference-only notifications. Cancellation
is a three-event request/acknowledgement/terminal protocol, and the MCP Tasks view in
`scripts/forge-mcp-tasks.py` maps task IDs, status, TTL, polling, result references, and
cancellation back to Forge history without becoming a second source of truth.

Pin every run to an immutable definition descriptor before dispatch: workflow and definition
version, workflow code/schema digests, worker/build identity, policy and feature-flag digests,
compatibility revision, and stable-step identity revision. `run.started` repeats the descriptor
identity inside the hash chain. Inspect it with `python3 scripts/forge-runtime.py definition
--run-id RUN_ID`; preflight a candidate with `compatibility --operation
replay|checkpoint_restore|migration|effect_retry|continue_as_new`. Workers should pass that same
candidate descriptor to `claim_outbox(..., definition_descriptor=...)` before a retry lease is
changed. Inspect an offline alias registry with `rollout --registry-json REGISTRY --reference
ALIAS`. Aliases may redirect or roll back new runs, but in-flight runs stay pinned. A changed
descriptor is accepted only when it is exact, explicitly declares the pinned digest compatible,
or crosses an explicit continue-as-new boundary. The reviewed v3-to-v4 migration synthesizes a
legacy descriptor for old histories without rewriting their canonical event rows.

Derive stable step and operation identities with the definition contract helpers; do not include
timestamps, randomness, prompts, credentials, or provider responses in those identities. A
definition digest is an identity and compatibility gate, not a claim of exactly-once provider
execution.

When a run needs a different storage implementation, negotiate the backend contract before
starting it with `scripts/forge-backends.py`. The descriptor is capability- and consistency-
aware; unsupported guarantees fail closed, while an explicitly allowed degraded result carries
only a digest reference. The SQLite/WAL adapter is the durable reference. The in-memory fault
adapter is useful for deterministic crash, duplicate-delivery, and ambiguous-commit fixtures.
Run the same offline matrix against both adapters before accepting a new implementation:

```bash
python3 scripts/forge-backends.py describe --backend sqlite
python3 scripts/forge-backends.py negotiate --backend memory \
  --requirements-json '{"capabilities":["fenced_leases"],"consistency_level":"strict_serializable"}'
python3 scripts/forge-backends.py conformance --backend all
```

For a distributed revision and watch contract, negotiate every guarantee before starting a
run and execute the deterministic etcd-first matrix:

```bash
python3 scripts/forge-backends.py describe --backend etcd
python3 scripts/forge-backends.py negotiate --backend etcd \
  --requirements-json '{"required_capabilities":["remote_revisions","watch_delivery","snapshot_recovery","compaction_recovery","fenced_leases"],"consistency_level":"strict_serializable"}'
python3 scripts/forge-backends.py watch-conformance --backend etcd
```

The etcd facade keeps canonical Forge transitions in strict-serializable runtime storage and
models remote revisions, watch delivery, reconnects, and compaction as provider-neutral evidence.
It is a deterministic offline contract test, not a claim that a live etcd cluster is available.
Normalize notifications into `forge-distributed.py` before observation: sort and deduplicate by
remote revision and canonical event reference, reject gaps, stale cursors, foreign watch IDs,
tampered cursors, and raw CloudEvent data. Observation may advance only its verified cursor
evidence; it must not mutate canonical Forge history. After compaction or cursor loss, restore a
digest-verified snapshot and replay the contiguous suffix, or fail closed.

The offline matrix models a dedicated Forge event stream. A live etcd watch must define its key
range and use progress/revision evidence because etcd revisions are cluster-wide; unrelated writes
can create numeric gaps in a filtered watch. Never treat an unexplained gap as harmless.

Treat remote revision numbers, transaction IDs, watch cursors, compaction markers, and
CloudEvents as reference-only metadata. CloudEvents use `source` plus `id` for identity and keep
payloads behind `data_ref`; see the [CloudEvents specification](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md).
The [etcd API guarantees](https://etcd.io/docs/v3.7/learning/api_guarantees/) and
[watch/compaction guidance](https://etcd.io/docs/v3.7/dev-guide/interacting_v3/) are provider
semantics that the adapter must verify, not silently assume.

Remote revisions, transaction IDs, watch cursors, compaction markers, and CloudEvents belong
in the reference-only envelope returned by `adapter_evidence`; its schema is
`data/runtime-backend-evidence.schema.json`. Forge event IDs, sequence numbers, hash-chain
parents, leases, and provider idempotency remain canonical. The contract promises at-least-once
delivery with idempotent effects, never exactly-once provider execution.

For deterministic race coverage, use the chaos schedule harness. It is seedable and offline: the
schedule contains symbolic faults and references only, while the runner drives the real backend
adapters and compares canonical history, outcomes, receipts, and privacy evidence. Keep the CI
corpus bounded; a passing seed set is evidence, not an exhaustive interleaving proof. Retain a
failing schedule and digest-only result, then shrink it before promoting the minimized seed into
regression evidence. Backend-scoped `expected_failure` predicates are enforced during replay;
missing or changed failure classes fail closed with digest-only mismatch evidence:

```bash
python3 scripts/forge-chaos.py generate --seed 6601 --output /tmp/forge-schedule.json
python3 scripts/forge-chaos.py run --schedule /tmp/forge-schedule.json --backend all
python3 scripts/forge-chaos.py shrink --schedule /tmp/failing-schedule.json --backend memory
python3 scripts/forge-chaos.py corpus
```

## Deterministic model routing

Use the routing contract when a workflow has more than one provider/model route. Capability and
policy constraints are evaluated before scoring: required tools, structured output, context
window, modality, host, region, data policy, replay safety, pins, and budgets can only exclude a
route, never be outweighed by a score. The decision record contains candidate status, exclusion
reason, score source, fallback plan, budget state, policy revision, request digest, and outcome
evidence digests. Raw prompts, tool content, credentials, and provider bodies are rejected at the
boundary.

Live decisions are deterministic static decisions by default. An adaptive policy fails closed in
`decide` until an offline replay proves its minimum-sample, confidence, quality-regression, cost,
failure, approval-burden, and replay-budget gates. Pin a provider, model, or route per workflow;
set `disable_adaptation` for an individual request when a workflow requires static behavior.
Replay is an offline comparison only and does not mutate policy or activate itself:

```bash
python3 scripts/forge-routing.py inspect --policy POLICY.json
python3 scripts/forge-routing.py decide --policy POLICY.json --request REQUEST.json
python3 scripts/forge-routing.py replay \
  --baseline-policy BASELINE.json \
  --candidate-policy CANDIDATE.json \
  --episodes EPISODES.json
```

Issue a reviewed, digest-bound rollout certificate before enabling adaptive decisions. Preview,
canary, active, rollback, and retired stages are explicit; canary cohorts are derived from the
request digest and outside requests fall back to static scoring. The default adaptive `decide`
path remains denied without an activated certificate:

```bash
python3 scripts/forge-routing.py activate \
  --baseline-policy BASELINE.json \
  --candidate-policy CANDIDATE.json \
  --episodes EPISODES.json \
  --rollout ROLLOUT.json \
  --output ROUTING-CERTIFICATE.json
python3 scripts/forge-routing.py decide \
  --policy CANDIDATE.json \
  --request REQUEST.json \
  --certificate ROUTING-CERTIFICATE.json
```

See `docs/routing.md` and the versioned contracts in `data/runtime-routing-*.schema.json` for
the input and output shapes. Replay evidence is numeric and digest-only; an agent's confidence
field is never accepted as ground-truth quality.

## GitHub Agentic Workflows

Use the bounded `forge-gh-aw-v1` adapter when a Forge workflow needs a GitHub Agentic
Workflows projection. The adapter validates the canonical capability graph, pins the upstream
`gh aw` compiler, rejects dispatcher cycles and protected-file writes, and turns every external
operation into a staged policy effect. The agent job stays read-only; safe outputs are the only
mutation boundary.

Inspect and compile from the repository root:

```bash
python3 scripts/forge-gh-aw.py plan --spec data/gh-aw-workflows.json --json
python3 scripts/forge-gh-aw.py compile --spec data/gh-aw-workflows.json --output build/gh-aw
python3 scripts/forge-gh-aw.py check --spec data/gh-aw-workflows.json --output build/gh-aw
```

The default lock is an offline contract preview and stops before mutation. Install the exact
upstream extension and add `--upstream` to produce native locks. Native locks can contain
known upstream provider/auth secret names, but Forge never commits their values and rejects
unknown references. Read [GitHub Agentic Workflows](../../../../docs/gh-aw.md) for the full
contract, release surface, and runtime integration boundary.

### Durable gh-aw episodes

Bind a dispatcher to the Forge SQLite/WAL runtime when the workflow must survive process
boundaries. The bridge pins the compiled gh-aw manifest and Forge definition, stages one
approval-gated dispatch effect per declared worker, and exposes only digest/reference receipts
at the provider boundary:

```bash
python3 scripts/forge-gh-aw-runtime.py start \
  --dispatcher forge-dispatcher \
  --request-digest sha256:REQUEST_DIGEST
python3 scripts/forge-gh-aw-runtime.py dispatch \
  --dispatcher forge-dispatcher --episode-id EPISODE_ID \
  --request-digest sha256:REQUEST_DIGEST
python3 scripts/forge-gh-aw-runtime.py claim \
  --dispatcher forge-dispatcher --episode-id EPISODE_ID \
  --worker-id gh-aw-provider --limit 4
```

After the provider verifies the approval and performs its idempotent GitHub operation, acknowledge
the lease with `ack --receipt-json`, then record `worker-start`, `worker-complete` or
`worker-fail`. Claim and acknowledge worker safe outputs through the same outbox; use `finish`
only after every task and effect gate passes, or `cancel` for the durable request/acknowledgement/
terminal cancellation protocol. `inspect` returns the privacy-safe projection defined by
`data/runtime-gh-aw-episode.schema.json`; it never includes effect payloads or raw provider
receipts. The bridge is local-first and does not call GitHub itself.

For a live GitHub effect, keep the secret-free request envelope outside runtime history and use
the fenced provider stages. Planning is no-effect; approval is one-use and bound to the exact
effect/request/operation digests; execution additionally requires the expected `gh` login and an
explicit flag:

```bash
python3 scripts/forge-gh-aw-provider.py plan \
  --request REQUEST.json --effect-id EFFECT_ID \
  --worker-id gh-aw-provider --lease-generation GENERATION
python3 scripts/forge-gh-aw-provider.py approve \
  --request REQUEST.json --effect-id EFFECT_ID \
  --worker-id gh-aw-provider --lease-generation GENERATION
python3 scripts/forge-gh-aw-provider.py execute \
  --request REQUEST.json --effect-id EFFECT_ID \
  --worker-id gh-aw-provider --lease-generation GENERATION \
  --approval-id APPROVAL_ID --expected-login LOGIN --execute
```

The provider supports only the four compiled safe-output types. It revalidates title/label,
comment, dispatch, and PR file constraints, compares PR head/file evidence immediately before
creation, asks the current GitHub API for workflow-dispatch run details, and writes only bounded
authorization/receipt evidence to its 0600 hash-chained journal. Never retry an ambiguous
dispatch blindly; reconcile it first. The contract is at-least-once with idempotent recovery,
not exactly-once provider execution. See `data/runtime-gh-aw-provider-request.schema.json` and
[GitHub Agentic Workflows](../../../../docs/gh-aw.md).

## How to delegate well (this makes or breaks it)

When you spawn a specialist subagent, set two things deliberately:

- **The model** — pass a `model` override on the delegation (`haiku`/`sonnet`/`opus`/
  `fable`) chosen from the routing policy, so the tier matches the task, not the default.
- **The brief** — write it for a colleague who just walked in: the goal and *why*, what
  you've ruled out, the exact files/lines and acceptance criteria, and the response length
  you want. Never delegate understanding ("based on your findings, fix it" produces shallow
  work). Give lookups the exact command; give investigations the question.

Run independent specialists **in parallel** (multiple delegations in one turn) and **trust
but verify** every summary.

## When NOT to orchestrate

Orchestration has overhead (planning, ledger, delegation round-trips). For a single-file
change or a task under ~3 steps, just do it directly. Reach for the conductor loop when the
work is genuinely multi-part, spans specialties, or benefits from parallelism and mixed
model tiers.
