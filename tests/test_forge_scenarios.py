"""Behavioral tests for Forge's cross-host scenario evidence runner."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "evals/run_scenarios.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_scenarios", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_repository_scenarios_are_valid_and_reference_adapter_passes():
    module = load_module()
    scenarios = module.load_scenarios(REPO / "evals/scenarios.jsonl")
    adapter = module.ReferenceAdapter()

    results = [adapter.run(REPO, scenario) for scenario in scenarios]

    assert len(scenarios) == 6
    assert all(result["status"] == "passed" for result in results)


def test_result_artifact_declares_host_matrix(tmp_path):
    module = load_module()
    output = tmp_path / "results.json"

    report = module.run_suite(REPO, REPO / "evals/scenarios.jsonl", ["reference"], output=output, receipts=None)
    stored = json.loads(output.read_text())

    assert report["adapter_contract_version"] == 1
    assert set(report["host_matrix"]) == {"reference", "claude", "codex", "agentskills"}
    assert stored["artifact"] == str(output)
    assert stored["host_matrix"]["claude"]["runner_env"] == "FORGE_CLAUDE_SCENARIO_RUNNER"


def test_live_payload_contract_rejects_missing_tools_and_score():
    module = load_module()
    scenario = {
        "expected": {
            "required_tools": ["Read"],
            "forbidden_tools": ["Write"],
            "artifacts": [{"path": "result.json"}],
            "score": {"minimum": 0.8},
        }
    }

    errors = module.validate_live_payload(REPO, scenario, {"passed": True, "tools": ["Write"], "score": 0.5})

    assert "missing required tools: Read" in errors
    assert "forbidden tools used: Write" in errors
    assert "missing required artifact: result.json" in errors
    assert "runner score 0.5 is below minimum 0.8" in errors


def test_live_adapter_records_host_usage_and_cost(monkeypatch, tmp_path):
    module = load_module()
    runner = tmp_path / "runner.py"
    runner.write_text(
        "import json\n"
        "json.load(__import__('sys').stdin)\n"
        "print(json.dumps({'passed': True, 'model': 'test-model', 'host_version': 'host-1', 'input_tokens': 10, 'output_tokens': 4, 'cost_usd': 0.02, 'tools': ['Read'], 'artifacts': ['result.json'], 'score': 0.9}))\n"
    )
    monkeypatch.setenv("FORGE_TEST_SCENARIO_RUNNER", f"{sys.executable} {runner}")
    adapter = module.CliAdapter("test", "python", "FORGE_TEST_SCENARIO_RUNNER")
    monkeypatch.setattr(adapter, "host_version", lambda: "python-host-1")
    scenario = {
        "id": "live-case",
        "expected": {
            "required_tools": ["Read"],
            "artifacts": [{"path": "result.json"}],
            "score": {"minimum": 0.8},
        },
    }

    result = adapter.run(REPO, scenario, live=True, budget_usd=1, repetitions=2)

    assert result["status"] == "passed"
    assert result["statistics"]["host_versions"] == ["host-1"]
    assert result["statistics"]["models"] == ["test-model"]
    assert result["statistics"]["input_tokens"] == 20
    assert result["statistics"]["cost_usd"] == 0.04


def test_scenario_paths_cannot_escape_repository():
    module = load_module()

    with pytest.raises(module.ScenarioError, match="escapes"):
        module.safe_path(REPO, "../secrets.txt")


def test_invalid_scenario_categories_fail_before_execution(tmp_path):
    module = load_module()
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps({"schema_version": 1, "id": "bad-case", "category": "unknown", "target": {"kind": "file", "name": "README.md"}, "prompt": "x", "expected": {}}) + "\n")

    with pytest.raises(module.ScenarioError, match="category"):
        module.load_scenarios(path)


def test_mixed_live_outcomes_are_flaky_with_statistics():
    module = load_module()

    result = module.aggregate_attempts(
        "claude",
        "case",
        [
            {"passed": True, "model": "model-a", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01},
            {"passed": False, "model": "model-a", "input_tokens": 12, "output_tokens": 6, "cost_usd": 0.02},
        ],
    )

    assert result["status"] == "flaky"
    assert result["statistics"]["pass_rate"] == 0.5
    assert result["statistics"]["variance"] == 0.25
    assert result["statistics"]["confidence_interval_95"][0] < 0.5 < result["statistics"]["confidence_interval_95"][1]


def test_non_live_host_adapters_are_explicitly_skipped():
    module = load_module()
    scenario = module.load_scenarios(REPO / "evals/scenarios.jsonl")[0]

    result = module.CliAdapter("claude", "claude", "MISSING_RUNNER").run(REPO, scenario, live=False)

    assert result["status"] == "skipped"
    assert "--live" in result["reason"]


def test_suite_can_run_all_adapters_without_credentials(tmp_path):
    module = load_module()
    report = module.run_suite(
        REPO,
        REPO / "evals/scenarios.jsonl",
        ["reference", "claude", "codex", "agentskills"],
        output=tmp_path / "results.json",
        receipts=tmp_path / "receipts.jsonl",
    )

    assert report["summary"]["failed"] == 0
    assert report["summary"]["flaky"] == 0
    assert report["summary"]["skipped"] == 12
    assert (tmp_path / "results.json").exists()
    events = [json.loads(line) for line in (tmp_path / "receipts.jsonl").read_text().splitlines()]
    assert events[0]["event_type"] == "run.started"
    assert events[-1]["event_type"] == "run.finished"
