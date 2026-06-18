---
name: error-handling
description: >-
  Use when designing how code handles failure — where to catch, what to propagate,
  fail-fast vs recover, retries and idempotency, and error types. Covers building
  robust failure paths without swallowing bugs or over-engineering for impossible
  cases.
---

# Error Handling

The failure path is real code and deserves the same care as the happy path — but more
errors are made by handling errors *wrong* (swallowing them) than by not handling them.

## Where to handle

- **Handle at the level that can do something about it.** A function that can't recover
  should propagate, not catch-and-log-and-continue. Catch where you can retry, fall back,
  translate to a user-facing result, or add context — not just to make the error quiet.
- **Validate at the boundary, trust inside.** Check untrusted input where it enters
  (request handlers, file/CLI/env parsing) and convert it to valid domain types. Inside
  the boundary, code can assume validity instead of re-checking everywhere.
- **Fail fast on programmer errors** (bugs: null where impossible, broken invariants) —
  crash loudly in dev/test so they're found. **Recover from operational errors** (network
  down, file missing, bad input) — these are expected and the program should handle them.

## What to propagate

- Add context as the error travels up: *what* you were doing when it failed, not just the
  low-level cause. Wrap, don't replace — keep the original cause inspectable (`%w` in Go,
  `raise ... from e` in Python, `cause` in JS).
- Use distinct error types/codes so callers can branch on them programmatically, instead
  of string-matching messages.
- Don't leak internals to users: log the detail, return a safe, actionable message.

## Retries and idempotency

- Retry only *transient* failures (timeouts, 429, 503) — never a deterministic 4xx or a
  validation error; that just loops.
- Use exponential backoff with jitter and a cap on attempts. Unbounded retries are an
  outage amplifier.
- Make any operation that may be retried **idempotent** (idempotency keys, upserts) so a
  retry can't double-charge or double-create.

## Resources and partial failure

- Release resources on every path — `finally`/`defer`/context managers/`using`. A handle
  leaked only on the error path is the bug you find under load.
- Leave state consistent on failure: a partial operation should roll back or be safely
  resumable, not leave half-written data.

## Anti-patterns (these hide bugs)

- Empty `catch {}` / bare `except:` that swallows everything.
- Catching to log and then continuing as if nothing happened.
- Defensive checks for cases that cannot occur — they add noise and hide the one that
  can. Don't handle impossible scenarios; trust internal guarantees.
- Using exceptions for normal control flow across module boundaries.

The goal isn't maximum error handling — it's handling the errors that can actually happen,
at the right level, while letting bugs surface loudly.
