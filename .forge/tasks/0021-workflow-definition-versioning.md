---
id: 0021
title: Add workflow definition versioning and replay compatibility gates
status: done
agent: architect
model: opus
depends_on: [0017, 0020]
issue: 68
---

## Goal

Pin every durable run to an immutable workflow and worker definition, then fail closed when
replay, checkpoint restore, migration, or effect retry is incompatible with that definition.

## Acceptance criteria

- [x] Runs persist an immutable definition digest, worker/build revision, policy revision, and
      feature-flag decision digest.
- [x] Aliases select new runs only; in-flight runs remain pinned until explicit continue-as-new or
      a reviewed migration transition.
- [x] Compatibility preflight covers replay, checkpoints, migrations, and effect retries.
- [x] Stable step identities and idempotency keys are deterministic and tested against replay.
- [x] Golden fixtures cover compatible, incompatible, canary, rollback, and retirement paths.
- [x] Offline CLI inspection reports the pinned definition and compatibility decision without raw
      prompts, credentials, tool payloads, or provider responses.
- [x] Backend conformance, full validation, and release projections pass.

## Research decisions

- AWS qualified durable invocation versions model the pin for new versus in-progress executions.
- Determinism and stable step-name guidance makes identity a contract, not an implementation detail.
- Version rollout must preserve idempotent provider operations; a version pin does not imply
  exactly-once external execution.

## Verification

- PR [#70](https://github.com/AlisinaDevelo/md-files/pull/70) merged as
  `79a8feb4883f9c79185d1b073c9e1d0dce45c83b` and closed issue #68.
- `228 passed`; definition/runtime focused coverage is 34 tests.
- Both portable backends pass 12/12 conformance cases.
- Ruff, `scripts/validate.sh`, capability compilation/projections, and reproducible release
  surfaces pass; static eval is 312/313 with the existing one situational-description warning.
- Hosted main CI run
  [30976592398](https://github.com/AlisinaDevelo/md-files/actions/runs/30976592398) is green,
  including host/Codex validation and release packaging.
