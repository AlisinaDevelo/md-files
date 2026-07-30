---
name: forge-cmd-stack
description: Plan, inspect, submit, restack, repair, or land a stack of dependent pull requests
disable-model-invocation: true
---

Manage the user's stacked-change workflow with the `stacked-changes` skill.

Use `.forge/stack.json` for branch and PR ancestry. Start with status. Design independent,
bottom-up changes; validate every branch against its immediate parent; plan submission or
restacking before changing Git or GitHub. Prefer GitHub's first-party `gh stack` provider
when available. Require explicit approval before pushes, rebases,
force-with-lease, PR creation/base edits, or merges. Land parent-first and stop to
revalidate after each merge. Never use `--force`, rewrite shared branches, or bypass a
rejected lease.
