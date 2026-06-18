---
description: Clean up the current diff — remove cruft and simplify, without changing behavior
argument-hint: "[optional: path; defaults to current changes]"
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git status:*), Edit
model: sonnet
---

Tidy the current changes (or $ARGUMENTS if a path is given). Quality only — this is not a
bug hunt and not a feature change.

- Status: !`git status --short`
- Diff: !`git diff HEAD`

Look for and fix, behavior-preserving:

- Debug output, commented-out code, stray `console.log`/`print`/`dump`.
- Now-unused imports, variables, and functions left by the change.
- Obvious duplication introduced by the diff that has a clean shared form.
- Unclear names where a rename meaningfully improves readability.
- Dead branches the change made unreachable.

Touch only what the change introduced — don't reformat or refactor untouched code, and
don't add abstractions. If you spot a real bug while tidying, report it separately rather
than fixing it here. Show the edits and confirm nothing behavioral changed.
