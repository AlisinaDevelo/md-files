# Engineering Principles

Stack-agnostic principles to reference from a project's `CLAUDE.md` or to keep an agent
aligned. These encode the defaults a strong engineer applies without being told.

## Simplicity

- Write the minimum code that solves the problem. If 200 lines could be 50, write 50.
- No abstraction without at least two concrete call sites. Resist speculative generality.
- No error handling for scenarios that can't happen. No features beyond what was asked.
- Delete code. The best diff is often a negative one.

## Correctness first

- Make it correct, then make it clear, then make it fast — in that order.
- Handle the edges: empty, null, zero, one, many, max, overflow, and the failure path.
- Validate untrusted input at the boundary; trust it inside.
- A faster or prettier wrong answer is still wrong.

## Change discipline

- Touch only what the task requires. Don't refactor, reformat, or "improve" adjacent code.
- Separate refactoring from behavior change — never in the same commit.
- Keep changes small and reviewable. Commit in atomic increments.
- Match the existing style and conventions, even ones you'd do differently.

## Tests

- Test behavior, not implementation, so refactors don't break tests but bugs do.
- Cover the risk surface — edges and failures — not just the happy path.
- Reproduce a bug as a failing test before fixing it.
- Tests must be deterministic: no real clock, network, or ordering dependence.

## Security & data

- Never commit secrets. Use env vars or a secrets manager.
- Parameterize queries; encode output for its sink; authorize every protected action.
- Treat data as long-lived: get the model right, enforce integrity in the database,
  make migrations reversible.

## Communication

- State assumptions; ask when genuinely ambiguous; recommend rather than enumerate.
- Express uncertainty honestly — say what would confirm a claim.
- Report outcomes faithfully: failing tests, skipped steps, and partial results included.

## The two-hat rule

At any moment you are either **adding behavior** or **refactoring** — never both. Switch
hats deliberately and keep the diffs separate so reviewers can reason about each.
