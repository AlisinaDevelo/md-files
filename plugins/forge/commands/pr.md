---
description: Draft a pull request description from the branch's commits and incremental diff
argument-hint: "[optional: base branch, defaults to stack parent or default branch]"
allowed-tools: Read, Bash(git diff:*), Bash(git log:*), Bash(git status:*), Bash(git branch:*), Bash(git config:*), Bash(git remote:*)
model: sonnet
---

Draft a pull request description for the current branch.

- Current branch: !`git branch --show-current`
- Stack state: read `.forge/stack.json` when present.

Base branch (if provided): $ARGUMENTS

Resolve the base in this order: explicit argument; current branch's parent in
`.forge/stack.json`; `branch.<name>.gh-merge-base`; repository default branch. Inspect
`git log <base>..HEAD` and `git diff <base>...HEAD` so committed changes are included. For
a stacked PR, the base must be its immediate parent, never trunk.

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
mixes concerns, note that it might be worth splitting. For a stack, include position,
parent PR/branch, downstack dependency, and upstack links from the `stacked-changes`
skill. Lead with what and why.
