# OpenAI Agent Plugin Submission Packet

Forge is prepared as a skills-only OpenAI Agent Plugin candidate. This packet records
repository-verifiable evidence and keeps external publication state explicit. It does not
claim directory approval or universal availability.

## Reproduce

Run this command from a clean checkout:

```bash
python3 scripts/build_openai_submission_evidence.py \
  --output /tmp/forge-openai-plugin-evidence.json
```

The runner builds the exact Codex release candidate, verifies the release manifest, SBOM,
hash inventory, and archive, validates the strict plugin contract, checks the submission
fields, and runs five positive plus three negative offline contract cases. The JSON report
records the source commit, source epoch, archive name, archive digest, manifest digest,
observations, and external blockers.

## Submission fields

| Field | Repository evidence | External state |
|---|---|---|
| Listing name, description, category | Codex interface metadata | Ready for owner review |
| Publisher | Manifest author identity and HTTPS profile | Identity verification pending |
| Support | GitHub issue tracker URL | Ready |
| Privacy and terms | Repository policy URLs | Ready for owner review |
| Starter prompts | Three manifest default prompts | Ready |
| Release notes | Changelog URL | Ready |
| Availability | Explicit pending status in the report | Must be entered in portal |
| Portal draft and review | Not repository-verifiable | Blocked on owner identity action |

## Cases

### Positive

1. Orchestration exposes a task ledger and solve loop.
2. The solve loop requires acceptance and verification.
3. Stacked delivery preserves parent relationships and lease-safe Git operations.
4. Policy and doctor workflows keep external effects reviewable.
5. The Codex manifest exposes a populated skills directory.

### Negative

1. Capability triggers are explicit; an unrelated request has no catch-all activation path.
2. Release policy defaults to deny and requires approval for external release effects.
3. A malformed plugin manifest is rejected by the strict Codex validator.

These cases are offline release-candidate contracts. They are useful evidence for the
submission packet, but they are not a substitute for the platform portal's own test run.

## Owner blocker

The remaining external step is publisher identity verification and creation of a portal
draft. Until that happens, Forge must remain documented as **not submitted**. MCP and custom
UI are intentionally excluded; see [task 0041](../.forge/tasks/0041-evaluate-optional-openai-mcp-ui.md)
for the separate decision track.

See [task 0040](../.forge/tasks/0040-openai-skills-submission-evidence.md) and the official
[OpenAI submission guidance](https://developers.openai.com/plugins/deploy/submission) for
the boundary between repository evidence and external publication.
