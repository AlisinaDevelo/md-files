---
name: forge-cmd-commit
description: Draft a Conventional Commit message for staged changes
disable-model-invocation: true
---

Create a Conventional Commit message for the currently staged changes.

Use any text the user typed after the command as an intent hint to inform the type and scope.

Start by running:
- `git diff --staged --stat` to see what's staged
- `git diff --staged` to read the full diff
- `git log --oneline -10` to see the recent commit style for reference

Steps:
1. If nothing is staged, stop and tell the user to stage changes (suggest `git add -p`).
2. Infer the correct type (feat/fix/docs/refactor/perf/test/build/ci/chore) and optional scope from the diff. If the diff mixes unrelated concerns, point that out and suggest splitting rather than writing one muddy commit.
3. Write the message: imperative, lowercase, ≤72-char subject; a body explaining *why* when it isn't obvious; `BREAKING CHANGE:` footer or `!` if applicable.
4. Match the repo's existing commit conventions shown in the log.
5. Show the proposed message and the exact `git commit -m "..."` command to run. Do not commit — wait for the user to confirm. Never add any AI co-author trailer.
