---
name: forge-cmd-optimize
description: Diagnose and fix a performance problem, measuring before and after
disable-model-invocation: true
---

Investigate and optimize the performance problem the user described. Measure first — do not change code on intuition.

Use any text the user typed after the command as the performance problem description — a slow endpoint, high-latency function, memory issue, or specific file/path to investigate.

1. Define the metric and target (latency p50/p95/p99, throughput, memory, CPU, query count) and what "fast enough" means.
2. Reproduce and profile the slow path: timing, profiler/flame graph, query logs, `EXPLAIN ANALYZE`, or a benchmark. Find where time/resources actually go.
3. Attack the dominant cost (Amdahl's law). Look for N+1 queries, missing indexes, repeated work in loops, serial I/O that could be concurrent, wrong data structures, over-fetching, allocation churn.
4. Apply the fix, then re-measure with the same method. Report before/after numbers.
5. Note trade-offs and whether a CI benchmark should guard the gain.

A change with no measured improvement isn't an optimization — say so and revert it. Confirm behavior is unchanged: a faster wrong answer is still wrong.
