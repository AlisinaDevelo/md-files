---
id: 0030
title: Add operator-confirmed gh-aw dispatch reconciliation
status: done
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

- [x] Reconciliation is a separate explicit provider operation and requires the expected
      authenticated `gh` login plus an operator confirmation flag at the CLI boundary.
- [x] The provider performs only a bounded `GET` by run ID and rejects repository, workflow
      path, event, ref, URL, or run identity drift before changing local state.
- [x] A verified run produces the same reference-only receipt contract as normal execution,
      appends hash-chained reconciliation evidence, and acknowledges the current fenced lease.
- [x] Reconciliation is safe after a worker crash, stale lease recovery, duplicate invocation,
      and an already-recorded journal success; raw run responses never enter durable evidence.
- [x] Tests, docs, capability projections, release rendering, local validation, and hosted CI
      pass under the `AlisinaDevelo` GitHub identity.

## Scope boundary

This slice reconciles only `dispatch-workflow` effects. It does not claim that GitHub workflow
dispatch is exactly-once, infer inputs that GitHub does not expose in run metadata, or broaden
the provider's safe-output allowlist.

## Verification

- The provider adds an explicit `reconcile --reconcile` CLI operation. It authenticates the
  expected `gh` login, performs one `GET /repos/{owner}/{repo}/actions/runs/{run_id}`, verifies
  the exact compiled lock path, `workflow_dispatch` event, requested branch, repository URL, and
  run ID, then reuses the existing policy/journal/lease/inbox boundaries.
- The focused provider suite passes (`10 passed`), including malformed event rejection, expired
  lease reclaim, successful reconciliation, raw-response exclusion, and duplicate replay. The
  full suite passes (`278 passed`); Ruff, `scripts/validate.sh`, Markdown lint (195 files),
  ShellCheck, and all 12 cross-host scenarios pass.
- Two Forge 3.6.0 release builds are byte-identical across Claude, Codex, Agent Skills, SBOM,
  manifest, and checksum outputs; both manifests verify against commit `b894d91`.
- Hosted CI run
  [31281554928](https://github.com/AlisinaDevelo/md-files/actions/runs/31281554928) is green;
  OpenSSF Scorecard is skipped on this feature branch.
