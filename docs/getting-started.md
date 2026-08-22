# Getting Started

Forge is a Claude Code toolkit and Agent Skills-compatible pack for Codex, Zed, and
OpenCode. You can use it several ways, from lowest to highest commitment.

## Option 1 — Install as a Claude Code plugin (recommended)

This wires up agents, skills, commands, **and** hooks in one step, and keeps them
updated with a `git pull`.

```bash
# In Claude Code, add this repo as a marketplace, then install the plugin:
/plugin marketplace add AlisinaDevelo/md-files
/plugin install forge@forge
```

Restart Claude Code. Verify with `/agents` (you'll see the Forge agents), `/help` (the
slash commands), and by triggering a skill.

## Option 2 — Install as a Codex plugin

This gives Codex the Forge methodology skills, including orchestration, task ledgers, and
the solve loop.

```bash
codex plugin marketplace add AlisinaDevelo/md-files
codex plugin add forge@forge
```

Start a new Codex thread after installing so the plugin skills are loaded.

## Option 3 — Symlink into your Claude user config

Installs agents, skills, and commands at the user level (`~/.claude`). Hooks are left to
you to review and wire up (they run shell commands).

```bash
git clone https://github.com/AlisinaDevelo/md-files.git
cd md-files
./scripts/install.sh            # symlink (or --copy, or --dry-run)
```

## Option 4 — Install `.agents` skills for Codex, Zed, or OpenCode

This installs the Forge methodology skills plus specialist and command shims into
`~/.agents/skills`, which Codex, Zed, and OpenCode can read.

```bash
git clone https://github.com/AlisinaDevelo/md-files.git
cd md-files/zed
./install.sh            # symlink (or --copy, or --dry-run)
```

For an OpenCode-only install that does not change Zed configuration, run the repository
installer from the checkout root:

```bash
cd md-files
./scripts/install-opencode.sh --copy
```

See [OpenCode support](opencode.md) for the installed locations and verification steps.

## Option 5 — Cherry-pick

Everything here is plain Markdown and small scripts. Copy the individual agents, skills,
commands, or instruction snippets you want into your own `~/.claude/` or project
`.claude/` directory. Nothing is coupled — take what's useful.

## First things to try

- Run `/review` on a branch with changes — get a severity-ranked review of your diff.
- Run `/forge <goal>` when you are not sure which Forge capability to use.
- Ask Claude to "plan" a feature — the `architect` agent / `/plan` command produces a
  step-by-step plan before any code.
- Ask for "Forge orchestration" on a large goal — `/orchestrate` plans at Opus/Fable,
  writes a task ledger, routes tasks by agent/model, and drains the ledger with
  `/solve-loop`.
- Run `/stack status` in a large feature — Forge chooses GitHub native or another explicit
  provider, checks every parent edge, and plans reviewable dependent PRs without mutating
  Git or GitHub by default.
- Run `/doctor` before orchestration or delivery — it reports host tools, manifest and
  catalog drift, worktree state, stack validity, GitHub branch policy, rulesets, signed
  commits, and Merge Queue coverage without changing anything.
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
the plugin `name`/`author` in `plugins/forge/.claude-plugin/plugin.json` and
`plugins/forge/.codex-plugin/plugin.json`, the marketplace metadata in
`.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json`, and the install
URLs in the README to point at your fork. The components themselves need no changes.

See [usage-patterns.md](usage-patterns.md) for how the pieces combine in real workflows.
See [bundles-and-workflows.md](bundles-and-workflows.md) and [CATALOG.md](../CATALOG.md)
when choosing a focused Forge route.
See [stacked-changes.md](stacked-changes.md) for the current GitHub-native stack workflow,
provider comparison, safety model, and CI guidance.
See [github-native-stacks.md](github-native-stacks.md) for native stack inspect, import,
SHA-guarded reconciliation, and private-preview fallback behavior.
See [../plugins/forge/skills/doctor/SKILL.md](../plugins/forge/skills/doctor/SKILL.md) for
diagnostic statuses, offline behavior, JSON output, and read-only boundaries.
See [receipts.md](receipts.md) for the local evidence contract, privacy boundary, and
optional OTLP export.
See [github-task-ledger.md](github-task-ledger.md) for idempotent GitHub Issues sync,
native task relationships, conflict handling, and recovery.
See [release-provenance.md](release-provenance.md) for release asset verification,
installed-file mapping, SBOMs, and artifact attestations.
See [marketplace-readiness.md](marketplace-readiness.md) for repository marketplace
installation, directory status, publisher links, and host smoke tests.
See [capability-ir.md](capability-ir.md) for the canonical capability graph, host
projections, and migration workflow.
