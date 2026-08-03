# Capability IR

Forge maintains a versioned canonical capability graph at
[`data/capabilities.json`](../data/capabilities.json). It is the intermediate
representation for the reviewed agents, skills, and commands projected into Claude
Code, Codex, and the Agent Skills-compatible install.

## Source contract

The Markdown files under `plugins/forge/` remain the reviewed authoring format. The v2
graph embeds each instruction body so deterministic renderers do not need to re-parse
source files. Each component records:

- a stable `id`, `kind`, and source path;
- normalized frontmatter used for routing and metadata;
- identity, trigger kind, canonical Markdown instructions, tools, permissions, inputs,
  outputs, and linked eval scenarios;
- SHA-256 digests for the full source and instruction body;
- nested skill resources such as references and executable scripts;
- a lightweight risk label for catalog and review tooling;
- host extension requirements; and
- an explicit projection for every supported host.

The embedded body is regenerated from the reviewed Markdown and compared byte-for-byte
during graph validation. It is not an independently edited prompt corpus. A source edit
is incomplete until the graph is re-imported and reviewed.

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

# Check the catalog and host projections.
python3 scripts/generate_catalog.py --check
python3 scripts/render_capabilities.py --check

# Inspect a rendered projection without modifying the repository.
python3 scripts/render_capabilities.py --host agentskills --output /tmp/forge-projection

# Produce prompt-safe semantic evidence between graph revisions.
python3 scripts/diff_capabilities.py --before /tmp/capabilities-v1.json --format markdown

# Migrate a reviewed v1 graph only when source parity is proven.
python3 scripts/migrate_capabilities.py --input /tmp/capabilities-v1.json --output /tmp/capabilities-v2.json
```

`./scripts/validate.sh` runs both graph and renderer checks, and release packaging refuses
to build when either is stale or non-deterministic. A source edit that is not reflected
in the committed graph therefore fails locally and in CI.

## Host projections

| Host | Native projection | Deliberate degradation |
|------|-------------------|-------------------------|
| Claude Code | Agents, skills, and commands | Hooks, output styles, and settings remain host extensions |
| Codex | Skills | Claude agents and slash commands are omitted because Codex has no equivalent native kind |
| Agent Skills-compatible install | Skills | Agents and commands use reviewed Zed skill shims |

The graph records these decisions rather than silently pretending that every host has the
same runtime model. The `hosts` contract names the manifest and extensions associated
with each target; each component's `host_projections` then records `native`, `shim`, or
`omitted` mode and its path. `scripts/render_capabilities.py` consumes those projections
and writes a fresh host tree under the requested output directory. Native skills retain
their nested resources. Agent and command shims receive host-safe names and metadata;
Claude-only shell substitutions and `$ARGUMENTS` are adapted at that boundary.

Third-party hosts use the v1 adapter contract in
[`data/host-adapter.schema.json`](../data/host-adapter.schema.json) and can be rendered
without changing the compiler core:

```python
from scripts.render_capabilities import render_adapter

render_adapter(repo, graph, output, adapter_contract)
```

Adapters declare which component kinds are native or shims, their output roots, naming
prefixes, and extension inventory. Unsafe paths, overlapping native/shim kinds, and
unsupported component kinds fail closed.

Semantic diffs report component additions, removals, renames, metadata, permission,
resource, eval, and host-projection changes. Instruction changes are represented by
SHA-256 digests only; raw instruction bodies are never included in evidence output.
Migration accepts a v1 graph only when every component, source path, digest, resource
inventory, risk label, and host projection still matches the current reviewed source.

## Migration workflow

When adding, removing, or renaming a capability:

1. Edit the reviewed Markdown source and its resources.
2. Run `python3 scripts/compile_capabilities.py --write`.
3. Review the graph diff, especially identity, permissions, eval links, resources, and projections.
4. Run `python3 scripts/render_capabilities.py --check` and inspect a representative output tree.
5. Regenerate or check `CATALOG.md` and `data/catalog.json`.
6. Run `./scripts/validate.sh` and the normal test and lint gates.

Renames are intentionally visible as a removal plus an addition. This prevents an
apparently harmless path change from changing a host install contract without review.

## Interoperability references

Forge follows the portable Agent Skills convention of a skill directory with a required
`SKILL.md` and optional supporting resources. See the
[Agent Skills specification](https://github.com/agentskills/agentskills) for the host
format and [description guidance](https://agentskills.io/skill-creation/optimizing-descriptions)
that informs progressive loading.

The graph also follows the useful separation used by
[GitHub Agentic Workflows](https://github.github.com/gh-aw/reference/compilation-process/):
editable source is kept distinct from deterministic generated output. Forge applies that
discipline to capability import, host projections, and catalog projections while keeping
Markdown as the reviewed authoring format.

## Current boundary

The body-aware compiler and deterministic component renderer are now in place. The
renderer generates component files, nested skill resources, built-in manifests, and
host-specific shims. Release bundles, workflow metadata, and the repository's reviewed
Zed shims remain explicit release artifacts for now; the next slice should derive those
surfaces from rendered projections and add semantic-diff and schema-migration reports.
