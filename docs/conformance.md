# Cross-host conformance

Forge's conformance runner turns high-risk behavior into executable, machine-readable
evidence. The shared fixtures live in [`evals/scenarios.jsonl`](../evals/scenarios.jsonl),
their provider-neutral contract is [`data/scenarios.schema.json`](../data/scenarios.schema.json),
and the supported hosts are declared in [`data/host-capabilities.json`](../data/host-capabilities.json).

## Run deterministic evidence

Run every adapter contract without credentials:

```bash
python3 evals/run_scenarios.py \
  --adapter all \
  --no-receipts \
  --output /tmp/forge-scenario-results.json
```

The reference adapter checks the repository's prompts, safety effects, required files, and
declared artifacts. The Agent Skills adapter shares the same fixtures. Claude and Codex are
reported as explicit `skipped` results until a live run is requested; a skip is not a pass for
a live release gate.

CI runs this credential-free subset and uploads the JSON result as a workflow artifact. The
official `skills-ref@0.1.5` validator separately checks every Forge skill directory in the
host-validation job. The validator follows the [Agent Skills specification](https://github.com/agentskills/agentskills).

## Run a live host

Live execution is opt-in, budgeted, and requires the corresponding host CLI plus an external
runner command. The runner receives one scenario JSON object on standard input and must emit
one JSON object on standard output:

```json
{
  "passed": true,
  "model": "host-model-id",
  "host_version": "host-version",
  "input_tokens": 1200,
  "output_tokens": 340,
  "cost_usd": 0.012,
  "tools": ["Read"],
  "artifacts": [{"path": "result.json"}],
  "score": 1.0
}
```

Configure one runner per host and run repeated attempts when variance matters:

```bash
export FORGE_CLAUDE_SCENARIO_RUNNER="python3 /path/to/claude-scenario-runner.py"
python3 evals/run_scenarios.py \
  --adapter claude \
  --live \
  --budget-usd 5 \
  --repetitions 3 \
  --output /tmp/forge-claude-results.json
```

Use `FORGE_CODEX_SCENARIO_RUNNER` and `--adapter codex` for Codex. The harness validates
required and forbidden tools, required artifact paths, response constraints when a runner
returns `response`, and score bounds before accepting the runner's `passed` flag. Reports
include host versions, model IDs, token totals, cost totals, Bernoulli variance, and Wilson
95% confidence intervals. A mixed outcome is `flaky` and exits non-zero; it cannot silently
turn a release gate green.

## Receipts and result shape

By default, runs write a versioned result file under `.forge/scenario-results/` and append
privacy-safe `run.started`, `task.finished`, and `run.finished` events to
`.forge/receipts.jsonl`. Use `--no-receipts` for isolated CI checks. The result contract is
[`data/scenario-results.schema.json`](../data/scenario-results.schema.json); receipt details
are documented in [`docs/receipts.md`](receipts.md).

## Adding a host

Adding a host is a contract change, not just a new CLI branch:

1. Add an adapter entry to [`data/host-capabilities.json`](../data/host-capabilities.json).
2. Implement the host runner using the stdin/stdout contract above, including version,
   model, usage, cost, tool, artifact, and score evidence.
3. Run the existing shared fixtures and add host-specific cases only for documented host
   differences.
4. Add deterministic adapter tests and a CI invocation that does not require credentials.
5. Document any intentional Agent Skills compatibility exception beside the adapter.

The harness is deliberately not a claim that model behavior is deterministic. It makes the
uncertainty visible and prevents missing evidence from being mistaken for success.
