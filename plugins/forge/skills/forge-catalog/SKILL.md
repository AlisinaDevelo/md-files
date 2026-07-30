---
name: forge-catalog
description: >-
  Use when choosing which Forge agent, skill, command, bundle, or workflow should handle
  a request; when comparing Forge capabilities; when building a focused install surface;
  or when a user asks "what should I use?" before starting work. Routes to the smallest
  useful Forge capability instead of loading everything.
---

# Forge Catalog

Use this skill as Forge's front door. Your job is to choose the smallest useful Forge
capability for the user's goal, then hand off to that capability with a clear reason.

## Route by Intent

- **Small code change:** use the normal development loop (`/plan` only if needed, then
  implement, `/test`, `/review`).
- **Large or ambiguous goal:** use `/orchestrate`, then `.forge/tasks/`, then
  `/solve-loop`.
- **Known specialist depth:** pick the specialist agent directly (`security-auditor`,
  `frontend-specialist`, `database-expert`, `sre`, etc.).
- **Methodology question:** pick a skill (`test-driven-development`, `root-cause-debugging`,
  `safe-database-migrations`, `threat-modeling`, etc.).
- **Release/documentation workflow:** use `/changelog`, `/pr`, `/commit`, `/docs`, or the
  `technical-writing` / `pull-request-authoring` skills.
- **Large reviewable change:** use `stacked-changes`, `/stack`, and `/stack-review` when
  dependent slices should be reviewed and landed separately.
- **Unclear request:** ask one short clarifying question only if the route changes the work.

## Bundle Shortcuts

Use [docs/bundles-and-workflows.md](../../../../docs/bundles-and-workflows.md) when the user
wants a role-based starting point:

- **Core Engineering:** everyday planning, tests, review, debugging, commit/PR.
- **Orchestration:** plan high, ledger, solve loop, verify.
- **Production Hardening:** security, dependency, performance, observability, SRE.
- **Data & Backend:** API, database, data engineering, migrations, caching.
- **Frontend Product:** frontend, accessibility, docs, product-facing polish.

## Catalog Files

- [CATALOG.md](../../../../CATALOG.md) is the human-readable component catalog.
- [data/catalog.json](../../../../data/catalog.json) is the machine-readable catalog.
- [data/bundles.json](../../../../data/bundles.json) lists curated bundles.
- [data/workflows.json](../../../../data/workflows.json) lists ordered workflows.

Prefer a focused route over activating multiple adjacent capabilities. Forge wins by
composition and verification, not by dumping every skill into context.
