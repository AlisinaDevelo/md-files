# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.2.0] — 2026-08-03

### Added

- **Native GitHub Stack Merge** — exact-range previews, expected-head protection, scoped
  policy approval, durable async request UUIDs, timeout-safe resume, Merge Queue observation,
  `merge_group` correlation, provider-native fallback, and indeterminate partial-landing
  detection.

## [3.1.0] — 2026-08-03

### Added

- **Forge Doctor** — a read-only, schema-versioned preflight for host tools, manifest and
  catalog drift, worktree and stack state, GitHub branch policy, rulesets, signed commits,
  and Merge Queue coverage. Human and JSON output support online and offline operation.
- **Run receipts** — append-only, privacy-safe JSONL events with idempotency, causality,
  truncated-record recovery, a versioned schema, and an optional OTLP/HTTP JSON adapter.
- **GitHub task-ledger sync** — an explicit local/GitHub authority backend with stable task
  markers, conflict stops, native sub-issues and blocked-by dependencies, bounded
  pagination, resumable mutations, deletion/rename safeguards, and receipt-backed evidence.
- **GitHub native stack reconciliation** — inspect/import support for REST and cursor-paginated
  GraphQL stack state, deterministic manifest snapshots, divergence classification, SHA-guarded
  create/append/relink/unstack plans, retry recovery, and private-preview fallback.
- **Cross-host conformance scenarios** — versioned JSONL fixtures, deterministic reference and
  Agent Skills adapters, explicit Claude/Codex live contracts, tool/artifact/score enforcement,
  receipt-linked results, confidence intervals, flaky-run gates, and CI evidence artifacts.
- **Declarative policy plane** — versioned action envelopes and decision schemas, readable
  default/review/GitHub/release/production profiles, protected-resource constraints, staged
  no-effect previews, one-use approvals bound to exact digests and policy revisions, pre-effect
  re-evaluation, privacy-safe committed-effect receipts, and opt-in task-ledger/stack adapters.

## [3.0.1] — 2026-07-31

### Added

- **Security and support policy** — documented private vulnerability reporting, support
  channels, and the boundaries around host permissions and credential management.
- **Host validation** — CI now validates every Agent Skill directory and both Claude and
  Codex marketplace surfaces.
- **OpenSSF Scorecard evidence** — protected CI produces SARIF security results for the
  repository.

### Changed

- **Workflow trust boundary** — GitHub Actions use reviewed immutable commit SHAs,
  least-privilege default permissions, and explicit elevated permissions only for
  Scorecard publication.

## [3.0.0] — 2026-07-31

### Added

- **GitHub-native stacked delivery** — the `stacked-changes` skill defaults to GitHub's
  first-party `gh stack`, released July 2026, with explicit adapters for vanilla
  Git/GitHub CLI, Graphite, Aviator, Sapling, and classic ghstack.
- **Portable stack engine** — an auditable standard-library CLI with a versioned
  `.forge/stack.json` manifest, provider selection, graph validation, real Git ancestry
  inspection, incremental commit/file counts, PR linking/body navigation, and safe
  submit/restack/land plans that never mutate by default.
- **`/stack` and `/stack-review`** — author/conductor and bottom-up reviewer workflows for
  planning, checking, submitting, restacking, repairing, reviewing, and landing stacks.
- **Stacked Delivery bundle and workflow** — machine-readable and human-readable routing
  from orchestration through incremental review and protected landing.
- **Industry research and recovery guide** — current GitHub/Graphite/Aviator/Sapling/
  ghstack comparison, CI/merge-queue guidance, signed-commit behavior, partial-push
  handling, rejected-lease recovery, and provider-specific failure modes.
- **Behavior contracts** — deterministic evals now enforce safety and review invariants for
  high-risk skills, commands, and scripts.
- **Stack workflow tests** — 20 new tests cover manifests, invalid graphs, Git ancestry,
  adapters, plan safety, PR navigation, CLI behavior, and force-with-lease guard behavior.

### Changed

- Orchestration now chooses both a delivery task graph and, when useful, a separate review
  stack graph.
- `/pr` resolves the immediate stack parent and includes committed changes using a
  parent-to-HEAD diff.
- Git workflow guidance permits documented rebasing of explicitly owned stack branches
  only with recovery refs, post-state verification, and `--force-with-lease`.
- `.agents` installation now preserves complete nested skill directories, including
  references and executable scripts.
- Catalog validation is genuinely read-only in `--check` mode; release validation now
  enforces manifest version parity, Codex marketplace resolution, and skill-script health.
- GitHub Actions CI now supports `merge_group` checks for Merge Queue.
- Forge now ships 20 agents, 23 skills, 20 Claude slash commands, and 63 `.agents`
  surfaces, backed by 304 deterministic eval checks and 74 tests.

## [2.1.0] — 2026-07-08

### Added

- **Forge Catalog** — generated [CATALOG.md](CATALOG.md) and `data/catalog.json` covering
  agents, skills, commands, model defaults, paths, and risk labels.
- **`/forge` command** — a new front door that chooses the smallest useful Forge agent,
  skill, command, bundle, or workflow for a goal.
- **`forge-catalog` skill** — routing guidance for capability selection, bundles, and
  workflows.
- **Bundles and workflows** — [docs/bundles-and-workflows.md](docs/bundles-and-workflows.md),
  `data/bundles.json`, and `data/workflows.json` for focused role-based starts and ordered
  execution paths.
- **Quality bar** — [docs/quality-bar.md](docs/quality-bar.md) defines component standards,
  risk labels, and release gates.
- **Competitive audit** — [docs/competitive-audit.md](docs/competitive-audit.md) captures
  what Forge borrows from larger skill libraries and where Forge should deliberately differ.
- **Catalog generator** — `scripts/generate_catalog.py` plus validation that fails when the
  generated catalog is stale.

### Changed

- Bumped Forge manifests to `2.1.0`.
- Forge now ships 20 agents, 22 methodology skills, 18 Claude slash commands, and 60
  `.agents` skills for Codex/Zed-style installs. Static prompt eval coverage grows to 265
  checks.

## [2.0.0] — 2026-07-08

### Added

- **Multi-model orchestration** — new `orchestration` skill with a conductor loop for
  planning at Opus/Fable, decomposing into a ledger, routing concrete tasks to the right
  specialist/model tier, integrating results, and verifying before done.
- **Task ledger** — new `task-ledger` skill and task template for Jira/GitHub-issue-like
  local markdown tasks under `.forge/tasks/`, with status, dependencies, acceptance
  criteria, assigned agent, and model tier. Includes GitHub issue and MCP-backed tracker
  guidance.
- **Solve loops** — new `iterate-to-done` skill plus `/solve-loop` command to repeatedly
  drain ready tasks, verify evidence against acceptance criteria, and stop cleanly on done,
  blocked, budget, or no-progress conditions.
- **Orchestration commands** — `/orchestrate`, `/tasks`, and `/solve-loop` for driving
  large goals end to end from the main conversation, where subagent spawning actually
  works.
- **Codex plugin support** — `.agents/plugins/marketplace.json` and
  `plugins/forge/.codex-plugin/plugin.json` so Forge can install as a Codex marketplace
  plugin in addition to Claude Code.
- **Codex/Zed command shims** — `.agents` skills for `forge-cmd-orchestrate`,
  `forge-cmd-tasks`, and `forge-cmd-solve-loop`.

### Changed

- Bumped Forge manifests to `2.0.0`.
- Updated docs and install instructions for Claude Code, Codex plugin installs, and
  `.agents` skill installs.
- Forge now ships 20 agents, 21 methodology skills, 17 Claude slash commands, and 58
  `.agents` skills for Codex/Zed-style installs. Static prompt eval coverage grows to 259
  checks.

## [1.3.0] — 2026-06-29

### Added

- **Forge for Zed** — full port of Forge to Zed's agent system (`zed/` directory).
  - **52 skills** installed globally to `~/.agents/skills/`: 18 methodology skills
    (unchanged), 20 specialist agent skills (`forge-<name>`), and 14 slash command
    skills (`forge-cmd-<name>` with `disable-model-invocation: true` so they appear
    in the `/` menu).
  - **2 agent profiles** — `Forge: Concise Engineer` and `Forge: Mentor` — added to
    `~/.config/zed/settings.json` under `agent.profiles`.
  - **Global `AGENTS.md`** at `~/.config/zed/AGENTS.md` with engineering principles,
    skill catalog, profile descriptions, and honest documentation of what doesn't port
    (hooks, which Zed doesn't support yet).
  - **`zed/install.sh`** — idempotent installer that symlinks or copies all skills,
    the AGENTS.md, and the profiles into the right Zed locations.

## [1.2.0] — 2026-06-29

### Added

- **Architecture diagrams** — three Mermaid diagrams in `docs/architecture.md`: component
  overview, hook lifecycle sequence, and skill-loading flow. Makes the internals inspectable
  at a glance.

## [1.1.0] — 2026-06-21

### Added

- **2 agents** — `data-engineer` (pipelines, ETL/ELT, warehouse modeling, data quality;
  distinct from `database-expert`) and `sre` (SLOs, error budgets, capacity, toil; distinct
  from `devops-engineer` and `incident-responder`).
- **3 skills** — `feature-flags` (rollout + cleanup discipline), `caching-strategies`
  (patterns, TTLs, invalidation, stampedes), `concurrency-and-parallelism` (races, locks,
  async, idempotency).
- **2 commands** — `/changelog` (draft from commits since the last release) and `/scaffold`
  (scaffold a component matching repo conventions).
- **`prompt-engineering` operating-patterns reference** (`PATTERNS.md`) distilled from
  production agent prompts, plus a sharper `tech-lead` delegation briefing.

Now 20 agents, 18 skills, 14 commands; the prompt-quality eval grows to 241 checks.

## [1.0.1] — 2026-06-18

### Fixed

- **`scan-secrets` coverage** — the hook now detects Stripe live keys (`sk_live_…`) and
  modern OpenAI project/service keys (`sk-proj-…`, `sk-svcacct-…`, `sk-admin-…`), which the
  earlier `sk-[A-Za-z0-9]{32,}` pattern missed because of the hyphen. Found by dogfooding
  the toolkit on itself. Hook test suite grows to 54.

### Documented

- The `guard-bash` match-anywhere trade-off (quoted/echoed/commented trigger text is
  blocked) is now spelled out in the design rationale as a deliberate false-positive-over-
  false-negative choice, with the fixture-assembly workaround.

## [1.0.0] — 2026-06-18

All schemas verified against the official Claude Code documentation. The repo uses the
canonical marketplace layout — a marketplace catalog at the root listing the `forge`
plugin under `plugins/forge/`.

### Added

- **Plugin packaging** — `.claude-plugin/marketplace.json` (root catalog) +
  `plugins/forge/.claude-plugin/plugin.json` so the repo installs as a Claude Code
  marketplace and plugin, with a `$schema` reference for editor validation.
- **18 agents** — code-reviewer, debugger, security-auditor, test-engineer, architect,
  refactoring-specialist, performance-optimizer, database-expert, api-designer,
  frontend-specialist, accessibility-auditor, dependency-auditor, devops-engineer,
  docs-writer, incident-responder, code-archaeologist, migration-specialist, tech-lead.
- **15 skills** — test-driven-development, root-cause-debugging, code-review-rubric (+
  checklist), refactoring-catalog (+ catalog), conventional-commits, pull-request-authoring,
  api-design, threat-modeling, safe-database-migrations, performance-profiling,
  observability, technical-writing, git-workflow, error-handling, prompt-engineering.
- **12 slash commands** — review, commit, test, debug, plan, refactor, security-scan, pr,
  optimize, explain, docs, tidy.
- **5 lifecycle hooks** — SessionStart repo-context injector, dangerous-command guard,
  secret scanner, auto-formatter, completion notification.
- **2 output styles** — Concise Engineer and Mentor.
- **Status line** — model · directory · git · context% · cost.
- **Settings & MCP examples** — example `settings.json` (permission allowlist, secret-deny
  rules, status line, output style) and least-privilege MCP server configs.
- **Instructions library** — `CLAUDE.md` templates (project + global), engineering
  principles, and language guides (TypeScript, Python, Go).
- **Evidence layer** — `evals/` with 213 static prompt-quality checks and an opt-in
  LLM-judge behavioral eval (7 cases); `tests/` with a 52-test pytest suite for the hooks.
- **Tooling** — `scripts/validate.sh`, `scripts/install.sh`, a `justfile`, and CI that
  runs validation, the hook tests, the static evals, markdown lint, shellcheck, and
  ruff/manifest checks on every push.
- **Docs** — getting started, usage patterns, architecture, design rationale, and CI &
  headless usage guides.

[Unreleased]: https://github.com/AlisinaDevelo/md-files/compare/v3.2.0...HEAD
[3.2.0]: https://github.com/AlisinaDevelo/md-files/compare/v3.1.0...v3.2.0
[3.1.0]: https://github.com/AlisinaDevelo/md-files/compare/v3.0.1...v3.1.0
[3.0.1]: https://github.com/AlisinaDevelo/md-files/releases/tag/v3.0.1
[3.0.0]: https://github.com/AlisinaDevelo/md-files/releases/tag/v3.0.0
[2.1.0]: https://github.com/AlisinaDevelo/md-files/releases/tag/v2.1.0
[2.0.0]: https://github.com/AlisinaDevelo/md-files/releases/tag/v2.0.0
[1.0.0]: https://github.com/AlisinaDevelo/md-files/releases/tag/v1.0.0
