---
name: forge-cmd-tidy
description: Clean up the current diff — remove cruft and simplify, without changing behavior
disable-model-invocation: true
---

Tidy the current changes (or the path the user specified, if given). Quality only — this is not a bug hunt and not a feature change.

Use any text the user typed after the command as a target path to scope the tidy. If nothing is specified, tidy the current diff.

Start by running `git status --short` and `git diff HEAD` to see what's changed.

Look for and fix, behavior-preserving:

- Debug output, commented-out code, stray `console.log`/`print`/`dump`.
- Now-unused imports, variables, and functions left by the change.
- Obvious duplication introduced by the diff that has a clean shared form.
- Unclear names where a rename meaningfully improves readability.
- Dead branches the change made unreachable.

Touch only what the change introduced — don't reformat or refactor untouched code, and don't add abstractions. If you spot a real bug while tidying, report it separately rather than fixing it here. Show the edits and confirm nothing behavioral changed.
