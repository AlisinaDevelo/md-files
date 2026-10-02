---
id: 0054
title: Adopt the portable Agent Plugins 1.0 release format
status: done
agent: interoperability-engineer
model: standard
depends_on: [0040, 0043]
issue: 133
---

## Goal

Make Forge's skills package portable while retaining older host projections.

## Acceptance criteria

- [x] Generate root identity and OpenAI settings without duplicating editable metadata.
- [x] Test complete inline replacement, compatibility fallback, and fixed skill discovery.
- [x] Reject malformed JSON, invalid listing metadata, and unsafe or ambiguous archives.
- [x] Include the portable manifest in deterministic archives and installed contract replay.
- [x] Pass the complete local release gate on the exact published head and merge the PR.

## Completion Evidence

PR [#137](https://github.com/AlisinaDevelo/md-files/pull/137) merged as
`06bc24121430ab35f43c8b0e8f90c896bf74df4b`. The complete local release gate passed on
`8b986734663d3709a22e140eb97eebb10fd02095`: 459 tests, lint and compilation, security
corpora, two byte-identical builds, archive verification, installed replay, and isolated
Claude/Codex marketplace lifecycle checks. Independent review findings about compatibility
validation and ZIP aliases were fixed and covered by regression tests before merge.

## Evidence boundary

The local profile is stricter than the portable core schema. Package validation and
deterministic replay do not establish model quality, connected execution, or public
directory availability. Sources: [Agent Plugins 1.0](https://agent-plugins.org/specification)
and [OpenAI packaging](https://developers.openai.com/plugins/build/plugins), reviewed
2026-10-02.
