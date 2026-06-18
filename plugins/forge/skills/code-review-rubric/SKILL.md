---
name: code-review-rubric
description: >-
  Use when reviewing code or a pull request to apply a consistent quality bar.
  Provides a severity-ranked rubric covering correctness, security, tests,
  readability, and maintainability, plus how to write feedback that gets fixed.
  See CHECKLIST.md for the full pre-merge checklist.
---

# Code Review Rubric

Review to find what matters and communicate it so it gets fixed. Precision over volume —
ten real issues beat fifty nitpicks. Don't review formatting a linter owns.

## Priority order

Spend attention top-down; the lower items rarely matter if the top ones are wrong.

1. **Correctness** — does it do what it claims? Logic errors, off-by-one, unhandled
   null/empty, wrong error handling, broken invariants, race conditions.
2. **Security** — anything touching auth, crypto, secrets, or untrusted input. Injection,
   missing authz, secrets in code, unsafe deserialization, path traversal.
3. **Failure & resources** — leaked handles/connections, missing timeouts, unbounded
   growth, partial-failure leaving inconsistent state, retries without backoff.
4. **Tests** — proportional to risk, asserting behavior not implementation, covering
   edges and failure paths. Would they catch a regression?
5. **API & contract** — backward compatibility, leaky abstractions, surprising side
   effects, consistent error shapes.
6. **Readability & maintainability** — names, dead code, duplication, functions doing too
   much, comments explaining *why* (keep) vs *what* (noise).

For the exhaustive item list, load **CHECKLIST.md**.

## Severity labels

- **🔴 Blocking** — must fix before merge (bugs, security, data loss).
- **🟡 Should-fix** — real issues that aren't merge-blockers; fix soon.
- **🟢 Nit** — optional polish; mark it as optional so it isn't mistaken for a blocker.

## Writing feedback that lands

- Give location → problem → impact → suggested fix. Specific and actionable.
- Critique the code, not the author. "This leaks the connection on the error path,"
  not "you forgot."
- Explain the *why* so the lesson generalizes.
- Distinguish "this is wrong" from "I'd prefer" — don't dress up taste as defect.
- Call out what's genuinely good; it calibrates trust and reinforces patterns.
- If unsure whether something's a bug, say so and name what would confirm it.

## What not to do

Don't rewrite the author's code in your style. Don't demand abstractions for single-use
code. Don't block on preferences. Don't nitpick what the formatter already handles.
