---
name: git-workflow
description: >-
  Use when working with git beyond writing a commit message — branching, rebasing
  vs merging, resolving conflicts, recovering lost work, and bisecting to find a bad
  commit. Covers what is safe on shared branches and what is not.
---

# Git Workflow

Git is a content-addressable history you can almost always recover from. The rules below
keep history readable and keep you out of the irreversible corners.

## Branching

- Branch per unit of work off the latest base. Keep branches short-lived — long-lived
  branches drift and conflict.
- Rebase your *own* unpushed branch onto the updated base to keep a linear history before
  opening a PR: `git fetch && git rebase origin/main`.

## Rebase vs. merge — the one rule that matters

- **Rebase to clean up history that only you have.** Never rebase commits you've already
  pushed and others may have based work on — it rewrites hashes and forces everyone else
  to recover. "Don't rebase shared/public branches" is the rule; private branch cleanup
  is fine.
- **Merge to integrate shared branches.** A merge commit is honest about when integration
  happened and is safe for history others already have.

## Resolving conflicts

- Read both sides before editing — understand what each change intended, don't just pick
  one. The conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) bound the competing hunks.
- After resolving: `git add` the files, then continue (`git rebase --continue` /
  `git merge --continue`). Run the tests before finishing — a clean merge can still be
  semantically broken.
- Bail out safely if it's a mess: `git rebase --abort` / `git merge --abort` returns you
  to the pre-operation state.

## Recovery — git rarely loses committed work

- **`git reflog`** is the undo log for HEAD. Reset to the wrong place, botched a rebase,
  "lost" a branch? The prior HEAD is in the reflog: `git reset --hard HEAD@{1}`.
- **`git revert <sha>`** undoes a commit by adding an inverse commit — the safe way to
  undo something already pushed (vs. `reset`, which rewrites history).
- Uncommitted changes are the real loss risk — `git stash` before risky operations.

## Finding a bad commit

`git bisect` binary-searches history for the commit that introduced a bug:

```text
git bisect start
git bisect bad                 # current commit is broken
git bisect good <known-good>   # this older commit worked
# git checks out the midpoint — test it, then:
git bisect good   # or: git bisect bad
# repeat until git names the first bad commit, then:
git bisect reset
```

Automate it with `git bisect run <test-command>` when the test is scriptable.

## Don't

Force-push to `main`/`master`/`shared` branches. Rewrite pushed history others build on.
`git reset --hard` with uncommitted changes you care about. `git clean -fd` without
checking what it'll delete first (`git clean -nd` previews).
