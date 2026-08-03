# Policy Plane

Forge's policy plane is the authorization boundary for actions that may create an
external effect or mutate a protected resource. It is implemented by the standard-
library script at `plugins/forge/skills/policy/scripts/forge-policy.py` and exposed at
`scripts/forge-policy.py`.

## Action contract

Every evaluated action is a versioned envelope. It binds:

- stable action identity and exact tool name;
- canonical arguments, without copying them into receipts;
- repository, branch, paths, and domains;
- principal and absolute workspace;
- intended effect, externality, risk, cost, and fan-out.

The action digest is SHA-256 over the canonical envelope plus the selected policy
revision. It changes when material arguments, resource scope, principal, workspace,
policy, branch, or file paths change.

## Profiles and decisions

Profiles are JSON files under `policies/`. The default decision is conservative and
unknown external writes are denied. Ordered rules can return `allow`, `deny`,
`require_approval`, `constrain`, or `transform`. Profile and rule constraints express
allowed tools, repositories, branches, paths, domains, cost, and fan-out.

Instruction, workflow, dependency-lock, security, settings, and plugin-manifest paths
are protected. An otherwise-allow decision for a protected path is upgraded to
`require_approval`.

## Approval lifecycle

Approvals are append-only records in `.forge/approvals.jsonl`, mode `0600` on supported
hosts. Each approval is short-lived, one-use, and bound to the exact action digest,
principal, workspace, policy revision, tool, resource scope, and intended effect. A
caller cannot reuse an approval as a bearer token for another action.

The safe adapter sequence is:

```text
plan -> stage (optional) -> evaluate -> approve -> re-evaluate immediately before effect
     -> consume exact approval -> external effect -> commit receipt
```

Staged previews do not call a mutation adapter and do not consume an approval. The
policy engine records a `staged-preview` outcome for evidence.

## Receipts and extensions

Decision receipts include the rule, reason, principal, policy revision, action digest,
resource summary, intended effect, and final committed effect. Arguments, prompts,
credentials, and raw results are excluded; the existing receipt store applies its
privacy sanitizer as a second boundary.

`PolicySession` is the adapter protocol. Optional enterprise policy providers can wrap
the session at the adapter boundary without adding a dependency to Forge core. The
bundled task-ledger and stacked-changes adapters opt in with `--policy-profile` and
support `--policy-staged`, `--policy-approval`, and `--policy-approvals`.

## CLI examples

```bash
python3 scripts/forge-policy.py --profile default profiles
python3 scripts/forge-policy.py --profile github-mutation evaluate --action action.json
python3 scripts/forge-policy.py --profile github-mutation stage --action action.json
python3 scripts/forge-policy.py --profile github-mutation approve --action action.json
python3 scripts/forge-policy.py --profile github-mutation authorize --action action.json --approval-id ID
```

Schemas live in [`data/action-envelope.schema.json`](../data/action-envelope.schema.json),
[`data/policy-decision.schema.json`](../data/policy-decision.schema.json), and
[`data/policy.schema.json`](../data/policy.schema.json).
