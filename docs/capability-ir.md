# Capability IR

Forge maintains a versioned canonical capability graph at
[`data/capabilities.json`](../data/capabilities.json). It is the inventory and
compatibility contract for the reviewed agents, skills, and commands that are
projected into Claude Code, Codex, and the Agent Skills-compatible install.

## Source of truth

The Markdown files under `plugins/forge/` remain the reviewed instruction source.
The graph does not duplicate their bodies. Instead, each component records:

- a stable `id`, `kind`, and source path;
- normalized frontmatter used for routing and metadata;
- SHA-256 digests for the full source and instruction body;
- nested skill resources such as references and executable scripts;
- a lightweight risk label for catalog and review tooling; and
- an explicit projection for every supported host.

This makes source edits visible without creating a second prompt corpus. A change to a
component is incomplete until the graph is re-imported and reviewed.

## Schema and commands

The graph contract is defined by
[`data/capabilities.schema.json`](../data/capabilities.schema.json). The importer is
stdlib-only, deterministic, and intentionally small enough to audit:

```bash
# Check that the committed graph matches every current source and projection.
python3 scripts/compile_capabilities.py --check

# After an intentional component change, import the new graph and review the diff.
python3 scripts/compile_capabilities.py --write
git diff -- data/capabilities.json

# Check the catalog projection that consumes the graph.
python3 scripts/generate_catalog.py --check
```

`./scripts/validate.sh` runs the graph check as part of the repository gate, and release
packaging refuses to build when the graph is stale. A source edit that is not reflected
in the committed graph therefore fails locally and in CI.

## Host projections

| Host | Native projection | Deliberate degradation |
|------|-------------------|-------------------------|
| Claude Code | Agents, skills, and commands | Hooks, output styles, and settings remain host extensions |
| Codex | Skills | Claude agents and slash commands are omitted because Codex has no equivalent native kind |
| Agent Skills-compatible install | Skills | Agents and commands use reviewed Zed skill shims |

The graph records these decisions rather than silently pretending that every host has the
same runtime model. The `hosts` contract names the manifest and extensions associated with
each target; each component's `host_projections` then records `native`, `shim`, or
`omitted` mode and its path.

## Migration workflow

When adding, removing, or renaming a capability:

1. Edit the reviewed Markdown source and its resources.
2. Run `python3 scripts/compile_capabilities.py --write`.
3. Review the graph diff, especially identity, risk, resources, and projections.
4. Regenerate or check `CATALOG.md` and `data/catalog.json`.
5. Run `./scripts/validate.sh` and the normal test and lint gates.

Renames are intentionally visible as a removal plus an addition. This prevents an
apparently harmless path change from changing a host's install contract without review.

## Interoperability references

Forge follows the portable Agent Skills convention of a skill directory with a required
`SKILL.md` and optional supporting resources. See the
[Agent Skills specification](https://github.com/agentskills/agentskills) for the host
format and [description guidance](https://agentskills.io/skill-creation/optimizing-descriptions)
that informs progressive loading.

The graph also follows the useful separation used by
[GitHub Agentic Workflows](https://github.github.com/gh-aw/reference/compilation-process/):
editable source is kept distinct from deterministic generated output. Forge's current
slice applies that discipline to capability inventory and catalog projections while
keeping Markdown bodies as source.

## Current boundary

This is the phase-one graph foundation. It does not yet synthesize every instruction body,
plugin manifest, bundle, workflow, or third-party host adapter from a body-level IR. Those
surfaces remain reviewed repository artifacts and are checked by their existing validators.
The next compiler slice should introduce a body-level representation and a stable adapter
interface, then generate host files with semantic diffs and conformance fixtures. Until
that work lands, the graph must be described as an inventory and drift contract, not as a
complete host generator.
