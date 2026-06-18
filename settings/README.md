# Settings

Example [Claude Code `settings.json`](https://code.claude.com/docs/en/settings) to pair
with Forge. Settings layer by scope (later overrides earlier):

| Scope | File | Commit it? |
|-------|------|------------|
| User | `~/.claude/settings.json` | personal, not in any repo |
| Project | `.claude/settings.json` | yes — shared team defaults |
| Local | `.claude/settings.local.json` | no — gitignored personal overrides |

## What's in the example

[`settings.json.example`](settings.json.example) shows the high-value keys:

- **`permissions.allow`** — an allowlist of safe, read-only and test commands so Claude
  runs them without prompting you. Tune to your stack (swap `npm`/`pytest`/`just` for
  yours). Pair with the Forge `guard-bash` hook, which blocks the genuinely dangerous
  commands regardless of allowlist.
- **`permissions.deny`** — belt-and-suspenders: never read `.env`/secrets, even if asked.
  Complements the `scan-secrets` hook (which stops Claude *writing* secrets).
- **`statusLine`** — wires up [`../statusline/forge-statusline.sh`](../statusline/).
- **`outputStyle`** — selects one of the Forge output styles (e.g. `"Concise Engineer"`).

## Note on hooks

You do **not** copy hooks into settings when you install Forge as a plugin — the plugin
ships its own `hooks/hooks.json` and Claude Code loads it automatically. The `settings.json`
hooks block is only for hooks you define outside a plugin. Keeping Forge's guardrails in
the plugin (not your settings) means a `git pull` updates them and you can't accidentally
drop one.

## Validate

```bash
jq empty settings/settings.json.example   # valid JSON
```

The `$schema` line gives you autocomplete and validation in editors that understand JSON
Schema.
