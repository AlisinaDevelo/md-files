---
name: stacked-changes
description: >-
  Use when a feature is too large for one reviewable pull request; when creating,
  restacking, reviewing, repairing, or landing dependent GitHub pull requests; or when
  choosing between vanilla git/gh, Graphite, and Sapling for a stacked-change workflow.
---

# Stacked Changes

A stack is an ordered set of small pull requests where each branch targets the branch
immediately below it. It keeps implementation moving while earlier changes are reviewed,
without asking a reviewer to absorb one giant diff.

## Decide whether to stack

Stack when a change has several independently reviewable steps with real dependency order.
Do not stack unrelated work, a tiny change, or pieces that only make sense when reviewed as
one unit.

Good split patterns:

- foundation → behavior → integration
- schema → API → client → end-to-end tests
- behavior-preserving refactor → behavior change
- generated code or dependency update → code that consumes it
- low-risk scaffolding → isolated risky change → rollout

Every PR must build or test at its own boundary, explain its dependency, and remain
understandable without reading the entire stack.

## Use explicit state

Forge keeps provider and branch ancestry in `.forge/stack.json`; task delivery dependencies
stay in `.forge/tasks/`. Do not overload one with the other. Prefer GitHub's first-party
`gh stack` provider when Stacked PRs are enabled for the repository; use Forge's manifest
as the portable planning and verification layer.

The bundled engine is at `scripts/forge-stack.py` relative to this skill:

```bash
python3 scripts/forge-stack.py init --trunk main
python3 scripts/forge-stack.py add feature/schema --parent main
python3 scripts/forge-stack.py add feature/api --parent feature/schema
python3 scripts/forge-stack.py status
python3 scripts/forge-stack.py check
python3 scripts/forge-stack.py plan submit
```

`status` and `check` inspect real Git ancestry. `plan submit`, `plan restack`, and `plan
land` print provider-native commands but never run them. Read [REFERENCE.md](REFERENCE.md)
for the schema, adapters, GitHub settings, and recovery playbooks.

For repositories with GitHub native Stacked PRs enabled, use the companion
`scripts/forge-stack-sync.py` adapter to inspect or import remote state and to plan/apply
native create, append, relink, and unstack operations. It keeps remote identifiers and SHA
snapshots in the manifest, treats GitHub as an explicit mutation boundary, and falls back to
the provider engine when the private-preview API returns 404. See
[GitHub Native Stacks](../../../../docs/github-native-stacks.md).

For an approved native landing, use `scripts/forge-stack-merge.py`. It previews the exact
contiguous range, expected head SHAs, merge method, queue mode, readiness gates, and policy
effect before submitting `PUT .../merge-async`. It persists the returned request UUID in
`.forge/stack-merge.json`, resumes polling after a timeout without a duplicate submit, and
records `pending`, `enqueued`, `merged`, `failed`, or `indeterminate` outcomes. An
`indeterminate` result is a stop signal: inspect remote state before doing anything else.

```bash
python3 scripts/forge-stack-merge.py --repo OWNER/REPO plan --pr 42 --merge-action default
python3 scripts/forge-stack-merge.py --repo OWNER/REPO submit --pr 42 --yes
python3 scripts/forge-stack-merge.py --repo OWNER/REPO poll --operation-id OPERATION_ID
python3 scripts/forge-stack-merge.py --repo OWNER/REPO queue-event --event merge-group.json --operation-id OPERATION_ID
```

Use `--policy-profile policies/github-mutation.json` for the scoped approval boundary and
`--policy-staged` to preview without a submit. The adapter fails closed when required
checks, reviews, unresolved threads, ruleset evidence, or queue policy are unavailable;
`--allow-unknown-readiness` is an explicit degraded-mode escape hatch for installations
whose preview API cannot expose those fields. Native Stack Merge 404s produce a documented
provider-native bottom-up fallback plan instead of pretending an ordinary PR merge is
atomic.

## Author loop

1. Design the stack bottom-up and write one-sentence intent plus acceptance criteria for
   each change.
2. Create each branch from its immediate parent and commit one coherent review unit.
3. Run the narrow tests for that PR; run integration tests at the top of the stack.
4. Submit bottom-up. New PRs should be drafts until each incremental diff is ready.
5. Add stack navigation to every PR body. Base each PR on its immediate parent branch.
6. Address feedback at the branch where it belongs, then restack descendants and verify
   their diffs again.
7. Land from the bottom. Stop on conflict, failing checks, stale approval requirements, or
   an unexpected remote update.

## Review loop

- Review from the trunk-adjacent PR upward, but do not serialize review unnecessarily.
- Diff every branch against its immediate parent, never all branches against trunk.
- Judge each PR independently for correctness, tests, rollback, and reviewability.
- Scan upstack when a later change modifies code introduced below.
- Record findings on the PR that owns the code; mention downstream impact separately.

## Safety invariants

- Never rewrite trunk, a shared branch, or a branch whose ownership is unclear.
- Before a restack: require a clean worktree, fetch the remote, record current refs, and
  inspect whether review is active.
- If rewritten branches were already pushed, use `--force-with-lease`, never `--force`.
  A rejected lease is new information: fetch and inspect; do not bypass it.
- Preserve a recovery anchor (branch/tag or reflog reference) before a multi-branch rebase.
- After every restack, re-run `check`, inspect every incremental diff, and resubmit the
  affected PRs.
- Treat a zero exit code as transport status, not proof. Verify post-command remote state:
  re-check remote heads, PR bases, stack positions, and CI after submit, sync, push, or
  merge.
- Changing a GitHub PR base can obsolete comments and approvals. Call that out before doing
  it.

The stack is healthy only when local ancestry, remote branches, PR bases, and CI agree.
