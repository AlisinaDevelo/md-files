# Pre-Merge Review Checklist

Load this when you want the exhaustive item list behind the rubric. Not every item
applies to every change — use judgment proportional to risk.

## Correctness

- [ ] Does the code do what the PR claims?
- [ ] Edge cases: empty, null/None/undefined, zero, one, many, max, negative, overflow.
- [ ] Boundary conditions and off-by-one in loops/slices/ranges.
- [ ] Error paths handled and propagated correctly; no swallowed errors.
- [ ] Invariants and preconditions preserved.
- [ ] Concurrency: shared state, race conditions, deadlocks, atomicity where needed.
- [ ] No reliance on undefined behavior, implicit ordering, or platform quirks.

## Security

- [ ] Untrusted input validated/sanitized before use.
- [ ] Queries parameterized; no string-built SQL/commands.
- [ ] AuthZ checked on every protected operation (not just authN).
- [ ] No secrets in code, logs, or error messages.
- [ ] Crypto uses vetted primitives; passwords hashed with a slow KDF.
- [ ] Output encoded for its sink (HTML/URL/shell) to prevent injection/XSS.
- [ ] No sensitive data in logs or responses.

## Reliability & resources

- [ ] Files, connections, locks, and handles are released on all paths.
- [ ] External calls have timeouts and bounded retries with backoff.
- [ ] No unbounded memory growth or unbounded result sets.
- [ ] Partial failure leaves the system in a consistent state.
- [ ] Idempotency where operations may be retried.

## Tests

- [ ] New behavior is covered; bug fixes include a regression test.
- [ ] Tests assert observable behavior, not implementation details.
- [ ] Failure and edge cases tested, not just the happy path.
- [ ] Tests are deterministic (no real clock/network/order dependence).
- [ ] A deliberately broken implementation would fail these tests.

## Design & maintainability

- [ ] Change is scoped to its stated purpose; no unrelated churn.
- [ ] Names reveal intent; no abbreviations that obscure.
- [ ] No needless duplication; no premature abstraction either.
- [ ] Functions do one thing at one level of abstraction.
- [ ] Public API is backward compatible (or the break is intentional + noted).
- [ ] Comments explain *why*, not *what*; no commented-out code.
- [ ] Dead code, debug output, and TODOs without owners removed.

## Operability

- [ ] Meaningful logging at the right level; errors are actionable.
- [ ] Metrics/traces for new critical paths where the project expects them.
- [ ] Feature flags / config documented; safe defaults.
- [ ] Migration/rollout/rollback considered for risky changes.

## Hygiene

- [ ] CI green: build, tests, lint, format, type-check.
- [ ] Docs/README/changelog updated if behavior or usage changed.
- [ ] PR description explains what, why, and how it was tested.
