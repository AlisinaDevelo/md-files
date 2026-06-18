---
name: conventional-commits
description: >-
  Use when writing git commit messages and structuring commits. Covers the
  Conventional Commits format, choosing the right type/scope, breaking-change
  notation, and how to split work into small, atomic, reviewable commits.
---

# Conventional Commits

A commit message format that's both human- and machine-readable, enabling automated
changelogs and semantic versioning.

## Format

```text
<type>(<optional scope>): <description>

<optional body — what & why, wrapped at ~72 cols>

<optional footer — BREAKING CHANGE:, Refs:, Closes:>
```

- **Description**: imperative mood, lowercase, no trailing period, ≤ ~72 chars.
  "add retry to fetch" not "added retries" / "adds a retry".
- **Body**: explain *why* and the context a reviewer needs — not a restatement of the
  diff. Optional for trivial changes.

## Types

| Type | Use for | SemVer |
|------|---------|--------|
| `feat` | a new feature | MINOR |
| `fix` | a bug fix | PATCH |
| `docs` | documentation only | — |
| `style` | formatting, no logic change | — |
| `refactor` | behavior-preserving restructuring | — |
| `perf` | performance improvement | PATCH |
| `test` | adding/fixing tests | — |
| `build` | build system or dependencies | — |
| `ci` | CI configuration | — |
| `chore` | maintenance, no src/test change | — |
| `revert` | reverting a prior commit | — |

## Breaking changes

Either append `!` after the type/scope, or add a `BREAKING CHANGE:` footer (or both):

```text
feat(api)!: remove deprecated v1 auth endpoints

BREAKING CHANGE: clients on /v1/auth must migrate to /v2/auth before upgrading.
```

This triggers a MAJOR version bump.

## Atomic commits

One logical change per commit. A commit should be independently reviewable and
revertable. If the message needs "and," consider splitting. Don't mix a refactor with a
behavior change — reviewers can't tell which lines changed behavior. Stage in hunks
(`git add -p`) to keep them clean.

## Examples

```text
fix(cart): prevent negative quantity on rapid decrement clicks
feat(auth): add TOTP-based two-factor login
refactor(pricing): extract tax calculation into PricingService
perf(search): add composite index to cut p95 query time 8x
docs(readme): document the local dev bootstrap steps
```

Keep messages factual and about *what changed* (and why in the body) — not a narrative
of your process.
