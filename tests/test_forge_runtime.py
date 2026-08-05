"""Recovery and concurrency tests for the local Forge runtime store."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-runtime.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_runtime", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def start(module, path):
    store = module.RuntimeStore(path)
    store.start_run(
        "run-1",
        "feature-flow",
        "definition-v1",
        "policy-v1",
        occurred_at="2026-08-04T08:00:00Z",
    )
    return store


def make_effect(*, task_id="build", activity_id="github-issue", attempt=1, payload=None):
    return {
        "effect_type": "github.issue.create",
        "task_id": task_id,
        "activity_id": activity_id,
        "attempt": attempt,
        "effect_definition_revision": "effect-v1",
        "payload": payload or {"target_ref": "github:issues/1", "request_digest": "sha256:request"},
    }


def test_lifecycle_and_task_state_replay_after_reopen(tmp_path):
    module = load_module()
    database = tmp_path / "runtime.sqlite3"
    store = start(module, database)
    store.append_event("run-1", "run.paused", idempotency_key="pause-1", occurred_at="2026-08-04T08:01:00Z")
    store.append_event("run-1", "run.resumed", idempotency_key="resume-1", occurred_at="2026-08-04T08:02:00Z")
    store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "build", "title": "Build", "depends_on": []},
        idempotency_key="task-build-scheduled",
        occurred_at="2026-08-04T08:03:00Z",
    )
    store.append_event(
        "run-1",
        "task.started",
        {"task_id": "build", "attempt": 1},
        idempotency_key="task-build-started-1",
        occurred_at="2026-08-04T08:04:00Z",
    )
    store.append_event(
        "run-1",
        "task.completed",
        {"task_id": "build", "output_ref": "sha256:build"},
        idempotency_key="task-build-completed",
        occurred_at="2026-08-04T08:05:00Z",
    )
    store.append_event("run-1", "run.completed", idempotency_key="run-completed", occurred_at="2026-08-04T08:06:00Z")
    expected = store.state("run-1")
    assert expected["status"] == "completed"
    assert expected["sequence"] == 7
    assert expected["tasks"]["build"] == {
        "status": "completed",
        "attempt": 1,
        "depends_on": [],
        "title": "Build",
        "output_ref": "sha256:build",
    }
    store.close()

    with module.RuntimeStore(database) as reopened:
        assert reopened.state("run-1") == expected
        history = reopened.history("run-1")
        assert history[-1]["previous_hash"] == history[-2]["event_hash"]


def test_idempotency_returns_original_and_conflicts_fail_closed(tmp_path):
    module = load_module()
    store = start(module, tmp_path / "runtime.sqlite3")
    first = store.append_event("run-1", "run.paused", idempotency_key="pause-1", occurred_at="2026-08-04T08:01:00Z")
    retry = store.append_event("run-1", "run.paused", idempotency_key="pause-1", occurred_at="2026-08-04T09:01:00Z")
    assert retry == first
    assert len(store.history("run-1")) == 2
    with pytest.raises(module.RuntimeStoreError, match="different event data"):
        store.append_event("run-1", "run.resumed", idempotency_key="pause-1")


def test_invalid_transitions_and_raw_payloads_are_rejected(tmp_path):
    module = load_module()
    store = start(module, tmp_path / "runtime.sqlite3")
    store.append_event("run-1", "run.paused", idempotency_key="pause-1")
    with pytest.raises(module.RuntimeStoreError, match="run.paused is invalid"):
        store.append_event("run-1", "run.paused", idempotency_key="pause-2")
    store.append_event("run-1", "run.resumed", idempotency_key="resume-1")
    with pytest.raises(module.RuntimeStoreError, match="not allowed in durable state"):
        store.append_event(
            "run-1",
            "task.scheduled",
            {"task_id": "unsafe", "api_token": "raw secret"},
            idempotency_key="unsafe-task",
        )


def test_event_and_outbox_intent_commit_atomically(tmp_path):
    module = load_module()
    database = tmp_path / "runtime.sqlite3"
    store = start(module, database)
    event = store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
        idempotency_key="task-build-scheduled",
        effect=make_effect(),
        occurred_at="2026-08-04T08:03:00Z",
    )
    effects = store.list_outbox("run-1")
    assert len(effects) == 1
    assert effects[0]["source_event_id"] == event["event_id"]
    with pytest.raises(module.RuntimeStoreError, match="effect identity already exists"):
        store.append_event(
            "run-1",
            "task.started",
            {"task_id": "build", "attempt": 1},
            idempotency_key="task-build-started-1",
            effect=make_effect(),
        )
    assert len(store.history("run-1")) == 2
    assert len(store.list_outbox("run-1")) == 1


def test_effect_identity_is_stable_and_payload_boundary_is_private(tmp_path):
    module = load_module()
    database = tmp_path / "runtime.sqlite3"
    store = start(module, database)
    first = store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
        idempotency_key="task-build-scheduled",
        effect=make_effect(),
        occurred_at="2026-08-04T08:03:00Z",
    )
    first_effect = store.list_outbox("run-1")[0]
    retry = store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
        idempotency_key="task-build-scheduled",
        effect=make_effect(),
        occurred_at="2026-08-04T09:00:00Z",
    )
    assert retry == first
    assert store.list_outbox("run-1")[0]["effect_id"] == first_effect["effect_id"]
    with pytest.raises(module.RuntimeStoreError, match="not allowed in durable state"):
        store.append_event(
            "run-1",
            "task.scheduled",
            {"task_id": "unsafe", "depends_on": []},
            idempotency_key="task-unsafe-scheduled",
            effect=make_effect(
                task_id="unsafe",
                payload={"provider_response_body": "raw provider response"},
            ),
        )


def test_outbox_claim_ack_and_duplicate_inbox_delivery(tmp_path):
    module = load_module()
    store = start(module, tmp_path / "runtime.sqlite3")
    store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
        idempotency_key="task-build-scheduled",
        effect=make_effect(),
        occurred_at="2026-08-04T08:03:00Z",
    )
    effect_id = store.list_outbox("run-1")[0]["effect_id"]
    claimed = store.claim_outbox("worker-a", now="2026-08-04T08:10:00Z", lease_seconds=60)
    assert len(claimed) == 1
    assert claimed[0]["status"] == "leased"
    assert claimed[0]["delivery_attempts"] == 1
    with pytest.raises(module.RuntimeStoreError, match="not allowed in durable state"):
        store.acknowledge_outbox(
            effect_id,
            "worker-a",
            {"status": "succeeded", "response_body": "raw provider body"},
        )
    receipt = {
        "status": "succeeded",
        "provider_request_id": "provider:req-123",
        "result_ref": "sha256:" + "a" * 64,
    }
    assert store.acknowledge_outbox(effect_id, "worker-a", receipt) == receipt
    assert store.record_inbox(effect_id, receipt) == receipt
    with pytest.raises(module.RuntimeStoreError, match="conflicting inbox receipt"):
        store.record_inbox(effect_id, {"status": "succeeded", "provider_request_id": "provider:req-999"})
    assert store.list_outbox("run-1")[0]["status"] == "succeeded"
    assert store.list_inbox("run-1")[0]["receipt"] == receipt
    assert store.outbox_attempts(effect_id)[0]["outcome"] == "succeeded"


def test_tampered_outbox_breaks_delivery(tmp_path):
    module = load_module()
    database = tmp_path / "runtime.sqlite3"
    store = start(module, database)
    store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
        idempotency_key="task-build-scheduled",
        effect=make_effect(),
        occurred_at="2026-08-04T08:03:00Z",
    )
    store.close()
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE runtime_outbox SET payload_json = ?",
        ('{"target_ref":"github:issues/999"}',),
    )
    connection.commit()
    connection.close()
    with module.RuntimeStore(database) as reopened:
        with pytest.raises(module.RuntimeStoreError, match="outbox effect hash mismatch"):
            reopened.list_outbox("run-1")


def test_outbox_lease_expiry_retry_and_dead_letter(tmp_path):
    module = load_module()
    store = start(module, tmp_path / "runtime.sqlite3")
    store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
        idempotency_key="task-build-scheduled",
        effect=make_effect(),
        occurred_at="2026-08-04T08:03:00Z",
    )
    effect_id = store.list_outbox("run-1")[0]["effect_id"]
    store.claim_outbox("worker-a", now="2026-08-04T08:10:00Z", lease_seconds=10)
    reclaimed = store.claim_outbox("worker-b", now="2026-08-04T08:10:11Z", lease_seconds=10)
    assert reclaimed[0]["delivery_attempts"] == 2
    retried = store.fail_outbox(
        effect_id,
        "worker-b",
        error_ref="sha256:" + "b" * 64,
        retryable=True,
        next_attempt_at="2026-08-04T08:11:00Z",
        now="2026-08-04T08:10:12Z",
    )
    assert retried["status"] == "retry"
    store.claim_outbox("worker-c", now="2026-08-04T08:11:00Z", lease_seconds=10)
    dead_lettered = store.fail_outbox(
        effect_id,
        "worker-c",
        error_ref="sha256:" + "c" * 64,
        retryable=False,
        now="2026-08-04T08:11:01Z",
    )
    assert dead_lettered["status"] == "dead_letter"
    assert [item["outcome"] for item in store.outbox_attempts(effect_id)] == [
        "reclaimed",
        "retry",
        "dead_letter",
    ]


def test_concurrent_outbox_claimers_get_one_lease(tmp_path):
    module = load_module()
    database = tmp_path / "runtime.sqlite3"
    store = start(module, database)
    store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
        idempotency_key="task-build-scheduled",
        effect=make_effect(),
        occurred_at="2026-08-04T08:03:00Z",
    )
    store.close()

    def claim(worker_id):
        with module.RuntimeStore(database) as worker:
            return worker.claim_outbox(worker_id, now="2026-08-04T08:10:00Z", lease_seconds=60)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ("worker-a", "worker-b")))
    assert sorted(len(result) for result in results) == [0, 1]


def test_tampering_breaks_replay(tmp_path):
    module = load_module()
    database = tmp_path / "runtime.sqlite3"
    store = start(module, database)
    store.close()
    connection = sqlite3.connect(database)
    connection.execute("UPDATE runtime_events SET payload_json = ? WHERE sequence = 1", ("{}",))
    connection.commit()
    connection.close()
    with module.RuntimeStore(database) as reopened, pytest.raises(
        module.RuntimeStoreError, match="event hash mismatch"
    ):
        reopened.state("run-1")


def test_tampered_run_metadata_breaks_replay(tmp_path):
    module = load_module()
    database = tmp_path / "runtime.sqlite3"
    store = start(module, database)
    store.close()
    connection = sqlite3.connect(database)
    connection.execute("UPDATE runtime_runs SET workflow_id = ? WHERE run_id = ?", ("tampered", "run-1"))
    connection.commit()
    connection.close()
    with module.RuntimeStore(database) as reopened, pytest.raises(
        module.RuntimeStoreError, match="run.started payload does not match workflow_id"
    ):
        reopened.state("run-1")


def test_concurrent_task_writers_get_unique_sequences(tmp_path):
    module = load_module()
    database = tmp_path / "runtime.sqlite3"
    with start(module, database):
        pass

    def append_task(index: int):
        with module.RuntimeStore(database) as worker:
            return worker.append_event(
                "run-1",
                "task.scheduled",
                {"task_id": f"task-{index}", "depends_on": []},
                idempotency_key=f"task-{index}-scheduled",
            )

    with ThreadPoolExecutor(max_workers=6) as executor:
        events = list(executor.map(append_task, range(6)))
    with module.RuntimeStore(database) as store:
        history = store.history("run-1")
        assert [event["sequence"] for event in history] == list(range(1, 8))
        assert len({event["event_id"] for event in events}) == 6
        assert len(store.state("run-1")["tasks"]) == 6
