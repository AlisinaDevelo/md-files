---
id: 0046
title: Add trajectory and agentic-security regression harness
status: done
agent: test-engineer
model: sonnet
depends_on: [0024, 0025]
issue: 87
---

## Goal

Add a bounded, digest-only regression harness for agent trajectories, guardrails, handoffs,
tool calls, approvals, and outcomes.

## Implementation contract

- The canonical corpus is JSONL and uses `forge-trajectory-v1`; every event is ordered,
  reference-based, and rejects raw prompts, credentials, provider bodies, and tool content.
- The deterministic evaluator reports per-case checks plus aggregate quality, cost, latency,
  failure, approval-burden, and replay-stability metrics.
- Baseline comparison is thresholded and digest-bound. An optional external judge may contribute
  separately labeled evidence, but cannot change the deterministic release result.
- The release gate runs a small offline corpus and emits only counts, digests, statuses, and
  metric summaries.

## Acceptance criteria

- [x] The trajectory format versions agent, workflow, tool, guardrail, handoff, approval, and
      outcome events without storing prompts, credentials, raw tool content, or provider bodies.
- [x] Deterministic checks cover least agency, authorization scope, approval ordering, replay,
      leakage, unsafe action, and terminal outcome invariants.
- [x] Baseline and candidate reports compare quality, cost, latency, failure, approval burden,
      and replay stability with bounded thresholds.
- [x] Optional model-based judging is isolated, labeled, and never the sole release oracle.
- [x] A small offline corpus runs locally and integrates with the existing release gate.

## Verification

- `python3 -m pytest tests/test_forge_trajectory.py`: 10 passed.
- The checked-in corpus reports 4 passed cases: 2 positive/near-miss and 2 expected threat
  failures; replay stability is 1.0 and the deterministic evaluator is the release oracle.
- The configured local release gate passed on the implementation commit with the full test,
  static-eval, cross-host, packaging, installation, replay, and attestation checks.

## Scope boundary

Do not introduce a hosted evaluator, unbounded agent simulations, or raw trace retention.

## Primary sources

- [OpenAI Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/)
- [OpenTelemetry GenAI agent spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md)
- [OWASP Agentic AI threats and mitigations](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/)
