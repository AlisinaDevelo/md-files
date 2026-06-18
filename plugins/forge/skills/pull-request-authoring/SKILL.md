---
name: pull-request-authoring
description: >-
  Use when opening a pull request — writing the description, sizing the change, and
  making it easy and fast to review. Covers PR structure, what reviewers need, and
  how to keep PRs small enough to actually get good review.
---

# Pull Request Authoring

A PR is a request for someone's time and trust. Make it cheap to grant: small, clearly
motivated, and easy to verify.

## Size it to be reviewable

Small PRs get better review and merge faster. Aim for a focused change a reviewer can
hold in their head — roughly under ~400 lines of meaningful diff. If it's bigger, split
by concern: refactor separately from behavior change; mechanical changes (renames,
formatting) in their own PR so the substantive diff stands out.

## Description structure

```text
## What
<one-paragraph summary of the change>

## Why
<the problem or motivation; link the issue/ticket>

## How
<the approach, and any non-obvious decisions or trade-offs>

## Testing
<how you verified it — tests added, manual steps, before/after>

## Screenshots / output
<for UI or CLI changes>

## Notes for reviewers
<where to focus, known limitations, follow-ups deliberately left out>
```

Lead with *what* and *why* — a reviewer who understands the intent reviews the diff far
better. Don't make them reverse-engineer the goal from the code.

## Before you open it

- Self-review the diff first; you'll catch the obvious stuff and spare the reviewer.
- Ensure CI is green: build, tests, lint, format.
- Remove debug output, commented-out code, and unrelated changes.
- Confirm the PR does one thing. Scope creep is the most common review-killer.

## Reviewer experience

- Call out the riskiest part and where to focus attention.
- Explain non-obvious choices inline as PR comments so reviewers don't have to ask.
- Respond to feedback by fixing or discussing — don't relitigate settled decisions.
- Keep the branch up to date but don't force-push over in-progress review threads.

## Anti-patterns

A 2,000-line PR titled "updates." Mixing a dependency bump with a feature. A description
that just says "see commits." No testing notes. These all push cost onto the reviewer
and slow everyone down.
