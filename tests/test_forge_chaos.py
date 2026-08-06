"""Deterministic chaos schedules and shrinking contract tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-chaos.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_chaos", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generated_schedule_is_seed_deterministic_and_digest_only():
    module = load_module()
    first = module.generate_schedule(6601)
    second = module.generate_schedule(6601)

    assert first == second
    assert first["schedule_ref"].startswith("sha256:")
    assert {
        "commit_crash",
        "duplicate_delivery",
        "stale_worker_mutation",
        "wait_signal_race",
        "cancel_race",
        "checkpoint_corruption",
        "provider_timeout",
        "privacy_probe",
        "cursor_gap",
        "compaction_recovery",
        "verify_replay",
    }.issubset({action["kind"] for action in first["actions"]})
    assert "sentinel-never-persist" not in json.dumps(first, sort_keys=True)


def test_same_schedule_passes_all_backends_with_explicit_degradation():
    module = load_module()
    result = module.run_all(module.generate_schedule(6601))

    assert result["status"] == "passed"
    assert result["comparison"]["status"] == "passed"
    assert result["comparison"]["mismatches"] == []
    assert result["summary"] == {"backends": 3, "passed": 1, "degraded": 2, "failed": 0}
    statuses = {item["backend"]["backend_id"]: item["status"] for item in result["results"]}
    assert statuses == {"sqlite-wal": "degraded", "memory-fault": "degraded", "etcd-watch-sim": "passed"}
    assert all(item["status"] != "failed" for result_item in result["results"] for item in result_item["actions"])


def test_shrinker_removes_irrelevant_actions_and_preserves_failure_class():
    module = load_module()
    schedule = module.make_schedule(
        991,
        [
            {"action_id": "noise-before", "kind": "start_run", "run_id": "noise-before"},
            {"action_id": "target-start", "kind": "start_run", "run_id": "target"},
            {
                "action_id": "target-expectation",
                "kind": "expect_state",
                "run_id": "target",
                "expected_status": "completed",
            },
            {"action_id": "noise-after", "kind": "start_run", "run_id": "noise-after"},
        ],
    )

    original = module.run_schedule(schedule, "memory")
    shrunk = module.shrink_schedule(schedule, "memory")
    minimized = module.validate_schedule(shrunk["minimized_schedule"])
    replayed = module.run_schedule(minimized, "memory")

    assert original["status"] == replayed["status"] == "failed"
    assert shrunk["failure_class"] == replayed["failure_class"] == "terminal_outcome_mismatch"
    assert shrunk["removed_action_count"] == 2
    assert [action["action_id"] for action in minimized["actions"]] == ["target-start", "target-expectation"]


def test_cli_generate_inspect_and_replay(tmp_path, capsys):
    module = load_module()
    schedule_path = tmp_path / "schedule.json"

    assert module.main(["generate", "--seed", "7001", "--length", "1", "--output", str(schedule_path)]) == 0
    assert module.main(["inspect", "--schedule", str(schedule_path)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["action_count"] == 1
    assert inspected["redaction"] == "digest-only"

    assert module.main(["replay", "--schedule", str(schedule_path), "--backend", "memory"]) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["status"] == "passed"
    assert replay["replayed"] is True


def test_invalid_schedule_rejects_raw_payload_boundary():
    module = load_module()
    with pytest.raises(module.ChaosError, match="digest-only"):
        module.make_schedule(
            1,
            [
                {
                    "action_id": "raw",
                    "kind": "start_run",
                    "run_id": "raw",
                    "prompt": "must not enter a schedule",
                }
            ],
        )
