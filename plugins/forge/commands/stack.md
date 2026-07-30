---
description: Plan, inspect, submit, restack, repair, or land a stack of dependent pull requests
argument-hint: "[status | init | add | check | submit | restack | review | land | repair]"
allowed-tools: Read, Grep, Glob, Bash(git:*), Bash(gh pr:*), Bash(gh stack:*), Bash(gt:*), Bash(av:*), Bash(sl:*), Bash(ghstack:*), Bash(python3:*), Edit, Write
model: opus
---

Manage the current stacked-change workflow: $ARGUMENTS

Use the `stacked-changes` skill and its bundled `scripts/forge-stack.py` engine. Keep
`.forge/stack.json` as branch/PR ancestry state and `.forge/tasks/` as delivery-task state.
Prefer GitHub's first-party `gh stack` provider when it is installed and enabled for the
repository; otherwise use the manifest's explicit provider.

- Start with `status` when no action is given.
- For `init` or `add`, design a bottom-up stack whose PRs are independently reviewable.
- For `check`, validate the manifest, local branch existence, ancestry, and incremental
  commit ranges.
- For `submit`, print and inspect the engine's submit plan first. Do not push or create/edit
  PRs until the user explicitly approves that external mutation.
- For `restack`, require a clean worktree, fetch first, record recovery refs, and show the
  full plan. Do not rebase or force-with-lease until explicitly approved.
- For `review`, compare each branch with its immediate parent and review bottom-up.
- For `land`, verify approvals/checks and merge parent-first. Stop after each merge to
  restack/retarget and revalidate the next PR; respect the repository's merge queue.
  With native GitHub stacks use `gh stack merge`, not ordinary `gh pr merge`.
- For `repair`, identify the first divergence across local ancestry, remote refs, PR bases,
  or CI. Preserve work and provide a reversible recovery sequence.

Never use `--force`, rewrite trunk/shared branches, bypass a rejected lease, or claim a
stack is healthy without checking each incremental diff and post-command remote state.
