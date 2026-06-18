# TypeScript / JavaScript Instructions

Paste the relevant lines into a project `CLAUDE.md`. Keep only what's true for the repo.

## Types

- `strict` mode on. No `any` — use `unknown` and narrow, or a precise type. No
  non-null `!` assertions to silence the compiler; fix the type instead.
- Prefer `type`/`interface` that mirror the domain. Make illegal states unrepresentable
  (discriminated unions over loose flags).
- Type the boundaries (API responses, env, params) with a runtime validator (zod/valibot)
  — don't trust `as`.

## Style

- `const` by default; `let` only when reassigned. No `var`.
- Pure functions where practical; isolate side effects.
- Prefer immutable updates over mutation in shared state.
- Use the project's module style consistently (ESM vs CJS); respect path aliases.

## Async

- `async/await` over raw `.then()` chains. Always handle rejection.
- Don't fire-and-forget promises; `await` or explicitly `void` with a reason.
- Parallelize independent awaits with `Promise.all`; don't serialize by accident.

## React (if applicable)

- Function components + hooks. Follow the rules of hooks.
- Lift state only as far as needed; derive, don't duplicate.
- Stable keys (not array index for dynamic lists). Memoize only where the profiler shows
  it pays. Handle loading/empty/error states for every async surface.

## Tooling

- Respect the repo's ESLint/Prettier/tsconfig — don't override. Run type-check + lint
  before declaring done.
- Match the existing test framework (Vitest/Jest) and assertion style.
