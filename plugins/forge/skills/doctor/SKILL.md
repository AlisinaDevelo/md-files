---
name: doctor
description: >-
  Use before orchestration, stack delivery, or a release when the host and repository
  need a read-only capability and merge-readiness preflight. Run the Forge Doctor CLI,
  interpret pass/warn/fail/unknown evidence, and never mutate policy or install tools.
---

# Forge Doctor

Forge Doctor is a read-only preflight for the host and repository. It turns capability
drift and merge surprises into evidence before a run starts.

## Run it

From the repository root:

```bash
python3 scripts/forge-doctor.py
python3 scripts/forge-doctor.py --json
python3 scripts/forge-doctor.py --offline
```

Use `--strict` in CI or a release gate when warnings and unknown checks should fail the
caller. The default mode exits non-zero only for a `fail` check.

## Interpret results

- `pass` means the check found the expected capability or policy.
- `warn` means work can continue, but a degraded capability or policy gap is visible.
- `fail` means the run should stop until the reported condition is repaired.
- `unknown` means the evidence was unavailable, commonly because the run is offline or
  the GitHub token lacks a read scope.

The JSON report has schema version `1`. It is evidence for orchestration and CI policy,
not a security certification. It intentionally excludes prompts, credentials, tool
arguments, and repository file contents beyond concise paths and summaries.

## Boundaries

Doctor does not install tools, write catalogs, change Git state, call mutating GitHub
endpoints, alter branch protection, or declare a repository secure. Keep local Forge
stack state in `.forge/stack.json`; Doctor only validates it when present.
