"""Offline integrity and privacy tests for Forge runtime lineage."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/observability/scripts/forge-lineage.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_lineage", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_effect(task_id: str = "build"):
    return {
        "effect_type": "github.issue.create",
        "task_id": task_id,
        "activity_id": "github-issue",
        "attempt": 1,
        "effect_definition_revision": "effect-v1",
        "payload": {
            "target_ref": "github:issues/1",
            "request_digest": "sha256:request",
        },
    }


def prepared_runtime(tmp_path, *, task_id: str = "build"):
    lineage = load_module()
    runtime = lineage._runtime_module()
    database = tmp_path / "runtime.sqlite3"
    store = runtime.RuntimeStore(database)
    store.start_run(
        "run-1",
        "feature-flow",
        "definition-v1",
        "policy-v1",
        occurred_at="2026-08-05T00:00:00Z",
    )
    store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": task_id, "depends_on": []},
        idempotency_key=f"task-{task_id}-scheduled",
        effect=make_effect(task_id),
        occurred_at="2026-08-05T00:00:01Z",
    )
    effect_id = store.list_outbox("run-1")[0]["effect_id"]
    return lineage, runtime, database, store, effect_id


def test_export_is_deterministic_and_binds_successful_effect(tmp_path):
    lineage, _runtime, database, store, effect_id = prepared_runtime(tmp_path)
    claimed = store.claim_outbox("worker-a", now="2026-08-05T00:00:02Z")[0]
    store.acknowledge_outbox(
        effect_id,
        "worker-a",
        {"status": "succeeded", "provider_request_id": "provider:req-1"},
        lease_generation=claimed["lease_generation"],
        received_at="2026-08-05T00:00:03Z",
    )
    store.close()

    first = lineage.export_manifest(database)
    second = lineage.export_manifest(database)
    assert first == second
    assert lineage.verify_manifest(first)["verified"] is True
    assert first["effects"][0]["source_sequence"] == 2
    assert {receipt["receipt_type"] for receipt in first["receipts"]} == {"effect.outcome", "effect.receipt"}
    assert "github:issues/1" not in json.dumps(first)
    assert "request_digest" not in json.dumps(first)


def test_retry_and_dead_letter_outcomes_are_verifiable(tmp_path):
    lineage, _runtime, database, store, effect_id = prepared_runtime(tmp_path)
    first = store.claim_outbox("worker-a", now="2026-08-05T00:00:02Z")[0]
    store.fail_outbox(
        effect_id,
        "worker-a",
        lease_generation=first["lease_generation"],
        error_ref="sha256:" + "a" * 64,
        retryable=True,
        next_attempt_at="2026-08-05T00:01:00Z",
        now="2026-08-05T00:00:03Z",
    )
    second = store.claim_outbox("worker-b", now="2026-08-05T00:01:01Z")[0]
    store.fail_outbox(
        effect_id,
        "worker-b",
        lease_generation=second["lease_generation"],
        error_ref="sha256:" + "b" * 64,
        retryable=False,
        now="2026-08-05T00:01:02Z",
    )
    store.close()

    manifest = lineage.export_manifest(database)
    assert [receipt["status"] for receipt in manifest["receipts"] if receipt["receipt_type"] == "effect.outcome"] == [
        "retry",
        "dead_letter",
    ]
    assert lineage.verify_manifest(manifest)["verified"] is True


def test_policy_receipts_are_projected_without_raw_content(tmp_path):
    lineage, _runtime, database, store, _effect_id = prepared_runtime(tmp_path)
    store.close()
    receipt_module = lineage._receipts_module()
    receipts_path = tmp_path / "receipts.jsonl"
    receipt_store = receipt_module.ReceiptStore(receipts_path)
    receipt_store.append(
        receipt_module.make_event(
            "outcome.recorded",
            "run-1",
            attributes={
                "action_digest": "sha256:" + "c" * 64,
                "policy_revision": "policy-v1",
                "rule_id": "github-write",
                "status": "authorized",
                "prompt": "never export this raw value",
            },
        )
    )

    manifest = lineage.export_manifest(database, receipts_path)
    rendered = json.dumps(manifest)
    assert "never export this raw value" not in rendered
    assert any(receipt["receipt_type"] == "policy.decision" for receipt in manifest["receipts"])
    assert lineage.verify_manifest(manifest)["verified"] is True


def test_manifest_digest_and_receipt_digest_tampering_fail_closed(tmp_path):
    lineage, _runtime, database, store, effect_id = prepared_runtime(tmp_path)
    claimed = store.claim_outbox("worker-a", now="2026-08-05T00:00:02Z")[0]
    store.acknowledge_outbox(
        effect_id,
        "worker-a",
        {"status": "succeeded", "provider_request_id": "provider:req-1"},
        lease_generation=claimed["lease_generation"],
        received_at="2026-08-05T00:00:03Z",
    )
    store.close()
    manifest = lineage.export_manifest(database)

    changed = copy.deepcopy(manifest)
    changed["receipts"][0]["status"] = "dead_letter"
    with pytest.raises(lineage.LineageError, match="manifest digest mismatch"):
        lineage.verify_manifest(changed)

    changed = copy.deepcopy(manifest)
    changed["receipts"][0]["status"] = "dead_letter"
    body = {key: value for key, value in changed.items() if key != "manifest_digest"}
    changed["manifest_digest"] = lineage.digest_ref(body)
    with pytest.raises(lineage.LineageError, match="receipt identity mismatch|receipt digest mismatch"):
        lineage.verify_manifest(changed)

    unsupported = copy.deepcopy(manifest)
    unsupported["unsupported"] = True
    body = {key: value for key, value in unsupported.items() if key != "manifest_digest"}
    unsupported["manifest_digest"] = lineage.digest_ref(body)
    with pytest.raises(lineage.LineageError, match="unsupported fields"):
        lineage.verify_manifest(unsupported)


def test_missing_parent_and_generation_mismatch_fail_closed(tmp_path):
    lineage, _runtime, database, store, effect_id = prepared_runtime(tmp_path)
    claimed = store.claim_outbox("worker-a", now="2026-08-05T00:00:02Z")[0]
    store.acknowledge_outbox(
        effect_id,
        "worker-a",
        {"status": "succeeded", "provider_request_id": "provider:req-1"},
        lease_generation=claimed["lease_generation"],
        received_at="2026-08-05T00:00:03Z",
    )
    store.close()
    manifest = lineage.export_manifest(database)

    missing_parent = copy.deepcopy(manifest)
    missing_parent["effects"][0]["source_event_id"] = "missing-event"
    body = {key: value for key, value in missing_parent.items() if key != "manifest_digest"}
    missing_parent["manifest_digest"] = lineage.digest_ref(body)
    with pytest.raises(lineage.LineageError, match="no parent event"):
        lineage.verify_manifest(missing_parent)

    wrong_generation = copy.deepcopy(manifest)
    wrong_generation["receipts"][0]["lease_generation"] += 1
    body = {key: value for key, value in wrong_generation.items() if key != "manifest_digest"}
    wrong_generation["manifest_digest"] = lineage.digest_ref(body)
    with pytest.raises(lineage.LineageError, match="receipt digest mismatch|receipt identity mismatch|lease generation mismatch"):
        lineage.verify_manifest(wrong_generation)
