---
description: Choose the right Forge agent, skill, command, bundle, or workflow for a goal
argument-hint: "<goal, workflow, bundle, or capability question>"
allowed-tools: Read, Grep, Glob, Bash
model: sonnet
---

Help choose and start the right Forge capability for: $ARGUMENTS

Use the `forge-catalog` skill. Read only the catalog files needed for the decision:

- Catalog summary: !`sed -n '1,220p' CATALOG.md 2>/dev/null || echo "(CATALOG.md missing)"`
- Bundles/workflows: !`sed -n '1,260p' docs/bundles-and-workflows.md 2>/dev/null || echo "(bundles doc missing)"`

Return:

1. The recommended Forge route: command, skill, agent, bundle, or workflow.
2. Why this route is the smallest useful one.
3. The exact next prompt or command the user can run.

If the request is already clearly a direct coding task, do not over-route it. Say which
Forge method applies and proceed with the work.
