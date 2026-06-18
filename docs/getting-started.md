# Getting Started

Forge is a Claude Code toolkit. You can use it three ways, from lowest to highest
commitment.

## Option 1 — Install as a plugin (recommended)

This wires up agents, skills, commands, **and** hooks in one step, and keeps them
updated with a `git pull`.

```bash
# In Claude Code, add this repo as a marketplace, then install the plugin:
/plugin marketplace add AlisinaDevelo/md-files
/plugin install forge@forge
```

Restart Claude Code. Verify with `/agents` (you'll see the Forge agents), `/help` (the
slash commands), and by triggering a skill.

## Option 2 — Symlink into your user config

Installs agents, skills, and commands at the user level (`~/.claude`). Hooks are left to
you to review and wire up (they run shell commands).

```bash
git clone https://github.com/AlisinaDevelo/md-files.git
cd md-files
./scripts/install.sh            # symlink (or --copy, or --dry-run)
```

## Option 3 — Cherry-pick

Everything here is plain Markdown and small scripts. Copy the individual agents, skills,
commands, or instruction snippets you want into your own `~/.claude/` or project
`.claude/` directory. Nothing is coupled — take what's useful.

## First things to try

- Run `/review` on a branch with changes — get a severity-ranked review of your diff.
- Ask Claude to "plan" a feature — the `architect` agent / `/plan` command produces a
  step-by-step plan before any code.
- Make an edit that includes a fake AWS key — watch the secret-scanner hook block it.
- Ask Claude to "debug" a failing test — the root-cause method kicks in.

## Configure to taste

- **Trim the hooks.** Open `plugins/forge/hooks/hooks.json` and remove any you don't want (e.g. the
  desktop notification). The dangerous-command guard and secret scanner are the
  high-value ones.
- **Adjust agent models.** Each agent's frontmatter sets a `model`. Bump heavy reasoning
  agents (`architect`, `tech-lead`) to a larger model, or pull simple ones down.
- **Layer your CLAUDE.md.** Start from `instructions/templates/global-CLAUDE.md` for your
  personal defaults, and use the project template per repo.

## Using Forge in any project

Forge is **project-agnostic** — install it once at user scope and it works in every repo
you open. It assumes nothing about your stack, framework, language, or directory layout:

- **Agents and skills** describe general engineering methods; the stack-specific ones
  (`frontend-specialist`, `database-expert`, …) only trigger on relevant requests, so they
  stay quiet in projects where they don't apply.
- **Hooks adapt to the project they run in.** `session-context` reads the current repo's
  git state (and no-ops outside a git repo); `format-file` runs whatever formatter is
  installed for the file type (and silently does nothing if none is); `guard-bash` and
  `scan-secrets` are content-based and language-agnostic. None of them hardcode a path.
- **Nothing is wired to this repo.** The shipped plugin contains no absolute paths, no
  author-specific assumptions, and no references to the `md-files` repo itself.

So the recommended path — `/plugin marketplace add AlisinaDevelo/md-files` then
`/plugin install forge@forge` — gives you the whole toolkit in any project. Per-project
conventions belong in that project's `CLAUDE.md` (start from
[`instructions/templates/`](../instructions/templates/)), not in Forge.

**Forking it as your own toolkit?** Everything's plain Markdown and small scripts. Change
the plugin `name`/`author` in `plugins/forge/.claude-plugin/plugin.json`, the marketplace
`name`/`owner` in `.claude-plugin/marketplace.json`, and the install URLs in the README to
point at your fork. The components themselves need no changes.

See [usage-patterns.md](usage-patterns.md) for how the pieces combine in real workflows.
