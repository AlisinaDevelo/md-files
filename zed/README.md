# Forge for Zed

Forge ported to [Zed](https://zed.dev) and `.agents`-based Codex setups — the same
specialist expertise, orchestration discipline, and engineering methods adapted to what
the host agent actually supports.

## What's included

| Component | Count | Zed mechanism |
|---|---|---|
| Methodology skills | 25 | `~/.agents/skills/<name>/` |
| Specialist agent skills | 20 | `~/.agents/skills/forge-<name>/` |
| Slash command skills | 22 | `~/.agents/skills/forge-cmd-<name>/` with `disable-model-invocation: true` |
| Agent profiles | 2 | `~/.config/zed/settings.json` → `agent.profiles` |
| Global instructions | 1 | `~/.config/zed/AGENTS.md` |

## Install

```bash
cd zed
./install.sh          # installs everything (idempotent, safe to re-run)
./install.sh --dry-run  # preview what will be installed
./install.sh --copy     # copy files instead of symlinking
```

## Usage

### Skills (auto-triggered)

Forge skills load automatically when the situation matches their description. You can also mention them explicitly: "use the forge-debugger approach" or `@forge-debugger`.

### Slash commands

Type `/forge-cmd-` in the agent panel to see all 22 commands. Examples:

- `/forge-cmd-forge` — choose the right Forge route
- `/forge-cmd-review` — review the current diff
- `/forge-cmd-commit` — draft a Conventional Commit
- `/forge-cmd-plan your feature idea` — get an implementation plan
- `/forge-cmd-debug the failing test` — root-cause a bug
- `/forge-cmd-orchestrate ship this feature` — plan, ledger, route, and solve
- `/forge-cmd-tasks list` — inspect or update the task ledger
- `/forge-cmd-solve-loop` — drain ready tasks until done or blocked
- `/forge-cmd-stack` — inspect, submit, restack, repair, or land a PR stack
- `/forge-cmd-stack-review` — review every layer against its immediate parent
- `/forge-cmd-policy` — evaluate policy, stage effects, approve, authorize, or record outcomes

### Profiles

Select **Forge: Concise Engineer** or **Forge: Mentor** from the profile selector in the agent panel. Concise leads with the answer; Mentor explains the why.

## What doesn't port (yet)

Zed doesn't support lifecycle hooks, so the following Claude Code features have no equivalent:

| Hook | Effect | Workaround |
|---|---|---|
| `guard-bash` | Blocks destructive shell commands | Use Zed's permission system in settings |
| `scan-secrets` | Blocks writing credentials to files | Add `scan-secrets.py` as a pre-commit git hook |
| `format-file` | Auto-formats after every edit | Zed auto-formats on save natively |
| `notify` | Desktop notification on turn complete | Zed has built-in turn-complete indicators |

Hook scripts are still available at `../plugins/forge/hooks/scripts/` for use as git hooks or CI checks.

## Files

```text
zed/
├── README.md               this file
├── install.sh              idempotent install script
├── skills/                 67 installed skill surfaces
│   ├── methodology/        25 methodology skills plus nested refs/scripts
│   ├── agents/             20 specialist agent skills
│   └── commands/           22 slash command skills
├── settings/
│   └── profiles.json       the two Forge profiles to merge into settings.json
└── AGENTS.md               global instructions for ~/.config/zed/AGENTS.md
```
