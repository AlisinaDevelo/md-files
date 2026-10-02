# OpenCode

Forge integrates with OpenCode through Agent Skills (`SKILL.md`) and `AGENTS.md`. The
installer does not install Claude Code hooks, plugin manifests, or Codex marketplace
metadata; configure OpenCode permissions separately for its tools.

## Configuration Profiles

The default [`opencode.json`](../opencode.json) keeps the V1 skills object:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "skills": {
    "paths": ["./plugins/forge/skills"]
  }
}
```

Keep this profile for V1 installations. OpenCode V2 is intended to read supported V1
configuration without rewriting it. The optional
[`opencode.v2.json`](../opencode.v2.json) shows V2's native array form:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "skills": ["./plugins/forge/skills"]
}
```

`opencode.v2.json` is a reference profile, not a filename OpenCode discovers
automatically.
Select it explicitly when testing with a V2 build; do not replace `opencode.json` for V1
users. From the Forge repository root, select the profile for V2 with:

```bash
OPENCODE_CONFIG="$PWD/opencode.v2.json" opencode debug config
```

Relative skill paths resolve from OpenCode's active working directory, so run from the
Forge repository root when using either profile. In V2, skill IDs are derived from the
skill path, not the frontmatter `name`; Forge keeps the final directory name and skill
name aligned.

## Install

From a Forge checkout:

```bash
./scripts/install-opencode.sh --copy
```

The installer writes only these targets by default:

The global projection contains 67 skills: 25 methodology, 20 specialist, and 22 command
skills.

| Surface | Default location | Contents |
|---|---|---|
| Global skills | `~/.agents/skills/` | Forge Agent Skills |
| Global instructions | `~/.config/opencode/AGENTS.md` | Forge engineering rules |

Use `--symlink` to link installed files to this checkout, or `--dry-run` to preview the
operations without writing. Existing conflicting files are preserved unless `--force` is
explicitly supplied. `--force` replaces conflicting files or symlinks one at a time and
always refuses a directory; it never recursively removes user directories. The installer
does not prune unrelated or stale files. Set `OPENCODE_SKILLS_DIR` or
`OPENCODE_CONFIG_DIR` to change the respective destinations.

## Verify

Restart OpenCode after installation. For V1, run:

```bash
opencode --version
opencode debug config
opencode debug skill
```

For V2, use `opencode debug config` to inspect normalized configuration sources.
V2 does not provide `opencode debug skill`; its experimental read-only `skill.list`
API is the discovery surface. Skill activation uses the exact path-derived ID.

Ask OpenCode to use `orchestration`, `task-ledger`, `iterate-to-done`, or
`forge-cmd-review` for a relevant request. Skills load on demand rather than injecting
their full bodies into every prompt.

## Host Boundaries

OpenCode discovers Agent Skills from its configured skill roots and the supported
compatibility directories. Global Forge skills are installed under `~/.agents/skills/`;
the global `AGENTS.md` is installed under `~/.config/opencode/`. OpenCode does not consume
Forge's `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, or repository
marketplace manifests. Claude lifecycle hooks such as destructive-command guards, secret
scanning, formatting, and notifications do not run automatically in OpenCode.

Forge's model labels are guidance, not OpenCode model identifiers. Configure the
provider and model in OpenCode separately; do not copy Claude or Codex model aliases into
an OpenCode config.

See the official [V1 config](https://opencode.ai/docs/config),
[V1 skills](https://opencode.ai/docs/skills),
[V2 config](https://opencode.ai/v2/docs/config),
[V2 skills](https://opencode.ai/v2/docs/skills), and
[V1-to-V2 migration](https://opencode.ai/v2/docs/migrate-v1/) documentation for the host
contract and migration details.
