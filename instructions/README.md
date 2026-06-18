# Instructions Library

Reusable `CLAUDE.md` building blocks. `CLAUDE.md` is the project memory Claude Code
loads automatically into every session — it's the highest-leverage place to encode how
*your* team works so the model follows it without being re-told each time.

## What lives here

| File | Use |
|------|-----|
| [`templates/CLAUDE.md.template`](templates/CLAUDE.md.template) | Annotated starting point for a project's `CLAUDE.md` |
| [`templates/global-CLAUDE.md`](templates/global-CLAUDE.md) | Personal defaults for `~/.claude/CLAUDE.md` (apply to every project) |
| [`engineering-principles.md`](engineering-principles.md) | Stack-agnostic principles to paste into or reference from a `CLAUDE.md` |
| [`languages/`](languages/) | Language/stack-specific guidance snippets |

## How to use

1. Copy `templates/CLAUDE.md.template` to your project root as `CLAUDE.md`.
2. Fill in the project-specific sections; delete what doesn't apply.
3. Pull in relevant snippets from `languages/` and `engineering-principles.md`.
4. Keep it short and high-signal — every line costs context budget and competes for
   attention. Prune anything Claude already does well by default.

## What makes a good CLAUDE.md

- **Specific over generic.** "Run `just test` before committing" beats "write good
  tests." Encode the things that are non-obvious or project-specific.
- **Imperative and testable.** Commands to run, conventions to follow, paths that matter.
- **The non-obvious only.** Don't restate what's discoverable from the code or what the
  model does anyway. Capture the tribal knowledge.
- **Layered.** Personal habits in `~/.claude/CLAUDE.md`; project rules in the repo's
  `CLAUDE.md`; subsystem rules in nested `CLAUDE.md` files closer to the code.
