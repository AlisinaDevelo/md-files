# Model-Routing Policy

The point of orchestration is to spend model capability where it changes the outcome and
save it everywhere else. Route each task to a tier by the *kind of thinking it needs*, not
by how important the overall project feels.

## The tiers

Claude Code accepts these `model` values on an agent's frontmatter and as a per-delegation
override on the Agent tool: `haiku`, `sonnet`, `opus`, `fable`, a full model id, or
`inherit`. Rough capability/cost ordering: **Haiku < Sonnet < Opus < Fable**.

| Tier | Use it for | Examples |
|------|-----------|----------|
| **Fable / Opus** | Deep reasoning where a wrong plan is expensive: architecture, decomposition, gnarly root-cause debugging, security threat modeling, ambiguous "figure out how" work. | Design the migration; find the intermittent race; plan the whole feature. |
| **Sonnet** | The bulk of the work: implementing a well-specified task, writing tests, refactoring with a safety net, writing docs, code review. | Implement the ticket; add tests for module X; write the README. |
| **Haiku** | Mechanical, well-defined, high-volume, or parallel-fan-out work where judgment is minimal. | Rename across files; scaffold boilerplate; wide codebase search; format/lint sweeps; a first-pass triage of many items. |

## The routing heuristic

Ask of each task: **"If this is done slightly wrong, how expensive is the mistake, and how
much judgment does getting it right require?"**

- High judgment / expensive-if-wrong → **Opus or Fable**. Use **Fable** for the hardest,
  longest-horizon reasoning and the most ambiguous "own this and figure it out" work; **Opus**
  for strong reasoning at lower cost.
- Well-specified, moderate judgment → **Sonnet**. This should be *most* of your delegations.
- Low judgment, mechanical, or a wide parallel fan-out → **Haiku**.

Default the main conversation (the conductor) to **Opus or Fable** so planning is strong,
then delegate *down* the tiers for execution. Delegating a boilerplate rename to Fable wastes
money; planning a system with Haiku wastes the whole run.

## Setting the model

- **Per specialist agent** — the `model:` in its frontmatter is its default tier (e.g.
  `architect` and `tech-lead` default to `opus`; most execution agents to `sonnet`).
- **Per delegation** — override it on the Agent tool call (`model: "haiku"`) when *this*
  instance of the task wants a different tier than the agent's default. The override wins.
- **The conductor** — set the main model with `/model` (e.g. `claude-fable-5` or
  `claude-opus-4-8`) before an `/orchestrate` run so the planning happens at the right tier.

## A worked routing

Goal: "Add rate limiting to our public API."

- Plan the approach and decompose → **conductor, Opus/Fable**.
- Design the limiter (algorithm, storage, headers) → `architect`, **Opus**.
- Implement the middleware → `frontend-specialist`/impl, **Sonnet**.
- Write tests incl. burst/edge cases → `test-engineer`, **Sonnet**.
- Threat-model the new surface → `security-auditor`, **Opus**.
- Update the API docs and changelog → `docs-writer` / `/changelog`, **Haiku or Sonnet**.
- Sweep call sites that must set the new header → **Haiku** (mechanical, parallel).
