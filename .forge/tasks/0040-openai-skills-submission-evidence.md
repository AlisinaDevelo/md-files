---
id: 0040
title: Prepare OpenAI skills-only submission evidence
status: done
agent: docs-writer
model: sonnet
depends_on: [0038, 0039]
issue: 82
---

## Goal

Prepare an owner-reviewed submission packet for Forge's skills-only OpenAI Plugin Directory
entry without overstating repository evidence or the external publication state.

## Acceptance criteria

- [x] Five positive and three negative test cases run against the release candidate with
      reproducible evidence and clear expected behavior.
- [x] Listing, publisher, support, privacy, terms, starter prompt, release note, and
      availability fields are checked against the submission form.
- [x] The candidate archive, version, and evidence are linked from one reviewable artifact.
- [x] The available project-portal review state is recorded with its date and evidence
      boundary; public directory listing is not inferred from project approval.

## Context

OpenAI's public submission flow is separate from local/repository marketplace installation.
It requires verified publisher identity and portal-managed metadata in addition to the files
committed here.

## Scope boundary

Do not add an MCP server or custom UI to satisfy this task. Forge is currently a skills-only
engineering workflow plugin and should stay that way unless a concrete user workflow needs
server-backed tools or visual interaction.

## Verification

- `scripts/build_openai_submission_evidence.py` produced five positive and three negative
  offline release-candidate contract cases.
- The candidate Codex archive, release manifest, SHA-256 inventory, SPDX metadata, and strict
  plugin validator all passed.
- The report records the exact source commit and archive digest, and CI uploads it as a
  reviewable artifact.
- Owner-provided OpenAI project Plugins evidence dated 2026-08-18 shows Forge 3.6.0 as
  **Approved**. This confirms project-level review state only; public directory listing and
  universal availability remain outside repository-verifiable evidence.
