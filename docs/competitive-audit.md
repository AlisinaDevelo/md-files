# Competitive Audit

Reviewed repositories:

- [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills)
- [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills)
- [sickn33/antigravity-awesome-skills](https://github.com/sickn33/antigravity-awesome-skills)

## Honest Read

Forge is not the biggest skill repository. It should not try to be. The competitors win
on breadth, directory-style discoverability, and multi-tool installer surface. Forge wins
on tight engineering defaults, safety hooks, focused specialist agents, evals, and release
discipline.

## What They Do Better

| Area | Competitive signal | Forge response |
|------|--------------------|----------------|
| Catalog surface | Huge human-readable and machine-readable catalogs. | Added `CATALOG.md`, `data/catalog.json`, and `/forge`. |
| Bundles | Role/domain bundles make onboarding easier. | Added focused Forge bundles and workflows. |
| Quality bar | Explicit contribution and validation standards. | Added [quality-bar.md](quality-bar.md). |
| Cross-tool story | Install targets for many tools. | Keep Claude, Codex, and `.agents` first; document others only when tested. |
| Skill authoring | Templates, pipelines, and audit scripts. | Fold into Forge quality gate without copying their process sprawl. |

## Where Forge Should Lead

- **Fewer, sharper capabilities.** Prefer 30 excellent, tested components over 300 shallow
  ones.
- **Evidence-backed claims.** Keep static evals, hook tests, markdown lint, shellcheck,
  and plugin validation as the visible proof layer.
- **Orchestration as product surface.** The big differentiator is not "more skills"; it is
  plan → ledger → routed execution → verified done.
- **Plugin-safe by default.** Codex and Claude installs should work without users editing
  paths by hand.
- **Security humility.** Defensive security skills must keep authorization and approval
  boundaries explicit.

## July 2026 Update: Stacked Delivery

The competitive target is no longer only skill catalogs. GitHub's first-party Stacked PRs,
Graphite, Aviator, Sapling, and classic ghstack now expose different source-control and
merge semantics.

Forge 3.0 responds at the layer an agent toolkit can credibly own:

- provider detection and one explicit mutation authority per stack
- portable `.forge/stack.json` ancestry beside, not inside, the task ledger
- GitHub native as the default, with vanilla, Graphite, Aviator, Sapling, and ghstack
  adapters
- plan-first operations with no hidden rebases, force pushes, PR edits, or merges
- bottom-up incremental review plus post-command verification
- recovery playbooks for conflicts, rejected leases, partial submission, and partial push
- deterministic stack-engine tests and behavior contracts for the prompts

This does not make Forge a replacement for Graphite's hosted review UI or Aviator's merge
queue. It makes Forge a stronger cross-provider conductor: it knows which engine is in
charge, applies a consistent safety policy, and verifies the real state afterward.

## Next Moves

1. Add a real, idempotent GitHub issue sync backend for `.forge/tasks`.
2. Import native GitHub Stack API state into `.forge/stack.json` without making two sources
   of truth.
3. Add focused plugin bundles if Codex/Claude marketplace UX benefits from smaller packs.
4. Build a hosted docs/catalog page only after the generated local catalog is stable.
