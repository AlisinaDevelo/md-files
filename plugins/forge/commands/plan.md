---
description: Produce a step-by-step implementation plan before writing code
argument-hint: "<the feature, refactor, or task to plan>"
allowed-tools: Read, Grep, Glob, Bash
model: opus
---

Produce an implementation plan for: $ARGUMENTS

Do not write implementation code — plan it. First read the codebase to understand the
system you're planning within (relevant modules, data models, conventions, boundaries).

Deliver:

```text
## Goal
<one sentence>

## Approach
<chosen approach + one-line why; note rejected alternatives and why not>

## Key files & boundaries
- `path/...` — <role in this change>

## Plan
1. <step> — verify: <how to confirm this step is done & correct>
2. ...

## Risks & open questions
- <risk> → <mitigation>
- <decision that needs my input before proceeding>

## Out of scope
<what this explicitly does not do>
```

Bias toward the simplest design that satisfies the requirements. Order steps so the
system stays working between them. If the request is underspecified in a way that changes
the design, ask before guessing.
