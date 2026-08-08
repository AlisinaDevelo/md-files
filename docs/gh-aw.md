# GitHub Agentic Workflows

Forge includes a bounded adapter for GitHub Agentic Workflows (gh-aw). It projects the
canonical Forge capability graph and workflow metadata into deterministic Markdown sources,
policy-gated effect plans, and lock files that can be compiled by a pinned upstream `gh aw`
extension.

The adapter is intentionally a contract boundary. It does not turn a local workflow
description into permission to mutate GitHub, and it never stores secret values.

## Compile

From the repository root:

```bash
python3 scripts/forge-gh-aw.py plan --spec data/gh-aw-workflows.json --json
python3 scripts/forge-gh-aw.py compile \
  --spec data/gh-aw-workflows.json \
  --output build/gh-aw
python3 scripts/forge-gh-aw.py check \
  --spec data/gh-aw-workflows.json \
  --output build/gh-aw
```

The default compiler emits an offline contract preview. Its safe-output job stops before
mutation, so the preview cannot be mistaken for a production effect processor. For native
gh-aw locks, install the exact pinned extension and pass `--upstream`:

```bash
gh extension install github/gh-aw --pin v0.85.4
python3 scripts/forge-gh-aw.py compile \
  --spec data/gh-aw-workflows.json \
  --output build/gh-aw-native \
  --upstream
python3 scripts/forge-gh-aw.py check \
  --spec data/gh-aw-workflows.json \
  --output build/gh-aw-native
```

Native compilation follows the upstream [gh-aw compilation process](https://github.github.com/gh-aw/reference/compilation-process/)
and keeps the pinned version and commit in the generated manifest. The generated source uses
the upstream Markdown frontmatter contract, while Forge adds capability digests, bounded
dispatch declarations, protected-path checks, and policy evidence.

Hosted CI runs the native command in a temporary runner directory through the `gh-aw-native`
job. The verifier requires the exact Forge source and definition digests, upstream compiler
version and schema metadata, strict compilation, a SHA-pinned action manifest, and a complete
artifact inventory. This gate compiles and checks locks only; it does not dispatch a workflow,
approve a safe output, or publish generated files.

## Safety boundary

- Agent jobs receive read-only GitHub permissions. Forge rejects generated locks that grant
  `contents`, `issues`, `pull-requests`, or `actions` write permission to the agent job.
- Mutations are represented only as declared gh-aw safe outputs and are included in a staged
  Forge effect plan that must remain `require_approval` under `policies/gh-aw.json`.
- The fallback lock is preview-only and exits before mutation. Native execution requires the
  pinned upstream processor and its own safe-output runtime.
- Native gh-aw locks may contain names of upstream provider/auth secrets needed at runtime.
  Forge permits only the known upstream names, never values, and rejects unknown references.
- Definition, graph, source, effect-set, episode, and idempotency digests make source-to-lock
  drift and replay identity inspectable without persisting prompts or provider responses.
- The optional Forge provider worker is no-effect by default. Live execution requires the
  current fenced lease, an exact one-use approval, an expected authenticated GitHub login, and
  an explicit `--execute` acknowledgement.

## Canonical inputs

- `data/gh-aw-workflows.json` is the reviewed workflow specification.
- `data/runtime-gh-aw.schema.json` defines the adapter schema and pinned upstream contract.
- `data/runtime-gh-aw-episode.schema.json` defines the privacy-safe durable episode projection.
- `data/runtime-gh-aw-provider-request.schema.json` defines the secret-free provider envelope.
- `policies/gh-aw.json` constrains the external effect boundary.
- `plugins/forge/skills/orchestration/scripts/forge-gh-aw.py` owns validation and rendering.
- `plugins/forge/skills/orchestration/scripts/forge-gh-aw-runtime.py` binds staged effects to the
  Forge SQLite/WAL runtime without calling GitHub.
- `plugins/forge/skills/orchestration/scripts/forge-gh-aw-provider.py` plans, approves, executes,
  and acknowledges the four compiled GitHub safe-output types.

The workflow examples cover a staged dispatcher, issue triage, CI diagnosis, documentation
maintenance, and bounded feature planning. They are examples and contract fixtures; they do
not authorize themselves.

## Durable runtime bridge

The bridge binds one `forge-dispatcher` invocation to a durable Forge episode. It pins the
compiled manifest and runtime definition, derives a stable `gh-aw:` episode ID, schedules one
approval-gated outbox intent per declared worker, and correlates worker tasks, safe outputs, and
reference-only provider receipts. It is intentionally local-first: it does not call GitHub or
store provider bodies, prompts, credentials, or tokens.

```bash
python3 scripts/forge-gh-aw-runtime.py start \
  --dispatcher forge-dispatcher \
  --request-digest sha256:REQUEST_DIGEST
python3 scripts/forge-gh-aw-runtime.py dispatch \
  --dispatcher forge-dispatcher --episode-id EPISODE_ID \
  --request-digest sha256:REQUEST_DIGEST
python3 scripts/forge-gh-aw-runtime.py inspect \
  --dispatcher forge-dispatcher --episode-id EPISODE_ID
```

The provider loop claims the outbox with a lease, verifies the external approval, authorizes the
current lease immediately before the provider call, submits stable idempotency evidence, and
acknowledges a bounded receipt. Then the worker lifecycle is recorded with `worker-start`,
`worker-complete` or `worker-fail`; safe outputs are claimed and acknowledged through the same
outbox. Repeating an accepted transition with the same identity is idempotent. Stale leases,
conflicting receipts, undeclared workers, source drift, terminal episodes, and unapproved effects
fail closed. `finish` requires all tasks and effects to succeed; `cancel` records durable request,
acknowledgement, and terminal cancellation events and fences further claims.

The projection returned by `inspect` is defined by
[`data/runtime-gh-aw-episode.schema.json`](../data/runtime-gh-aw-episode.schema.json). It contains
digests, task/effect summaries, provider reference IDs, and receipt digests, not raw outbox
payloads or receipt bodies. The bridge remains the Forge runtime boundary; the provider worker
does not become a second source of truth.

## Fenced provider worker

The `forge-gh-aw-provider-v1` worker consumes a request file separately from runtime history.
`request_ref` is the SHA-256 digest of the canonical `repository`, `workflow_id`,
`safe_output_type`, and `operations` object. The envelope repeats episode and workflow identity,
but raw titles, bodies, inputs, and changed-file lists remain outside the runtime database,
approval store, receipts, and CLI plan output. Dispatch envelopes cover every compiled target
exactly once; each leased dispatch effect selects only its declared worker.

After `claim` returns an effect ID and lease generation, run the local stages in order:

```bash
python3 scripts/forge-gh-aw-provider.py plan \
  --request /secure/path/provider-request.json \
  --effect-id EFFECT_ID --worker-id gh-aw-provider --lease-generation GENERATION

python3 scripts/forge-gh-aw-provider.py approve \
  --request /secure/path/provider-request.json \
  --effect-id EFFECT_ID --worker-id gh-aw-provider --lease-generation GENERATION \
  --ttl-seconds 600

python3 scripts/forge-gh-aw-provider.py execute \
  --request /secure/path/provider-request.json \
  --effect-id EFFECT_ID --worker-id gh-aw-provider --lease-generation GENERATION \
  --approval-id APPROVAL_ID --expected-login AlisinaDevelo --execute

python3 scripts/forge-gh-aw-provider.py reconcile \
  --request /secure/path/provider-request.json \
  --effect-id EFFECT_ID --worker-id gh-aw-provider --lease-generation GENERATION \
  --approval-id APPROVAL_ID --expected-login AlisinaDevelo --run-id RUN_ID --reconcile
```

`plan` performs no provider call and does not consume an approval. `approve` binds one short-lived
use to the exact effect, request reference, sanitized operation digests, repository, paths, and
policy revision. `execute` first verifies `gh api user`, then rechecks the lease and policy before
calling a bounded REST endpoint. Issue and comment limits, configured title prefixes and labels,
dispatch allowlists, and pull-request file scope are enforced again outside the agent process.
Pull requests also compare the planned head SHA and complete changed-file set immediately before
creation. Workflow dispatch requests ask GitHub to return the run ID and URLs for a direct receipt.
If a dispatch is accepted but its run details are lost before the provider journal is written, use
`reconcile` with the operator-supplied run ID. It performs one read-only run lookup, requires the
compiled lock workflow, `workflow_dispatch` event, requested ref, repository URL, and run ID to
match, then records the normal bounded receipt. It never infers dispatch inputs from run metadata.

The 0600 provider journal is append-only and hash-chained. It records only authorization digests,
approval handles, and bounded receipts, allowing a retry to close the post-write/pre-acknowledgement
window without repeating the provider call. A dispatch crash before its returned run details are
journaled remains ambiguous and fails closed until this explicit reconciliation step. Forge promises
at-least-once delivery with idempotent recovery where GitHub exposes enough evidence; it does not
claim exactly-once provider execution.
