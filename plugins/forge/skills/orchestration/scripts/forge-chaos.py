#!/usr/bin/env python3
"""Run deterministic, digest-only Forge runtime schedules across backends."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import random
import sqlite3
import re
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CONTRACT_REVISION = "forge-chaos-v1"
BASE_TIME = datetime(2026, 8, 6, tzinfo=timezone.utc)
CORPUS_SEEDS = (6601, 6602, 6603)
BACKENDS = ("sqlite", "memory", "etcd")
ACTION_KINDS = {
    "start_run",
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
    "expect_state",
}
COMMIT_POINTS = {"append.before_commit", "append.after_commit"}
ACTION_CAPABILITIES = {
    "cursor_gap": {"remote_revisions", "watch_delivery"},
    "compaction_recovery": {"remote_revisions", "watch_delivery", "snapshot_recovery", "compaction_recovery"},
}
ACTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
REFERENCE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
FORBIDDEN_KEYS = {
    "arguments",
    "body",
    "content",
    "output",
    "password",
    "prompt",
    "raw",
    "response",
    "secret",
    "token",
    "tool_argument",
    "tool_args",
    "tool_input",
    "tool_output",
    "tool_result",
    "provider_response",
    "provider_response_body",
}


class ChaosError(ValueError):
    """Raised when a schedule or harness contract is invalid."""


class ChaosInvariantError(RuntimeError):
    """Raised when a runtime invariant is violated by a backend."""

    def __init__(self, failure_class: str, message: str) -> None:
        super().__init__(message)
        self.failure_class = failure_class


def _load_backends() -> Any:
    path = Path(__file__).with_name("forge-backends.py")
    spec = importlib.util.spec_from_file_location("forge_chaos_backends", path)
    if spec is None or spec.loader is None:
        raise ChaosError(f"cannot load backend adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


backends = _load_backends()
runtime = backends.runtime
distributed = backends.distributed


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _error_ref(error: BaseException | str) -> str:
    return digest({"type": type(error).__name__ if isinstance(error, BaseException) else "error", "message": str(error)})


def _reference(value: Any, field: str) -> str:
    if not isinstance(value, str) or not REFERENCE_RE.fullmatch(value):
        raise ChaosError(f"{field} must be a sha256 reference")
    return value


def _reject_forbidden(value: Any, path: str = "schedule") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ChaosError(f"{path}.{key} is not allowed in digest-only schedules")
            _reject_forbidden(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden(nested, f"{path}[{index}]")


def _schedule_body(schedule: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in schedule.items() if key != "schedule_ref"}


def _validate_action(action: Any, index: int) -> dict[str, Any]:
    if not isinstance(action, Mapping):
        raise ChaosError(f"actions[{index}] must be an object")
    normalized = dict(action)
    allowed = {"action_id", "kind", "run_id", "point", "expected_status"}
    unknown = sorted(set(normalized) - allowed)
    if unknown:
        raise ChaosError(f"actions[{index}] contains unsupported fields: {', '.join(unknown)}")
    action_id = normalized.get("action_id")
    if not isinstance(action_id, str) or not ACTION_ID_RE.fullmatch(action_id):
        raise ChaosError(f"actions[{index}].action_id is invalid")
    kind = normalized.get("kind")
    if kind not in ACTION_KINDS:
        raise ChaosError(f"actions[{index}].kind is unsupported: {kind}")
    run_id = normalized.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ChaosError(f"actions[{index}].run_id is invalid")
    if kind == "commit_crash":
        if normalized.get("point") not in COMMIT_POINTS:
            raise ChaosError(f"actions[{index}].point must be a supported commit fault")
    elif "point" in normalized:
        raise ChaosError(f"actions[{index}].point is only valid for commit_crash")
    if kind == "expect_state":
        if normalized.get("expected_status") not in {"running", "paused", "input_required", "cancelling", "completed", "failed", "cancelled"}:
            raise ChaosError(f"actions[{index}].expected_status is invalid")
    elif "expected_status" in normalized:
        raise ChaosError(f"actions[{index}].expected_status is only valid for expect_state")
    return normalized


def validate_schedule(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ChaosError("schedule must be an object")
    schedule = dict(value)
    _reject_forbidden(schedule)
    allowed = {"schema_version", "contract_revision", "seed", "actions", "expected_failure", "schedule_ref"}
    unknown = sorted(set(schedule) - allowed)
    if unknown:
        raise ChaosError("schedule contains unsupported fields: " + ", ".join(unknown))
    if schedule.get("schema_version") != SCHEMA_VERSION:
        raise ChaosError(f"unsupported schedule schema: {schedule.get('schema_version')}")
    if schedule.get("contract_revision") != CONTRACT_REVISION:
        raise ChaosError("unsupported chaos contract revision")
    seed = schedule.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 or seed > 2**63 - 1:
        raise ChaosError("seed must be an unsigned 63-bit integer")
    actions = schedule.get("actions")
    if not isinstance(actions, list) or not actions or len(actions) > 128:
        raise ChaosError("actions must contain between 1 and 128 entries")
    normalized_actions = [_validate_action(action, index) for index, action in enumerate(actions)]
    action_ids = [action["action_id"] for action in normalized_actions]
    if len(set(action_ids)) != len(action_ids):
        raise ChaosError("action_id values must be unique")
    expected_failure = schedule.get("expected_failure")
    if expected_failure is not None:
        if not isinstance(expected_failure, Mapping):
            raise ChaosError("expected_failure must be an object")
        expected_failure = dict(expected_failure)
        if set(expected_failure) - {"backend", "failure_class"}:
            raise ChaosError("expected_failure contains unsupported fields")
        if expected_failure.get("backend") not in (*BACKENDS, None):
            raise ChaosError("expected_failure.backend is unsupported")
        if "failure_class" in expected_failure and (
            not isinstance(expected_failure["failure_class"], str) or not expected_failure["failure_class"]
        ):
            raise ChaosError("expected_failure.failure_class must be a non-empty string")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "seed": seed,
        "actions": normalized_actions,
    }
    if expected_failure is not None:
        normalized["expected_failure"] = expected_failure
    expected_ref = digest(normalized)
    if schedule.get("schedule_ref") != expected_ref:
        raise ChaosError("schedule_ref does not match canonical schedule content")
    normalized["schedule_ref"] = expected_ref
    return normalized


def make_schedule(
    seed: int,
    actions: list[Mapping[str, Any]],
    *,
    expected_failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    schedule: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "seed": seed,
        "actions": [dict(action) for action in actions],
    }
    if expected_failure is not None:
        schedule["expected_failure"] = dict(expected_failure)
    schedule["schedule_ref"] = digest(_schedule_body(schedule))
    return validate_schedule(schedule)


def generate_schedule(seed: int, *, length: int | None = None) -> dict[str, Any]:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 or seed > 2**63 - 1:
        raise ChaosError("seed must be an unsigned 63-bit integer")
    actions: list[dict[str, Any]] = [
        {"action_id": "a01-start", "kind": "start_run", "run_id": "chaos-start"},
        {
            "action_id": "a02-pre-commit-crash",
            "kind": "commit_crash",
            "run_id": "chaos-pre-commit",
            "point": "append.before_commit",
        },
        {
            "action_id": "a03-post-commit-crash",
            "kind": "commit_crash",
            "run_id": "chaos-ambiguous-commit",
            "point": "append.after_commit",
        },
        {"action_id": "a04-duplicate", "kind": "duplicate_delivery", "run_id": "chaos-duplicate"},
        {"action_id": "a05-stale-worker", "kind": "stale_worker_mutation", "run_id": "chaos-fencing"},
        {"action_id": "a06-wait-signal", "kind": "wait_signal_race", "run_id": "chaos-wait"},
        {"action_id": "a07-cancel", "kind": "cancel_race", "run_id": "chaos-cancel"},
        {
            "action_id": "a08-checkpoint-corruption",
            "kind": "checkpoint_corruption",
            "run_id": "chaos-checkpoint",
        },
        {"action_id": "a09-provider-timeout", "kind": "provider_timeout", "run_id": "chaos-timeout"},
        {"action_id": "a10-privacy", "kind": "privacy_probe", "run_id": "chaos-privacy"},
        {"action_id": "a11-cursor-gap", "kind": "cursor_gap", "run_id": "chaos-cursor"},
        {
            "action_id": "a12-compaction",
            "kind": "compaction_recovery",
            "run_id": "chaos-compaction",
        },
        {"action_id": "a13-replay", "kind": "verify_replay", "run_id": "chaos-replay"},
    ]
    randomizer = random.Random(seed)
    randomizer.shuffle(actions)
    if length is not None:
        if isinstance(length, bool) or not isinstance(length, int) or length < 1 or length > len(actions):
            raise ChaosError(f"length must be between 1 and {len(actions)}")
        actions = actions[:length]
    return make_schedule(seed, actions)


def _at(action_index: int, offset_seconds: int = 0) -> str:
    value = BASE_TIME + timedelta(seconds=action_index * 100 + offset_seconds)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _ref(char: str) -> str:
    return "sha256:" + char * 64


def _effect() -> dict[str, Any]:
    return {
        "effect_type": "chaos.effect",
        "task_id": "build",
        "activity_id": "chaos-activity",
        "attempt": 1,
        "effect_definition_revision": "effect-v1",
        "payload": {"target_ref": "fixture:target", "request_digest": _ref("a")},
    }


def _start(adapter: Any, run_id: str, action_index: int) -> dict[str, Any]:
    return adapter.start_run(
        run_id,
        "chaos-flow",
        "definition-v1",
        "policy-v1",
        occurred_at=_at(action_index),
    )


def _schedule(adapter: Any, run_id: str, action_index: int, *, effect: bool = False) -> dict[str, Any]:
    return adapter.append_event(
        run_id,
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
        idempotency_key=f"{run_id}:task-build-scheduled",
        occurred_at=_at(action_index, 1),
        effect=_effect() if effect else None,
    )


def _prepare_task(adapter: Any, run_id: str, action_index: int) -> None:
    _start(adapter, run_id, action_index)
    _schedule(adapter, run_id, action_index)
    adapter.append_event(
        run_id,
        "task.started",
        {"task_id": "build", "attempt": 1},
        idempotency_key=f"{run_id}:task-build-started",
        occurred_at=_at(action_index, 2),
    )


def _prepare_wait(adapter: Any, run_id: str, action_index: int) -> dict[str, Any]:
    _prepare_task(adapter, run_id, action_index)
    return adapter.create_wait(
        run_id,
        "build",
        _ref("b"),
        _ref("c"),
        wait_id=f"{run_id}:wait",
        resume_contract="workflow-v1",
        ttl_seconds=60,
        poll_interval_ms=1000,
        occurred_at=_at(action_index, 3),
    )


def _assert(condition: bool, failure_class: str, message: str) -> None:
    if not condition:
        raise ChaosInvariantError(failure_class, message)


def _handle_start(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    run_id = str(action["run_id"])
    event = _start(adapter, run_id, index)
    context.add(run_id)
    history = adapter.history(run_id)
    _assert(len(history) == 1, "append_ordering", "start event did not create one canonical history row")
    return {"outcome": "accepted", "event_ref": _ref(event["event_hash"][:1]), "history_digest": digest(history)}


def _handle_commit_crash(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    run_id = str(action["run_id"])
    point = str(action["point"])
    _start(adapter, run_id, index)
    context.add(run_id)
    adapter.fail_next(point)
    fault_seen = False
    try:
        _schedule(adapter, run_id, index, effect=True)
    except backends.BackendFault:
        fault_seen = True
    _assert(fault_seen, "fault_injection", "configured commit fault was not observed")
    history = adapter.history(run_id)
    outbox = adapter.list_outbox(run_id)
    if point == "append.before_commit":
        _assert(len(history) == 1 and not outbox, "atomic_event_effect", "pre-commit crash left durable state")
        classification = "pre_commit_crash"
    else:
        _assert(len(history) == 2 and len(outbox) == 1, "ambiguous_commit", "post-commit crash lost event or effect")
        classification = "ambiguous_commit"
    retry = _schedule(adapter, run_id, index, effect=True)
    _assert(len(adapter.history(run_id)) == 2, classification, "retry changed canonical history after recovery")
    _assert(len(adapter.list_outbox(run_id)) == 1, "atomic_event_effect", "retry duplicated the effect intent")
    return {
        "outcome": "recovered",
        "failure_class": classification,
        "event_ref": _ref(retry["event_hash"][:1]),
        "history_digest": digest(adapter.history(run_id)),
        "receipt_digest": digest(adapter.list_outbox(run_id)),
    }


def _handle_duplicate(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    run_id = str(action["run_id"])
    _start(adapter, run_id, index)
    _schedule(adapter, run_id, index, effect=True)
    context.add(run_id)
    effect_id = adapter.list_outbox(run_id)[0]["effect_id"]
    claim = adapter.claim_outbox("worker-a", run_id=run_id, now=_at(index, 3), lease_seconds=30)[0]
    receipt = {"status": "succeeded", "provider_request_id": "chaos:req", "result_ref": _ref("d")}
    adapter.acknowledge_outbox(
        effect_id,
        "worker-a",
        receipt,
        lease_generation=claim["lease_generation"],
        received_at=_at(index, 4),
    )
    duplicate = adapter.record_inbox(effect_id, receipt, received_at=_at(index, 5))
    _assert(duplicate == receipt, "duplicate_acceptance", "duplicate delivery changed the original receipt")
    _assert(len(adapter.list_inbox(run_id)) == 1, "duplicate_acceptance", "duplicate delivery created another inbox row")
    return {"outcome": "deduplicated", "receipt_digest": digest(receipt), "effect_ref": _ref(effect_id[:1])}


def _handle_stale_worker(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    run_id = str(action["run_id"])
    _start(adapter, run_id, index)
    _schedule(adapter, run_id, index, effect=True)
    context.add(run_id)
    effect_id = adapter.list_outbox(run_id)[0]["effect_id"]
    first = adapter.claim_outbox("worker-a", run_id=run_id, now=_at(index, 3), lease_seconds=5)[0]
    second = adapter.claim_outbox("worker-b", run_id=run_id, now=_at(index, 10), lease_seconds=5)[0]
    _assert(second["lease_generation"] > first["lease_generation"], "fencing", "lease reclaim did not advance generation")
    before = digest({"outbox": adapter.list_outbox(run_id), "leases": adapter.runtime.lease_events(effect_id)})
    rejected = False
    try:
        adapter.heartbeat_outbox(
            effect_id,
            "worker-a",
            lease_generation=first["lease_generation"],
            now=_at(index, 11),
        )
    except runtime.RuntimeStoreError:
        rejected = True
    after = digest({"outbox": adapter.list_outbox(run_id), "leases": adapter.runtime.lease_events(effect_id)})
    _assert(rejected, "stale_mutation", "stale worker heartbeat was accepted")
    _assert(before == after, "stale_mutation", "rejected stale worker mutated lease state")
    current = adapter.list_outbox(run_id)[0]
    _assert(current["lease_owner"] == "worker-b", "fencing", "stale worker replaced the current lease owner")
    return {"outcome": "fenced", "lease_generation": second["lease_generation"], "lease_digest": after}


def _handle_wait_signal(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    run_id = str(action["run_id"])
    wait = _prepare_wait(adapter, run_id, index)
    context.add(run_id)
    signal = adapter.runtime.receive_signal(
        run_id,
        f"{run_id}:signal",
        "notify",
        _ref("e"),
        _ref("c"),
        wait_id=wait["payload"]["wait_id"],
        occurred_at=_at(index, 4),
    )
    submission = adapter.runtime.submit_input(
        run_id,
        wait["payload"]["wait_id"],
        f"{run_id}:submission",
        _ref("f"),
        _ref("c"),
        input_schema_digest=_ref("b"),
        occurred_at=_at(index, 5),
    )
    state = adapter.state(run_id)
    _assert(signal["event_type"] == "signal.received", "wait_signal_race", "signal was not recorded")
    _assert(submission["event_type"] == "wait.input_submitted", "wait_signal_race", "input was not recorded")
    _assert(state["waits"][wait["payload"]["wait_id"]]["status"] == "submitted", "lost_cancellation", "wait did not resume after signal/input race")
    return {"outcome": "resumed", "history_digest": digest(adapter.history(run_id)), "state_digest": digest(state)}


def _handle_cancel(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    run_id = str(action["run_id"])
    wait = _prepare_wait(adapter, run_id, index)
    context.add(run_id)
    auth = _ref("c")
    adapter.runtime.request_cancel(
        run_id,
        reason_ref=_ref("1"),
        authorization_context_digest=auth,
        occurred_at=_at(index, 4),
    )
    adapter.runtime.acknowledge_cancel(
        run_id,
        ack_ref=_ref("2"),
        authorization_context_digest=auth,
        occurred_at=_at(index, 5),
    )
    adapter.runtime.cancel_run(run_id, occurred_at=_at(index, 6))
    state = adapter.state(run_id)
    wait_state = state["waits"][wait["payload"]["wait_id"]]
    _assert(state["status"] == "cancelled", "lost_cancellation", "cancellation did not reach terminal state")
    _assert(wait_state["status"] == "cancelled", "lost_cancellation", "cancellation did not close the active wait")
    return {"outcome": "cancelled", "history_digest": digest(adapter.history(run_id)), "state_digest": digest(state)}


def _handle_checkpoint_corruption(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    run_id = str(action["run_id"])
    _prepare_task(adapter, run_id, index)
    checkpoint = adapter.checkpoint_run(run_id, created_at=_at(index, 3))
    adapter.append_event(
        run_id,
        "task.completed",
        {"task_id": "build", "output_ref": _ref("7")},
        idempotency_key=f"{run_id}:task-build-completed",
        occurred_at=_at(index, 4),
    )
    context.add(run_id)
    adapter.runtime.connection.execute(
        "UPDATE runtime_checkpoints SET state_json = ? WHERE checkpoint_id = ?",
        (canonical_json({"state_ref": _ref("8")}), checkpoint["checkpoint_id"]),
    )
    restored = adapter.restore_state(run_id)
    _assert(restored["recovered"] is True, "checkpoint_recovery", "corrupt checkpoint was accepted")
    _assert(restored["state"] == adapter.state(run_id), "broken_replay", "checkpoint recovery diverged from full replay")
    return {"outcome": "recovered", "checkpoint_ref": _ref(checkpoint["checkpoint_id"][:1]), "state_digest": digest(restored["state"])}


def _handle_provider_timeout(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    run_id = str(action["run_id"])
    _start(adapter, run_id, index)
    _schedule(adapter, run_id, index, effect=True)
    context.add(run_id)
    effect_id = adapter.list_outbox(run_id)[0]["effect_id"]
    claim = adapter.claim_outbox("worker-a", run_id=run_id, now=_at(index, 3), lease_seconds=5)[0]
    retry = adapter.runtime.fail_outbox(
        effect_id,
        "worker-a",
        lease_generation=claim["lease_generation"],
        error_ref=_ref("9"),
        retryable=True,
        next_attempt_at=_at(index, 20),
        now=_at(index, 6),
    )
    _assert(retry["status"] == "retry", "provider_timeout", "provider timeout did not become retryable")
    reclaimed = adapter.claim_outbox("worker-b", run_id=run_id, now=_at(index, 21), lease_seconds=5)[0]
    _assert(reclaimed["delivery_attempts"] == 2, "provider_timeout", "retry did not create a new delivery attempt")
    return {"outcome": "retryable", "attempt": reclaimed["delivery_attempts"], "effect_ref": _ref(effect_id[:1])}


def _handle_privacy(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    run_id = str(action["run_id"])
    _start(adapter, run_id, index)
    context.add(run_id)
    rejected = False
    try:
        adapter.append_event(
            run_id,
            "task.scheduled",
            {"task_id": "private", "depends_on": [], "prompt": "sentinel-never-persist"},
            idempotency_key=f"{run_id}:private",
            occurred_at=_at(index, 1),
        )
    except runtime.RuntimeStoreError:
        rejected = True
    _assert(rejected, "privacy_leakage", "raw content crossed the durable state boundary")
    history = adapter.history(run_id)
    _assert(len(history) == 1, "privacy_leakage", "privacy probe changed canonical history")
    return {"outcome": "rejected", "privacy_evidence_digest": digest(history)}


def _watch_reference(char: str) -> str:
    return _ref(char)


def _publish_watch(adapter: Any, number: int, *, revision: int | None = None) -> dict[str, Any]:
    return adapter.watch.publish(
        event_ref=_watch_reference(str(number % 10)),
        transaction_ref=_watch_reference(str((number + 1) % 10)),
        cloud_event={
            "source": "urn:forge:chaos",
            "id": f"chaos-event-{number}",
            "type": "com.forge.runtime.chaos.v1",
            "time": _at(number),
            "data_ref": _watch_reference(str((number + 2) % 10)),
        },
        remote_revision=revision,
    )


def _require_watch(adapter: Any) -> Any:
    if not hasattr(adapter, "watch"):
        raise ChaosError("watch action requires an etcd adapter")
    adapter.watch = distributed.RevisionWatchAdapter(provider="etcd")
    return adapter.watch


def _handle_cursor_gap(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    watch = _require_watch(adapter)
    _publish_watch(adapter, 1, revision=1)
    third = _publish_watch(adapter, 3, revision=3)
    cursor = {"watch_id": watch.watch_id, "remote_revision": 0, "compaction_revision": 0}
    try:
        adapter.observe_watch([third], cursor)
    except distributed.DistributedRecoveryError as error:
        _assert(error.reason_code == "cursor_gap", "cursor_gap", "cursor gap was misclassified")
        return {"outcome": "rejected", "failure_class": "cursor_gap", "evidence_digest": digest(error.evidence)}
    raise ChaosInvariantError("cursor_gap", "cursor gap was accepted")


def _handle_compaction(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    watch = _require_watch(adapter)
    _publish_watch(adapter, 1, revision=1)
    snapshot = adapter.watch.snapshot(state_ref=_watch_reference("a"))
    second = _publish_watch(adapter, 2, revision=2)
    adapter.watch.compact(1)
    cursor = {"watch_id": watch.watch_id, "remote_revision": 0, "compaction_revision": 0}
    try:
        adapter.observe_watch([second], cursor)
    except distributed.DistributedRecoveryError as error:
        _assert(error.reason_code == "compaction_required", "compaction_recovery", "compaction boundary was misclassified")
    else:
        raise ChaosInvariantError("compaction_recovery", "stale cursor crossed the compaction boundary")
    recovered = adapter.recover_watch(snapshot=snapshot, replay_notifications=[second])
    _assert(recovered["status"] == "recovered", "compaction_recovery", "snapshot replay did not recover the watch")
    return {
        "outcome": "recovered",
        "snapshot_ref": recovered["snapshot_ref"],
        "cursor_ref": recovered["cursor"]["cursor_ref"],
        "evidence_digest": recovered["evidence_digest"],
    }


def _handle_replay(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    run_id = str(action["run_id"])
    _prepare_task(adapter, run_id, index)
    adapter.checkpoint_run(run_id, created_at=_at(index, 3))
    adapter.append_event(
        run_id,
        "task.completed",
        {"task_id": "build", "output_ref": _ref("b")},
        idempotency_key=f"{run_id}:task-build-completed",
        occurred_at=_at(index, 4),
    )
    context.add(run_id)
    full_state = adapter.state(run_id)
    restored = adapter.restore_state(run_id)
    _assert(restored["state"] == full_state, "broken_replay", "suffix replay diverged from full replay")
    _assert([row["sequence"] for row in adapter.history(run_id)] == list(range(1, len(adapter.history(run_id)) + 1)), "append_ordering", "history sequence is not contiguous")
    return {"outcome": "verified", "history_digest": digest(adapter.history(run_id)), "state_digest": digest(full_state)}


def _handle_expect_state(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    run_id = str(action["run_id"])
    state = adapter.state(run_id)
    context.add(run_id)
    if state["status"] != action["expected_status"]:
        raise ChaosInvariantError(
            "terminal_outcome_mismatch",
            f"expected {action['expected_status']}, observed {state['status']}",
        )
    return {"outcome": "matched", "state_digest": digest(state)}


HANDLERS = {
    "start_run": _handle_start,
    "commit_crash": _handle_commit_crash,
    "duplicate_delivery": _handle_duplicate,
    "stale_worker_mutation": _handle_stale_worker,
    "wait_signal_race": _handle_wait_signal,
    "cancel_race": _handle_cancel,
    "checkpoint_corruption": _handle_checkpoint_corruption,
    "provider_timeout": _handle_provider_timeout,
    "privacy_probe": _handle_privacy,
    "cursor_gap": _handle_cursor_gap,
    "compaction_recovery": _handle_compaction,
    "verify_replay": _handle_replay,
    "expect_state": _handle_expect_state,
}


def _action_result(
    action: Mapping[str, Any],
    *,
    status: str,
    outcome: str,
    evidence: Mapping[str, Any] | None = None,
    error: BaseException | str | None = None,
    failure_class: str | None = None,
) -> dict[str, Any]:
    return {
        "action_id": action["action_id"],
        "kind": action["kind"],
        "status": status,
        "outcome": outcome,
        "failure_class": failure_class,
        "error_ref": _error_ref(error) if error is not None else None,
        "evidence_digest": digest(evidence or {}) if evidence is not None else None,
    }


def _execute_action(adapter: Any, action: Mapping[str, Any], index: int, context: set[str]) -> dict[str, Any]:
    required = ACTION_CAPABILITIES.get(str(action["kind"]), set())
    missing = sorted(required - set(adapter.descriptor["capabilities"]))
    if missing:
        return _action_result(
            action,
            status="unsupported",
            outcome="unsupported",
            evidence={"missing_capabilities": missing},
        )
    try:
        evidence = HANDLERS[str(action["kind"])](adapter, action, index, context)
    except ChaosInvariantError as error:
        return _action_result(
            action,
            status="failed",
            outcome="invariant_violation",
            error=error,
            failure_class=error.failure_class,
        )
    except (
        backends.BackendContractError,
        backends.BackendFault,
        distributed.DistributedRecoveryError,
        runtime.RuntimeStoreError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        sqlite3.Error,
    ) as error:  # pragma: no cover - classification protects CLI callers
        return _action_result(
            action,
            status="failed",
            outcome="backend_error",
            error=error,
            failure_class="backend_contract_error",
        )
    return _action_result(
        action,
        status="passed",
        outcome=str(evidence.get("outcome", "accepted")),
        evidence=evidence,
        failure_class=evidence.get("failure_class"),
    )


def _canonical_projection(adapter: Any, action_results: list[Mapping[str, Any]], run_ids: set[str]) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for run_id in sorted(run_ids):
        history = adapter.history(run_id)
        state = adapter.state(run_id)
        outbox = adapter.list_outbox(run_id)
        inbox = adapter.list_inbox(run_id)
        runs.append(
            {
                "run_id": run_id,
                "history_digest": digest(history),
                "state_digest": digest(state),
                "receipt_digest": digest(inbox),
                "effect_digest": digest(outbox),
                "status": state["status"],
            }
        )
    return {
        "actions": [
            {
                "action_id": item["action_id"],
                "kind": item["kind"],
                "status": item["status"],
                "outcome": item["outcome"],
                "failure_class": item["failure_class"],
                "evidence_digest": item["evidence_digest"],
            }
            for item in action_results
        ],
        "runs": runs,
        "privacy_evidence": sorted(
            item["evidence_digest"]
            for item in action_results
            if item["kind"] == "privacy_probe" and item["evidence_digest"] is not None
        ),
    }


def run_schedule(schedule: Mapping[str, Any], backend_kind: str) -> dict[str, Any]:
    schedule = validate_schedule(schedule)
    if backend_kind not in BACKENDS:
        raise ChaosError(f"unknown backend: {backend_kind}")
    with tempfile.TemporaryDirectory(prefix="forge-chaos-") as directory:
        path = Path(directory) / "runtime.sqlite3" if backend_kind in {"sqlite", "etcd"} else None
        adapter = backends.make_backend(backend_kind, path)
        try:
            context: set[str] = set()
            action_results = [
                _execute_action(adapter, action, index, context)
                for index, action in enumerate(schedule["actions"])
            ]
            projection = _canonical_projection(adapter, action_results, context)
            failed = [item for item in action_results if item["status"] == "failed"]
            unsupported = [item for item in action_results if item["status"] == "unsupported"]
            status = "failed" if failed else "degraded" if unsupported else "passed"
            failure_class = failed[0]["failure_class"] if failed else None
            result = {
                "schema_version": SCHEMA_VERSION,
                "contract_revision": CONTRACT_REVISION,
                "schedule_ref": schedule["schedule_ref"],
                "backend": adapter.descriptor,
                "status": status,
                "failure_class": failure_class,
                "actions": action_results,
                "summary": {
                    "total": len(action_results),
                    "passed": sum(item["status"] == "passed" for item in action_results),
                    "unsupported": len(unsupported),
                    "failed": len(failed),
                },
                "canonical": projection,
            }
            result["result_digest"] = digest(result)
            return result
        finally:
            adapter.close()


def compare_results(schedule: Mapping[str, Any], results: list[Mapping[str, Any]]) -> dict[str, Any]:
    schedule = validate_schedule(schedule)
    if not results:
        raise ChaosError("at least one backend result is required")
    mismatches: list[dict[str, Any]] = []
    baseline = results[0]
    baseline_actions = {item["action_id"]: item for item in baseline["canonical"]["actions"]}
    baseline_runs = {item["run_id"]: item for item in baseline["canonical"]["runs"]}
    action_by_id = {item["action_id"]: item for item in schedule["actions"]}
    for candidate in results[1:]:
        candidate_actions = {item["action_id"]: item for item in candidate["canonical"]["actions"]}
        candidate_runs = {item["run_id"]: item for item in candidate["canonical"]["runs"]}
        for action_id, expected in baseline_actions.items():
            actual = candidate_actions.get(action_id)
            if actual is None:
                mismatches.append({"action_id": action_id, "reason_ref": digest({"kind": "missing_action", "backend": candidate["backend"]["backend_id"]})})
                continue
            action = action_by_id[action_id]
            if expected["status"] == "unsupported" or actual["status"] == "unsupported":
                required = ACTION_CAPABILITIES.get(str(action["kind"]), set())
                missing_allowed = required - set(candidate["backend"]["capabilities"])
                if actual["status"] == "unsupported" and missing_allowed:
                    continue
                if expected["status"] == "unsupported" and required - set(baseline["backend"]["capabilities"]):
                    continue
            if (expected["status"], expected["outcome"], expected["failure_class"]) != (
                actual["status"],
                actual["outcome"],
                actual["failure_class"],
            ):
                mismatches.append({"action_id": action_id, "reason_ref": digest({"expected": expected, "actual": actual})})
            if (
                expected["status"] == actual["status"] == "passed"
                and expected["evidence_digest"] != actual["evidence_digest"]
            ):
                mismatches.append({"action_id": action_id, "reason_ref": digest({"kind": "evidence", "expected": expected["evidence_digest"], "actual": actual["evidence_digest"]})})
        for run_id, expected in baseline_runs.items():
            actual = candidate_runs.get(run_id)
            if actual is None:
                mismatches.append({"run_id": run_id, "reason_ref": digest({"kind": "missing_run", "backend": candidate["backend"]["backend_id"]})})
                continue
            for field in ("history_digest", "state_digest", "receipt_digest", "effect_digest", "status"):
                if expected[field] != actual[field]:
                    mismatches.append({"run_id": run_id, "reason_ref": digest({"field": field, "expected": expected[field], "actual": actual[field]})})
    comparison = {
        "status": "failed" if mismatches else "passed",
        "backend_count": len(results),
        "mismatches": mismatches,
        "comparison_digest": digest(
            {
                "schedule_ref": schedule["schedule_ref"],
                "projections": [result["canonical"] for result in results],
            }
        ),
    }
    return comparison


def run_all(schedule: Mapping[str, Any]) -> dict[str, Any]:
    schedule = validate_schedule(schedule)
    results = [run_schedule(schedule, backend) for backend in BACKENDS]
    comparison = compare_results(schedule, results)
    status = "failed" if any(result["status"] == "failed" for result in results) or comparison["status"] == "failed" else "passed"
    output = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "schedule": schedule,
        "status": status,
        "comparison": comparison,
        "results": results,
        "summary": {
            "backends": len(results),
            "passed": sum(result["status"] == "passed" for result in results),
            "degraded": sum(result["status"] == "degraded" for result in results),
            "failed": sum(result["status"] == "failed" for result in results),
        },
    }
    output["result_digest"] = digest(output)
    return output


def _failure_class(result: Mapping[str, Any]) -> str | None:
    if result.get("failure_class"):
        return str(result["failure_class"])
    for action in result.get("actions", []):
        if action.get("status") == "failed" and action.get("failure_class"):
            return str(action["failure_class"])
    return None


def _same_failure(schedule: Mapping[str, Any], backend_kind: str, target_class: str) -> bool:
    result = run_schedule(schedule, backend_kind)
    return result["status"] == "failed" and _failure_class(result) == target_class


def shrink_schedule(schedule: Mapping[str, Any], backend_kind: str) -> dict[str, Any]:
    schedule = validate_schedule(schedule)
    original_result = run_schedule(schedule, backend_kind)
    target_class = _failure_class(original_result)
    if original_result["status"] != "failed" or target_class is None:
        raise ChaosError("schedule does not produce a classified failure")
    actions = list(schedule["actions"])
    granularity = 2
    while len(actions) > 1:
        chunk_size = max(1, (len(actions) + granularity - 1) // granularity)
        removed = False
        for start in range(0, len(actions), chunk_size):
            candidate_actions = actions[:start] + actions[start + chunk_size :]
            if not candidate_actions:
                continue
            candidate = make_schedule(schedule["seed"], candidate_actions, expected_failure=schedule.get("expected_failure"))
            if _same_failure(candidate, backend_kind, target_class):
                actions = candidate_actions
                granularity = max(2, granularity - 1)
                removed = True
                break
        if not removed:
            if granularity >= len(actions):
                break
            granularity = min(len(actions), granularity * 2)
    minimized = make_schedule(schedule["seed"], actions, expected_failure=schedule.get("expected_failure"))
    minimized_result = run_schedule(minimized, backend_kind)
    output = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "backend": backend_kind,
        "original_schedule_ref": schedule["schedule_ref"],
        "original_result_digest": original_result["result_digest"],
        "failure_class": target_class,
        "minimized_schedule": minimized,
        "minimized_result_digest": minimized_result["result_digest"],
        "removed_action_count": len(schedule["actions"]) - len(actions),
    }
    output["shrink_ref"] = digest(output)
    return output


def inspect_schedule(schedule: Mapping[str, Any]) -> dict[str, Any]:
    schedule = validate_schedule(schedule)
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "schedule_ref": schedule["schedule_ref"],
        "seed": schedule["seed"],
        "action_count": len(schedule["actions"]),
        "action_kinds": sorted({action["kind"] for action in schedule["actions"]}),
        "actions": [
            {key: action[key] for key in ("action_id", "kind", "run_id") if key in action}
            for action in schedule["actions"]
        ],
        "expected_failure": schedule.get("expected_failure"),
        "redaction": "digest-only",
    }


def run_corpus(seeds: tuple[int, ...] = CORPUS_SEEDS) -> dict[str, Any]:
    entries = []
    for seed in seeds:
        schedule = generate_schedule(seed)
        result = run_all(schedule)
        entries.append(
            {
                "seed": seed,
                "schedule_ref": schedule["schedule_ref"],
                "status": result["status"],
                "comparison_digest": result["comparison"]["comparison_digest"],
                "result_digest": result["result_digest"],
            }
        )
    output = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "status": "passed" if all(entry["status"] == "passed" for entry in entries) else "failed",
        "seeds": list(seeds),
        "entries": entries,
        "redaction": "digest-only",
    }
    output["result_digest"] = digest(output)
    return output


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ChaosError(f"cannot read JSON from {path}: {error}") from error


def _write_json(value: Any, path: Path | None) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if path is None:
        print(rendered, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def _schedule_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--schedule", type=Path, help="digest-only schedule JSON")
    parser.add_argument("--seed", type=int, default=6601, help="seed used when --schedule is omitted")


def _load_or_generate(args: argparse.Namespace) -> dict[str, Any]:
    return validate_schedule(_load_json(args.schedule)) if args.schedule else generate_schedule(args.seed)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic, digest-only Forge runtime chaos schedules")
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="generate a seeded schedule")
    generate.add_argument("--seed", type=int, default=6601)
    generate.add_argument("--length", type=int)
    generate.add_argument("--output", type=Path)

    run = sub.add_parser("run", help="run a schedule against one backend or all backends")
    _schedule_argument(run)
    run.add_argument("--backend", choices=[*BACKENDS, "all"], default="all")
    run.add_argument("--output", type=Path)

    replay = sub.add_parser("replay", help="replay a captured schedule offline")
    replay.add_argument("--schedule", type=Path, required=True)
    replay.add_argument("--backend", choices=[*BACKENDS, "all"], default="all")
    replay.add_argument("--output", type=Path)

    shrink = sub.add_parser("shrink", help="delta-debug a classified failing schedule")
    shrink.add_argument("--schedule", type=Path, required=True)
    shrink.add_argument("--backend", choices=BACKENDS, default="memory")
    shrink.add_argument("--output", type=Path)

    inspect = sub.add_parser("inspect", help="inspect schedule metadata without executing it")
    inspect.add_argument("--schedule", type=Path, required=True)
    inspect.add_argument("--output", type=Path)

    corpus = sub.add_parser("corpus", help="run the bounded deterministic CI seed corpus")
    corpus.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "generate":
            _write_json(generate_schedule(args.seed, length=args.length), args.output)
            return 0
        if args.command == "inspect":
            _write_json(inspect_schedule(_load_json(args.schedule)), args.output)
            return 0
        if args.command == "shrink":
            _write_json(shrink_schedule(_load_json(args.schedule), args.backend), args.output)
            return 0
        if args.command == "corpus":
            result = run_corpus()
            _write_json(result, args.output)
            return 0 if result["status"] == "passed" else 1
        schedule = _load_or_generate(args)
        if args.backend == "all":
            result = run_all(schedule)
        else:
            result = run_schedule(schedule, args.backend)
        if args.command == "replay":
            result = {**result, "replayed": True}
            result["result_digest"] = digest(result)
        _write_json(result, args.output)
        return 0 if result["status"] in {"passed", "degraded"} else 1
    except (ChaosError, OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "error_ref": _error_ref(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
