---
id: 0052
title: Admit gh-aw sandbox runtime profiles and MCP Gateway configuration
status: done
agent: security-engineer
model: standard
depends_on: [0051]
issue: 21
---

## Goal

Extend the versioned gh-aw admission boundary to cover current sandbox runtime profiles and
the experimental MCP Gateway without accepting credentials or claiming live execution.

## Acceptance criteria

- [x] Version the firewall admission contract and normalize supported runtime profiles.
- [x] Require literal justification for non-default or privileged runtime profiles and reject
      ambiguous disabled-sandbox combinations.
- [x] Record MCP Gateway enablement and bounded port while excluding API-key values.
- [x] Render runtime and gateway decisions into native gh-aw fields and bind them through the
      existing policy digest, native admission, and provider evidence.
- [x] Add deterministic normalization, rendering, schema, and rejection tests.
- [x] Run the full local release gate.
- [x] Publish one ready stacked PR.

## Research decisions

- Current gh-aw documents `sandbox.agent.runtime` as the selector for Docker, gVisor, Docker
  sandbox, Cloud Hypervisor, and the privileged Docker/iptables profile.
- Current gh-aw documents the MCP Gateway as an experimental feature with a sandbox port; Forge
  records only the feature decision and port because gateway API keys are upstream secrets.
- The v2 contract is digest-bound so a runtime-profile or gateway change invalidates native and
  provider admission evidence rather than silently changing execution topology.

## Scope boundary

Do not launch AWF, create containers, open host ports, connect to an MCP Gateway, or handle API-key
values in this slice.

## Verification

Clean local release gate passed at commit `7aa9b0d6282dbb760bcf057af57dbc46adede5b9`:

- `./scripts/local-release-check.sh` -> `LOCAL_RELEASE_GATE=passed`
- `394 passed` full pytest suite; static evals `333/334` with one existing warning and zero failures.
- Backend conformance, trajectory, authority, host-admission, A2A card/task, deterministic
  chaos, release attestation, offline archive, and marketplace checks passed.
- Two release builds were byte-identical; installed candidate replay passed with 2 identical
  attempts over 8 cases.
- Candidate `forge-3.6.0-codex.tar.gz`: SHA-256
  `81e40a42612504a3243010d36163f0aee0461b00548906c00db17f68dc61806d`, 112 installed files,
  25 installed skills.
- Ready stacked PR: [#101](https://github.com/AlisinaDevelo/md-files/pull/101), based on
  `feature/gh-aw-firewall-admission` and related to issue #21.

## Primary sources

- [AWF network permissions](https://github.github.com/gh-aw/reference/network/)
- [AWF sandbox configuration](https://github.github.com/gh-aw/reference/sandbox/)
