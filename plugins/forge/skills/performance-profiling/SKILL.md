---
name: performance-profiling
description: >-
  Use when investigating a performance problem — slow endpoints, high latency,
  memory/CPU pressure, or N+1 queries. A measure-first method to find the real
  bottleneck and verify the gain, instead of guessing at optimizations.
---

# Performance Profiling

The first rule: **measure before you optimize.** Intuition about where time goes is
wrong often enough that acting on it wastes effort and risks making things slower.

## Method

1. **Define the metric and target.** Latency (p50/p95/p99), throughput, memory, CPU, or
   query count — and what "fast enough" is. No target means no way to know you're done.
2. **Reproduce and profile.** Trigger the slow path under realistic conditions and
   measure where time/resources go: a profiler/flame graph, request timing, query logs,
   `EXPLAIN ANALYZE`, allocation traces, a benchmark. Suspect, then confirm.
3. **Attack the dominant cost (Amdahl's law).** Optimizing a 5% cost caps your gain at
   5%. Find and fix what dominates the profile.
4. **Re-measure with the same method.** Report before/after. A change with no measured
   improvement isn't an optimization — revert it.
5. **Guard against regression.** Note trade-offs (memory↔speed, cache invalidation,
   complexity). Consider a benchmark in CI for the hot path.

## High-yield bottlenecks

- **N+1 queries** — a query per row in a loop → batch/eager-load. Usually the single
  biggest backend win.
- **Missing/!used index** — full scans on a filtered/sorted column → add the right
  composite index in the right column order.
- **Repeated work** — recomputing inside a loop what could be hoisted out, or caching
  what's stable (with an invalidation story).
- **Wrong data structure** — O(n²) where a set/map gives O(n); linear scans of large
  lists.
- **Serial I/O** — independent network/disk calls run sequentially → parallelize.
- **Over-fetching / over-serializing** — pulling and marshalling data you discard.
- **Allocation churn** — allocations in a hot loop → reuse buffers, reduce copies.

## Discipline

- Don't micro-optimize cold paths or trade clarity for gains that don't move the metric.
- Don't add caching without invalidation.
- A faster wrong answer is still wrong — confirm behavior is unchanged.

Premature optimization wastes time; *informed* optimization, targeted by measurement at
the dominant cost, is one of the highest-leverage things you can do.
