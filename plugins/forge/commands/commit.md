---
description: Create a well-formed Conventional Commit for the staged changes
argument-hint: "[optional: a hint about intent or scope]"
allowed-tools: Read, Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash(git add:*), Bash(git commit:*)
model: sonnet
disable-model-invocation: true
---

Create a Conventional Commit for the currently staged changes.

- Staged changes: !`git diff --staged --stat`
- Staged diff: !`git diff --staged`
- Recent commit style for reference: !`git log --oneline -10`

Intent hint (if provided): $ARGUMENTS

Steps:

1. If nothing is staged, stop and tell me to stage changes (suggest `git add -p`).
2. Infer the correct type (feat/fix/docs/refactor/perf/test/build/ci/chore) and optional
   scope from the diff. If the diff mixes unrelated concerns, point that out and suggest
   splitting rather than writing one muddy commit.
3. Write the message: imperative, lowercase, ≤72-char subject; a body explaining *why*
   when it isn't obvious; `BREAKING CHANGE:` footer or `!` if applicable.
4. Match the repo's existing commit conventions shown above.
5. Show me the proposed message and the commit command. Do not commit until I confirm,
   and never add any AI co-author trailer.
