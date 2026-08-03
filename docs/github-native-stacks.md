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
