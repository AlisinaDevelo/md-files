# Usage Patterns

How the agents, skills, commands, and hooks combine in real workflows. The toolkit is
designed so the right capability surfaces at the right moment — these are the seams.

## The development loop

When you are unsure which Forge route fits, start with `/forge <goal>`. It chooses the
smallest useful agent, skill, command, bundle, or workflow.

```mermaid
flowchart LR
  plan["plan\narchitect / /plan"] --> impl[implement]
  impl --> review["review\ncode-reviewer / /review"]
  review --> test["test\ntest-engineer / /test"]
  test --> debug["debug\ndebugger / /debug"]
  debug --> commit["/commit"]
  commit --> pr["/pr"]
```

1. **Plan.** For anything non-trivial, start with `/plan` (or the `architect` agent). Get
   a step-by-step plan and surface the risks before writing code.
2. **Implement.** Write the change. The `prompt-engineering`, language, and
   `engineering-principles` instructions keep the model on-style and minimal.
3. **Review.** Run `/review` on the diff. The `code-review-rubric` skill backs the
   severity ranking; the `code-reviewer` agent does the deep pass.
4. **Test.** `/test` writes behavior-focused tests matching your harness; the
   `test-driven-development` skill guides the red-green-refactor loop when you go
   test-first.
5. **Debug.** When something breaks, `/debug` or the `debugger` agent runs the
   hypothesis-driven, root-cause method instead of patching symptoms.
6. **Ship.** `/commit` writes a Conventional Commit; `/pr` drafts the description.

## Specialist deep-dives

Pull in a specialist agent when a task needs depth:

- Touching auth, payments, or user input? → `security-auditor` / `/security-scan`.
- Slow endpoint or memory pressure? → `performance-optimizer` / `/optimize`.
- Schema change on a live DB? → `database-expert` + the `safe-database-migrations` skill.
- Building UI? → `frontend-specialist`, then `accessibility-auditor` before done.
- Before a release? → `dependency-auditor` for CVEs and upgrade planning.

## Orchestrating big work

For a large, ambiguous task, run `/orchestrate <goal>`. The main conversation acts as the
conductor because it can spawn specialist subagents; subagents themselves cannot spawn
more subagents. That one fact keeps the design honest: plan and coordinate from the main
loop, then delegate concrete tasks outward.

```mermaid
flowchart LR
  goal["goal"] --> plan["plan at Opus/Fable"]
  plan --> ledger[".forge/tasks ledger"]
  ledger --> route["route agent + model"]
  route --> dispatch["dispatch ready tasks"]
  dispatch --> verify["verify acceptance criteria"]
  verify --> update["update ledger"]
  update --> route
  update --> done["done or blocked"]
```

The default backend is local markdown: `.forge/tasks/<id>-<slug>.md` plus an optional
`.forge/tasks/README.md` board. Each task records status, dependencies, acceptance
criteria, assigned specialist, and model tier. Use GitHub issues with `/tasks sync-gh`
when GitHub should be the source of truth; use Jira/Linear through MCP if those servers
are connected.

Model routing is explicit:

- **Opus/Fable** — planning, architecture, hard debugging, security design, ambiguous
  "figure out how" work.
- **Sonnet** — implementation, tests, docs, normal refactors, most concrete tasks.
- **Haiku** — mechanical edits, broad searches, scaffolding, format/lint sweeps.

Use `/solve-loop` to drain an existing ledger. It repeatedly finds ready tasks, dispatches
them, verifies real evidence against acceptance criteria, and updates status until the
ledger is done or genuinely blocked. The ledger is the source of truth; a specialist
summary is never enough to mark a task done.

## Always-on guardrails

The hooks run automatically in the background:

- **Dangerous-command guard** blocks catastrophic shell commands (`rm -rf /`, force-push
  to main, fork bombs).
- **Secret scanner** blocks writing credentials into files.
- **Auto-format** runs your formatter after every edit.
- **Notify** pings you when a turn finishes.

These need no invocation — they shape every session quietly.

## Layering instructions

`~/.claude/CLAUDE.md` (how *you* work) → project `CLAUDE.md` (how *this repo* works) →
nested `CLAUDE.md` (how *this subsystem* works). Lower, more-specific files win. Keep each
short and high-signal.
