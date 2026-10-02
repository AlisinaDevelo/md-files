---
id: 0054
title: Adopt the portable Agent Plugins 1.0 release format
status: in_progress
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
- [ ] Pass the complete local release gate on the exact published head and merge the PR.

## Evidence boundary

The local profile is stricter than the portable core schema. Package validation and
deterministic replay do not establish model quality, connected execution, or public
directory availability. Sources: [Agent Plugins 1.0](https://agent-plugins.org/specification)
and [OpenAI packaging](https://developers.openai.com/plugins/build/plugins), reviewed
2026-10-02.
