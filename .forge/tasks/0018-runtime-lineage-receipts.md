---
id: 0018
title: Add verifiable execution lineage and receipt integrity
status: done
agent: observability-specialist
model: sonnet
depends_on: [0017]
---

## Goal

Make runtime execution evidence independently verifiable offline while preserving the canonical
event history, explicit at-least-once effect boundary, and privacy-safe defaults.

## Acceptance criteria

- [x] A deterministic lineage manifest binds each external effect to its scheduling event,
      event sequence/head hash, effect identity, attempt, lease generation, adapter contract,
      and provider request reference.
- [x] Receipt tampering, conflicting reuse, missing parent evidence, and lease-generation
      mismatches fail closed in an offline verifier.
- [x] Retries, reclaimed attempts, dead letters, adapter outcomes, inbox receipts, and policy
      decisions have versioned receipt envelopes with deterministic digests.
- [x] Export and verify are deterministic across repeated runs and supported Python versions;
      unknown optional evidence is accepted only under an explicit extension namespace.
- [x] W3C trace context and pinned OpenTelemetry mappings use bounded, low-cardinality fields;
      raw prompts, credentials, tool arguments/results, and provider response bodies are never
      exported by default.
- [x] Existing GitHub/SLSA/in-toto release attestations remain the artifact provenance path;
      runtime lineage does not claim signatures or exactly-once provider execution.
- [x] Schemas, CLI inspection, lineage fixtures, privacy/tamper tests, docs, and deterministic
      release validation pass.

## Context

This is GitHub issue #56 after the checkpointed recovery and migration slice in #55. The design
follows OpenTelemetry/W3C context propagation, the versioned GenAI semantic conventions,
SLSA/in-toto subject-and-digest binding, and GitHub artifact attestation verification. It derives
evidence from canonical runtime history and existing receipt/policy stores instead of replacing
them with telemetry.

## Verification

Implemented in PR #62 and merged as `3893d3b`. Local verification reached 206 tests, 312/313
static eval checks with the existing situational warning, 12 cross-host scenarios, full
structure validation, Markdownlint, ShellCheck, and byte-identical reproducible 3.6.0 bundles.
Hosted Ruff, pytest, host validation, package verification, Markdown, ShellCheck, evals, plugin
manifest, structure, and OpenSSF Scorecard checks all passed. GitHub issue #56 is closed.
