---
description: Explain how a file, function, or system works — clearly and accurately
argument-hint: "<file path, symbol, or concept>"
allowed-tools: Read, Grep, Glob, Bash
model: sonnet
---

Explain: $ARGUMENTS

Read the actual code before explaining — don't infer behavior from names. Then explain
at the right altitude:

1. **Purpose** — what it does and why it exists, in one or two sentences.
2. **How it works** — the flow, the key data structures, and the important decisions.
   Trace the main path end to end.
3. **Contracts & edges** — inputs, outputs, side effects, error handling, and any
   non-obvious assumptions or gotchas.
4. **Connections** — how it fits with the surrounding code (callers, dependencies).

Use concrete references (`file:line`) so I can follow along. Call out anything that looks
buggy, surprising, or risky. If something is genuinely unclear from the code, say so
rather than guessing.
