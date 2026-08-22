# OpenCode

Forge supports OpenCode through its stable Agent Skills and `AGENTS.md` interfaces. The
repository does not pretend that Claude plugin hooks or Codex marketplace manifests are
portable host features.

## Install

From a Forge checkout:

```bash
./scripts/install-opencode.sh --copy
```

The installer writes only to the OpenCode-compatible locations:

| Surface | Location | Contents |
|---|---|---|
| Global skills | `~/.agents/skills/` | 25 methodology skills, 20 specialist skills, and 22 command skills |
| Global instructions | `~/.config/opencode/AGENTS.md` | Forge engineering and verification rules |

Use `--symlink` when the checkout should provide live updates, or `--dry-run` to preview
the exact files. Existing conflicting files are preserved unless `--force` is supplied.

The project-level `opencode.json` also points OpenCode at `plugins/forge/skills`, so a
fresh checkout exposes the 25 methodology skills without a global install.

## Verify

Restart OpenCode after installation, then run:

```bash
opencode --version
opencode debug config
opencode debug skill
```

Ask OpenCode to use `orchestration`, `task-ledger`, `iterate-to-done`, or
`forge-cmd-review` for a relevant request. Skills load on demand rather than injecting
their full bodies into every prompt.

## Host boundaries

OpenCode does not consume Forge's `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`,
or repository marketplace manifests. Claude lifecycle hooks such as destructive-command
guards, secret scanning, formatting, and notifications also do not run automatically in
OpenCode. Use OpenCode's permission rules and repository hooks/CI for those controls.

Forge's model labels are guidance, not OpenCode model identifiers. Configure the provider
and model in OpenCode separately; do not copy Claude or Codex model aliases into an
OpenCode config.

See the [OpenCode Agent Skills documentation](https://opencode.ai/docs/skills),
[rules documentation](https://opencode.ai/docs/rules/), and
[command documentation](https://opencode.ai/docs/commands/) for the host contract.
