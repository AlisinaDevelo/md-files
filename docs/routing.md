# Deterministic Model Routing

Forge routing is a privacy-safe decision contract for workflows that can use more than one
provider/model route. It is intentionally offline-first: a route policy can be inspected and
replayed without credentials, network calls, prompts, tool payloads, or provider response bodies.

## Decision boundary

The policy declares route capabilities, static scores, costs, latency, fallbacks, execution
budgets, and adaptive activation gates. A request declares the host, required tools, output shape,
context size, modalities, region, data policy, replay requirement, token estimates, pins, and an
optional adaptation disable switch.

Routing filters ineligible routes before scoring. A route cannot score past a missing tool,
structured-output support, context window, modality, region, host, data policy, replay-safety
guarantee, pin, or budget. If every route is excluded, the decision is denied with candidate
reason codes and a digest-only decision reference. Fallbacks are validated as an acyclic route
graph and only eligible fallbacks appear in the decision.

The live entry point is deterministic:

```bash
python3 scripts/forge-routing.py decide \
  --policy POLICY.json \
  --request REQUEST.json
```

Static and disabled policies can select a route immediately. An adaptive policy returns
`adaptive_not_activated` from live `decide`; the runtime never treats that failure as permission
to self-modify. A request can set `disable_adaptation` to force static behavior for a workflow or
episode. Provider, model, and route pins are checked before budgets and scoring.

## Offline replay

Replay evaluates a baseline and candidate policy over the same normalized episode set. Episodes
contain only request metadata and numeric outcome evidence: quality score, cost, latency, failure,
and approval burden. The replay result includes per-policy metrics, route counts, comparison
deltas, and an activation result. A candidate is eligible only when all of these gates pass:

- candidate mode is `adaptive`;
- minimum observed samples and quality lower-bound confidence are met;
- missing outcome evidence is absent;
- quality regression, cost increase, failure-rate increase, and approval-burden increase stay
  within policy limits; and
- replay cost stays within the candidate's replay budget.

Replay status means the comparison executed. `activation.status` is the separate decision that is
either `eligible` or `blocked`. A blocked replay is valid evidence, not an activation. The live
runtime has no command that changes a policy based on replay output.

```bash
python3 scripts/forge-routing.py replay \
  --baseline-policy BASELINE.json \
  --candidate-policy CANDIDATE.json \
  --episodes EPISODES.json
```

Replay uses the redacted outcome corpus as bounded offline evidence for counterfactual scoring;
this is not an online learning claim. Production integrations must pin the policy revision and
define their own reviewed evidence-window and rollout process before enabling adaptive decisions.

## Privacy and provenance

The routing validator rejects prompt-like and provider-content fields recursively. Decision,
policy, request, outcome, and replay identities are SHA-256 references. An agent confidence value
is explicitly rejected as ground-truth quality; quality must be an accepted outcome measurement
from the workflow's reviewed evaluator or human process.

The contracts are versioned in:

- [`runtime-routing-policy.schema.json`](../data/runtime-routing-policy.schema.json)
- [`runtime-routing-decision.schema.json`](../data/runtime-routing-decision.schema.json)
- [`runtime-routing-replay.schema.json`](../data/runtime-routing-replay.schema.json)

The implementation is `plugins/forge/skills/orchestration/scripts/forge-routing.py`; the root
wrapper keeps the command ergonomic for repository users.
