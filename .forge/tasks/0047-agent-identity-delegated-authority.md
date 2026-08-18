---
id: 0047
title: Add agent identity and delegated authority contract
status: planned
agent: architect
model: opus
depends_on: [0018, 0022, 0025]
issue: 88
---

## Goal

Define a versioned, offline-verifiable identity and delegated-authority contract for agents,
workflows, providers, and human approvals.

## Acceptance criteria

- [ ] The descriptor binds issuer, subject, build, audience, scopes, parent delegation, expiry,
      nonce, revocation state, and policy revision.
- [ ] Action requests bind the identity, delegation chain, authorization decision, approval,
      runtime episode, provider operation, and provenance receipt.
- [ ] Least-agency, audience, expiry, replay, revocation, and scope-escalation failures are
      deterministic and fail closed.
- [ ] Offline verification supports a legacy principal profile without weakening the new
      contract and emits digest-only evidence.
- [ ] Connected execution remains opt-in until identity and authority evidence is verified.

## Scope boundary

Do not build a hosted identity provider or treat model self-description as authority.

## Primary sources

- [NIST AI Agent Standards Initiative](https://www.nist.gov/artificial-intelligence/ai-agent-standards-initiative)
- [NIST identity and authority concept paper](https://www.nist.gov/news-events/news/2026/02/new-concept-paper-identity-and-authority-software-agents)
- [OWASP Agentic Skills Top 10](https://owasp.org/www-project-agentic-skills-top-10/)
