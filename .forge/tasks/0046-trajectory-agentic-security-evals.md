---
id: 0046
title: Add trajectory and agentic-security regression harness
status: planned
agent: test-engineer
model: sonnet
depends_on: [0024, 0025]
issue: 87
---

## Goal

Add a bounded, digest-only regression harness for agent trajectories, guardrails, handoffs,
tool calls, approvals, and outcomes.

## Acceptance criteria

- [ ] The trajectory format versions agent, workflow, tool, guardrail, handoff, approval, and
      outcome events without storing prompts, credentials, raw tool content, or provider bodies.
- [ ] Deterministic checks cover least agency, authorization scope, approval ordering, replay,
      leakage, unsafe action, and terminal outcome invariants.
- [ ] Baseline and candidate reports compare quality, cost, latency, failure, approval burden,
      and replay stability with bounded thresholds.
- [ ] Optional model-based judging is isolated, labeled, and never the sole release oracle.
- [ ] A small offline corpus runs locally and integrates with the existing release gate.

## Scope boundary

Do not introduce a hosted evaluator, unbounded agent simulations, or raw trace retention.

## Primary sources

- [OpenAI Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/)
- [OpenTelemetry GenAI agent spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md)
- [OWASP Agentic AI threats and mitigations](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/)
