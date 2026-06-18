# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/AlisinaDevelo/md-files/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/AlisinaDevelo/md-files/releases/tag/v1.0.0
