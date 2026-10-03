---
id: 0057
title: Bind OSS contribution checks to an exact source revision
status: review
agent: tooling-engineer
model: standard
depends_on: []
---

## Goal

Make upstream contribution preparation reproducible without treating a green check
as permission to publish, sign legal attestations, or merge.

## Acceptance criteria

- [x] Provide a contributor skill covering upstream rules, scope, identity and review.
- [x] Plan explicit command vectors without executing repository-supplied instructions.
- [x] Run reviewed checks only on clean source and reject changed source or contracts.
- [x] Verify complete, successful, exact-head receipts without publishing raw output.
- [x] Test real Git repositories, command failures, timeouts and negative controls.
- [ ] Verify the installed helper, review the diff, merge and include it in 3.11.0.

## Evidence boundary

The receipt records local execution. It is not signed provenance, proof against a
malicious runner, proof that tests are sufficient, or authorization for public effects.
