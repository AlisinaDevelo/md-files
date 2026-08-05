"""Recovery and concurrency tests for the local Forge runtime store."""

from __future__ import annotations

import importlib.util
import json
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


def test_checkpoint_plus_suffix_matches_full_replay_and_is_idempotent(tmp_path):
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
    store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "test", "depends_on": []},
        idempotency_key="task-test-scheduled",
        effect=make_effect(
            task_id="test",
            activity_id="github-test",
            payload={"target_ref": "github:issues/2", "request_digest": "sha256:test-request"},
        ),
        occurred_at="2026-08-04T08:03:01Z",
    )
    store.append_event(
        "run-1",
        "task.started",
        {"task_id": "build", "attempt": 1},
        idempotency_key="task-build-started-1",
        occurred_at="2026-08-04T08:04:00Z",
    )
    checkpoint = store.checkpoint_run("run-1", created_at="2026-08-04T08:04:01Z")
    store.append_event(
        "run-1",
        "task.completed",
        {"task_id": "build", "output_ref": "sha256:build"},
        idempotency_key="task-build-completed",
        occurred_at="2026-08-04T08:05:00Z",
    )
    store.append_event(
        "run-1",
        "task.started",
        {"task_id": "test", "attempt": 1},
        idempotency_key="task-test-started-1",
        occurred_at="2026-08-04T08:05:01Z",
    )
    store.append_event(
        "run-1",
        "task.failed",
        {"task_id": "test", "retryable": False, "error_ref": "sha256:test-failure"},
        idempotency_key="task-test-failed-1",
        occurred_at="2026-08-04T08:05:02Z",
    )
    store.append_event("run-1", "run.completed", idempotency_key="run-completed", occurred_at="2026-08-04T08:06:00Z")
    full_state = store.state("run-1")
    restored = store.restore_state("run-1")
    assert restored["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert restored["checkpoint_sequence"] == checkpoint["event_sequence"]
    assert restored["replayed_sequence"] == full_state["sequence"]
    assert restored["state"] == full_state
    assert restored["state_digest"] == module._digest(full_state)
    assert restored["recovered"] is False
    assert (
        store.checkpoint_run(
            "run-1",
            upto_sequence=checkpoint["event_sequence"],
            created_at="2026-08-04T09:00:00Z",
        )
        == checkpoint
    )
    assert len(store.list_checkpoints("run-1")) == 1
    assert len(store.list_outbox("run-1")) == 2
    retry = store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
        idempotency_key="task-build-scheduled",
        effect=make_effect(),
    )
    assert retry["sequence"] == 2
    assert len(store.list_outbox("run-1")) == 2


def test_corrupt_checkpoint_and_suffix_recover_from_last_verified_prefix(tmp_path):
    module = load_module()
    database = tmp_path / "runtime.sqlite3"
    store = start(module, database)
    store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
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
    checkpoint = store.checkpoint_run("run-1", created_at="2026-08-04T08:04:01Z")
    store.append_event(
        "run-1",
        "task.completed",
        {"task_id": "build", "output_ref": "sha256:build"},
        idempotency_key="task-build-completed",
        occurred_at="2026-08-04T08:05:00Z",
    )
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE runtime_checkpoints SET state_json = ? WHERE checkpoint_id = ?",
        (json.dumps({"prompt": "must never persist"}), checkpoint["checkpoint_id"]),
    )
    connection.execute(
        "UPDATE runtime_events SET event_hash = ? WHERE sequence = 4",
        ("f" * 64,),
    )
    connection.commit()
    connection.close()

    with pytest.raises(module.RuntimeStoreError, match="event hash mismatch"):
        store.state("run-1")
    with pytest.raises(module.RuntimeStoreError, match="not allowed in durable state"):
        store.list_checkpoints("run-1")
    restored = store.restore_state("run-1")
    assert restored["checkpoint_id"] is None
    assert restored["replayed_sequence"] == 3
    assert restored["history_sequence"] == 4
    assert restored["state"]["tasks"]["build"]["status"] == "started"
    assert restored["recovered"] is True
    assert restored["recovery_error_ref"].startswith("sha256:")
    with pytest.raises(module.RuntimeStoreError, match="checkpoint .* is invalid"):
        store.restore_state("run-1", checkpoint["checkpoint_id"])


def test_migration_registry_supports_dry_run_rejection_resume_and_repeat(tmp_path):
    module = load_module()
    database = tmp_path / "runtime.sqlite3"
    store = start(module, database)
    store.append_event("run-1", "run.paused", idempotency_key="pause-1", occurred_at="2026-08-04T08:01:00Z")
    store.close()
    connection = sqlite3.connect(database)
    original_hash = connection.execute("SELECT event_hash FROM runtime_events WHERE sequence = 2").fetchone()[0]
    connection.execute("UPDATE runtime_meta SET value = '1' WHERE key = 'schema_version'")
    connection.execute("UPDATE runtime_events SET event_hash = ? WHERE sequence = 2", ("f" * 64,))
    connection.commit()
    connection.close()

    legacy = module.RuntimeStore(database, auto_migrate=False)
    assert legacy.migration_status()["requires_migration"] is True
    assert legacy.migrate(dry_run=True)["dry_run"] is True
    with pytest.raises(module.RuntimeStoreError, match="rejected by precondition"):
        legacy.migrate()
    failed = legacy.migration_status()
    assert failed["pending"][0]["status"] == "failed"
    connection = sqlite3.connect(database)
    connection.execute("UPDATE runtime_events SET event_hash = ? WHERE sequence = 2", (original_hash,))
    connection.execute(
        "UPDATE runtime_migrations SET status = 'started', completed_at = NULL, error_ref = NULL "
        "WHERE migration_id = ?",
        (module.MIGRATION_REGISTRY[1]["migration_id"],),
    )
    connection.commit()
    connection.close()
    resumed = legacy.migrate()
    assert resumed["current_version"] == module.DATABASE_SCHEMA_VERSION
    assert resumed["applied"][0]["status"] == "applied"
    assert legacy.state("run-1")["status"] == "paused"
    assert legacy.migrate()["applied"][0]["status"] == "applied"
    legacy.close()
    with module.RuntimeStore(database, auto_migrate=False) as reopened:
        assert reopened.state("run-1")["status"] == "paused"


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
    lease_generation = claimed[0]["lease_generation"]
    with pytest.raises(module.RuntimeStoreError, match="not allowed in durable state"):
        store.acknowledge_outbox(
            effect_id,
            "worker-a",
            {"status": "succeeded", "response_body": "raw provider body"},
            lease_generation=lease_generation,
        )
    receipt = {
        "status": "succeeded",
        "provider_request_id": "provider:req-123",
        "result_ref": "sha256:" + "a" * 64,
    }
    assert store.acknowledge_outbox(
        effect_id,
        "worker-a",
        receipt,
        lease_generation=lease_generation,
        received_at="2026-08-04T08:10:01Z",
    ) == receipt
    assert store.record_inbox(effect_id, receipt, received_at="2026-08-04T08:10:02Z") == receipt
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
    with module.RuntimeStore(database) as reopened, pytest.raises(
        module.RuntimeStoreError, match="outbox effect hash mismatch"
    ):
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
        lease_generation=reclaimed[0]["lease_generation"],
        error_ref="sha256:" + "b" * 64,
        retryable=True,
        next_attempt_at="2026-08-04T08:11:00Z",
        now="2026-08-04T08:10:12Z",
    )
    assert retried["status"] == "retry"
    claimed = store.claim_outbox("worker-c", now="2026-08-04T08:11:00Z", lease_seconds=10)
    dead_lettered = store.fail_outbox(
        effect_id,
        "worker-c",
        lease_generation=claimed[0]["lease_generation"],
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


def test_heartbeat_extends_current_lease_with_pinned_policy_and_evidence(tmp_path):
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
    claimed = store.claim_outbox(
        "worker-a",
        now="2026-08-04T08:10:00Z",
        lease_seconds=10,
        max_lease_seconds=30,
        heartbeat_seconds=8,
        policy_revisions={
            "lease": "lease-v2",
            "heartbeat": "heartbeat-v2",
            "activity_timeout": "timeout-v2",
            "cancellation": "cancel-v2",
            "retry": "retry-v2",
        },
    )
    assert claimed[0]["lease_generation"] == 1
    assert claimed[0]["lease"]["deadline_at"] == "2026-08-04T08:10:30.000Z"
    assert claimed[0]["lease"]["policy_revisions"]["heartbeat"] == "heartbeat-v2"

    heartbeated = store.heartbeat_outbox(
        effect_id,
        "worker-a",
        lease_generation=1,
        now="2026-08-04T08:10:05Z",
    )
    assert heartbeated["lease"]["expires_at"] == "2026-08-04T08:10:13.000Z"
    assert heartbeated["lease"]["last_heartbeat_at"] == "2026-08-04T08:10:05.000Z"
    assert heartbeated["lease"]["heartbeat_count"] == 1
    store.heartbeat_outbox(effect_id, "worker-a", lease_generation=1, now="2026-08-04T08:10:10Z")
    store.heartbeat_outbox(effect_id, "worker-a", lease_generation=1, now="2026-08-04T08:10:16Z")
    bounded = store.heartbeat_outbox(effect_id, "worker-a", lease_generation=1, now="2026-08-04T08:10:22Z")
    assert bounded["lease"]["expires_at"] == "2026-08-04T08:10:30.000Z"
    assert bounded["lease"]["heartbeat_count"] == 4
    context = store.authorize_outbox_effect(
        effect_id,
        "worker-a",
        lease_generation=1,
        now="2026-08-04T08:10:06Z",
    )
    assert context == {
        "effect_id": effect_id,
        "idempotency_key": "forge-effect:" + effect_id,
        "worker_id": "worker-a",
        "lease_generation": 1,
        "lease_expires_at": "2026-08-04T08:10:30.000Z",
        "lease_deadline_at": "2026-08-04T08:10:30.000Z",
    }
    assert [event["event_type"] for event in store.lease_events(effect_id)] == [
        "claimed",
        "heartbeat",
        "heartbeat",
        "heartbeat",
        "heartbeat",
    ]
    with pytest.raises(module.RuntimeStoreError, match="lease generation mismatch"):
        store.heartbeat_outbox(effect_id, "worker-a", lease_generation=2, now="2026-08-04T08:10:07Z")
    with module.RuntimeStore(tmp_path / "runtime.sqlite3") as reopened:
        persisted = reopened.list_outbox("run-1")[0]
        assert persisted["lease_generation"] == 1
        assert persisted["lease"]["last_heartbeat_at"] == "2026-08-04T08:10:22.000Z"
        assert persisted["lease"]["policy_revisions"] == {
            "lease": "lease-v2",
            "heartbeat": "heartbeat-v2",
            "activity_timeout": "timeout-v2",
            "cancellation": "cancel-v2",
            "retry": "retry-v2",
        }


def test_reclaim_advances_generation_and_fences_stale_same_worker(tmp_path):
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
    first = store.claim_outbox(
        "worker-a",
        now="2026-08-04T08:10:00Z",
        lease_seconds=10,
        max_lease_seconds=20,
        heartbeat_seconds=5,
    )[0]
    second = store.claim_outbox(
        "worker-a",
        now="2026-08-04T08:10:11Z",
        lease_seconds=10,
        max_lease_seconds=20,
        heartbeat_seconds=5,
    )[0]
    assert first["lease_generation"] == 1
    assert second["lease_generation"] == 2
    with pytest.raises(module.RuntimeStoreError, match="lease generation mismatch"):
        store.authorize_outbox_effect(effect_id, "worker-a", lease_generation=1, now="2026-08-04T08:10:12Z")
    with pytest.raises(module.RuntimeStoreError, match="lease generation mismatch"):
        store.heartbeat_outbox(effect_id, "worker-a", lease_generation=1, now="2026-08-04T08:10:12Z")
    with pytest.raises(module.RuntimeStoreError, match="lease generation mismatch"):
        store.fail_outbox(
            effect_id,
            "worker-a",
            lease_generation=1,
            error_ref="sha256:" + "d" * 64,
            retryable=True,
            now="2026-08-04T08:10:12Z",
        )
    receipt = {"status": "succeeded", "provider_request_id": "provider:req-1"}
    assert store.acknowledge_outbox(
        effect_id,
        "worker-a",
        receipt,
        lease_generation=2,
        received_at="2026-08-04T08:10:13Z",
    ) == receipt
    assert [event["event_type"] for event in store.lease_events(effect_id)] == [
        "claimed",
        "lease_lost",
        "claimed",
    ]


def test_heartbeat_and_reclaim_have_one_serialized_owner_outcome(tmp_path):
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
    claimed = store.claim_outbox(
        "worker-a",
        now="2026-08-04T08:10:00Z",
        lease_seconds=10,
        max_lease_seconds=30,
        heartbeat_seconds=8,
    )[0]
    store.close()

    def heartbeat():
        with module.RuntimeStore(database) as worker:
            try:
                return ("heartbeat", worker.heartbeat_outbox(
                    claimed["effect_id"],
                    "worker-a",
                    lease_generation=claimed["lease_generation"],
                    now="2026-08-04T08:10:09Z",
                ))
            except module.RuntimeStoreError as exc:
                return ("heartbeat-error", str(exc))

    def reclaim():
        with module.RuntimeStore(database) as worker:
            try:
                return ("reclaim", worker.claim_outbox(
                    "worker-b",
                    now="2026-08-04T08:10:11Z",
                    lease_seconds=10,
                    max_lease_seconds=30,
                    heartbeat_seconds=8,
                ))
            except module.RuntimeStoreError as exc:
                return ("reclaim-error", str(exc))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(lambda operation: operation(), (heartbeat, reclaim))
    outcomes = {first[0], second[0]}
    assert outcomes in ({"heartbeat", "reclaim"}, {"heartbeat-error", "reclaim"})
    with module.RuntimeStore(database) as reopened:
        current = reopened.list_outbox("run-1")[0]
        if current["lease_generation"] == 1:
            assert current["lease"]["expires_at"] == "2026-08-04T08:10:17.000Z"
        else:
            assert current["lease_generation"] == 2
            assert current["lease"]["owner"] == "worker-b"


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
