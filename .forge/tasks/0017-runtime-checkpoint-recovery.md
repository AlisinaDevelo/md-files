---
id: 0017
title: Add checkpointed recovery and fail-closed migrations
status: done
agent: migration-specialist
model: sonnet
depends_on: [0015, 0016]
---

## Goal

Bound replay cost for long-running runs while keeping recovery deterministic, privacy-safe,
and explicit about incompatible runtime history.

## Acceptance criteria

- [x] A checkpoint plus its verified event suffix reconstructs the same state digest as full replay.
- [x] Corrupt checkpoints or event suffixes fail closed and recover from the last valid prefix.
- [x] Unknown or incompatible database, workflow, definition, policy, or checkpoint revisions
      produce actionable migration errors.
- [x] A migration registry exposes source/target versions, preconditions, dry-run output,
      result evidence, and rollback/restore guidance; interrupted migrations can resume.
- [x] Old-history fixtures cover successful migration, rejected migration, interrupted migration,
      and repeated resume without duplicate external effects.
- [x] Sibling effect intents committed before a later failure remain idempotently addressable
      after checkpoint restore without duplicate scheduling.
- [x] Checkpoint state remains reference-only and rejects raw prompts, credentials, tool
      arguments/results, and provider responses.
- [x] CLI inspection, schemas, docs, crash/recovery tests, and deterministic release validation pass.

## Context

This is GitHub issue #55 after the generation-fenced effect boundary in #54. The design follows
checkpointed supersteps and pending-write recovery in LangGraph and Microsoft Agent Framework,
durable history and retry behavior in Dapr/Temporal, and the Forge safe-database-migrations
expand/contract rules. Human waits, adaptive routing, and distributed backends remain separate.

## Verification

- `python3 -m pytest -q` - 200 passed
- `python3 evals/run.py` - 312/313 passed, one situational warning
- `python3 evals/run_scenarios.py --adapter all --no-receipts` - 12 passed
- `./scripts/validate.sh`, Ruff, ShellCheck, and Markdown lint - passed
- Deterministic 3.6.0 Agents, Claude, and Codex archives verified offline
