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

## Canonical inputs

- `data/gh-aw-workflows.json` is the reviewed workflow specification.
- `data/runtime-gh-aw.schema.json` defines the adapter schema and pinned upstream contract.
- `data/runtime-gh-aw-episode.schema.json` defines the privacy-safe durable episode projection.
- `policies/gh-aw.json` constrains the external effect boundary.
- `plugins/forge/skills/orchestration/scripts/forge-gh-aw.py` owns validation and rendering.
- `plugins/forge/skills/orchestration/scripts/forge-gh-aw-runtime.py` binds staged effects to the
  Forge SQLite/WAL runtime without calling GitHub.

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
current lease immediately before the provider call, submits the provider idempotency key, and
acknowledges a bounded receipt. Then the worker lifecycle is recorded with `worker-start`,
`worker-complete` or `worker-fail`; safe outputs are claimed and acknowledged through the same
outbox. Repeating an accepted transition with the same identity is idempotent. Stale leases,
conflicting receipts, undeclared workers, source drift, terminal episodes, and unapproved effects
fail closed. `finish` requires all tasks and effects to succeed; `cancel` records durable request,
acknowledgement, and terminal cancellation events and fences further claims.

The projection returned by `inspect` is defined by
[`data/runtime-gh-aw-episode.schema.json`](../data/runtime-gh-aw-episode.schema.json). It contains
digests, task/effect summaries, provider reference IDs, and receipt digests, not raw outbox
payloads or receipt bodies. The bridge is the Forge runtime boundary; a future provider adapter
can perform the live GitHub operation without becoming a second source of truth.
