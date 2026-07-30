---
name: forge-cmd-stack-review
description: Review a stacked pull request series bottom-up against each immediate parent
disable-model-invocation: true
---

Review the stack using `stacked-changes` and `code-review-rubric`.

Validate the stack first, then review from the trunk-adjacent branch upward. Diff every
branch against its immediate parent, judge it as an independent change, scan upstack for
later edits to code introduced below, and attach findings to the PR that owns the code.
Lead with severity-ranked findings and end with the safe landing prefix, blockers, and
remaining verification.
