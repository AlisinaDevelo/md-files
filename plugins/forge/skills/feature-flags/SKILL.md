---
name: feature-flags
description: >-
  Use when adding, rolling out, or cleaning up feature flags — gating a change,
  doing a progressive/canary release, building a kill switch, or removing a stale
  flag. Covers flag types, safe rollout, and the discipline that keeps flags from
  becoming permanent tech debt.
---

# Feature Flags

A feature flag decouples *deploy* from *release*: ship the code dark, turn it on when
ready, turn it off instantly if it misbehaves. Powerful — and a debt magnet if you don't
retire them. The single most important rule: **every flag needs a removal plan from the
day it's created.**

## Flag types (don't conflate them)

- **Release flag** — temporary, gates an in-progress feature. Removed once fully rolled out.
- **Ops / kill switch** — long-lived, lets you disable an expensive or risky subsystem under
  load or incident. Kept on purpose.
- **Experiment flag** — drives an A/B test; removed when the experiment concludes.
- **Permission / entitlement** — long-lived, gates by plan/tenant. This is config, not a
  feature flag — treat it as such.

Mixing these is how you end up with 200 flags nobody understands. Name and document which
kind each one is.

## Safe rollout

- **Default off.** A new flag's default is the old behavior. Shipping the code does nothing
  until you deliberately turn it on.
- **Ramp progressively:** internal → 1% → canary cohort → 10% → 50% → 100%, watching the
  error rate and key metrics at each step. Don't jump to 100%.
- **Make it killable instantly** — flipping off must not require a deploy, and off must be a
  safe state at any ramp percentage.
- **Both paths must work at every step.** While a flag is live, old and new code paths both
  run in production. Test both; don't let the off-path rot.

## The cleanup discipline (where teams fail)

- A release flag is **temporary**. When it's at 100% and stable, delete the flag *and the
  dead branch* — the code, the config, the tests for the old path. A flag left in forever is
  a permanent `if` nobody dares remove.
- Track flag age. A release flag older than its feature is a smell. Put an expiry/owner on
  it; review stale flags regularly.
- Avoid **flag dependencies** (flag B only sane when flag A is on) — they multiply states
  combinatorially and make reasoning impossible.

## Gotchas

- **State explosion:** N flags = up to 2^N code paths. Keep the live set small.
- **Consistency:** a user flipping mid-session between on/off paths can hit inconsistent
  state — evaluate the flag once per request/session, not per call.
- **Don't gate data migrations on a release flag** the way you'd gate UI — a half-migrated
  schema behind a flag is a different, riskier problem (see `safe-database-migrations`).
