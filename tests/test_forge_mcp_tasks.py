"""MCP Tasks projection tests for the durable Forge wait protocol."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-mcp-tasks.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_mcp_tasks", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def start_wait(module, database):
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
        "sha256:" + "a" * 64,
        "sha256:" + "b" * 64,
        wait_id="wait-1",
        resume_contract="workflow-v1",
        ttl_seconds=60,
        poll_interval_ms=1000,
        occurred_at="2026-08-05T08:03:00Z",
    )
    return store


def test_mcp_view_result_notifications_and_reference_only_output(tmp_path):
    module = load_module()
    store = start_wait(module, tmp_path / "runtime.sqlite3")
    adapter = module.McpTasksAdapter(store)

    view = adapter.get_task("run-1", "wait-1", now="2026-08-05T08:03:10Z")
    assert view["taskId"] == "run-1:wait-1"
    assert view["status"] == "input_required"
    assert view["ttl"] == 50_000
    assert adapter.notifications("run-1", "wait-1")[-1]["status"] == "input_required"
    with pytest.raises(module.McpTaskError, match="unavailable"):
        adapter.get_result("run-1", "wait-1")

    store.submit_input(
        "run-1",
        "wait-1",
        "submission-1",
        "sha256:" + "c" * 64,
        "sha256:" + "b" * 64,
        input_schema_digest="sha256:" + "a" * 64,
        occurred_at="2026-08-05T08:03:20Z",
    )
    result = adapter.get_result("run-1", "wait-1")
    assert result["result"]["_meta"]["forge"]["input_digest"] == "sha256:" + "c" * 64
    assert adapter.notifications("run-1", "wait-1", after_sequence=4)[0]["status"] == "completed"
    assert "raw response" not in str(result["result"])


def test_mcp_cancel_is_atomic_and_authorization_bound(tmp_path):
    module = load_module()
    store = start_wait(module, tmp_path / "runtime.sqlite3")
    adapter = module.McpTasksAdapter(store)

    with pytest.raises(module.runtime.RuntimeStoreError, match="authorization context mismatch"):
        adapter.cancel("run-1", "wait-1", "sha256:" + "d" * 64, occurred_at="2026-08-05T08:03:30Z")

    cancelled = adapter.cancel(
        "run-1",
        "wait-1",
        "sha256:" + "b" * 64,
        occurred_at="2026-08-05T08:03:30Z",
    )
    assert cancelled["status"] == "cancelled"
    state = store.state("run-1")
    assert state["cancel_acknowledged"] is True
    assert [event["event_type"] for event in store.history("run-1")[-3:]] == [
        "run.cancel_requested",
        "cancel.acknowledged",
        "run.cancelled",
    ]
