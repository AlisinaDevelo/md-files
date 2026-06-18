---
name: root-cause-debugging
description: >-
  Use when diagnosing a bug, failing test, crash, or wrong output. A disciplined,
  hypothesis-driven method for finding the true root cause from evidence instead of
  guessing or masking symptoms. Use before writing any fix.
---

# Root-Cause Debugging

Find the originating wrong assumption, not the nearest symptom. Fixes applied to
symptoms create more bugs; fixes applied to causes are durable.

## The method

1. **Reproduce deterministically.** Capture the exact command, inputs, environment, and
   full error/trace. If it's flaky, find what flips it — ordering, timing, shared state,
   uninitialized data. You can't fix what you can't trigger on demand.
2. **Read the trace from your deepest frame outward.** Locate the implicated code and
   *read it* — don't infer behavior from names.
3. **Form a falsifiable hypothesis.** "X is null here because Y returns null when Z."
   State what you'd observe if it's true.
4. **Test it with evidence.** A targeted log/print, a narrowed test, an inspected value,
   a minimal reproducer. Confirm or kill the hypothesis. Iterate. Never assert a cause
   you haven't observed.
5. **Trace to the origin.** A wrong value at line 200 was usually set at line 40. Walk
   backward until reality first diverged from intent. That's the root cause.
6. **Fix the cause, then verify.** Re-run the failing case *and* its neighbors to confirm
   the fix works and breaks nothing.

## Techniques

- **Bisect** — `git bisect` to find the introducing commit; binary-search the input or
  the code path to halve the search space each step.
- **Rubber-duck** — explain the flow aloud; the wrong assumption often surfaces mid-
  sentence.
- **Minimal reproducer** — strip the case to the smallest thing that still fails.
- **Differential** — what's different between the passing and failing case? Environment,
  data, version, order.

## Anti-patterns (these hide bugs, they don't fix them)

- Wrapping in try/catch to silence an exception you don't understand.
- Adding `if (x == null) return` without asking why `x` is null.
- Retrying a deterministic failure.
- Changing a test's expected value to match buggy output.

## When stuck

State your current hypothesis, the evidence for and against it, and the single
experiment that would confirm or refute it next. Don't thrash — each action should
eliminate possibilities.
