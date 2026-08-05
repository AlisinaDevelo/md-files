---
id: 0016
title: Add generation-fenced worker heartbeats and recovery
status: done
agent: concurrency-engineer
model: sonnet
depends_on: [0014, 0015]
---

## Goal

Give long-running external effects a bounded heartbeat protocol and prevent stale workers
from mutating or re-submitting an effect after lease reclaim.

## Acceptance criteria

- [x] Current workers can heartbeat only before expiry and within a persisted maximum deadline.
- [x] Every claim and reclaim advances a lease generation; acknowledgement, failure, and
      provider submission authorization require the current worker plus generation.
- [x] Heartbeats, claims, and lease loss are reference-only evidence outside canonical history.
- [x] Pinned lease, heartbeat, timeout, cancellation, and retry policy revisions survive restart.
- [x] Crash, reclaim, same-worker generation reuse, deadline, and concurrency races are covered.
- [x] CLI inspection, schemas, docs, release surfaces, and full repository validation pass.

## Context

This is GitHub issue #54 after the transactional event/outbox boundary in #53. The design
follows Temporal activity heartbeats and idempotency, AWS outbox delivery, and Chubby-style
lock generation sequencers. Snapshots, human waits, adaptive routing, and distributed
backends remain separate roadmap slices.

## Verification

- `python3 -m pytest -q` - 197 passed
- `python3 evals/run.py` - 312/313 passed, one pre-existing situational warning
- `python3 evals/run_scenarios.py --adapter all --no-receipts` - 12 passed
- `./scripts/validate.sh`, Ruff, ShellCheck, and Markdown lint - passed
