"""Tests for the durable Forge GitHub Agentic Workflows episode bridge."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-gh-aw-runtime.py"
SPEC_PATH = REPO / "data/gh-aw-workflows.json"
REF_A = "sha256:" + "a" * 64
REF_B = "sha256:" + "b" * 64
REF_C = "sha256:" + "c" * 64


def load_module():
    spec = importlib.util.spec_from_file_location("forge_gh_aw_runtime_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def prepare(module, tmp_path: Path) -> tuple[Path, Path]:
    output = tmp_path / "gh-aw"
    module._compiler().compile_artifacts(REPO, SPEC_PATH, output)
    return output, tmp_path / "runtime.sqlite3"


def prepare_native(module, tmp_path: Path) -> tuple[Path, Path]:
    fixture_path = REPO / "tests/test_forge_gh_aw.py"
    fixture_spec = importlib.util.spec_from_file_location("forge_gh_aw_native_fixture", fixture_path)
    assert fixture_spec and fixture_spec.loader
    fixture_module = importlib.util.module_from_spec(fixture_spec)
    sys.modules[fixture_spec.name] = fixture_module
    fixture_spec.loader.exec_module(fixture_module)
    output = tmp_path / "gh-aw-native"
    fixture_module.native_fixture(module._compiler(), output)
    return output, tmp_path / "runtime.sqlite3"


def receipt(module, effect: dict, *, result_ref: str = REF_C) -> dict[str, str]:
    payload = effect["payload"]
    return {
        "status": "succeeded",
        "episode_id": payload["episode_id"],
        "workflow_id": payload["workflow_id"],
        "safe_output_type": payload["safe_output_type"],
        "approval_id": REF_A,
        "adapter_contract_revision": module.BRIDGE_REVISION,
        "provider_request_id": f"provider:{effect['effect_id']}",
        "result_ref": result_ref,
    }


def start_and_dispatch(module, output: Path, database: Path) -> str:
    started = module.start_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        REF_A,
        occurred_at="2026-08-08T04:00:00Z",
    )
    episode_id = started["episode_id"]
    dispatched = module.dispatch_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        REF_A,
        occurred_at="2026-08-08T04:01:00Z",
    )
    assert len(dispatched["tasks"]) == 4
    assert all(item["status"] == "pending" for item in dispatched["effects"])
    return episode_id


def acknowledge_all(module, output: Path, database: Path, episode_id: str, worker_id: str, now: str) -> list[dict]:
    claimed = module.claim_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        worker_id,
        limit=10,
        now=now,
    )["claimed"]
    for effect in claimed:
        module.acknowledge_episode(
            SPEC_PATH,
            output,
            database,
            "forge-dispatcher",
            episode_id,
            effect["effect_id"],
            worker_id,
            effect["lease_generation"],
            receipt(module, effect),
            received_at=now,
        )
    return claimed


def test_episode_lifecycle_is_durable_replay_safe_and_privacy_safe(tmp_path):
    module = load_module()
    output, database = prepare(module, tmp_path)
    episode_id = start_and_dispatch(module, output, database)

    dispatches = acknowledge_all(module, output, database, episode_id, "dispatcher-provider", "2026-08-08T04:10:00Z")
    assert len(dispatches) == 4

    worker_ids = [
        "forge-issue-triage",
        "forge-ci-diagnosis",
        "forge-docs-maintenance",
        "forge-feature-planning",
    ]
    for index, worker_id in enumerate(worker_ids):
        started = module.start_worker(
            SPEC_PATH,
            output,
            database,
            "forge-dispatcher",
            episode_id,
            worker_id,
            occurred_at=f"2026-08-08T04:1{index}:00Z",
        )
        replayed = module.start_worker(
            SPEC_PATH,
            output,
            database,
            "forge-dispatcher",
            episode_id,
            worker_id,
            occurred_at=f"2026-08-08T04:1{index}:30Z",
        )
        assert replayed["sequence"] == started["sequence"]
        completed = module.complete_worker(
            SPEC_PATH,
            output,
            database,
            "forge-dispatcher",
            episode_id,
            worker_id,
            f"sha256:{index + 1:064x}",
            occurred_at=f"2026-08-08T04:2{index}:00Z",
        )
        replayed = module.complete_worker(
            SPEC_PATH,
            output,
            database,
            "forge-dispatcher",
            episode_id,
            worker_id,
            f"sha256:{index + 1:064x}",
            occurred_at=f"2026-08-08T04:2{index}:30Z",
        )
        assert replayed["sequence"] == completed["sequence"]

    outputs = acknowledge_all(module, output, database, episode_id, "safe-output-provider", "2026-08-08T04:40:00Z")
    assert len(outputs) == 4
    finished = module.finish_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        occurred_at="2026-08-08T04:50:00Z",
    )
    replayed = module.finish_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        occurred_at="2026-08-08T04:51:00Z",
    )
    assert finished["status"] == "completed"
    assert replayed["sequence"] == finished["sequence"]
    assert len(replayed["effects"]) == 8
    assert all(item["status"] == "succeeded" for item in replayed["effects"])
    serialized = json.dumps(replayed, sort_keys=True)
    assert '"payload"' not in serialized
    assert '"receipt"' not in serialized
    required = {
        "schema_version",
        "contract_revision",
        "episode_id",
        "runtime_definition_digest",
        "gh_aw_definition_digest",
        "tasks",
        "effects",
        "receipts",
        "correlation",
        "correlation_digest",
    }
    assert required <= replayed.keys()
    assert len(replayed["receipts"]) == 8


def test_dispatch_effects_use_dispatcher_policy_and_worker_task_identity(tmp_path):
    module = load_module()
    output, database = prepare(module, tmp_path)
    episode_id = start_and_dispatch(module, output, database)
    runtime = module._runtime()

    with runtime.RuntimeStore(database) as store:
        effects = store.list_outbox(episode_id)
    assert len(effects) == 4
    assert {item["task_id"] for item in effects} == {
        "forge-issue-triage",
        "forge-ci-diagnosis",
        "forge-docs-maintenance",
        "forge-feature-planning",
    }
    assert {item["payload"]["workflow_id"] for item in effects} == {"forge-dispatcher"}
    assert {item["payload"]["safe_output_type"] for item in effects} == {"dispatch-workflow"}
    assert all(item["payload"]["policy_decision"] == "require_approval" for item in effects)


def test_partial_failure_and_terminal_replay_are_idempotent(tmp_path):
    module = load_module()
    output, database = prepare(module, tmp_path)
    episode_id = start_and_dispatch(module, output, database)
    acknowledge_all(module, output, database, episode_id, "dispatcher-provider", "2026-08-08T05:10:00Z")
    worker_id = "forge-ci-diagnosis"
    module.start_worker(SPEC_PATH, output, database, "forge-dispatcher", episode_id, worker_id)
    failed = module.fail_worker(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        worker_id,
        REF_B,
        retryable=False,
    )
    replayed = module.fail_worker(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        worker_id,
        REF_B,
        retryable=False,
    )
    assert replayed["sequence"] == failed["sequence"]
    terminal = module.finish_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        outcome="failed",
        error_ref=REF_C,
    )
    replayed = module.finish_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        outcome="failed",
        error_ref=REF_C,
    )
    assert terminal["status"] == "failed"
    assert replayed["sequence"] == terminal["sequence"]
    failed_task = next(item for item in replayed["tasks"] if item["task_id"] == worker_id)
    assert failed_task["status"] == "failed"


def test_cancellation_fences_claims_and_acknowledgements(tmp_path):
    module = load_module()
    output, database = prepare(module, tmp_path)
    episode_id = start_and_dispatch(module, output, database)
    claimed = module.claim_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        "dispatcher-provider",
        now="2026-08-08T06:00:00Z",
    )["claimed"]
    effect = claimed[0]
    cancelled = module.cancel_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        REF_A,
        REF_B,
        occurred_at="2026-08-08T06:01:00Z",
    )
    replayed = module.cancel_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        REF_A,
        REF_B,
        occurred_at="2026-08-08T06:02:00Z",
    )
    assert cancelled["status"] == "cancelled"
    assert replayed["sequence"] == cancelled["sequence"]
    with pytest.raises(module.GhAwRuntimeError, match="not running"):
        module.claim_episode(
            SPEC_PATH,
            output,
            database,
            "forge-dispatcher",
            episode_id,
            "late-provider",
        )
    with pytest.raises(module.GhAwRuntimeError, match="termination"):
        module.acknowledge_episode(
            SPEC_PATH,
            output,
            database,
            "forge-dispatcher",
            episode_id,
            effect["effect_id"],
            "dispatcher-provider",
            effect["lease_generation"],
            receipt(module, effect),
        )


def test_receipts_are_strictly_bounded_to_references(tmp_path):
    module = load_module()
    output, database = prepare(module, tmp_path)
    episode_id = start_and_dispatch(module, output, database)
    effect = module.claim_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        "dispatcher-provider",
        now="2026-08-08T07:00:00Z",
    )["claimed"][0]
    invalid = receipt(module, effect)
    invalid["raw_provider_body"] = "do not persist this"
    with pytest.raises(module.GhAwRuntimeError, match="unsupported fields"):
        module.acknowledge_episode(
            SPEC_PATH,
            output,
            database,
            "forge-dispatcher",
            episode_id,
            effect["effect_id"],
            "dispatcher-provider",
            effect["lease_generation"],
            invalid,
        )


def test_native_preflight_is_deterministic_and_does_not_advance_episode(tmp_path):
    module = load_module()
    output, database = prepare_native(module, tmp_path)
    started = module.start_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        REF_A,
        occurred_at="2026-08-08T08:00:00Z",
    )
    episode_id = started["episode_id"]
    with module._runtime().RuntimeStore(database) as store:
        before = store.state(episode_id)

    first = module.preflight_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        REF_A,
    )
    second = module.preflight_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        REF_A,
    )

    assert first == second
    assert first["$schema"] == module.ADMISSION_SCHEMA
    assert first["mode"] == "upstream-gh-aw"
    assert first["admission_id"].startswith("sha256:")
    assert first["history_sequence"] == before["sequence"]
    assert first["history_head"] == started["history_head"]
    assert first["artifacts"]["lock"]["path"] == "workflows/forge-dispatcher.lock.yml"
    assert first["native_job_roles"] == [
        "activation",
        "agent",
        "conclusion",
        "detection",
        "safe_outputs",
    ]
    assert "prompt" not in json.dumps(first, sort_keys=True).lower()
    with module._runtime().RuntimeStore(database) as store:
        after = store.state(episode_id)
    assert after["sequence"] == before["sequence"]
    assert after["status"] == before["status"]


def test_native_preflight_rejects_preview_artifacts(tmp_path):
    module = load_module()
    output, database = prepare(module, tmp_path)
    started = module.start_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        REF_A,
        occurred_at="2026-08-08T08:10:00Z",
    )

    with pytest.raises(module.GhAwRuntimeError, match="requires upstream native artifacts"):
        module.preflight_episode(
            SPEC_PATH,
            output,
            database,
            "forge-dispatcher",
            started["episode_id"],
            REF_A,
        )


def test_native_preflight_rejects_request_bound_episode_mismatch(tmp_path):
    module = load_module()
    output, database = prepare_native(module, tmp_path)
    started = module.start_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        REF_A,
        occurred_at="2026-08-08T08:20:00Z",
    )

    with pytest.raises(module.GhAwRuntimeError, match="episode_id is not bound to request_digest"):
        module.preflight_episode(
            SPEC_PATH,
            output,
            database,
            "forge-dispatcher",
            started["episode_id"],
            REF_B,
        )


def test_native_preflight_writes_only_the_same_certificate(tmp_path):
    module = load_module()
    output, database = prepare_native(module, tmp_path)
    started = module.start_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        REF_A,
        occurred_at="2026-08-08T08:30:00Z",
    )
    certificate_path = tmp_path / "admission.json"
    first = module.preflight_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        started["episode_id"],
        REF_A,
        certificate_path=certificate_path,
    )
    assert json.loads(certificate_path.read_text(encoding="utf-8")) == first
    second = module.preflight_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        started["episode_id"],
        REF_A,
        certificate_path=certificate_path,
    )
    assert second == first
    certificate_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(module.GhAwRuntimeError, match="certificate path already contains"):
        module.preflight_episode(
            SPEC_PATH,
            output,
            database,
            "forge-dispatcher",
            started["episode_id"],
            REF_A,
            certificate_path=certificate_path,
        )
