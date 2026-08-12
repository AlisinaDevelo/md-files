# Bundles and Workflows

Bundles answer "which Forge capabilities belong together?" Workflows answer "in what
order should they run?"

Forge bundles are intentionally small. They are routing presets, not mega-skills.

## Bundles

### Core Engineering

For everyday implementation work.

- `/plan`
- `test-driven-development`
- `/test`
- `/review`
- `/debug`
- `/commit`
- `/pr`

### Orchestration

For large, ambiguous, multi-step work.

- `/forge`
- `/orchestrate`
- `orchestration`
- `task-ledger`
- `/tasks`
- `iterate-to-done`
- `/solve-loop`

### Stacked Delivery

For large features that should be reviewed as dependent, incremental changes.

- `stacked-changes`
- `/stack`
- `/stack-review`
- `pull-request-authoring`
- `git-workflow`
- `/pr`
- `/review`

### Production Hardening

For risk reduction before shipping.

- `security-auditor`
- `/security-scan`
- `dependency-auditor`
- `performance-optimizer`
- `/optimize`
- `observability`
- `sre`

### Data and Backend

For APIs, schemas, migrations, and data systems.

- `api-designer`
- `database-expert`
- `data-engineer`
- `safe-database-migrations`
- `caching-strategies`
- `concurrency-and-parallelism`

### Frontend Product

For user-facing product work.

- `frontend-specialist`
- `accessibility-auditor`
- `technical-writing`
- `/docs`
- `code-reviewer`
- `test-engineer`

### Constellation Integration

For read-only coordination across a private multi-repository constellation.

- `architect`
- `orchestration`
- `task-ledger`
- `code-reviewer`
- `threat-modeling`
- `doctor`
- `dependency-auditor`
- `incident-responder`
- `technical-writing`

This bundle is a routing preset, not a permission grant. Its profile detects workspace
aliases and repository language evidence, but does not authorize security actions,
GitHub mutations, deployments, or production changes. Use the policy and approval
boundaries already defined by the selected host before any external effect.

## Workflows

### Ship a Feature

1. `/forge <feature goal>` — choose direct vs orchestrated route.
2. `/plan` or `/orchestrate` — define scope and acceptance criteria.
3. Implement in small steps.
4. `/test` — cover the risk surface.
5. `/review` — catch correctness, security, and maintainability issues.
6. `/commit` and `/pr` — ship with a clean human summary.

### Run an Orchestrated Release

1. `/orchestrate <release goal>` — plan at Opus/Fable and create `.forge/tasks`.
2. `/tasks list` — inspect the ledger and dependencies.
3. `/solve-loop` — drain ready tasks, verify evidence, and update status.
4. `/changelog` — summarize user-facing changes.
5. `/review` and `/security-scan` — final release gate.
6. Tag or publish only after the checks pass.

### Ship a Stacked Feature

1. `/orchestrate <goal>` — plan tasks and decide whether the review graph should be a
   stack.
2. `/stack init` — choose GitHub native, vanilla, Graphite, Aviator, Sapling, or classic
   ghstack and define the ultimate base.
3. Add bottom-up branches where every layer is independently understandable and testable.
4. `/stack check` then `/stack submit` — validate local ancestry and inspect the
   provider-native submission plan before changing GitHub.
5. `/stack-review` — review each layer against its immediate parent, bottom-up.
6. Address feedback on the owning layer, restack descendants, and verify post-command
   remote state.
7. `/stack land` — respect protection and queue policy; land atomically with native GitHub
   stacks or parent-first with the selected provider.

### Harden a Production App

1. `threat-modeling` — identify assets, trust boundaries, and likely failures.
2. `security-auditor` / `/security-scan` — review code and configuration.
3. `dependency-auditor` — check vulnerable and risky packages.
4. `performance-optimizer` / `/optimize` — measure and fix bottlenecks.
5. `observability` + `sre` — logs, metrics, SLOs, rollback, and runbooks.

### Stabilize a Flaky System

1. `/debug` — root-cause the failure before patching.
2. `concurrency-and-parallelism` or `caching-strategies` if the symptoms point there.
3. `/test` — reproduce and lock the behavior.
4. `/solve-loop` if the stabilization effort has multiple independent tasks.
5. `/review` — verify the fix did not mask the symptom.

## Machine-Readable Files

- [data/bundles.json](../data/bundles.json)
- [data/workflows.json](../data/workflows.json)
- [data/catalog.json](../data/catalog.json)
