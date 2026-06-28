---
name: forge-cmd-explain
description: Explain how a file, function, or system works — clearly and accurately
disable-model-invocation: true
---

Explain what the user specified (a file path, symbol, or concept).

Use any text the user typed after the command as the target to explain — a file path, function name, class, module, or concept.

Read the actual code before explaining — don't infer behavior from names. Then explain at the right altitude:

1. **Purpose** — what it does and why it exists, in one or two sentences.
2. **How it works** — the flow, the key data structures, and the important decisions. Trace the main path end to end.
3. **Contracts & edges** — inputs, outputs, side effects, error handling, and any non-obvious assumptions or gotchas.
4. **Connections** — how it fits with the surrounding code (callers, dependencies).

Use concrete references (`file:line`) so the user can follow along. Call out anything that looks buggy, surprising, or risky. If something is genuinely unclear from the code, say so rather than guessing.
