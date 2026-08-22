# Forge Instructions

USE FORGE for software-engineering work. Prefer the available Forge skills for planning,
implementation, testing, debugging, review, security, and release work when they are
installed for the host.

## Forge checkout

Forge is a host-neutral collection of engineering skills and small scripts. In a Forge
checkout, Claude Code and Codex use their native plugin projections, while OpenCode uses
the Agent Skills projection declared in `opencode.json` and installed by
`scripts/install-opencode.sh`.

## Change discipline

- In a Forge checkout, read `CONTRIBUTING.md` and the relevant implementation before
  editing. In another repository, follow that repository's instructions first.
- Keep changes focused, auditable, and free of secrets or generated output.
- Preserve host-specific boundaries: Claude hooks and plugin manifests are not assumed to
  exist in OpenCode.
- Use the active repository's existing scripts and tests instead of adding parallel
  abstractions.

## Verification

Run the narrowest relevant checks while developing, then run the complete documented gate
before release work. In a Forge checkout:

```bash
./scripts/validate.sh
python3 -m pytest tests/ -q
```

For OpenCode discovery, use `opencode debug config` and `opencode debug skill` after
installing the Agent Skills projection. OpenCode permissions replace Claude lifecycle
hooks at that host boundary.
