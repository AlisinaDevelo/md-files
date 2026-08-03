---
name: forge-cmd-policy
description: Evaluate Forge policy, stage an effect, issue a scoped approval, or record a committed outcome.
disable-model-invocation: true
---

# Forge Policy

Manage the policy plane: `$ARGUMENTS`

Use the `policy` methodology skill and `python3 scripts/forge-policy.py` for:

- `profiles` — inspect readable profiles;
- `evaluate` — inspect a decision, rule, reason, constraints, revision, and digest;
- `stage` — produce a no-effect preview without consuming approval;
- `approve` — issue a short-lived, one-use approval for an exact action;
- `authorize` — re-evaluate immediately before an effect;
- `commit` — record final committed-effect evidence.

Never copy raw arguments, prompts, credentials, or tool results into approval records or
receipts. Mutation adapters also retain their explicit confirmation gates.
