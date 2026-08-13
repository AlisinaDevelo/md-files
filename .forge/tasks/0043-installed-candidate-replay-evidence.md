---
id: 0043
title: Add installed-candidate replay evidence
status: done
agent: test-engineer
model: sonnet
depends_on: [0040]
issue: 82
---

## Goal

Bind the OpenAI submission packet to an isolated installation of the exact Codex release
candidate and prove that its admission cases replay deterministically from the installed bytes.

## Acceptance criteria

- [x] The exact candidate archive is installed into an isolated temporary tree and strictly
      validated after installation.
- [x] The installed tree matches the archive byte for byte and records its manifest version,
      file count, skill count, and source archive digest.
- [x] Five positive and three negative admission cases replay twice against the installed tree
      and digest-bound release policy with one stable case-set digest.
- [x] Documentation and evidence clearly distinguish offline installation/replay from real host
      lifecycle smoke and external OpenAI portal approval.

## Scope boundary

Do not add new plugin capabilities, MCP servers, custom UI, or portal claims. This task only
hardens the existing skills-only candidate evidence.

## Verification

- `python3 -m pytest tests/ -q`: 309 passed.
- `./scripts/validate.sh`, full Ruff, Python compilation, ShellCheck, and Markdown lint passed.
- Static eval passed 333 of 334 checks with one warning and no failures; deterministic scenarios
  passed 12 with 12 unsupported live-host cases skipped.
- Both portable runtime backends passed all 12 conformance cases; deterministic chaos corpus
  generation passed.
- Two release builds were byte-identical, both release manifests verified offline, and strict
  Claude and Codex archive validation passed.
- Isolated Claude and Codex install, reinstall, resource, remove, and absence checks passed.
- Evidence recorded 98 installed files, 25 skills, archive byte equality, strict validation,
  five positive and three negative cases, and two identical replay attempts.
- External blocker: publisher identity verification, portal draft creation, availability entry,
  and OpenAI review remain owner actions outside the repository.
