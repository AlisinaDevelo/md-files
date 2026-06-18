---
description: Diagnose a bug or failing test and find the root cause before fixing
argument-hint: "<the error, failing test, or wrong behavior>"
allowed-tools: Read, Grep, Glob, Bash
model: sonnet
---

Diagnose this problem and find the root cause: $ARGUMENTS

Work the hypothesis-driven method — do not jump to a fix:

1. **Reproduce** deterministically. Establish the exact command, inputs, and full
   error/trace. If it's flaky, find what flips it.
2. **Localize** — read the trace from the deepest frame you own outward; read the actual
   implicated code.
3. **Hypothesize** — state a specific, falsifiable cause and what you'd observe if true.
4. **Test it** with evidence (a targeted log, narrowed test, inspected value). Confirm or
   kill it. Iterate.
5. **Trace to the origin** — walk backward to where reality first diverged from intent.

Then report: symptom, root cause (with `file:line` and the symptom←cause chain), the
evidence that proves it, the minimal fix that addresses the *cause*, and how to verify.
Do not mask the symptom with a try/catch or defensive check. If you can't reach
certainty, say so and give the next experiment that would confirm it.
