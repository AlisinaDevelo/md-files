---
description: Write or extend tests for the given code, matching the repo's harness
argument-hint: "<file, function, or feature to test>"
allowed-tools: Read, Grep, Glob, Bash
model: sonnet
---

Write tests for: $ARGUMENTS

1. Read the target code and the existing tests next to it. Detect the test framework,
   naming, fixtures, and assertion style already in use — follow them exactly. Do not
   introduce a new test dependency.
2. Identify the contract: inputs, outputs, side effects, invariants, error conditions.
3. Enumerate cases — happy paths, boundaries (0/1/n/max/empty/null), and failure paths —
   and prioritize by how the code is actually used.
4. Write tests that assert observable behavior (not implementation), one reason to fail
   each, deterministic (inject clocks/seeds, isolate I/O).
5. Run them. Confirm they pass on correct code and would fail on broken code.

Report the test files, the command to run them, and what's covered vs. intentionally out
of scope. If the code is hard to test, name the smallest seam that would fix that — but
don't refactor unless I ask.
