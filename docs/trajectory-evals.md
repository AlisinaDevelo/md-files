# Trajectory Security Evidence

Forge evaluates agent behavior at the episode level without storing prompts, credentials,
provider response bodies, or raw tool content. The contract is `forge-trajectory-v1` and is
implemented by `scripts/forge-trajectory-evals.py`.

## Contract

Each trajectory binds:

- an immutable workflow definition and policy digest;
- ordered workflow, agent, handoff, guardrail, approval, tool, and outcome events;
- opaque actor, action, tool, delegation, and result references;
- a replay digest derived from the canonical events and outcome; and
- bounded quality, cost, latency, failure, approval-burden, and replay-stability metrics.

The evaluator fails closed when an actor uses a scope it did not receive, a child delegation
widens its parent scope, a high-risk or external action bypasses approval, a denied guardrail is
followed, replay or terminal evidence does not bind, or a raw-content field appears. Timestamps
are checked for ordering but never used to produce a nondeterministic result.

## Offline corpus

Run the checked-in positive, near-miss, negative, and adversarial cases:

```bash
python3 scripts/forge-trajectory-evals.py evaluate \
  --corpus tests/fixtures/trajectories/v1.jsonl --json
```

The report contains case identifiers, digests, check counts, metric summaries, and statuses. A
negative fixture is successful only when the evaluator rejects it for the expected reason. The
release gate keeps this result separate from static prompt quality and runtime backend
conformance.

## Baseline comparison

Baseline and candidate JSONL corpora must contain the same measured case identifiers. Forge
compares quality and replay stability as absolute rates, and cost, latency, and approval burden
as relative changes. Thresholds are explicit and can be supplied as a JSON object:

```bash
python3 scripts/forge-trajectory-evals.py compare \
  --baseline baseline.jsonl --candidate candidate.jsonl \
  --thresholds thresholds.json --json
```

The comparison is evidence, not a claim that a finite corpus proves agent security.

## Optional judge boundary

An external model judge is opt-in and receives only trajectory references, deterministic statuses,
case identifiers, and the pinned model reference. It uses an HTTPS endpoint, a short timeout, and
a bounded response. Forge records a request digest and scores but always marks
`release_oracle: false`; a judge cannot turn a deterministic failure into a release pass.

```bash
export FORGE_JUDGE_API_KEY=...
python3 scripts/forge-trajectory-evals.py judge \
  --corpus tests/fixtures/trajectories/v1.jsonl \
  --endpoint https://judge.example.test/evaluate \
  --model-ref judge:model-v1 --json
```

This is an integration contract, not a hosted evaluator or a provider credential in the Forge
plugin. The local release gate never invokes it.

## Research basis

- [OpenAI trace grading](https://developers.openai.com/api/docs/guides/trace-grading)
- [OpenAI Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/)
- [OpenAI Agents SDK guardrails](https://openai.github.io/openai-agents-python/guardrails/)
- [OpenTelemetry GenAI agent spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md)
- [OWASP Agentic Skills checklist](https://owasp.org/www-project-agentic-skills-top-10/checklist.html)
- [NIST AI Agent Standards Initiative](https://www.nist.gov/artificial-intelligence/ai-agent-standards-initiative)
