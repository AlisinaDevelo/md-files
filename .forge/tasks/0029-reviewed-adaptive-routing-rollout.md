---
id: 0029
title: Add reviewed adaptive-routing rollout certificates
status: review
agent: architect
model: opus
depends_on: [0025]
issue: 22
---

## Goal

Turn an eligible offline routing replay into an explicit, digest-bound rollout certificate
without allowing an unreviewed policy to activate adaptive decisions. Keep rollout state
deterministic and provider-neutral so the certificate can be consumed by Codex, Claude, or a
future provider adapter.

## Acceptance criteria

- [x] A versioned rollout artifact binds baseline and candidate policy revisions, the replay
      reference, the normalized evidence-window reference, an explicit approval reference, and
      a rollout stage.
- [x] Preview, canary, active, rollback, and retired stages have validated traffic and approval
      rules; blocked replay evidence never activates adaptive routing.
- [x] Canary membership is deterministic from the request digest, and requests outside the
      cohort use static fallback behavior.
- [x] A certificate is rejected when its policy, replay, evidence, stage, or approval binding is
      stale or mismatched; no raw request, outcome, prompt, or provider content is persisted.
- [x] The CLI and Python API expose certificate issuance and explicit certificate consumption;
      the default adaptive `decide` path remains fail-closed without a certificate.
- [ ] Claude, Codex, and Agent Skills release projections ship the rollout schema, focused tests
      pass, and the full validation suite remains green.

## Scope boundary

This task adds a deterministic offline certificate and local decision boundary. It does not
connect a provider, persist rollout state, or claim cryptographic identity for an external
approval reference. A production control plane must verify approval ownership, expiry, and
one-use semantics before issuing a certificate.

## Verification

Local verification:

- Focused routing, release-surface, and backend schema coverage: `20 passed`.
- Full repository suite: `277 passed`.
- `./scripts/validate.sh`, exact CI Ruff scope, Markdown lint (`194 files`), ShellCheck, and
  static scenarios (`12 passed, 0 failed, 12 skipped`) pass.
- Hosted CI and reproducible release packaging remain required before marking this task done.
