# Competitive Audit

Last reviewed: 2026-10-02 (UTC).

Reviewed repositories:

- [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills)
- [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills)
- [sickn33/antigravity-awesome-skills](https://github.com/sickn33/antigravity-awesome-skills)

## Honest Read

Forge is not the biggest skill repository. The comparators offer substantially broader
catalogs and discovery surfaces. Forge concentrates on engineering workflows, explicit
effect boundaries, deterministic tooling, and inspectable release evidence. That is a
product focus, not a measured claim of superior outcomes or model quality.

## October 2026 Refresh

These are README claims at pinned commits, not independently audited skill counts or
head-to-head task results:

| Comparator | Pinned source | Relevant scope |
|---|---|---|
| Claude Skills | [`19392f7`](https://github.com/alirezarezvani/claude-skills/blob/19392f7a08264ed00486a251f5b2098321771f94/README.md) | Advertises 388 skills, 118 agents, 150 commands, and 13 tool targets; broad engineering and business workflows. |
| Awesome Agent Skills | [`fd4c28d`](https://github.com/VoltAgent/awesome-agent-skills/blob/fd4c28d3be5576a88b1a0b0c4f5267c448d94ef5/README.md) | Advertises 1,497+ skills; primarily a curated discovery collection. |
| Agentic Awesome Skills | [`7bb0ab4`](https://github.com/sickn33/agentic-awesome-skills/blob/7bb0ab4f7d5539228c6a8bf34368a3f9b6c7abb8/README.md) | Advertises 2,635+ skills and AAS Core catalog inspection, stack validation, and immutable plan previews; apply and recovery remain experimental. |

AAS Core is the closest product comparator for inspectable planning and explicit selection.
Forge's ledger, policy, runtime, and release checks cover a different engineering surface.
No common workload, effectiveness metric, reliability benchmark, or usability study was
run against these projects. Neither feature lists nor passing Forge tests establish that
Forge supersedes them.

The concrete release response is portable Agent Plugins 1.0 packaging, inventory-bound
model selection, and version-specific OpenCode configuration with non-destructive installer
behavior. The acceptance evidence measures format compatibility, fail-closed inputs,
archive integrity, and reproducible offline replay. It does not measure agent reasoning,
live provider availability, connected orchestration quality, or public marketplace reach.

## Standards Decisions

- [Agent Plugins 1.0](https://agent-plugins.org/specification) supplies the portable root
  manifest and fixed component paths. Keep older host projections and validate each.
- [OpenAI packaging](https://developers.openai.com/plugins/build/plugins) defines complete
  inline OpenAI-extension replacement, not partial merging with a compatibility overlay.
- [OpenAI model guidance](https://learn.chatgpt.com/docs/models) and
  [Claude model configuration](https://code.claude.com/docs/en/model-config) are documentation,
  not proof of account availability. Bind routing to an explicit host inventory.
- [OpenCode v2 migration](https://opencode.ai/v2/docs/migrate-v1/) changes plugin and server
  APIs while retaining supported v1 configuration. A skills projection is not a native
  JavaScript plugin, and configuration parsing alone is not execution evidence.

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

## August 2026 Frontier Update

The competitive bar now includes protocol versioning, agent authority, trajectory-level
security evidence, portable release attestations, and native stacked delivery. MCP's
2026-07-28 final specification is stateless at the core and puts long-running work in the
Tasks extension. GitHub's native Stacked Pull Requests are in public preview, and GitHub
issue dependencies are available as a first-party graph. These changes reward explicit
adapter contracts and evidence more than another broad skill catalog.

Forge's prioritized response is tracked in the [frontier roadmap](frontier-roadmap.md) and
the release-scoped issues [#85](https://github.com/AlisinaDevelo/md-files/issues/85),
[#86](https://github.com/AlisinaDevelo/md-files/issues/86),
[#87](https://github.com/AlisinaDevelo/md-files/issues/87), and
[#88](https://github.com/AlisinaDevelo/md-files/issues/88).

## Next Moves

1. Deliver the versioned MCP Tasks, portable attestation, and trajectory-evaluation contracts
   as independently reviewable v3.7 slices.
2. Import native GitHub Stack and issue-dependency state into Forge evidence without creating
   a second source of truth.
3. Deliver identity and delegated-authority binding before enabling more connected execution.
4. Add focused plugin bundles only when install and activation evidence shows a real marketplace
   benefit; keep the generated local catalog authoritative.
