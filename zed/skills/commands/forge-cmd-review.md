---
name: forge-cmd-review
description: Review the current diff for correctness, security, and maintainability
disable-model-invocation: true
---

Review the code changes in this project for correctness, security, reliability, tests, and maintainability. Focus on the changed lines, but read enough surrounding context to judge intent.

Use any text the user typed after the command as a scope hint (a branch name or file path) to narrow the diff.

Start by running:

- `git status --short` to see what's changed
- `git diff --staged` to see staged changes
- `git diff` to see unstaged changes

If the user provided a scope hint (a branch or path), apply it to narrow the diff.

Apply the priority order: correctness → security → reliability → tests → API → readability.

Report findings grouped by severity:

- 🔴 Blocking — must fix before merge (bugs, security, data loss)
- 🟡 Should-fix — real issues, not merge-blockers
- 🟢 Nit — optional polish

For each finding: location (`file:line`), problem, impact, and a concrete fix. Call out what's genuinely good. Be precise — real issues over nitpicks. Flag anything you're unsure about as needs-verification rather than asserting it. Don't comment on formatting a linter owns.
