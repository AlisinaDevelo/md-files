---
id: 0042
title: Add generic constellation integration bundle
status: done
agent: architect
model: opus
depends_on: [0038, 0041]
---

## Goal

Provide a provider-neutral Forge routing bundle and read-only doctor profile for
multi-repository planning, contract checks, release qualification, and incident-quality
documentation without embedding consuming-repository identity or policy.

## Acceptance criteria

- [x] Add a catalog bundle for constellation planning, cross-repo contract checks, threat
      modeling, release qualification, and incident-quality docs.
- [x] Add a repo doctor profile that recognizes configurable workspace aliases and a
      language matrix.
- [x] Add evals for capability-claim honesty, issue dependency completeness, secret
      hygiene, and CI evidence.
- [x] Keep Forge provider-neutral and do not grant active security tools or action
      authority.

## Implementation notes

The bundle is routing metadata, not a permission grant. Consuming private repositories
may provide a local profile file, but private aliases and repository names must remain in
the consuming repository and never enter public Forge source or release artifacts.
