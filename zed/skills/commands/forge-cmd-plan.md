---
name: forge-cmd-plan
description: Produce a step-by-step implementation plan before writing code
disable-model-invocation: true
---

Produce an implementation plan for what the user described. Do not write implementation code — plan it.

Use any text the user typed after the command as the feature or change to plan.

First, read the codebase to understand the system you're planning within: relevant modules, data models, conventions, and boundaries.

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
- <decision that needs the user's input before proceeding>

## Out of scope
<what this explicitly does not do>
```

Bias toward the simplest design that satisfies the requirements. Order steps so the system stays working between them. If the request is underspecified in a way that changes the design, ask before guessing.
