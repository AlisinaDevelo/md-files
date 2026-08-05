---
id: 0021
title: Add workflow definition versioning and replay compatibility gates
status: planned
agent: architect
model: opus
depends_on: [0017, 0020]
issue: 68
---

## Goal

Pin every durable run to an immutable workflow and worker definition, then fail closed when
replay, checkpoint restore, migration, or effect retry is incompatible with that definition.

## Acceptance criteria

- [ ] Runs persist an immutable definition digest, worker/build revision, policy revision, and
      feature-flag decision digest.
- [ ] Aliases select new runs only; in-flight runs remain pinned until explicit continue-as-new or
      a reviewed migration transition.
- [ ] Compatibility preflight covers replay, checkpoints, migrations, and effect retries.
- [ ] Stable step identities and idempotency keys are deterministic and tested against replay.
- [ ] Golden fixtures cover compatible, incompatible, canary, rollback, and retirement paths.
- [ ] Offline CLI inspection reports the pinned definition and compatibility decision without raw
      prompts, credentials, tool payloads, or provider responses.
- [ ] Backend conformance, full validation, and release projections pass.

## Research decisions

- AWS qualified durable invocation versions model the pin for new versus in-progress executions.
- Determinism and stable step-name guidance makes identity a contract, not an implementation detail.
- Version rollout must preserve idempotent provider operations; a version pin does not imply
  exactly-once external execution.

## Verification

Track implementation and release evidence on GitHub issue #68. Promote a failing replay fixture to
the compatibility corpus before closing the task.
