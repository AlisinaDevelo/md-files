# Evals — the evidence layer

Most agent/skill repos ship prompts and ask you to trust them. Forge ships **evidence**:
a reproducible way to show the components do what their descriptions promise. This is the
difference between "I wrote some prompts" and "I can demonstrate these prompts work."

Evidence splits into two tiers, matching the two kinds of artifact in this repo.

## 1. Static prompt-quality checks (free, gated in CI)

```bash
python3 evals/run.py        # or: just eval
```

A linter for *prompts*. For every agent, skill, and command it verifies the properties
that make an LLM artifact actually fire and actually help:

- **Triggering** — agent/skill descriptions start with a trigger ("Use …"/"Use when …")
  and include an example. A description that doesn't trigger is dead weight.
- **Sizing** — descriptions are within the length the model can use (40–1024 chars).
- **Tool scoping** — read-only agents (reviewers, auditors, debuggers) carry no `Edit`/
  `Write` tool; least privilege is enforced, not just intended.
- **Validity** — `model` and `color` values are legal; skill `name` matches its directory;
  commands that take `$ARGUMENTS` declare an `argument-hint`; commands that inject shell
  with `` !`…` `` declare `allowed-tools`.
- **Structure** — every system prompt has the headed sections a model can follow.

This is deterministic, needs no API key, and runs on every push — so the toolkit can't
regress into vague descriptions or over-privileged agents without CI catching it.

## 2. Behavioral eval — LLM judge (the gold standard)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 evals/run.py --judge   # or: just eval-llm
```

Static checks prove a prompt is *well-formed*; only a behavioral eval proves it *works*.
For each case in [`cases.jsonl`](cases.jsonl), the harness:

1. Loads the target agent's system prompt and its configured model.
2. Sends the case's task to the Claude API under that system prompt.
3. Has a judge model (default `claude-opus-4-8`) score the response against the case's
   explicit criteria and return a pass/fail.

The cases encode the behaviors that matter: the `code-reviewer` must catch a planted SQL
injection *and* not invent problems in clean code; the `debugger` must reach a race
condition as root cause and refuse to mask it with a retry; the `architect` must plan
rather than dump code. Each is a falsifiable claim about an agent, checked against a real
model run.

### Adding a case

Append one JSON object per line to `cases.jsonl`:

```json
{"id": "short-id", "type": "agent", "target": "code-reviewer", "prompt": "<the task>", "criteria": ["<gradeable criterion>", "..."]}
```

Write criteria the way the `threat-modeling`/`code-review-rubric` skills advise rubrics —
specific and independently checkable ("flags the SQL injection", not "is a good review").

## Why this matters

The `prompt-engineering` skill in this repo tells you to test your prompts. The evals are
that test, made real and runnable. They're also the honest answer to "does this actually
reflect skill, or is it just generated text?" — you can run them and see.
