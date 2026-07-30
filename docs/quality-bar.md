# Forge Quality Bar

Forge does not try to win by having the most files. It wins when every component is
trustworthy, composable, and useful under pressure.

## Required for Every Component

| Area | Standard |
|------|----------|
| Trigger clarity | Frontmatter says when to use it and what not to use instead when ambiguity is likely. |
| Scope discipline | The component has one job. Adjacent workflows are linked rather than merged into a giant prompt. |
| Verification | The output says how correctness is checked: tests, diff review, rendered artifact, command output, or acceptance criteria. |
| Safety | Mutating, external, credentialed, production, or security-sensitive actions name their approval boundary. |
| Progressive disclosure | Long reference material lives in `references/`, `CATALOG.md`, or docs; the core prompt stays lean. |
| Examples | User-facing workflows include a concrete prompt, command, or output shape. |
| Compatibility | Claude Code, Codex, and `.agents` installs are considered before release. |

## Risk Labels

Forge uses lightweight risk labels in the generated catalog:

- `none` — reasoning/text only.
- `safe` — may read files or run non-mutating commands.
- `critical` — may write files, change state, call external systems, or publish.
- `security-sensitive` — defensive security work requiring care and authorization.

Risk labels guide routing and review; they do not replace judgment.

## Release Gate

Before a release, run:

```bash
./scripts/validate.sh
python3 evals/run.py
python3 -m pytest tests/ -q
npx --yes markdownlint-cli2 "**/*.md"
shellcheck plugins/forge/hooks/scripts/*.sh scripts/*.sh zed/install.sh
python3 scripts/generate_catalog.py --check
```

Also validate the plugin manifests:

```bash
claude plugin validate plugins/forge
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/forge
```

The gate also requires Claude, Codex, and marketplace version parity; executable and
compilable nested skill scripts; and `.agents` installation that preserves references and
scripts. If a component changes behavior, add or update an eval. Executable engines need
subprocess tests for their failure and recovery paths.

## What Forge Should Not Copy

- Giant catalogs without a quality gate.
- Persona sprawl that makes route selection harder.
- Vague "do everything" skills.
- Security or deployment guidance without approval boundaries.
- Generated skills that have no examples, limitations, or verification path.
