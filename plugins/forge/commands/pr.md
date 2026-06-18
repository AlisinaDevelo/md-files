---
description: Draft a pull request description from the branch's commits and diff
argument-hint: "[optional: base branch, defaults to the default branch]"
allowed-tools: Read, Bash(git diff:*), Bash(git log:*), Bash(git status:*), Bash(git branch:*)
model: sonnet
---

Draft a pull request description for the current branch.

- Current branch: !`git branch --show-current`
- Commits on this branch: !`git log --oneline @{u}.. 2>/dev/null || git log --oneline -15`
- Diff stat: !`git diff --stat HEAD`

Base branch (if provided): $ARGUMENTS

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

Base it on the actual commits and diff — don't invent changes. If the diff is large or
mixes concerns, note that it might be worth splitting. Lead with what and why.
