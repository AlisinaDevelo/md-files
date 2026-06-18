<div align="center">

# 🔨 Forge

**An enterprise-grade Claude Code toolkit — specialized agents, progressive-disclosure
skills, slash commands, and safety hooks that maximize the efficacy of LLMs in software
engineering.**

[![CI](https://github.com/AlisinaDevelo/md-files/actions/workflows/ci.yml/badge.svg)](https://github.com/AlisinaDevelo/md-files/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-plugin-d97757.svg)](https://docs.claude.com/en/docs/claude-code)
[![Agents](https://img.shields.io/badge/agents-18-8b5cf6.svg)](plugins/forge/agents/)
[![Skills](https://img.shields.io/badge/skills-15-06b6d4.svg)](plugins/forge/skills/)
[![Commands](https://img.shields.io/badge/commands-12-22c55e.svg)](plugins/forge/commands/)
[![Hook tests](https://img.shields.io/badge/hook%20tests-54%20passing-success.svg)](tests/)
[![Prompt evals](https://img.shields.io/badge/prompt%20evals-213%20checks-success.svg)](evals/)

</div>

---

Forge is a curated, batteries-included configuration for [Claude Code](https://docs.claude.com/en/docs/claude-code).
It packages the patterns that make an AI coding agent genuinely effective — clear role
definitions, disciplined methodologies, the right tools for each job, and guardrails that
keep it safe — into one installable plugin. Every artifact is plain Markdown or a small,
auditable script: no build step, no magic, nothing hidden from you.

## Table of contents

- [Why Forge](#why-forge)
- [Install](#install)
- [What's inside](#whats-inside)
  - [Agents](#agents)
  - [Skills](#skills)
  - [Commands](#commands)
  - [Hooks](#hooks)
  - [Output styles, status line & settings](#output-styles-status-line--settings)
  - [Instructions & MCP](#instructions--mcp)
  - [Evidence — evals & tests](#evidence--evals--tests)
- [How the pieces fit](#how-the-pieces-fit)
- [Repository layout](#repository-layout)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## Why Forge

LLM coding agents are only as good as the scaffolding around them. The same model
produces dramatically different results depending on whether it has a sharp role, a
proven method, scoped tools, and guardrails. Forge encodes that scaffolding:

- **Specialists, not a generalist.** Eighteen agents each with a focused role, a concrete
  methodology, scoped tools, and a defined output format — a reviewer that thinks like a
  reviewer, a debugger that finds root causes, an auditor that traces taint to sinks.
- **Methodology on tap.** Fifteen skills inject battle-tested practices — TDD, root-cause
  debugging, threat modeling, safe migrations — exactly when the situation calls for them.
- **One-keystroke workflows.** Twelve slash commands wrap the everyday loop: review,
  test, debug, plan, commit, PR.
- **Safety by default.** Lifecycle hooks block catastrophic commands and secret leaks,
  auto-format edits, inject repo context at session start, and notify you on completion —
  deterministically, without relying on the model to remember.
- **Proven, not asserted.** A real eval harness scores every prompt (213 static checks +
  an opt-in LLM-judge behavioral eval) and a 54-test suite covers the safety hooks. Run
  them yourself — `just check`. This is the [evidence layer](evals/), not a README claim.
- **Auditable & self-validating.** Read every prompt and script. CI validates structure,
  runs the tests, and scores the evals on every push.

## Install

**As a plugin (recommended — includes hooks):**

```bash
# In Claude Code:
/plugin marketplace add AlisinaDevelo/md-files
/plugin install forge@forge
```

**As user-level symlinks (agents, skills, commands):**

```bash
git clone https://github.com/AlisinaDevelo/md-files.git && cd md-files
./scripts/install.sh        # or --copy / --dry-run
```

**Cherry-pick:** everything is plain Markdown — copy any file into your own `~/.claude/`
or project `.claude/`. See [docs/getting-started.md](docs/getting-started.md) for details.

## What's inside

### Agents

Delegated, autonomous specialists with their own context and scoped tools.

| Agent | Role |
|-------|------|
| [`code-reviewer`](plugins/forge/agents/code-reviewer.md) | Severity-ranked review for correctness, security, and maintainability |
| [`debugger`](plugins/forge/agents/debugger.md) | Hypothesis-driven root-cause diagnosis |
| [`security-auditor`](plugins/forge/agents/security-auditor.md) | Defensive vulnerability review (OWASP/CWE, taint→sink) |
| [`test-engineer`](plugins/forge/agents/test-engineer.md) | Behavior-focused tests that reduce real risk |
| [`architect`](plugins/forge/agents/architect.md) | Implementation plans and architectural trade-offs |
| [`refactoring-specialist`](plugins/forge/agents/refactoring-specialist.md) | Behavior-preserving structural improvement |
| [`performance-optimizer`](plugins/forge/agents/performance-optimizer.md) | Measure-first bottleneck diagnosis and fixes |
| [`database-expert`](plugins/forge/agents/database-expert.md) | Schema design, query tuning, safe migrations |
| [`api-designer`](plugins/forge/agents/api-designer.md) | Consistent, evolvable API contracts |
| [`frontend-specialist`](plugins/forge/agents/frontend-specialist.md) | Component architecture, state, render performance |
| [`accessibility-auditor`](plugins/forge/agents/accessibility-auditor.md) | WCAG audit and remediation |
| [`dependency-auditor`](plugins/forge/agents/dependency-auditor.md) | CVEs, license risk, safe upgrade planning |
| [`devops-engineer`](plugins/forge/agents/devops-engineer.md) | CI/CD, containers, IaC, safe deploys |
| [`docs-writer`](plugins/forge/agents/docs-writer.md) | Accurate, example-driven documentation |
| [`incident-responder`](plugins/forge/agents/incident-responder.md) | Triage, mitigate, then root-cause + postmortem |
| [`code-archaeologist`](plugins/forge/agents/code-archaeologist.md) | Understand unfamiliar/legacy code before changing it |
| [`migration-specialist`](plugins/forge/agents/migration-specialist.md) | Incremental, reversible framework/library/API migrations |
| [`tech-lead`](plugins/forge/agents/tech-lead.md) | Orchestrates large tasks across the specialists |

### Skills

Methodologies and references injected into the current conversation when the situation
matches. Several use **progressive disclosure** — a lean `SKILL.md` plus deeper reference
files loaded only when needed.

| Skill | When it fires |
|-------|---------------|
| [`test-driven-development`](plugins/forge/skills/test-driven-development/) | Implementing test-first (red-green-refactor) |
| [`root-cause-debugging`](plugins/forge/skills/root-cause-debugging/) | Diagnosing a bug or failure |
| [`code-review-rubric`](plugins/forge/skills/code-review-rubric/) | Reviewing code (+ full checklist) |
| [`refactoring-catalog`](plugins/forge/skills/refactoring-catalog/) | Improving structure (+ smell→fix catalog) |
| [`conventional-commits`](plugins/forge/skills/conventional-commits/) | Writing commit messages |
| [`pull-request-authoring`](plugins/forge/skills/pull-request-authoring/) | Opening a reviewable PR |
| [`api-design`](plugins/forge/skills/api-design/) | Designing or reviewing an API |
| [`threat-modeling`](plugins/forge/skills/threat-modeling/) | Security design review (STRIDE) |
| [`safe-database-migrations`](plugins/forge/skills/safe-database-migrations/) | Schema changes on live data |
| [`performance-profiling`](plugins/forge/skills/performance-profiling/) | Investigating performance |
| [`observability`](plugins/forge/skills/observability/) | Adding logs/metrics/traces |
| [`technical-writing`](plugins/forge/skills/technical-writing/) | Writing developer docs |
| [`git-workflow`](plugins/forge/skills/git-workflow/) | Branching, rebasing, conflicts, recovery, bisect |
| [`error-handling`](plugins/forge/skills/error-handling/) | Designing robust failure paths |
| [`prompt-engineering`](plugins/forge/skills/prompt-engineering/) | Authoring agents/skills/commands |

### Commands

User-triggered prompt templates with argument and shell injection.

| Command | Does |
|---------|------|
| `/review` | Review the current diff, severity-ranked |
| `/commit` | Draft a Conventional Commit for staged changes |
| `/test` | Write tests matching the repo's harness |
| `/debug` | Root-cause a bug before fixing |
| `/plan` | Step-by-step implementation plan |
| `/refactor` | Behavior-preserving cleanup |
| `/security-scan` | Defensive security review of the diff |
| `/pr` | Draft a PR description from the branch |
| `/optimize` | Measure-first performance fix |
| `/explain` | Explain a file, symbol, or system |
| `/docs` | Write docs grounded in the code |
| `/tidy` | Remove cruft from the diff, behavior-preserving |

### Hooks

Deterministic guardrails the harness runs on lifecycle events — no model memory required.

| Hook | Event | Effect |
|------|-------|--------|
| [`session-context`](plugins/forge/hooks/scripts/session-context.py) | SessionStart | Injects current branch, ahead/behind, dirty count, and recent commits as context |
| [`guard-bash`](plugins/forge/hooks/scripts/guard-bash.py) | PreToolUse(Bash) | Blocks catastrophic commands (`rm -rf /`, force-push to main, fork bombs) |
| [`scan-secrets`](plugins/forge/hooks/scripts/scan-secrets.py) | PreToolUse(Write/Edit) | Blocks writing credentials into files |
| [`format-file`](plugins/forge/hooks/scripts/format-file.sh) | PostToolUse(Write/Edit) | Auto-formats edited files with the installed formatter |
| [`notify`](plugins/forge/hooks/scripts/notify.sh) | Stop | Desktop notification when a turn finishes |

### Output styles, status line & settings

- [`output-styles/`](plugins/forge/output-styles/) — selectable system-prompt modes:
  **Concise Engineer** (answer-first, no preamble) and **Mentor** (teaches the *why* as it
  works). Ship with the plugin; pick one via `/config`.
- [`statusline/`](statusline/) — a status line showing model · dir · git · context% · cost.
- [`settings/`](settings/) — example `settings.json` (permission allowlist, deny rules for
  secrets, status line, output style) to pair with the plugin.

### Instructions & MCP

- [`instructions/`](instructions/) — a `CLAUDE.md` template library, stack-agnostic
  [engineering principles](instructions/engineering-principles.md), and language snippets
  (TypeScript, Python, Go).
- [`mcp/`](mcp/) — example Model Context Protocol server configs with least-privilege
  guidance.

### Evidence — evals & tests

- [`evals/`](evals/) — the proof the prompts work: 213 static prompt-quality checks (free,
  in CI) plus an opt-in LLM-judge behavioral eval that scores agents against real tasks.
- [`tests/`](tests/) — a 54-test pytest suite covering the safety hooks (blocks the
  dangerous, allows the safe, fails open on garbage). `just check` runs it all.

## How the pieces fit

```text
        plan ──▶ implement ──▶ review ──▶ test ──▶ debug ──▶ ship
         │                       │          │        │         │
     architect              code-reviewer  test-   debugger  /commit
       /plan                  /review     engineer  /debug    /pr
                                           /test

   guardrails (always on):  guard-bash · scan-secrets · format-file · notify
```

Agents go deep on focused jobs; skills supply the method; commands trigger the loop;
hooks keep it safe. The `tech-lead` agent orchestrates all of them for big tasks. See
[docs/usage-patterns.md](docs/usage-patterns.md).

## Repository layout

```text
.claude-plugin/        marketplace manifest (catalog of plugins)
plugins/forge/         the Forge plugin
  .claude-plugin/        plugin manifest
  agents/                18 specialist subagents
  skills/                15 progressive-disclosure skills
  commands/              12 slash commands
  hooks/                 5 lifecycle hooks (session-context, guard, secrets, format, notify)
  output-styles/         selectable system-prompt modes
instructions/          CLAUDE.md templates, principles, language guides
mcp/                   example MCP server configs
statusline/            status line script
settings/              example settings.json
evals/                 prompt eval harness + cases (evidence)
tests/                 runnable hook tests
docs/                  getting started, usage, architecture, rationale, CI
scripts/               validate.sh, install.sh
.github/               CI, issue/PR templates, CODEOWNERS, dependabot
```

## Documentation

- [Getting started](docs/getting-started.md) — install options and first steps
- [Usage patterns](docs/usage-patterns.md) — how the components combine in real workflows
- [Architecture](docs/architecture.md) — how the repo is organized and why
- [Design rationale](docs/design-rationale.md) — the decisions and trade-offs behind Forge
- [CI & headless usage](docs/ci-and-headless.md) — run Forge in pipelines and automated review
- [Evals](evals/) — the evidence layer · [Tests](tests/) — hook test suite
- [Contributing](CONTRIBUTING.md) — add an agent, skill, command, or hook
- [Changelog](CHANGELOG.md)

## Contributing

Contributions are welcome — new agents, skills, commands, and hooks, or improvements to
existing ones. Run `./scripts/validate.sh` before opening a PR. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the conventions and the quality bar.

## License

[MIT](LICENSE) © Alisina Karimi
