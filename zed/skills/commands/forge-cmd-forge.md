---
name: forge-cmd-forge
description: Choose the right Forge agent, skill, command, bundle, or workflow for a goal
disable-model-invocation: true
---

Help choose and start the right Forge capability for the user's goal.

Use the `forge-catalog` skill. Prefer the smallest useful route: direct work for small
tasks, `/forge-cmd-orchestrate` for large ambiguous goals, a specialist skill for focused
depth, or a bundle/workflow when the user needs a role-based starting point.

Return the recommended route, why it fits, and the exact next prompt or command to run.
