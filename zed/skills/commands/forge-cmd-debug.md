---
name: forge-cmd-debug
description: Diagnose a bug or failing test and find the root cause before fixing
disable-model-invocation: true
---

Diagnose the problem the user described and find the root cause. Do not jump to a fix.

Use any text the user typed after the command as the problem description — a symptom, error message, failing test name, or reproduction steps.

Work the hypothesis-driven method:

1. **Reproduce** deterministically. Establish the exact command, inputs, and full error/trace. If it's flaky, find what flips it.
2. **Localize** — read the trace from the deepest frame you own outward; read the actual implicated code.
3. **Hypothesize** — state a specific, falsifiable cause and what you'd observe if true.
4. **Test it** with evidence (a targeted log, narrowed test, inspected value). Confirm or kill it. Iterate.
5. **Trace to the origin** — walk backward to where reality first diverged from intent.

Then report:

- Symptom (what fails, exact error, repro command)
- Root cause (with `file:line` and the symptom ← cause chain)
- Evidence that proves it
- The minimal fix that addresses the *cause*
- How to verify

Do not mask the symptom with a try/catch or defensive check. If you can't reach certainty, say so and give the next experiment that would confirm it.
