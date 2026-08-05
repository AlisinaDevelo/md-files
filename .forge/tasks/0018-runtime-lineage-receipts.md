---
id: 0018
title: Add verifiable execution lineage and receipt integrity
status: in-progress
agent: observability-specialist
model: sonnet
depends_on: [0017]
---

## Goal

Make runtime execution evidence independently verifiable offline while preserving the canonical
event history, explicit at-least-once effect boundary, and privacy-safe defaults.

## Acceptance criteria

- [ ] A deterministic lineage manifest binds each external effect to its scheduling event,
      event sequence/head hash, effect identity, attempt, lease generation, adapter contract,
      and provider request reference.
- [ ] Receipt tampering, conflicting reuse, missing parent evidence, and lease-generation
      mismatches fail closed in an offline verifier.
- [ ] Retries, reclaimed attempts, dead letters, adapter outcomes, inbox receipts, and policy
      decisions have versioned receipt envelopes with deterministic digests.
- [ ] Export and verify are deterministic across repeated runs and supported Python versions;
      unknown optional evidence is accepted only under an explicit extension namespace.
- [ ] W3C trace context and pinned OpenTelemetry mappings use bounded, low-cardinality fields;
      raw prompts, credentials, tool arguments/results, and provider response bodies are never
      exported by default.
- [ ] Existing GitHub/SLSA/in-toto release attestations remain the artifact provenance path;
      runtime lineage does not claim signatures or exactly-once provider execution.
- [ ] Schemas, CLI inspection, lineage fixtures, privacy/tamper tests, docs, and deterministic
      release validation pass.

## Context

This is GitHub issue #56 after the checkpointed recovery and migration slice in #55. The design
follows OpenTelemetry/W3C context propagation, the versioned GenAI semantic conventions,
SLSA/in-toto subject-and-digest binding, and GitHub artifact attestation verification. It derives
evidence from canonical runtime history and existing receipt/policy stores instead of replacing
them with telemetry.

## Verification

Pending implementation. The task remains `in-progress` until the verifier, fixtures, full test
matrix, and hosted release checks are complete.
