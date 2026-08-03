# GitHub Native Stacks

Forge keeps `.forge/stack.json` as the portable local graph and can reconcile it with
GitHub's native Stacked PR API through the standard-library adapter at
`plugins/forge/skills/stacked-changes/scripts/forge-stack-sync.py`.

GitHub Stacked PRs are currently a private-preview capability. A repository without the
feature receives a structured fallback result and can continue using `gh stack`, vanilla
GitHub PRs, Graphite, Aviator, Sapling, or classic ghstack through the existing provider
engine.

## Inspect and Import

Use a PR number, URL, branch, or the current checkout to identify the stack:

```bash
python3 scripts/forge-stack-sync.py --repo OWNER/REPO inspect --pr 42 --json
python3 scripts/forge-stack-sync.py --repo OWNER/REPO inspect --url https://github.com/OWNER/REPO/pull/42 --include-local
python3 scripts/forge-stack-sync.py --repo OWNER/REPO import --branch feature/api --write
python3 scripts/forge-stack-sync.py --repo OWNER/REPO inspect --pr 42 --api graphql --json
```

`import` is read-only unless `--write` is present. The generated manifest stores the native
stack number, global/node identity, ultimate base, ordered PRs, branch names, positions, and
head/base SHA snapshots. Volatile timestamps are intentionally excluded so re-importing the
same remote state is byte-stable.

## Reconciliation

```bash
python3 scripts/forge-stack-sync.py --repo OWNER/REPO plan --pr 42 --json
python3 scripts/forge-stack-sync.py --repo OWNER/REPO plan --pr 42 --unstack --json
python3 scripts/forge-stack-sync.py --repo OWNER/REPO apply --pr 42 --yes
python3 scripts/forge-stack-sync.py --repo OWNER/REPO --policy-profile policies/github-mutation.json apply --pr 42 --yes
python3 scripts/forge-stack-sync.py --repo OWNER/REPO --policy-profile policies/github-mutation.json --policy-staged apply --pr 42
```

`plan` never mutates GitHub. `apply` requires local authority and `--yes`; GitHub authority
is import/status-only. Plans can create a stack, append top layers, relink a PR base, or
explicitly unstack. Every mutation carries the expected current top/head SHA. Apply
re-fetches remote state before writing and stops on drift rather than overwriting it. An
optional `--policy-profile` adds declarative authorization, one-use approvals, protected
resource checks, and final policy receipts. `--policy-staged` previews every operation
without calling the stack client or consuming an approval. See [the policy-plane guide](policy-plane.md).

Retries are safe: an already-created matching stack or already-appended top layers are
recognized before another POST. Completed operation IDs persist in
`.forge/stack-sync.json`, and successful mutations emit idempotent privacy-safe receipts to
`.forge/receipts.jsonl`.

## Native Stack Merge

Use the separate landing adapter after `plan` and readiness review:

```bash
python3 scripts/forge-stack-merge.py --repo OWNER/REPO plan --pr 42 --merge-action default
python3 scripts/forge-stack-merge.py --repo OWNER/REPO \
  --policy-profile policies/github-mutation.json submit --pr 42 --yes
python3 scripts/forge-stack-merge.py --repo OWNER/REPO poll --operation-id OPERATION_ID
```

The plan binds the exact contiguous range from the lowest unmerged PR through the selected
target, every expected head SHA, the base SHA, merge method, merge action, readiness gates,
and expected result. Submit re-fetches the stack immediately before the effect and sends the
target head SHA to GitHub. `pending` UUIDs and `enqueued` queue handoffs persist in
`.forge/stack-merge.json`; retries poll those records instead of issuing a second submit.

The async result is not the whole queue lifecycle. An `enqueued` result must be followed by
queue observation and, when available, a correlated `merge_group` `checks_requested` event:

```bash
python3 scripts/forge-stack-merge.py --repo OWNER/REPO queue-event \
  --event merge-group.json --operation-id OPERATION_ID
```

The event must identify the repository and merge-group head SHA. If GitHub reports failure
but post-state inspection shows any selected PR merged, Forge returns `indeterminate` with
`stop-and-reconcile`; it never hides a partial landing. A repository without native Stack
Merge receives a provider-native bottom-up fallback plan. See the [policy plane](policy-plane.md)
for scoped approvals and staged previews.

## Divergence and Recovery

The adapter classifies state as `compatible`, `local-only`, `remote-only`, or `conflicting`.
Shared PR order, branch identity, and imported head SHA snapshots are compared explicitly.
Remote additions are not silently discarded. A remote stack with entries missing locally
requires `--unstack` before Forge will plan dissolution; without it, the result is a conflict.

If a stack was created or extended outside Forge, run `import --write` only after reviewing
the remote state. If local work is authoritative, update `.forge/stack.json`, run `plan`,
inspect expected SHAs, then apply. If a SHA changes between plan and apply, fetch and
reconcile again. Never bypass a conflict with a force push or by editing the recorded SHA.

The REST adapter uses GitHub's Stacks API for mutations; the optional GraphQL mode reads the
stack entry connection with bounded cursor pagination. A native 404 is a feature fallback,
not evidence that the repository or PR is corrupt.

## Primary Sources

- [GitHub Stack Merge API](https://github.github.com/gh-stack/reference/merge-api/)
- [GitHub Merge Queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
- [GitHub `merge_group` webhook](https://docs.github.com/en/webhooks/webhook-events-and-payloads#merge_group)
