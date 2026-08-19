"""MCP Tasks projection tests for the durable Forge wait protocol."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-mcp-tasks.py"
AUTH = "sha256:" + "b" * 64
SCHEMA = "sha256:" + "a" * 64
REQUEST_IDENTITY = "sha256:" + "e" * 64
REQUEST_META = {
    "io.modelcontextprotocol/clientCapabilities": {
        "extensions": {"io.modelcontextprotocol/tasks": {}}
    }
}


def load_module():
    spec = importlib.util.spec_from_file_location("forge_mcp_tasks", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def start_wait(module, database, *, wait_id="wait-1", expiration_outcome="fail_run"):
    store = module.runtime.RuntimeStore(database)
    store.start_run(
        "run-1",
        "feature-flow",
        "definition-v1",
        "policy-v1",
        occurred_at="2026-08-05T08:00:00Z",
    )
    store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
        idempotency_key="task-build-scheduled",
        occurred_at="2026-08-05T08:01:00Z",
    )
    store.append_event(
        "run-1",
        "task.started",
        {"task_id": "build", "attempt": 1},
        idempotency_key="task-build-started",
        occurred_at="2026-08-05T08:02:00Z",
    )
    store.create_wait(
        "run-1",
        "build",
        SCHEMA,
        AUTH,
        wait_id=wait_id,
        resume_contract="workflow-v1",
        ttl_seconds=60,
        poll_interval_ms=1000,
        expiration_outcome=expiration_outcome,
        occurred_at="2026-08-05T08:03:00Z",
    )
    return store


def request_id(view):
    return next(iter(view["inputRequests"]))


def test_machine_readable_contract_is_versioned():
    schema = json.loads((REPO / "data/runtime-mcp-tasks.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"].endswith("/runtime/mcp-tasks/v2")
    assert {"profile", "task", "ack"} <= set(schema["$defs"])


def test_profile_rejects_legacy_and_ambiguous_negotiation():
    module = load_module()

    profile = module.McpTasksAdapter.profile()
    assert profile["profile"] == "mcp-2026-07-28"
    assert profile["schemaVersion"] == 2
    assert profile["contractRevision"] == "forge-mcp-tasks-v2"
    assert profile["protocolVersion"] == "2026-07-28"
    assert profile["extension"] == "io.modelcontextprotocol/tasks"
    assert profile["methods"] == ["tasks/get", "tasks/update", "tasks/cancel"]
    assert profile["stateless"] is True
    assert profile["rawPayloads"] is False
    assert profile["inputResponses"] == "digest-reference-only"
    assert profile["requestNegotiation"] == "per-request"

    with pytest.raises(module.McpTaskError, match="unsupported MCP protocol revision"):
        module.McpTasksAdapter.negotiate("2025-11-25", [module.MCP_TASKS_EXTENSION])
    with pytest.raises(module.McpTaskError, match="ambiguous"):
        module.McpTasksAdapter.negotiate(
            module.MCP_PROTOCOL_VERSION,
            [module.MCP_TASKS_EXTENSION, module.MCP_TASKS_EXTENSION],
        )
    with pytest.raises(module.McpTaskError, match="not negotiated"):
        module.McpTasksAdapter.negotiate(module.MCP_PROTOCOL_VERSION, [])


def test_task_operations_require_per_request_capability_admission(tmp_path):
    module = load_module()
    store = start_wait(module, tmp_path / "runtime.sqlite3")
    adapter = module.McpTasksAdapter(store)

    with pytest.raises(module.McpTaskError, match="request metadata"):
        adapter.get_task("run-1", "wait-1", AUTH)
    with pytest.raises(module.McpTaskError, match="not negotiated for this request"):
        adapter.get_task(
            "run-1",
            "wait-1",
            AUTH,
            request_meta={"io.modelcontextprotocol/clientCapabilities": {"extensions": {}}},
        )
    with pytest.raises(module.McpTaskError, match="must be an object"):
        adapter.get_task(
            "run-1",
            "wait-1",
            AUTH,
            request_meta={
                "io.modelcontextprotocol/clientCapabilities": {
                    "extensions": {module.MCP_TASKS_EXTENSION: []}
                }
            },
        )
    assert module.McpTasksAdapter.negotiate_request(REQUEST_META)["requestNegotiation"] == "per-request"


def test_mcp_view_result_and_reference_only_input_round_trip(tmp_path):
    module = load_module()
    store = start_wait(module, tmp_path / "runtime.sqlite3")
    adapter = module.McpTasksAdapter(store)

    view = adapter.get_task(
        "run-1",
        "wait-1",
        AUTH,
        request_meta=REQUEST_META,
        now="2026-08-05T08:03:10Z",
        request_identity_digest=REQUEST_IDENTITY,
    )
    assert view["taskId"].startswith("forge-task-v2.")
    assert view["taskId"] != "run-1:wait-1"
    assert view["status"] == "input_required"
    assert view["ttlMs"] == 50_000
    assert view["pollIntervalMs"] == 1000
    assert view["_meta"]["forge"]["request_binding_digest"].startswith("sha256:")
    assert view["_meta"]["forge"]["contract_revision"] == "forge-mcp-tasks-v2"
    first_request_id = request_id(view)
    assert first_request_id.startswith("sha256:")
    assert view["inputRequests"][first_request_id]["_meta"]["forge"]["referenceOnly"] is True
    assert adapter.get_task(
        "run-1", "wait-1", AUTH, request_meta=REQUEST_META, request_identity_digest=REQUEST_IDENTITY
    )["taskId"] == view["taskId"]
    assert adapter.get_task_by_id(
        view["taskId"], AUTH, request_meta=REQUEST_META, request_identity_digest=REQUEST_IDENTITY
    )["taskId"] == view["taskId"]

    with pytest.raises(module.McpTaskError, match="authorization"):
        adapter.get_task("run-1", "wait-1", "sha256:" + "d" * 64, request_meta=REQUEST_META)
    with pytest.raises(module.McpTaskError, match="invalid"):
        adapter.get_task_by_id("run-1:wait-1", AUTH, request_meta=REQUEST_META)
    with pytest.raises(module.McpTaskError, match="unavailable"):
        adapter.get_result("run-1", "wait-1", AUTH, request_meta=REQUEST_META)

    input_digest = "sha256:" + "c" * 64
    assert adapter.update_by_id(
        view["taskId"],
        AUTH,
        input_digest,
        request_meta=REQUEST_META,
        input_schema_digest=SCHEMA,
        input_request_id=first_request_id,
        request_identity_digest=REQUEST_IDENTITY,
        submission_id="submission-1",
        occurred_at="2026-08-05T08:03:20Z",
    ) == {}
    assert adapter.update_by_id(
        view["taskId"],
        AUTH,
        input_digest,
        request_meta=REQUEST_META,
        input_schema_digest=SCHEMA,
        input_request_id=first_request_id,
        request_identity_digest=REQUEST_IDENTITY,
        submission_id="submission-1",
        occurred_at="2026-08-05T08:03:20Z",
    ) == {}
    with pytest.raises(module.runtime.RuntimeStoreError, match="different event data"):
        adapter.update_by_id(
            view["taskId"],
            AUTH,
            "sha256:" + "f" * 64,
            request_meta=REQUEST_META,
            input_schema_digest=SCHEMA,
            input_request_id=first_request_id,
            request_identity_digest=REQUEST_IDENTITY,
            submission_id="submission-1",
            occurred_at="2026-08-05T08:03:20Z",
        )

    result = adapter.get_result(
        "run-1", "wait-1", AUTH, request_meta=REQUEST_META, request_identity_digest=REQUEST_IDENTITY
    )
    assert result["taskId"] == view["taskId"]
    assert result["result"]["_meta"]["forge"]["input_digest"] == input_digest
    assert "raw response" not in str(result["result"])
    assert adapter.notifications("run-1", "wait-1", after_sequence=4)[0]["status"] == "completed"


def test_handles_are_isolated_and_input_rounds_reject_stale_responses(tmp_path):
    module = load_module()
    store = start_wait(module, tmp_path / "runtime.sqlite3")
    adapter = module.McpTasksAdapter(store)
    first = adapter.get_task(
        "run-1", "wait-1", AUTH, request_meta=REQUEST_META, request_identity_digest=REQUEST_IDENTITY
    )
    first_request_id = request_id(first)
    assert adapter.get_task("run-1", "wait-1", AUTH, request_meta=REQUEST_META)["taskId"] != first["taskId"]

    adapter.update_by_id(
        first["taskId"],
        AUTH,
        "sha256:" + "c" * 64,
        request_meta=REQUEST_META,
        input_schema_digest=SCHEMA,
        input_request_id=first_request_id,
        request_identity_digest=REQUEST_IDENTITY,
        occurred_at="2026-08-05T08:03:20Z",
    )
    next_schema = "sha256:" + "1" * 64
    store.create_wait(
        "run-1",
        "build",
        next_schema,
        AUTH,
        wait_id="wait-2",
        resume_contract="workflow-v1",
        ttl_seconds=60,
        poll_interval_ms=1000,
        occurred_at="2026-08-05T08:03:30Z",
    )
    second = adapter.get_task_by_id(
        first["taskId"], AUTH, request_meta=REQUEST_META, request_identity_digest=REQUEST_IDENTITY
    )
    second_request_id = request_id(second)
    assert second["status"] == "input_required"
    assert second_request_id != first_request_id
    with pytest.raises(module.McpTaskError, match="stale"):
        adapter.update_by_id(
            first["taskId"],
            AUTH,
            "sha256:" + "f" * 64,
            request_meta=REQUEST_META,
            input_schema_digest=SCHEMA,
            input_request_id=first_request_id,
            request_identity_digest=REQUEST_IDENTITY,
        )
    assert adapter.update_by_id(
        first["taskId"],
        AUTH,
        "sha256:" + "2" * 64,
        request_meta=REQUEST_META,
        input_schema_digest=next_schema,
        input_request_id=second_request_id,
        request_identity_digest=REQUEST_IDENTITY,
        occurred_at="2026-08-05T08:03:40Z",
    ) == {}


def test_mcp_cancel_is_atomic_authorization_bound_and_idempotent(tmp_path):
    module = load_module()
    store = start_wait(module, tmp_path / "runtime.sqlite3")
    adapter = module.McpTasksAdapter(store)

    with pytest.raises(module.McpTaskError, match="authorization"):
        adapter.cancel(
            "run-1", "wait-1", "sha256:" + "d" * 64, request_meta=REQUEST_META,
            occurred_at="2026-08-05T08:03:30Z"
        )

    cancelled = adapter.cancel(
        "run-1", "wait-1", AUTH, request_meta=REQUEST_META,
        request_identity_digest=REQUEST_IDENTITY, occurred_at="2026-08-05T08:03:30Z"
    )
    assert cancelled == {}
    state = store.state("run-1")
    assert state["cancel_acknowledged"] is True
    history_length = len(store.history("run-1"))
    assert adapter.cancel(
        "run-1", "wait-1", AUTH, request_meta=REQUEST_META,
        request_identity_digest=REQUEST_IDENTITY, occurred_at="2026-08-05T08:03:31Z"
    ) == {}
    assert len(store.history("run-1")) == history_length
    assert [event["event_type"] for event in store.history("run-1")[-3:]] == [
        "run.cancel_requested",
        "cancel.acknowledged",
        "run.cancelled",
    ]


def test_expiry_projects_fail_and_cancel_outcomes(tmp_path):
    module = load_module()
    failed_store = start_wait(module, tmp_path / "failed.sqlite3")
    failed_store.expire_wait("run-1", "wait-1", occurred_at="2026-08-05T08:04:00Z")
    failed_view = module.McpTasksAdapter(failed_store).get_task(
        "run-1", "wait-1", AUTH, request_meta=REQUEST_META, now="2026-08-05T08:04:00Z"
    )
    assert failed_view["status"] == "failed"
    assert failed_view["ttlMs"] == 0

    cancelled_store = start_wait(
        module, tmp_path / "cancelled.sqlite3", expiration_outcome="cancel_run"
    )
    cancelled_store.expire_wait("run-1", "wait-1", occurred_at="2026-08-05T08:04:00Z")
    cancelled_view = module.McpTasksAdapter(cancelled_store).get_task(
        "run-1", "wait-1", AUTH, request_meta=REQUEST_META, now="2026-08-05T08:04:00Z"
    )
    assert cancelled_view["status"] == "cancelled"
    assert cancelled_view["ttlMs"] == 0
