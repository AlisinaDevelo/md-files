---
name: concurrency-and-parallelism
description: >-
  Use when writing or reviewing concurrent code — threads, async/await, shared
  state, locks, and parallel work — or diagnosing a race condition, deadlock, or
  heisenbug that only appears under load. Covers the patterns that make concurrency
  correct and the traps that make it intermittently wrong.
---

# Concurrency & Parallelism

Concurrency is about *dealing with* many things at once (structure); parallelism is about
*doing* many things at once (execution). Both share the hard part: **shared mutable state.**
The defining trait of concurrency bugs is that they're intermittent and timing-dependent —
which is why they slip through tests and surface under production load.

## The core rule

**Don't share mutable state. If you must, protect every access to it.** Most concurrency
bugs are an unsynchronized read or write of state two tasks touch. The cheapest fix is
usually to *not share*: give each task its own data, communicate by passing messages/values,
and confine mutable state to one owner.

## Patterns that work

- **Immutability** — data that never changes after creation is automatically safe to share.
  Prefer it.
- **Confinement** — one thread/task owns a piece of state; others ask it, never touch it
  directly (the actor model, a single writer, a worker that owns a connection).
- **Message passing over shared memory** — hand off values through a queue/channel instead
  of locking a shared structure. Easier to reason about than a web of locks.
- **Bounded parallelism** — a worker pool / semaphore with a fixed size. Unbounded
  goroutines/threads/promises are a resource-exhaustion outage.

## When you do use locks

- Hold locks for the shortest span; never do I/O or call out to unknown code while holding
  one.
- **Acquire multiple locks in a consistent global order** — out-of-order acquisition is the
  classic deadlock. Better: don't hold more than one.
- Pick the right primitive: mutex for exclusive, read-write lock for read-heavy, atomic for
  a single counter/flag. A lock around a single increment is overkill; a missing one is a
  bug.

## Async-specific traps

- **Don't block the event loop** with sync I/O or CPU-bound work — it stalls every other
  task. Offload to a thread/process pool.
- **Await your futures.** A fire-and-forget promise swallows errors and races shutdown.
- **Parallelize independent awaits** (`Promise.all`/`gather`); don't serialize them by
  accident with sequential awaits.

## Idempotency and ordering

Anything that may run twice (retries, at-least-once delivery, a re-fired event) must be
**idempotent** — design the operation so a duplicate is harmless (idempotency keys,
upserts, dedup). Don't assume ordering across concurrent producers unless you enforce it.

## Diagnosing a race

It reproduces under load/ordering, not deterministically. Find what state two tasks share
and which access is unsynchronized; a thread/race sanitizer or targeted logging of the
interleaving confirms it. Don't "fix" it by adding a `sleep` — that hides the race, it
doesn't remove it (see `root-cause-debugging`). The fix is to remove the sharing or
synchronize the access, then prove it with the sanitizer or a stress test.
