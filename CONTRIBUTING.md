# Contributing to Forge

Thanks for contributing. Forge is a toolkit of prompts and small scripts — the bar is
**quality and precision over quantity**. A vague agent or an over-eager skill makes the
whole toolkit worse, so every addition should earn its place.

## Ground rules

- Run `./scripts/validate.sh` before opening a PR; CI runs it too.
- Keep markdown lint-clean (`markdownlint-cli2` config in `.markdownlint.yaml`).
- Use [Conventional Commits](plugins/forge/skills/conventional-commits/SKILL.md).
- Don't add an AI co-author trailer to commits.
- One focused change per PR; explain what and why (see the PR template).

## Adding an agent

Create `plugins/forge/agents/<name>.md` with YAML frontmatter and a system-prompt body.

```yaml
---
name: my-agent                 # kebab-case, matches the filename
description: >-                 # the ONLY thing the model sees when deciding to invoke
  Use this agent when <concrete situations + keywords a user would say>. Include
  1–2 example triggers. State what it's for and what it's not.
tools: Read, Grep, Glob, Bash  # least privilege — omit Edit for read-only agents
model: sonnet                  # haiku | sonnet | opus, by reasoning load
color: green
---
```

Body structure: **Role** (who it is, what it optimizes for) → **Method** (numbered,
concrete steps) → **Output format** (an explicit template) → **Boundaries** (what not to
do; what to do when uncertain). Write positive instructions; show formats with examples.

## Adding a skill

Create `plugins/forge/skills/<name>/SKILL.md`. The `description` must be situational and triggering
("Use when…"). Keep `SKILL.md` lean; push exhaustive references (checklists, catalogs)
into sibling files and point to them by name (progressive disclosure — see
`plugins/forge/skills/code-review-rubric/` and `plugins/forge/skills/refactoring-catalog/`).

## Adding a command

Create `plugins/forge/commands/<name>.md`. Frontmatter: `description`, optional `argument-hint`,
`allowed-tools` (scope tightly — e.g. `Bash(git diff:*)`), optional `model`. Use
`$ARGUMENTS`/`$1`, `` !`cmd` `` to inject shell output, and `@path` to inline files.

## Adding a hook

Add the script to `plugins/forge/hooks/scripts/` (make it `chmod +x`) and register it in
`plugins/forge/hooks/hooks.json`. Hooks must:

- **Fail open** on malformed input — never brick a session over a parse error.
- **Block hard** (exit 2 + a clear stderr message) only on high-confidence problems.
  False positives erode trust in the guard.
- Be cross-platform and degrade silently when an optional tool is absent.
- Reference scripts via `${CLAUDE_PLUGIN_ROOT}` so they resolve when installed as a plugin.

Test it by piping a sample payload (see the examples in the PR that added the guard).

## Quality bar

- **Descriptions trigger reliably** without over-firing on unrelated requests.
- **Specific over generic** — encode real methodology, not platitudes.
- **Calibrated** — instruct the model to express uncertainty and prefer evidence.
- **Minimal** — no abstraction or instruction that doesn't pull its weight in context.

## Local checks

```bash
./scripts/validate.sh                      # frontmatter, JSON, hook scripts
npx markdownlint-cli2 "**/*.md"            # markdown lint
shellcheck plugins/forge/hooks/scripts/*.sh scripts/*.sh # shell lint (if installed)
```
