---
id: 0029
title: Add reviewed adaptive-routing rollout certificates
status: done
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
- [x] Claude, Codex, and Agent Skills release projections ship the rollout schema, focused tests
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
- Two local Forge 3.6.0 release builds are byte-identical; the archive manifest verifies offline
  against commit `0f1d03e712165a1126de2502be118f28df2db1c8`.
- Hosted CI run [31280943839](https://github.com/AlisinaDevelo/md-files/actions/runs/31280943839)
  is green for corrective commit `74dd9b0b7c689aa444e6ff53ca1889f6e739105f` under
  `AlisinaDevelo`. The preceding run [31280868673](https://github.com/AlisinaDevelo/md-files/actions/runs/31280868673)
  caught Ruff 0.16's `RUF046` diagnostic; the redundant cast was removed and the full hosted
  matrix was rerun successfully.
