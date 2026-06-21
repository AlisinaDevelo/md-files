---
name: caching-strategies
description: >-
  Use when designing or debugging a cache — choosing a caching pattern, setting TTLs
  and invalidation, picking a layer (client/CDN/app/DB), or fixing staleness, a low
  hit rate, or a stampede. Complements performance-profiling (which finds the
  bottleneck); this decides whether and how to cache it.
---

# Caching Strategies

A cache trades freshness and complexity for speed. The famous hard part is real: **cache
invalidation.** Add a cache only when you've measured that the underlying work is the
bottleneck and the data tolerates some staleness — caching the wrong thing adds bugs for no
gain.

## Before you cache

- **Measure first.** Is this read actually hot and expensive? (Pair with
  `performance-profiling`.) Caching a cold path is pure complexity.
- **Can it be stale?** Decide the acceptable staleness window per dataset. "Must be exact"
  data (balances, inventory at checkout) needs a different approach than "good enough"
  (a profile name, a product description).

## Patterns

- **Cache-aside (lazy):** app checks cache, on miss loads from source and populates. Simple,
  the default. Risk: stampede on a cold/expired key.
- **Read-through / write-through:** the cache layer owns load/store. Keeps cache and source
  consistent on write; adds write latency.
- **Write-behind:** write to cache, flush to source async. Fast writes, but risks data loss
  and consistency gaps — use only when you can tolerate both.

## Invalidation — the crux

- **TTL** is the simplest correctness backstop: even if you forget to invalidate, the entry
  expires. Set it to the staleness you can tolerate. Add **jitter** so keys don't all expire
  at once (synchronized expiry causes a stampede).
- **Explicit invalidation** on write (delete/update the key) for data that must be fresh
  soon after a change — but it's easy to miss a write path, so pair it with a TTL.
- **Key design matters:** include every input that changes the result (params, version,
  tenant, locale). A key that omits an input serves one user's data to another — a cache
  key bug is a correctness/security bug.

## The failure modes to design against

- **Stampede / thundering herd:** many requests miss the same hot key at once and all hit
  the source. Mitigate with a short lock/single-flight on recompute, or serve-stale-while-
  revalidate.
- **Cold cache after deploy/restart:** the source gets the full load with no cache. Pre-warm
  hot keys, or ramp traffic.
- **Inconsistency:** the cache and source disagree. TTL bounds how long; explicit
  invalidation shortens it; accept that a cache is eventually consistent and design for it.
- **Unbounded growth:** set a max size and an eviction policy (LRU/LFU) — an unbounded cache
  is a memory leak.

## Layers

Cache as close to the user as the freshness allows: client/browser → CDN/edge → application
(in-process or shared store like Redis) → database/query cache. Each layer multiplies the
invalidation surface, so push outward only what tolerates the added staleness.
