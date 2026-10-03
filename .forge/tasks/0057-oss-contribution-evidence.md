---
id: 0057
title: Bind OSS contribution checks to an exact source revision
status: done
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
- [x] Verify the installed helper, review the diff, merge and include it in 3.11.0.

## Local Acceptance Evidence

- The contribution implementation and native SDK verification merged in PRs #141 and #142.
- Source-integrity commit `069bca74e6ac2ec40418f9cfe4497d61cd7063d3` passed the complete
  local release gate: 518 tests, five optional SDK skips, reproducible archives,
  offline verification, and identical installed replay. Hosted CI was not an acceptance gate.
- The packaged helper from 3.11.0 candidate `f738b5097547c32eba65692bf529b47b84cbcfe2`
  ran all 41 contribution contracts and verified the resulting exact-head receipt.
- The same candidate registered all 26 skills and read 28 script resources in OpenHands
  SDK 1.50.1 on Python 3.12.14; all five native compatibility tests passed without model calls.
- The integrated release must repeat the complete gate before publication. This ledger
  records implementation acceptance, not public-directory approval or signed provenance.

## Evidence boundary

The receipt records local execution. It is not signed provenance, proof against a
malicious runner, proof that tests are sufficient, or authorization for public effects.
