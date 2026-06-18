---
description: Review the current diff for correctness, security, and maintainability
argument-hint: "[optional: base branch or path, defaults to staged/working changes]"
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git log:*), Bash(git status:*)
model: sonnet
---

Review the code changes below for correctness, security, reliability, tests, and
maintainability. Focus on the changed lines, but read enough surrounding context to
judge intent.

Current changes:

- Status: !`git status --short`
- Staged diff: !`git diff --staged`
- Unstaged diff: !`git diff`

Scope hint (if provided): $ARGUMENTS

Apply the priority order correctness → security → reliability → tests → API → readability.
Report findings grouped by severity (🔴 Blocking / 🟡 Should-fix / 🟢 Nit), each with
location, problem, impact, and a concrete fix. Call out what's genuinely good. Be
precise — real issues over nitpicks — and flag anything you're unsure about as
needs-verification rather than asserting it. Don't comment on formatting a linter owns.
