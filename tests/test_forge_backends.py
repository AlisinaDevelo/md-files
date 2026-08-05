"""Portable backend negotiation and deterministic conformance tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

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


def test_conformance_and_backend_schemas_are_valid_json():
    for name in (
        "runtime-backend.schema.json",
        "runtime-backend-evidence.schema.json",
        "runtime-conformance.schema.json",
        "runtime-definitions.schema.json",
        "runtime-compatibility.schema.json",
    ):
        document = json.loads((REPO / "data" / name).read_text(encoding="utf-8"))
        assert document["$schema"].endswith("draft/2020-12/schema")
        assert document["type"] == "object"
