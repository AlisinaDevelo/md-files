# Stacked Changes Reference

## Manifest

Forge uses a committed, versioned manifest:

```json
{
  "version": 1,
  "provider": "github",
  "trunk": "main",
  "remote": "origin",
  "branches": [
    {"name": "feature/schema", "parent": "main", "pr": 41},
    {"name": "feature/api", "parent": "feature/schema", "pr": 42}
  ]
}
```

Branches are topologically ordered. A parent must be the trunk or a branch already listed.
`pr` is optional until the GitHub pull request exists. Supported providers are `github`,
`vanilla`, `graphite`, `aviator`, `sapling`, and `ghstack`.

## Engine Commands

Run `forge-stack.py --help` for all flags.

| Command | Effect |
|---------|--------|
| `init --trunk main` | Create an empty `.forge/stack.json` |
| `add BRANCH --parent BASE` | Add one branch after validating its parent |
| `link BRANCH PR` | Associate an existing GitHub PR number |
| `status [--json]` | Show branch existence, ancestry, incremental commits/files, and PR |
| `check` | Exit nonzero when the manifest or local Git graph is unhealthy |
| `plan submit` | Print the selected provider's submit command(s) |
| `plan restack` | Print the selected provider's restack/push command(s) |
| `plan land` | Print the provider-native stack landing command |
| `plan ACTION --tool PROVIDER` | Override the manifest provider for one plan |
| `body BRANCH` | Render stack navigation for a PR description |

The engine deliberately does not execute submission, rebases, force pushes, or merges.
Those transitions require repository context and human approval.

## Tool Adapters

### GitHub Stacked PRs

GitHub's first-party `gh stack` is Forge's default provider when the repository supports
it:

- Install with `gh extension install github/gh-stack`.
- Use `gh stack init`, `add`, `view`, and `submit` to create the stack.
- Use `gh stack rebase` then `gh stack push` after changing a lower layer. Push uses
  per-branch force-with-lease; verify every remote head because a multi-branch push may
  partially update before a rejected lease.
- Use `gh stack merge` rather than ordinary `gh pr merge`. A direct stack merge is atomic;
  merge-queue processing remains bottom-up and may span several merge groups.
- `gh stack sync` combines fetch, reconciliation, rebase, push, and PR/stack updates. In
  headless use, verify the remote result even when it exits successfully.
- Prefer local rebases when signed commits are required; server-side rebases create
  unsigned commits.

GitHub evaluates each layer against the stack's ultimate target, so trunk rules, CODEOWNERS,
and pull-request CI apply to mid-stack PRs. Webhooks expose stack id/number, size, position,
and ultimate base; the `stacked` pull-request action fires after a PR joins the stack.

### Native Stack Merge and Merge Queue

The async landing adapter is `scripts/forge-stack-merge.py` (also available as
`python3 scripts/forge-stack-merge.py`). Its state file is `.forge/stack-merge.json` and
its receipt stream is `.forge/receipts.jsonl`.

| Command | Effect |
|---------|--------|
| `plan --pr N` | Preview exact contiguous range, expected heads, readiness gates, policy effect, and expected result |
| `submit --pr N --yes` | Re-check remote heads, consume optional scoped approval, submit once, and poll |
| `poll --operation-id ID` | Resume a persisted pending or enqueued request without a new submit |
| `queue-event --event FILE --operation-id ID` | Correlate a `merge_group` `checks_requested` delivery with the enqueued receipt |

The adapter sends the selected target PR's expected head SHA to GitHub. It verifies every
selected layer before submission and verifies every selected PR after a terminal result. A
failed result with any remote merge evidence becomes `indeterminate` and requires manual
reconciliation; it is never reported as a clean failure. `enqueued` is a handoff state, not
completion: queue polling and correlated `merge_group` evidence remain part of the run.
If Stack Merge is unsupported, the adapter returns a provider-native bottom-up plan and
does not silently fall back to independent ordinary merges.

### Vanilla Git and GitHub CLI

- PR `base` is the immediate parent branch; PR `head` is the current branch.
- Use `gh pr create --base PARENT --head BRANCH --draft --fill`.
- Store the PR number with `link` so later plans update the base idempotently.
- Use the generated body block to make order and dependencies visible on GitHub.

### Graphite

- `gt submit --stack` creates or updates the stack.
- After parent changes, use `gt sync`, `gt restack`, then `gt submit --stack`.
- During conflict recovery use `gt continue`; use `gt abort` to return to the pre-restack
  state.
- Treat Graphite merge-stack and GitHub merge-queue compatibility as a repository-specific
  setting; verify current product support before enabling both.

### Sapling

- `sl pr submit --stack` creates or updates PRs for the commit stack.
- `sl rebase --restack` repairs descendants after an ancestor commit changes.
- Sapling's GitHub PR view can contain overlapping downstack commits; use a stack-aware
  review UI or verify each commit-range explicitly.

### Aviator

- `av branch`, `av restack`, `av pr`, and `av pr queue` cover local stack and queue flows.
- Treat `av sync` as destructive to remote edits unless current documentation says
  otherwise; never run it without the same clean-tree, ownership, and recovery preflight.

### Classic ghstack

- Use only for established repositories that rely on its synthetic base/head/orig branches.
- Preserve ghstack commit trailers across rebases and autosquash or duplicate PRs can be
  created.
- Land with `ghstack land`; ordinary GitHub merge is incompatible with its branch model.

## GitHub Repository Settings

- Required checks should validate each reviewable boundary; the top PR should also exercise
  the integrated stack.
- Strict "branch must be up to date" checks can multiply CI after every downstack merge.
  Prefer a merge queue or an explicit integration check where available.
- Dismissing stale approvals is safer for unreviewed changes, but restacking may invalidate
  approvals because the merge base changes. Choose deliberately and document the trade-off.
- Require resolved conversations, code-owner review for owned paths, and trusted sources for
  required status checks.
- If a merge queue is used, workflows must handle the `merge_group` event and test the
  synthetic merge commit, not only `pull_request`.

## Recovery Playbooks

### Restack conflict

1. Stop at the first conflicted branch; do not continue upstack.
2. Inspect conflict intent from both the parent and child.
3. Resolve, test that incremental change, continue the rebase, then check the full stack.
4. Abort if intent is unclear. The pre-restack anchor and reflog are the recovery path.

### Rejected force-with-lease

1. Do not retry with `--force`.
2. Fetch the remote branch and compare local, remote, and the saved pre-restack ref.
3. Determine whether a collaborator or automation pushed changes.
4. Reconcile explicitly, restack again if needed, and only then retry the lease.

### Parent merged

1. Fetch trunk and confirm the parent PR's merge result.
2. Rebase or restack the next branch onto trunk.
3. Retarget that PR to trunk, check whether comments/approvals became stale, and run CI.
4. Continue upward one PR at a time.

### Partial submission

Inspect existing PRs before creating anything. Link the PRs that succeeded, then re-run the
plan; existing PRs become base-update operations and missing PRs remain create operations.

## Primary Sources

- [GitHub: changing a pull request base](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/changing-the-base-branch-of-a-pull-request)
- [GitHub: ruleset rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [GitHub CLI: `gh pr create`](https://cli.github.com/manual/gh_pr_create)
- [GitHub Stacked PRs: overview](https://github.github.com/gh-stack/introduction/overview/)
- [GitHub Stacked PRs: CLI](https://github.github.com/gh-stack/reference/cli/)
- [GitHub Stacked PRs: workflows](https://github.github.com/gh-stack/guides/workflows/)
- [GitHub Stacked PRs: webhooks](https://github.github.com/gh-stack/reference/webhooks/)
- [Graphite: restack branches](https://graphite.com/docs/restack-branches)
- [Graphite: reviewing stacks](https://graphite.com/docs/best-practices-for-reviewing-stacks)
- [Graphite: structuring stacks](https://graphite.com/docs/how-to-structure-your-stacks)
- [Sapling: GitHub stack](https://sapling-scm.com/docs/git/sapling-stack/)
