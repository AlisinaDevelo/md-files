---
id: 0051
title: Add gh-aw firewall and content-integrity admission
status: review
agent: security-engineer
model: standard
depends_on: [0026, 0033, 0048, 0050]
issue: 98
---

## Goal

Bind the current GitHub Agentic Workflows network and sandbox boundary to deterministic
Forge admission evidence without executing a firewall, fetching content, or contacting a
provider.

## Acceptance criteria

- [x] Normalize versioned AWF firewall, network, URL-pattern, sandbox, and content-integrity
      fields with fail-closed credential, expression, insecure-pattern, and opt-out checks.
- [x] Emit the normalized policy and digest into compiled source/lock metadata and manifests.
- [x] Bind policy, source, and lock digests into native admission certificates and provider
      request evidence, including host provider-operation and execution references.
- [x] Add deterministic policy and evidence-drift tests without network or provider execution.
- [ ] Run the full local release gate and publish one stacked ready PR.

## Research decisions

- AWF currently supports `network.allowed`, `network.blocked`, `network.firewall.log-level`,
  `ssl-bump` with `allow-urls`, and `sandbox.agent: awf` or a literal-justified disabled mode.
- AWF applies its network allowlist to both egress and content sanitization; Forge therefore
  records an explicit redact-or-reject integrity decision rather than inventing a permissive
  content trust state.
- `request_ref` remains the operation digest for durable episode compatibility. The separate
  `contract_evidence_ref` binds the compiled policy/source/lock evidence before lease use.

## Scope boundary

Do not execute AWF, inspect HTTPS traffic, fetch URLs, add provider credentials, or implement
runtime firewall enforcement in this slice.

## Verification

Focused tests: pending final gate.

## Primary sources

- [AWF network permissions](https://github.github.com/gh-aw/reference/network/)
- [AWF sandbox configuration](https://github.github.com/gh-aw/reference/sandbox/)
