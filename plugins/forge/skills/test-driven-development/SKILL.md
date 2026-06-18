---
name: test-driven-development
description: >-
  Use when implementing a feature or fixing a bug test-first: write a failing test,
  make it pass with the minimum code, then refactor. Covers the red-green-refactor
  loop, what is worth testing, and the common pitfalls that make TDD backfire.
---

# Test-Driven Development

Write the test before the code. The test specifies the behavior; the code satisfies
it. This keeps the design testable, catches regressions immediately, and produces a
suite that documents intent.

## The loop: Red → Green → Refactor

1. **Red.** Write one small test for the next increment of behavior. Run it. It must
   fail — and fail for the *right reason* (the behavior is missing, not a typo). A test
   that passes before you write the code tests nothing.
2. **Green.** Write the minimum code to make it pass. Resist building beyond the test.
   Ugly-but-correct is fine here.
3. **Refactor.** With the test green as a safety net, clean up — names, duplication,
   structure. Re-run; stay green. Refactor the test too if it got messy.

Keep the steps small. A cycle should be minutes, not an afternoon. Commit at green.

## Bug fixing with TDD

Reproduce the bug as a failing test *first*. It pins the defect, proves the fix works,
and prevents regression. If you can't write a test that fails on the current code, you
don't yet understand the bug — go investigate before fixing.

## What to test

- The contract: inputs → outputs and side effects, not internal mechanics.
- Boundaries: 0, 1, n, max, empty, null, overflow.
- Failure paths: invalid input, downstream errors, partial failure.
- The specific behavior this change introduces.

## Pitfalls

- **Testing implementation, not behavior** → tests break on every refactor and stop
  catching real bugs. Assert observable results.
- **Tests that can't fail** → no negative-control; verify the test fails before you make
  it pass.
- **Over-mocking** → a test of mocks proving mocks were called. Mock only at real
  boundaries (network, clock, filesystem).
- **Skipping refactor** → green-and-move-on accrues mess. The third step isn't optional.
- **Giant tests** → many reasons to fail. One behavior per test.

## When strict TDD doesn't fit

Exploratory spikes, throwaway prototypes, and hard-to-test legacy edges may warrant
test-after or characterization tests instead. Be deliberate about the exception rather
than abandoning the discipline by default.
