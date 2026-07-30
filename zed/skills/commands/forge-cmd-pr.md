---
name: forge-cmd-pr
description: Draft a pull request description from the branch's commits and diff
disable-model-invocation: true
---

Draft a pull request description for the current branch.

Use any text the user typed after the command as a base branch name or additional context for the PR.

Resolve the base from an explicit argument, the current branch's parent in
`.forge/stack.json`, the branch's `gh-merge-base`, or the repository default. Then run:

- `git branch --show-current` to get the current branch
- `git log --oneline <base>..HEAD` to see commits in this PR
- `git diff --stat <base>...HEAD` to see all committed changes in this PR

For a stacked PR, use its immediate parent as the base and include stack navigation.

Produce a description with these sections:

```text
## What
<one-paragraph summary>

## Why
<the motivation / problem; link the issue if referenced in commits>

## How
<the approach and any non-obvious decisions or trade-offs>

## Testing
<how it was verified — tests, manual steps, before/after>

## Notes for reviewers
<where to focus, known limitations, deliberate follow-ups>
```

Base it on the actual commits and diff — don't invent changes. If the diff is large or mixes concerns, note that it might be worth splitting. Lead with what and why.
