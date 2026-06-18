# MCP Server Configurations

[Model Context Protocol](https://modelcontextprotocol.io) servers extend Claude Code with
tools and data sources — filesystem access, GitHub, databases, browser automation, and
more. They're how you give agents real capabilities beyond reading and editing files.

## Scopes

Claude Code reads MCP config from three places (later overrides earlier):

| Scope | File | Use |
|-------|------|-----|
| User | `~/.claude.json` | servers you want everywhere |
| Project | `.mcp.json` (repo root, committed) | servers the whole team shares |
| Local | project config, not committed | personal/experimental servers |

## Quickstart

Copy [`.mcp.json.example`](.mcp.json.example) to your project root as `.mcp.json`, keep
the servers you need, and fill in any required env. Then restart Claude Code and run
`/mcp` to confirm they're connected.

```bash
cp mcp/.mcp.json.example /path/to/your/project/.mcp.json
```

## Guidance

- **Least privilege.** Scope filesystem servers to the directories they need; give tokens
  the minimum permissions. An MCP server is code you're trusting with your tools.
- **Secrets via env, never inline.** Reference `${ENV_VAR}` and keep the actual values in
  your shell/secret store — never commit a token into `.mcp.json`.
- **Only what you use.** Each connected server adds tools (and tool descriptions) to the
  context. Disconnect ones you aren't using to keep the surface lean.
- **Vet third-party servers** before connecting — they can read what you expose to them.
