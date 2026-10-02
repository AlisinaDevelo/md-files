---
id: 0055
title: Resolve host model bindings against explicit inventories
status: in_progress
agent: orchestration-engineer
model: standard
depends_on: [0029]
issue: 134
---

## Goal

Resolve provider-neutral routing tiers to an exact model and reasoning effort supported
by a caller-supplied host inventory, without silent provider or availability assumptions.

## Acceptance criteria

- [x] Inspect bounded inventories and profiles with deterministic normalized digests.
- [x] Honor explicit pins and fail closed for missing, retired, or unsupported selections.
- [x] Reject malformed fields, duplicate keys, cross-host profiles, and invalid efforts.
- [x] Provide discover, inspect, and resolve guidance with reproducible synthetic fixtures.
- [ ] Pass the complete local release gate and packaged resolver replay, then merge.

## Evidence boundary

Inventories are caller-supplied evidence, not live discovery or authenticated availability.
The resolver does not make model calls, grant effect authority, or establish quality or
cost superiority. Ten focused resolver tests passed on 2026-10-02; the release profile
also checks an extracted resolver in two identical offline attempts without repo imports.
