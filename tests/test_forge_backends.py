"""Portable backend negotiation and deterministic conformance tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-backends.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_backends", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_descriptor_negotiation_accepts_rejects_and_degrades():
    module = load_module()
    sqlite = module.descriptor_for("sqlite")
    assert module.validate_descriptor(sqlite)["backend_id"] == "sqlite-wal"
    accepted = module.negotiate(
        sqlite,
        {"required_capabilities": ["fenced_leases"], "consistency_level": "strict_serializable"},
    )
    assert accepted["status"] == "accepted"

    memory = module.descriptor_for("memory")
    rejected = module.negotiate(memory, {"consistency_level": "strict_serializable"})
    assert rejected["status"] == "rejected"
    assert rejected["degradation_ref"].startswith("sha256:")
    degraded = module.negotiate(
        memory,
        {"consistency_level": "strict_serializable", "allow_degraded": True},
    )
    assert degraded["status"] == "degraded"

    etcd = module.descriptor_for("etcd")
    distributed = module.negotiate(
        etcd,
        {
            "required_capabilities": [
                "remote_revisions",
                "watch_delivery",
                "snapshot_recovery",
                "compaction_recovery",
                "fenced_leases",
            ],
            "consistency_level": "strict_serializable",
        },
    )
    assert distributed["status"] == "accepted"


def test_both_backends_pass_the_same_offline_fixture_matrix(tmp_path):
    module = load_module()
    results = []
    sqlite = module.make_backend("sqlite", tmp_path / "runtime.sqlite3")
    memory = module.make_backend("memory")
    try:
        results.extend([module.run_conformance(sqlite), module.run_conformance(memory)])
    finally:
        sqlite.close()
        memory.close()

    assert [result["status"] for result in results] == ["passed", "passed"]
    assert all(result["summary"] == {"total": 12, "passed": 12, "unsupported": 0, "degraded": 0, "failed": 0} for result in results)
    assert all(case["status"] == "passed" for result in results for case in result["cases"])
    assert {case["case_id"] for case in results[0]["cases"]} == {
        "append-ordering",
        "atomic-event-effect",
        "compare-and-swap-fencing",
        "durable-timer-wait",
        "checkpoint-restore",
        "inbox-dedupe",
        "migration",
        "backup-restore",
        "history-verification",
        "privacy-boundary",
        "ambiguous-commit",
        "adapter-evidence",
    }


def test_memory_conformance_is_byte_deterministic():
    module = load_module()
    first = module.make_backend("memory")
    second = module.make_backend("memory")
    try:
        assert module.run_conformance(first) == module.run_conformance(second)
    finally:
        first.close()
        second.close()


def test_etcd_watch_facade_passes_base_and_distributed_matrices(tmp_path):
    module = load_module()
    first = module.make_backend("etcd", tmp_path / "first.sqlite3")
    second = module.make_backend("etcd", tmp_path / "second.sqlite3")
    try:
        first_base = module.run_conformance(first)
        first_distributed = module.run_distributed_conformance(first)
        second_base = module.run_conformance(second)
        second_distributed = module.run_distributed_conformance(second)
    finally:
        first.close()
        second.close()

    assert first_base["status"] == first_distributed["status"] == "passed"
    assert first_base["summary"] == {"total": 12, "passed": 12, "unsupported": 0, "degraded": 0, "failed": 0}
    assert first_distributed["summary"] == {
        "total": 6,
        "passed": 6,
        "unsupported": 0,
        "degraded": 0,
        "failed": 0,
    }
    assert first_base == second_base
    assert first_distributed == second_distributed


def test_revision_watch_rejects_tampering_and_recovers_after_compaction():
    module = load_module()
    watch = module.distributed.RevisionWatchAdapter()
    notification = watch.publish(
        event_ref="sha256:" + "1" * 64,
        transaction_ref="sha256:" + "2" * 64,
        cloud_event={
            "source": "urn:forge:test",
            "id": "event-1",
            "type": "com.forge.test.v1",
            "data_ref": "sha256:" + "3" * 64,
        },
    )
    with pytest.raises(module.distributed.DistributedRecoveryError, match="unsupported fields"):
        watch.publish(
            event_ref=notification["event_ref"],
            transaction_ref=notification["transaction_ref"],
            cloud_event={
                "source": "urn:forge:test",
                "id": "event-1",
                "type": "com.forge.test.v1",
                "data": "must-not-persist",
            },
        )
    cursor = watch.cursor()
    tampered = dict(cursor)
    tampered["remote_revision"] = 0
    tampered["cursor_ref"] = cursor["cursor_ref"]
    with pytest.raises(module.distributed.DistributedRecoveryError, match="reference"):
        watch.observe([notification], tampered)

    snapshot = watch.snapshot(state_ref="sha256:" + "4" * 64)
    watch.compact(1)
    with pytest.raises(module.distributed.DistributedRecoveryError, match="compaction"):
        watch.observe([notification], {"watch_id": watch.watch_id, "remote_revision": 0})
    recovered = watch.recover(snapshot=snapshot, replay_notifications=[])
    assert recovered["status"] == "recovered"
    assert recovered["cursor"]["remote_revision"] == 1


def test_conformance_and_backend_schemas_are_valid_json():
    for name in (
        "runtime-backend.schema.json",
        "runtime-backend-evidence.schema.json",
        "runtime-conformance.schema.json",
        "runtime-distributed.schema.json",
        "runtime-chaos-schedule.schema.json",
        "runtime-chaos-result.schema.json",
        "runtime-chaos-corpus.schema.json",
        "runtime-definitions.schema.json",
        "runtime-compatibility.schema.json",
    ):
        document = json.loads((REPO / "data" / name).read_text(encoding="utf-8"))
        assert document["$schema"].endswith("draft/2020-12/schema")
        assert document["type"] == "object"
