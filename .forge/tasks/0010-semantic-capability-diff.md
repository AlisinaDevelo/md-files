---
id: 0010
title: Add semantic capability diff evidence
status: done
agent: test-engineer
model: sonnet
depends_on: [0006]
---

## Goal

Give reviewers deterministic semantic evidence for capability changes without copying
instruction bodies into diffs or receipts.

## Acceptance criteria

- [x] Added, removed, renamed, and changed components are categorized deterministically.
- [x] Body changes report SHA-256 evidence only.
- [x] Permission, resource, eval, and host-projection changes remain visible.
- [x] JSON and Markdown output modes are covered by tests.

## Context

The implementation is `scripts/diff_capabilities.py`; it compares arbitrary graph JSON
files and defaults the after revision to the current canonical graph.

## Notes

Implemented on `feat/capability-diff-migrations`. Raw instruction text is intentionally
excluded from semantic evidence.
