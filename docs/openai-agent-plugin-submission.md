# OpenAI Agent Plugin Submission Packet

Forge is prepared as a skills-only OpenAI Agent Plugin candidate. Owner-provided OpenAI
project portal evidence dated 2026-08-18 shows Forge 3.6.0 as **Approved**. This packet
records repository-verifiable evidence and keeps the remaining publication boundary explicit:
it does not claim public directory listing or universal availability.

## Reproduce

Run this command from a clean checkout:

```bash
python3 scripts/build_openai_submission_evidence.py \
  --output /tmp/forge-openai-plugin-evidence.json
```

The runner builds the exact OpenAI skills-only ZIP release candidate, verifies the release
manifest, SBOM, hash inventory, and archive, then installs that archive into an isolated
temporary tree. It
requires the installed files to match the archive byte for byte and reruns strict plugin
validation after installation. Five positive plus three negative contract cases then replay
twice against the installed bytes and the source release policy; both the policy input and
case set are bound by stable digests.

The JSON report records the source commit, source epoch, archive and manifest digests,
installed file and skill counts, installed-tree digest, replay digest, observations, and
external blockers.

Each `cases` entry is ready to transfer into the platform test form: `prompt` is the user
input, `expected_behavior` is the workflow contract, `expected_result_shape` describes the
result to look for, and `fixture_data` states the data needed to replay it. The fixture
statement explicitly keeps these checks offline and free of accounts, credentials, private
data, and network targets. Archive-bound observations remain alongside those fields so the
repository evidence can be distinguished from the portal's own test run.

## Candidate release

The current public candidate is [Forge 3.8.0](https://github.com/AlisinaDevelo/md-files/releases/tag/v3.8.0).
Use its [OpenAI skills-only ZIP](https://github.com/AlisinaDevelo/md-files/releases/download/v3.8.0/forge-3.8.0-openai.zip)
and verify it against the published [SHA-256 inventory](https://github.com/AlisinaDevelo/md-files/releases/download/v3.8.0/SHA256SUMS)
before uploading it. The generated report also records these URLs under
`submission_materials.listing.candidate_*` alongside the exact source commit and archive
digest. Do not mix a locally rebuilt archive with evidence generated for the public release.

## Submission fields

| Field | Repository evidence | External state |
|---|---|---|
| Listing name, description, category | Codex interface metadata | Ready for owner review |
| Publisher | Manifest author identity and HTTPS profile | Project portal approval shown; publisher details remain owner-managed |
| Support | GitHub issue tracker URL | Ready |
| Privacy and terms | Repository policy URLs | Ready for owner review |
| Starter prompts | Three manifest default prompts | Ready |
| Release notes | Changelog URL | Ready |
| Availability | Explicit status in the report | Project portal approval shown; public listing and availability not independently verified |
| Portal draft and review | Not repository-verifiable | Project portal shows Approved; public directory discoverability remains unverified |

## Portal workflow

The remaining steps are performed in the OpenAI Platform, not by this repository. Before
creating a draft, the submitting organization needs Apps Management write access and a
verified individual or business developer identity. The portal currently uses this flow:

1. Create a plugin submission and choose **Skills only**.
2. Upload the published [OpenAI skills-only ZIP](https://github.com/AlisinaDevelo/md-files/releases/download/v3.8.0/forge-3.8.0-openai.zip), after checking its [SHA-256 inventory](https://github.com/AlisinaDevelo/md-files/releases/download/v3.8.0/SHA256SUMS).
3. Complete the listing, publisher, policy URLs, starter prompts, five positive and three
   negative test cases, country availability, and release notes.
4. Review the complete draft and policy attestations, then choose **Submit for Review**.
5. After approval, choose **Publish** in the portal. Approval alone does not make the
   plugin visible in the shared ChatGPT and Codex directory.

Use the published archive and its matching evidence together. A locally rebuilt archive is
useful for verification, but it is not interchangeable with the release asset named above.

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

## Evidence boundary

The report's installation is an isolated offline extraction of the exact release archive. It
proves package contents and deterministic contract replay, but it does not claim a Codex or
Claude CLI marketplace lifecycle. Run the separate host smoke when those CLIs are available:

```bash
./scripts/marketplace-smoke.sh "$PWD"
```

That smoke uses isolated Claude and Codex homes to install, reinstall, inspect resources,
remove Forge, and verify removal. CI runs both the reproducible packet builder and this host
lifecycle smoke. Neither check can complete publisher identity verification or OpenAI portal
review.

## External status

The owner-provided project Plugins view records Forge 3.6.0 as **Approved** on 2026-08-18.
That evidence establishes the project-level review state shown by the portal. It does not
prove that Forge is discoverable in a public directory or universally available to other
accounts, so repository documentation keeps those states separate.

MCP and custom UI remain intentionally excluded from the current skills-only submission;
see [task 0041](../.forge/tasks/0041-evaluate-optional-openai-mcp-ui.md) for the separate
decision track.

See [task 0040](../.forge/tasks/0040-openai-skills-submission-evidence.md) and the official
[OpenAI submission guidance](https://developers.openai.com/plugins/deploy/submission) for
the boundary between repository evidence and external publication.
