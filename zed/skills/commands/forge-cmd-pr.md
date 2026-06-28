---
name: forge-cmd-pr
description: Draft a pull request description from the branch's commits and diff
disable-model-invocation: true
---

Draft a pull request description for the current branch.

Use any text the user typed after the command as a base branch name or additional context for the PR.

Start by running:

- `git branch --show-current` to get the current branch
- `git log --oneline @{u}.. 2>/dev/null || git log --oneline -15` to see commits on this branch
- `git diff --stat HEAD` to see the diff summary

If the user specified a base branch, use it for the log comparison.

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
