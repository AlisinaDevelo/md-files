---
description: Refactor code to improve structure while preserving behavior exactly
argument-hint: "<file, function, or smell to address>"
allowed-tools: Read, Grep, Glob, Bash, Edit
model: sonnet
---

Refactor: $ARGUMENTS

Behavior preservation is the contract.

1. Establish a safety net: confirm tests exist and pass for the code you'll touch. If
   they don't, say so and either write characterization tests first or ask before
   proceeding.
2. Identify the specific smell(s) — long function, duplication, tangled conditionals,
   unclear names, primitive obsession — and the named refactoring for each.
3. Apply changes in small, reversible steps. Run tests after each. Don't fix bugs or add
   features in the same pass; note any bug you find separately.
4. No abstraction without a second call site. Don't reformat untouched code or widen
   scope beyond what I asked.

Report what you changed, the smell each change addressed, and the verification (the tests
you ran and their result) proving behavior is unchanged. If you can't verify behavior
preservation, stop and tell me.
