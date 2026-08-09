---
id: 0040
title: Prepare OpenAI skills-only submission evidence
status: ready
agent: docs-writer
model: sonnet
depends_on: [0038, 0039]
issue: 82
---

## Goal

Prepare an owner-reviewed submission packet for Forge's skills-only OpenAI Plugin Directory
entry without claiming that the external review has happened.

## Acceptance criteria

- [ ] Five positive and three negative test cases run against the release candidate with
      reproducible evidence and clear expected behavior.
- [ ] Listing, publisher, support, privacy, terms, starter prompt, release note, and
      availability fields are checked against the submission form.
- [ ] The candidate archive, version, and evidence are linked from one reviewable artifact.
- [ ] A platform owner completes identity verification and creates a portal draft, or the
      task records the exact external blocker.

## Context

OpenAI's public submission flow is separate from local/repository marketplace installation.
It requires verified publisher identity and portal-managed metadata in addition to the files
committed here.

## Scope boundary

Do not add an MCP server or custom UI to satisfy this task. Forge is currently a skills-only
engineering workflow plugin and should stay that way unless a concrete user workflow needs
server-backed tools or visual interaction.
