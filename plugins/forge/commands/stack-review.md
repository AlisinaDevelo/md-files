---
description: Review a stacked pull request series bottom-up against each immediate parent
argument-hint: "[optional: path to .forge/stack.json or PR/branch]"
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git log:*), Bash(git show:*), Bash(gh pr view:*), Bash(gh stack view:*), Bash(python3:*)
model: opus
---

Review this stacked change: $ARGUMENTS

Use the `stacked-changes` and `code-review-rubric` skills.

1. Load `.forge/stack.json` or infer the explicit PR base/head relationships.
2. Validate the stack before reviewing. Report broken ancestry, missing branches, or
   mismatched PR bases as blocking workflow findings.
3. Review bottom-up, diffing every branch against its immediate parent. Do not review each
   branch against trunk, because that repeats downstack code and hides ownership.
4. Treat each PR as an independent change: correctness, security, tests, rollback, and
   whether its description explains why it exists.
5. Check upstack for later edits to code introduced below and attach findings to the PR
   that owns the code.
6. Finish with a stack-level verdict: safe landing prefix, blocked PRs, cross-stack risks,
   and the exact verification still required.

Lead with findings ordered by severity and identify both the branch/PR and file/line when
possible. Do not approve a whole stack merely because the top branch passes tests.
