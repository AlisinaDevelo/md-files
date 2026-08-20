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

Hosted CI runs the native command twice in isolated runner directories through the `gh-aw-native`
job and requires the complete artifact trees to be byte-identical. The verifier requires the exact
Forge source and definition digests, an empty top-level permission map, a read-only agent job,
write permission only in the upstream safe-output/conclusion boundary, upstream compiler version
and schema metadata, strict compilation, complete SHA coverage for emitted actions, digest-bound
upstream containers, the pinned native job dependency graph, and a complete artifact inventory.
This gate compiles and checks locks only; it does not dispatch a workflow, approve a safe output,
or publish generated files.

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
- The reviewed AWF policy binds allowed domains, blocked domains, HTTPS URL patterns, firewall
  log level, sandbox mode, and a redact-or-reject content-integrity decision to a policy digest.
  Disabled sandbox/firewall mode requires a literal operator justification and never carries URL
  filtering configuration.
- The optional Forge provider worker is no-effect by default. Live execution requires the
  current fenced lease, an exact one-use approval, an expected authenticated GitHub login, and
  an explicit `--execute` acknowledgement.
- A connected host may add a digest-only host admission proof. Forge checks its audience,
  resource, scope, lifetime, generation, nonce, and effect bindings; the host remains
  responsible for validating OAuth, DPoP, mTLS, SPIFFE, or JWS cryptography.

## Canonical inputs

- `data/gh-aw-workflows.json` is the reviewed workflow specification.
- `data/runtime-gh-aw.schema.json` defines the adapter schema and pinned upstream contract.
- `data/runtime-gh-aw-firewall.schema.json` defines the normalized AWF admission policy.
- `data/runtime-gh-aw-episode.schema.json` defines the privacy-safe durable episode projection.
- `data/runtime-gh-aw-admission.schema.json` defines the digest-only native execution admission certificate.
- `data/runtime-host-admission.schema.json` defines the digest-only host-authenticated admission proof.
- `data/runtime-gh-aw-provider-request.schema.json` defines the secret-free provider envelope.
- `plugins/forge/skills/orchestration/scripts/forge_gh_aw_firewall.py` normalizes the offline AWF
  admission policy and emits its deterministic digest.
- `policies/gh-aw.json` constrains the external effect boundary.
- `plugins/forge/skills/orchestration/scripts/forge-gh-aw.py` owns validation and rendering.
- `plugins/forge/skills/orchestration/scripts/forge-gh-aw-runtime.py` binds staged effects to the
  Forge SQLite/WAL runtime without calling GitHub.
- `plugins/forge/skills/orchestration/scripts/forge-gh-aw-provider.py` plans, approves, executes,
  and acknowledges the four compiled GitHub safe-output types.

The workflow examples cover a staged dispatcher, issue triage, CI diagnosis, documentation
maintenance, and bounded feature planning. They are examples and contract fixtures; they do
not authorize themselves.

## AWF admission policy

`defaults.firewall_policy` in `data/gh-aw-workflows.json` is the single reviewed egress policy.
The normalizer accepts only known AWF ecosystem identifiers or safe domain patterns, rejects
credentials and expressions, rejects insecure URL patterns, and requires `ssl_bump` for
path-scoped HTTPS allowlists. Its content-integrity contract permits only `redact` or `reject`
for untrusted content; there is no silent allow mode.

The compiler emits the normalized policy into the source and offline lock frontmatter. Every
manifest carries `firewall_policy_digest`. Native preflight certificates repeat the policy,
source, and lock digests. Provider request files must repeat the target workflow's evidence:

```json
{
  "contract_evidence": {
    "revision": "forge-gh-aw-firewall-v2",
    "firewall_policy_digest": "sha256:...",
    "source_digest": "sha256:...",
    "lock_digest": "sha256:..."
  },
  "contract_evidence_ref": "sha256:..."
}
```

`contract_evidence_ref` is the digest of the evidence object. The provider compares all three
digests with the compiled manifest before authorizing a lease, and includes the evidence
reference in the host provider-operation binding and execution digest. This is offline evidence;
Forge does not execute AWF, inspect HTTPS traffic, fetch content, or contact a provider here.
The policy shape follows the upstream [AWF network permissions](https://github.github.com/gh-aw/reference/network/)
and [sandbox configuration](https://github.github.com/gh-aw/reference/sandbox/) contracts.

The v2 policy also records the selected `sandbox.agent.runtime` profile. `docker` is the secure
default; `gvisor`, `docker-sbx`, and `cloud-hypervisor` require a literal runtime justification,
and `docker-sudo-iptables` is treated as an explicit privileged profile. A non-default profile
cannot be combined with a disabled sandbox. The compiler renders the profile into native
`sandbox.agent.runtime` fields without pretending to launch that runtime.

The optional `mcp_gateway` decision records only `enabled` and a bounded port. When enabled, the
compiler emits the upstream `mcp-gateway` feature and `sandbox.mcp.port`. Forge never accepts,
stores, or emits an API-key value; the upstream secret configuration remains outside the Forge
admission envelope. Gateway enablement requires an enabled AWF sandbox; a disabled sandbox cannot
carry an active gateway. Gateway routing is therefore auditable as configuration evidence, not
claimed as a live MCP connection.

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

### Host-authenticated admission

A connected host can write a `forge-host-admission-v1` proof containing references only. The
proof binds the host, audience, workspace, resource, request, authority, policy decision,
approval, lease, runtime episode, provider operation, provenance, scopes, and policy revision.
Forge enforces those bindings, short lifetime, generation, nonce replay protection, and
credential exclusion. The host remains responsible for the actual OAuth, DPoP, mTLS, SPIFFE, or
JWS verification.

For an explicit connected execution, pass the host proof and its context:

```bash
python3 scripts/forge-gh-aw-provider.py plan \
  --request /secure/path/provider-request.json \
  --effect-id EFFECT_ID --worker-id gh-aw-provider --lease-generation GENERATION \
  --host-admission /secure/path/host-admission.json \
  --host-ref host:codex \
  --host-audience audience:github \
  --host-workspace workspace:md-files
```

The provider verifies the proof while staging and rechecks it after `gh api user` succeeds,
before the first GitHub request. Omitting `--host-admission` preserves the explicit legacy
provider contract; it does not make a host-authentication claim.

## Native execution admission

Before a native upstream worker is allowed to consume a durable episode, run the read-only
preflight against the exact native artifact directory:

```bash
python3 scripts/forge-gh-aw-runtime.py preflight \
  --spec data/gh-aw-workflows.json \
  --output build/gh-aw-native \
  --db .forge/runtime.sqlite3 \
  --dispatcher forge-dispatcher \
  --episode-id EPISODE_ID \
  --request-digest sha256:REQUEST_DIGEST \
  --certificate .forge/gh-aw-admission.json
```

`preflight` requires `mode=upstream-gh-aw`, re-runs artifact verification, enforces the
deterministic request-bound episode ID, compares the pinned Forge runtime definition, and
rechecks the dispatcher source and native lock hashes. The resulting certificate binds the
upstream version/schema, native job roles, declared safe outputs, and verified history head to
one episode without storing prompts, provider content, credentials, or GitHub objects. Repeating
the command is byte-stable; an existing certificate may only be replaced by the exact same
certificate. It writes no runtime event and performs no GitHub call. The fenced provider consumes
this certificate and revalidates it against the current runtime before any provider effect.

### Native worker handoff

After the dispatcher has staged its effects, a native worker can claim one exact effect and carry
the admission into the provider boundary:

```bash
python3 scripts/forge-gh-aw-runtime.py native-handoff \
  --output build/gh-aw-native --db .forge/runtime.sqlite3 \
  --dispatcher forge-dispatcher --episode-id EPISODE_ID \
  --effect-id EFFECT_ID --worker-id gh-aw-native-worker \
  --certificate .forge/gh-aw-admission.json \
  --handoff .forge/gh-aw-worker-handoff.json \
  --request-ref sha256:REQUEST_REF
```

The command verifies the certificate, leases only the selected effect, and emits the strict
reference-only contract in [`data/runtime-gh-aw-worker-handoff.schema.json`](../data/runtime-gh-aw-worker-handoff.schema.json).
The envelope contains admission, episode, effect, request, and lease-generation references,
never the operation body, credentials, or a filesystem path. Repeating the command for the same
live lease is idempotent; a different owner, generation, effect, request, or certificate fails
closed. This is the local handoff contract, not a claim that a production runtime database or
provider deployment is already available.

Keep a long-running worker inside the pinned lease policy with a heartbeat bound to the same
effect, worker, and generation:

```bash
python3 scripts/forge-gh-aw-runtime.py heartbeat \
  --output build/gh-aw-native --db .forge/runtime.sqlite3 \
  --dispatcher forge-dispatcher --episode-id EPISODE_ID \
  --effect-id EFFECT_ID --worker-id gh-aw-native-worker \
  --lease-generation GENERATION
```

The fenced provider performs this heartbeat before and after authenticated login and every GitHub
transport request. A lost owner, generation, expiry, or deadline stops the next provider call.
If a remote call returns after the lease is lost, the provider keeps only the prior authorization
evidence and uses the existing journal recovery or explicit dispatch reconciliation path; it does
not claim exactly-once external execution.

## Fenced provider worker

The `forge-gh-aw-provider-v1` worker consumes a request file separately from runtime history.
`request_ref` is the SHA-256 digest of the canonical `repository`, `workflow_id`,
`safe_output_type`, and `operations` object. `contract_evidence_ref` separately binds the
normalized firewall policy and exact source/lock artifacts to the request. The envelope repeats episode and workflow identity,
but raw titles, bodies, inputs, and changed-file lists remain outside the runtime database,
approval store, receipts, and CLI plan output. Dispatch envelopes cover every compiled target
exactly once; each leased dispatch effect selects only its declared worker.

After `claim` returns an effect ID and lease generation, run the local stages in order:

```bash
python3 scripts/forge-gh-aw-provider.py plan \
  --request /secure/path/provider-request.json \
  --effect-id EFFECT_ID --worker-id gh-aw-provider --lease-generation GENERATION \
  --admission .forge/gh-aw-admission.json --handoff .forge/gh-aw-worker-handoff.json

python3 scripts/forge-gh-aw-provider.py approve \
  --request /secure/path/provider-request.json \
  --effect-id EFFECT_ID --worker-id gh-aw-provider --lease-generation GENERATION \
  --ttl-seconds 600 --admission .forge/gh-aw-admission.json \
  --handoff .forge/gh-aw-worker-handoff.json

python3 scripts/forge-gh-aw-provider.py execute \
  --request /secure/path/provider-request.json \
  --effect-id EFFECT_ID --worker-id gh-aw-provider --lease-generation GENERATION \
  --approval-id APPROVAL_ID --expected-login AlisinaDevelo \
  --admission .forge/gh-aw-admission.json \
  --handoff .forge/gh-aw-worker-handoff.json --execute

python3 scripts/forge-gh-aw-provider.py reconcile \
  --request /secure/path/provider-request.json \
  --effect-id EFFECT_ID --worker-id gh-aw-provider --lease-generation GENERATION \
  --approval-id APPROVAL_ID --expected-login AlisinaDevelo --run-id RUN_ID \
  --admission .forge/gh-aw-admission.json \
  --handoff .forge/gh-aw-worker-handoff.json --reconcile
```

`plan` performs no provider call and does not consume an approval. `approve` binds one short-lived
use to the exact effect, request reference, sanitized operation digests, repository, paths, and
policy revision. Native mode requires `--admission` on every stage; the provider rechecks its
artifact, runtime-definition, episode, request, and history-prefix binding after the authenticated
login and before transport or reconciliation work. When supplied, `--handoff` is revalidated at
the same boundary and binds the current lease generation to the native certificate. Preview mode
omits both native files. `execute`
first verifies `gh api user`, then rechecks the lease and policy before calling a bounded REST endpoint.
Issue and comment limits, configured title prefixes and labels,
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
