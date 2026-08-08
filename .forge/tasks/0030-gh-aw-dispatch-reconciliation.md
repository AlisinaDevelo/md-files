---
id: 0030
title: Add operator-confirmed gh-aw dispatch reconciliation
status: in_progress
agent: reliability-engineer
model: sonnet
depends_on: [0028]
issue: 21
---

## Goal

Close the documented post-dispatch ambiguity window without retrying a GitHub workflow
dispatch blindly. An operator must be able to present a run ID, have the provider verify
that the run belongs to the exact repository, compiled lock workflow, dispatch event, and
requested ref, then durably reconcile the existing authorization into the provider journal
and Forge inbox.

## Acceptance criteria

- [ ] Reconciliation is a separate explicit provider operation and requires the expected
      authenticated `gh` login plus an operator confirmation flag at the CLI boundary.
- [ ] The provider performs only a bounded `GET` by run ID and rejects repository, workflow
      path, event, ref, URL, or run identity drift before changing local state.
- [ ] A verified run produces the same reference-only receipt contract as normal execution,
      appends hash-chained reconciliation evidence, and acknowledges the current fenced lease.
- [ ] Reconciliation is safe after a worker crash, stale lease recovery, duplicate invocation,
      and an already-recorded journal success; raw run responses never enter durable evidence.
- [ ] Tests, docs, capability projections, release rendering, local validation, and hosted CI
      pass under the `AlisinaDevelo` GitHub identity.

## Scope boundary

This slice reconciles only `dispatch-workflow` effects. It does not claim that GitHub workflow
dispatch is exactly-once, infer inputs that GitHub does not expose in run metadata, or broaden
the provider's safe-output allowlist.
