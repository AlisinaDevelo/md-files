---
id: 0022
title: Add signed trace-context and provenance bridge for runtime episodes
status: planned
agent: observability-specialist
model: sonnet
depends_on: [0018, 0020]
issue: 65
---

## Goal

Connect canonical runtime history to portable traces and digest-bound provenance while keeping raw
prompts, credentials, tool content, and provider bodies out of default evidence.

## Acceptance criteria

- [ ] Version-pinned W3C and OpenTelemetry mappings correlate runs, episodes, effects, waits,
      provider references, and receipt digests deterministically.
- [ ] Sensitive and verbose attributes are digest/reference-only by default, with explicit opt-in
      filtering, truncation, and export controls.
- [ ] Signed provenance verifies subject, source, policy, and evidence-input digests offline;
      tampering and malformed trust material fail closed.
- [ ] Export loss or reordering cannot mutate canonical runtime state.
- [ ] Tests cover privacy regressions, malformed context, key rotation, and reproducible output.
- [ ] Retention, redaction, key custody, and incident response are documented.

## Research decisions

- OpenTelemetry semantic conventions are versioned and GenAI content fields are treated as
  potentially sensitive.
- W3C Trace Context is a correlation envelope, not a state-transition authority.
- SLSA-style subject digests and verification policy provide the provenance boundary.

## Verification

Track implementation and release evidence on GitHub issue #65. Keep the event history and receipt
verifier authoritative if an exporter is unavailable.
