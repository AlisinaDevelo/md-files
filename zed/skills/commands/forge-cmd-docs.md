---
name: forge-cmd-docs
description: Write or update documentation grounded in the actual code
disable-model-invocation: true
---

Write documentation for what the user specified (a file, module, API, or "README").

Use any text the user typed after the command as the documentation target — a file path, module name, symbol, or doc type (e.g. "README", "API reference").

Read the code and any existing docs first. Every claim must be verified against the source — don't document assumed behavior. Match the project's existing doc voice and structure.

- **README** → what it is, quickstart that actually runs, common tasks, links. No wall of prose before the first command.
- **API reference** → per public symbol: signature, params (types + constraints), return, errors, a short real example.
- **Architecture/ADR** → context, decision, alternatives, consequences (the *why*).
- **Docstrings** → what it does, params, returns, raises, example for non-trivial code.

Write for the reader's task: lead with how to use it, then how it works. Use minimal runnable examples derived from real signatures/tests. Deliver clean Markdown ready to commit, and flag anything you couldn't verify from the code.
