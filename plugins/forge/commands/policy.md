---
description: Evaluate Forge policy, stage an effect, issue a scoped approval, or record a committed outcome
argument-hint: "[profiles | evaluate | stage | approve | authorize | commit]"
allowed-tools: Read, Grep, Glob, Bash(python3:*), Edit, Write
model: opus
---

Manage the Forge policy plane: $ARGUMENTS

Use the `policy` skill for versioned action envelopes, profile evaluation, protected
resource handling, one-use approvals, staged previews, and decision receipts.

- Start with `profiles` to inspect the readable profiles in `policies/`.
- Use `evaluate` before an effect to inspect its rule, reason, constraints, and digest.
- Use `stage` for a no-effect preview. It never calls a mutation adapter or consumes an
  approval.
- Use `approve` only for a `require_approval` decision, then pass the returned approval
  ID to `authorize` immediately before the external effect.
- Use `commit` only after the adapter has returned; it records the final committed effect
  and a result digest without storing raw arguments.

The task-ledger and stacked-changes adapters opt in with `--policy-profile`; keep their
existing `--yes` confirmation and use `--policy-staged` for previews.
