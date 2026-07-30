# Task Template

The local-backend format: one markdown file per task at `.forge/tasks/<id>.md`, where `<id>`
is zero-padded and stable (e.g. `0007-rate-limit-middleware.md`). Copy this shape.

```markdown
---
id: 0007
title: Implement the rate-limit middleware
status: ready            # backlog | ready | in-progress | review | done | blocked
agent: frontend-specialist
model: sonnet            # haiku | sonnet | opus | fable
depends_on: [0006]       # ids that must be done first ([] if none)
change: null             # optional stack branch/change id; not dependency state
---

## Goal
One or two sentences: what this task delivers and why it matters to the overall goal.

## Acceptance criteria
- [ ] The concrete, checkable conditions for "done" — the test that passes, the behavior
      observed, the invariant that holds. If you can't write these, the task isn't ready.
- [ ] …

## Context
What the specialist needs that it can't see: the plan this fits into, what's already been
ruled out, the exact files/paths, the conventions to follow.

## Notes
(Filled during work — decisions made, links to the diff/PR, why the approach changed.)
```

## Status board (optional index)

Keep a `.forge/tasks/README.md` as an at-a-glance board so the conductor and a human can see
the run without opening every file:

```markdown
| id | title | status | agent | model | depends_on |
|----|-------|--------|-------|-------|------------|
| 0006 | Design the limiter | done | architect | opus | — |
| 0007 | Implement middleware | ready | frontend-specialist | sonnet | 0006 |
| 0008 | Tests incl. bursts | backlog | test-engineer | sonnet | 0007 |
```

## GitHub-backed variant

When mirroring to GitHub issues, the mapping is direct: **title → issue title**, **Goal +
Acceptance criteria + Context → issue body**, **status → labels or the issue's open/closed
state + a `status:` label**, **depends_on → a task-list or "blocked by #6" in the body**,
**agent/model → a line in the body** (`Assigned: frontend-specialist @ sonnet`). Create with
`gh issue create --title … --body …`; close with `gh issue close` once acceptance criteria
verifies.
