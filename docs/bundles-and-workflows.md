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
