#!/usr/bin/env python3
"""Store local Forge run history and reconstruct state deterministically."""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import re
import sqlite3
import sys
import uuid
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

try:
    from typing import Self
except ImportError:  # pragma: no cover - Python 3.10 and earlier
    Self = Any

SCHEMA_VERSION = 1
EFFECT_SCHEMA_VERSION = 1
LEASE_SCHEMA_VERSION = 1
DATABASE_SCHEMA_VERSION = 3
CHECKPOINT_SCHEMA_VERSION = 1
MIGRATION_SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/_-]{0,127}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
EVENT_TYPES = (
    "run.started",
    "run.paused",
    "run.resumed",
    "run.cancel_requested",
    "run.cancelled",
    "run.completed",
    "run.failed",
    "wait.created",
    "wait.input_submitted",
    "wait.expired",
    "signal.received",
    "cancel.acknowledged",
    "task.scheduled",
    "task.started",
    "task.completed",
    "task.failed",
    "task.cancelled",
)
RUN_TERMINAL = {"completed", "failed", "cancelled"}
TASK_TERMINAL = {"completed", "failed", "cancelled"}
WAIT_STATUSES = {"input_required", "submitted", "expired", "cancel_requested", "cancelled"}
EXPIRATION_OUTCOMES = {"fail_run", "cancel_run"}
SIGNAL_TYPES = {"resume", "notify", "cancel"}
MAX_ACTIVE_WAITS = 1
MAX_SIGNALS_PER_RUN = 256
FORBIDDEN_PAYLOAD_KEYS = {
    "arguments",
    "body",
    "content",
    "output",
    "password",
    "prompt",
    "raw",
    "result",
    "secret",
    "token",
    "tool_argument",
    "tool_args",
    "tool_input",
    "tool_output",
    "tool_result",
    "provider_response",
    "provider_response_body",
    "response",
    "response_body",
}
SENSITIVE_PAYLOAD_PARTS = {"authorization", "credential", "password", "prompt", "secret", "token"}
REFERENCE_PAYLOAD_KEYS = {
    "authorization_context_digest",
    "input_schema_digest",
    "input_digest",
    "payload_digest",
}
EFFECT_STATUSES = {"pending", "leased", "retry", "succeeded", "dead_letter"}
RECEIPT_STATUSES = {"accepted", "succeeded"}
ATTEMPT_OUTCOMES = {"leased", "reclaimed", "succeeded", "retry", "dead_letter"}
LEASE_EVENT_TYPES = {"claimed", "heartbeat", "lease_lost"}
MIGRATION_STATUSES = {"started", "applied", "failed"}
POLICY_REVISION_KEYS = ("lease", "heartbeat", "activity_timeout", "cancellation", "retry")
DEFAULT_POLICY_REVISIONS = {
    "lease": "lease-v1",
    "heartbeat": "heartbeat-v1",
    "activity_timeout": "activity-timeout-v1",
    "cancellation": "cancellation-v1",
    "retry": "retry-v1",
}
MIGRATION_REGISTRY = {
    1: {
        "migration_id": "runtime-db-1-to-2-checkpoint-recovery",
        "source_version": 1,
        "target_version": 2,
        "preconditions": [
            "every run has a contiguous, hash-valid event prefix",
            "every event reducer transition is valid",
            "canonical event rows remain unchanged",
        ],
        "rollback_instructions": (
            "Restore a verified SQLite backup and rerun the migration. The migration is additive; "
            "canonical event rows are never rewritten."
        ),
    },
    2: {
        "migration_id": "runtime-db-2-to-3-human-waits",
        "source_version": 2,
        "target_version": 3,
        "preconditions": [
            "every run has a contiguous, hash-valid event prefix",
            "every event reducer transition is valid under the wait-aware reducer",
            "legacy checkpoints are retained as evidence and excluded from v3 restore",
            "canonical event rows remain unchanged",
        ],
        "rollback_instructions": (
            "Restore a verified SQLite backup and rerun the migration. The migration changes only the "
            "runtime metadata version; canonical events and legacy checkpoints remain unchanged."
        ),
    },
}


class RuntimeStoreError(ValueError):
    """Raised when runtime history or a state transition is invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _digest_reference(value: Any, field: str) -> str:
    value = _text(value, field)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise RuntimeStoreError(f"{field} must be a sha256 reference")
    return value


def _error_ref(error: BaseException | str) -> str:
    return "sha256:" + sha256(str(error).encode("utf-8")).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise RuntimeStoreError(f"{field} must be a non-empty string of at most 128 characters")
    return value


def _identifier(value: Any, field: str) -> str:
    value = _text(value, field)
    if not IDENTIFIER_RE.fullmatch(value):
        raise RuntimeStoreError(f"{field} contains unsupported characters")
    return value


def _timestamp(value: Any) -> str:
    value = _text(value, "occurred_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeStoreError("occurred_at must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise RuntimeStoreError("occurred_at must include a timezone")
    return value


def _utc_timestamp(value: Any) -> str:
    parsed = datetime.fromisoformat(_timestamp(value).replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _after_seconds(value: str, seconds: int) -> str:
    parsed = datetime.fromisoformat(_utc_timestamp(value).replace("Z", "+00:00"))
    return (parsed + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _positive_int(value: Any, field: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeStoreError(f"{field} must be a positive integer")
    if maximum is not None and value > maximum:
        raise RuntimeStoreError(f"{field} must be at most {maximum}")
    return value


def _policy_revisions(value: Mapping[str, Any] | None) -> dict[str, str]:
    if value is None:
        return dict(DEFAULT_POLICY_REVISIONS)
    if not isinstance(value, Mapping):
        raise RuntimeStoreError("policy_revisions must be a JSON object")
    unknown = sorted(str(key) for key in value if key not in POLICY_REVISION_KEYS)
    if unknown:
        raise RuntimeStoreError("policy_revisions contains unsupported fields: " + ", ".join(unknown))
    revisions = dict(DEFAULT_POLICY_REVISIONS)
    for key in POLICY_REVISION_KEYS:
        if key in value:
            revisions[key] = _text(value[key], f"policy_revisions.{key}")
    return revisions


def _lease_policy(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None or value == {}:
        return {"schema_version": LEASE_SCHEMA_VERSION, "policy_revisions": dict(DEFAULT_POLICY_REVISIONS)}
    if not isinstance(value, Mapping):
        raise RuntimeStoreError("lease policy must be a JSON object")
    if value.get("schema_version", LEASE_SCHEMA_VERSION) != LEASE_SCHEMA_VERSION:
        raise RuntimeStoreError(f"unsupported lease policy schema: {value.get('schema_version')}")
    return {
        "schema_version": LEASE_SCHEMA_VERSION,
        "policy_revisions": _policy_revisions(value.get("policy_revisions")),
    }


def _payload(value: Mapping[str, Any], path: str = "payload") -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeStoreError(f"{path} must be a JSON object")
    normalized = json.loads(canonical_json(dict(value)))
    _validate_payload_keys(normalized, path)
    return normalized


def _receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _payload(value)
    status = normalized.get("status")
    if status not in RECEIPT_STATUSES:
        expected = ", ".join(sorted(RECEIPT_STATUSES))
        raise RuntimeStoreError(f"receipt.status must be one of: {expected}")
    return normalized


def _normalize_effect(run_id: str, value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeStoreError("effect must be a JSON object")
    allowed = {
        "activity_id",
        "attempt",
        "effect_definition_revision",
        "effect_type",
        "payload",
        "task_id",
    }
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise RuntimeStoreError("effect contains unsupported fields: " + ", ".join(unknown))
    task_id = _identifier(value.get("task_id"), "effect.task_id")
    activity_id = _identifier(value.get("activity_id"), "effect.activity_id")
    effect_type = _identifier(value.get("effect_type"), "effect.effect_type")
    effect_definition_revision = _text(
        value.get("effect_definition_revision"), "effect.effect_definition_revision"
    )
    attempt = _positive_int(value.get("attempt"), "effect.attempt")
    payload = _payload(value.get("payload", {}))
    material = canonical_json(
        {
            "run_id": run_id,
            "task_id": task_id,
            "activity_id": activity_id,
            "attempt": attempt,
            "effect_definition_revision": effect_definition_revision,
            "effect_type": effect_type,
        }
    )
    effect_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"forge-effect:{material}"))
    return {
        "schema_version": EFFECT_SCHEMA_VERSION,
        "run_id": run_id,
        "effect_id": effect_id,
        "idempotency_key": f"forge-effect:{effect_id}",
        "effect_type": effect_type,
        "task_id": task_id,
        "activity_id": activity_id,
        "activity_attempt": attempt,
        "effect_definition_revision": effect_definition_revision,
        "payload": payload,
    }


def _hash_outbox(effect: Mapping[str, Any], source_event_id: str) -> str:
    material = {
        "schema_version": effect["schema_version"],
        "effect_id": effect["effect_id"],
        "run_id": effect["run_id"],
        "source_event_id": source_event_id,
        "effect_type": effect["effect_type"],
        "task_id": effect["task_id"],
        "activity_id": effect["activity_id"],
        "activity_attempt": effect["activity_attempt"],
        "effect_definition_revision": effect["effect_definition_revision"],
        "idempotency_key": effect["idempotency_key"],
        "payload": effect["payload"],
    }
    return sha256(canonical_json(material).encode("utf-8")).hexdigest()


def _validate_payload_keys(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in REFERENCE_PAYLOAD_KEYS:
                if not isinstance(child, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", child):
                    raise RuntimeStoreError(f"{path}.{key} must be a sha256 reference")
                continue
            if normalized in FORBIDDEN_PAYLOAD_KEYS or any(
                part in SENSITIVE_PAYLOAD_PARTS for part in normalized.split("_")
            ):
                raise RuntimeStoreError(
                    f"{path}.{key} is not allowed in durable state; store a reference or digest instead"
                )
            _validate_payload_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_payload_keys(child, f"{path}[{index}]")


def _event_id(run_id: str, idempotency_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"forge-runtime:{run_id}:{idempotency_key}"))


def _derived_idempotency_key(prefix: str, value: str) -> str:
    candidate = f"{prefix}:{value}"
    return candidate if len(candidate) <= 128 else f"{prefix}:{_digest(value)}"


def _hash_event(event: Mapping[str, Any]) -> str:
    material = {
        "schema_version": event["schema_version"],
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "run_id": event["run_id"],
        "sequence": event["sequence"],
        "occurred_at": event["occurred_at"],
        "idempotency_key": event["idempotency_key"],
        "payload": event["payload"],
        "previous_hash": event["previous_hash"],
    }
    return sha256(canonical_json(material).encode("utf-8")).hexdigest()


def _validate_event_shape(event: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "event_id",
        "event_type",
        "run_id",
        "sequence",
        "occurred_at",
        "idempotency_key",
        "payload",
        "previous_hash",
        "event_hash",
    }
    missing = sorted(required - set(event))
    if missing:
        raise RuntimeStoreError("event is missing: " + ", ".join(missing))
    if event["schema_version"] != SCHEMA_VERSION:
        raise RuntimeStoreError(f"unsupported runtime schema_version: {event['schema_version']}")
    if event["event_type"] not in EVENT_TYPES:
        raise RuntimeStoreError(f"unsupported event type: {event['event_type']}")
    _identifier(event["run_id"], "run_id")
    _text(event["event_id"], "event_id")
    _text(event["idempotency_key"], "idempotency_key")
    if not isinstance(event["sequence"], int) or event["sequence"] < 1:
        raise RuntimeStoreError("sequence must be a positive integer")
    _timestamp(event["occurred_at"])
    _payload(event["payload"])
    if not HASH_RE.fullmatch(str(event["previous_hash"])):
        raise RuntimeStoreError("previous_hash must be a lowercase SHA-256 digest")
    if not HASH_RE.fullmatch(str(event["event_hash"])):
        raise RuntimeStoreError("event_hash must be a lowercase SHA-256 digest")


def _run_state(run: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run["run_id"],
        "workflow_id": run["workflow_id"],
        "definition_version": run["definition_version"],
        "policy_revision": run["policy_revision"],
        "status": "created",
        "sequence": 0,
        "tasks": {},
        "waits": {},
        "signals": {},
        "cancel_acknowledged": False,
    }


def _require_status(state: Mapping[str, Any], allowed: set[str], event_type: str) -> None:
    status = state["status"]
    if status not in allowed:
        expected = ", ".join(sorted(allowed))
        raise RuntimeStoreError(f"{event_type} is invalid while run is {status}; expected {expected}")


def _task_payload(event: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    payload = event["payload"]
    task_id = payload.get("task_id")
    return payload, _identifier(task_id, "payload.task_id")


def _wait_descriptor(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "wait_id",
        "task_id",
        "checkpoint_id",
        "checkpoint_sequence",
        "checkpoint_event_hash",
        "input_schema_digest",
        "policy_revision",
        "authorization_context_digest",
        "expires_at",
        "ttl_seconds",
        "poll_interval_ms",
        "expiration_outcome",
        "resume_contract",
    }
    unknown = sorted(str(key) for key in payload if key not in allowed)
    if unknown:
        raise RuntimeStoreError("wait payload contains unsupported fields: " + ", ".join(unknown))
    expiration_outcome = payload.get("expiration_outcome")
    if expiration_outcome not in EXPIRATION_OUTCOMES:
        expected = ", ".join(sorted(EXPIRATION_OUTCOMES))
        raise RuntimeStoreError(f"payload.expiration_outcome must be one of: {expected}")
    poll_interval_ms = payload.get("poll_interval_ms")
    _positive_int(poll_interval_ms, "payload.poll_interval_ms", maximum=3_600_000)
    return {
        "wait_id": _identifier(payload.get("wait_id"), "payload.wait_id"),
        "task_id": _identifier(payload.get("task_id"), "payload.task_id"),
        "checkpoint_id": _text(payload.get("checkpoint_id"), "payload.checkpoint_id"),
        "checkpoint_sequence": _positive_int(payload.get("checkpoint_sequence"), "payload.checkpoint_sequence"),
        "checkpoint_event_hash": _hash_reference(payload.get("checkpoint_event_hash"), "payload.checkpoint_event_hash"),
        "input_schema_digest": _digest_reference(payload.get("input_schema_digest"), "payload.input_schema_digest"),
        "policy_revision": _text(payload.get("policy_revision"), "payload.policy_revision"),
        "authorization_context_digest": _digest_reference(
            payload.get("authorization_context_digest"), "payload.authorization_context_digest"
        ),
        "expires_at": _utc_timestamp(payload.get("expires_at")),
        "ttl_seconds": _positive_int(payload.get("ttl_seconds"), "payload.ttl_seconds", maximum=2_592_000),
        "poll_interval_ms": poll_interval_ms,
        "expiration_outcome": expiration_outcome,
        "resume_contract": _text(payload.get("resume_contract"), "payload.resume_contract"),
    }


def _hash_reference(value: Any, field: str) -> str:
    value = _text(value, field)
    if not HASH_RE.fullmatch(value):
        raise RuntimeStoreError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _input_submission(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"wait_id", "submission_id", "input_digest", "input_schema_digest", "authorization_context_digest"}
    unknown = sorted(str(key) for key in payload if key not in allowed)
    if unknown:
        raise RuntimeStoreError("input payload contains unsupported fields: " + ", ".join(unknown))
    submission = {
        "wait_id": _identifier(payload.get("wait_id"), "payload.wait_id"),
        "submission_id": _identifier(payload.get("submission_id"), "payload.submission_id"),
        "input_digest": _digest_reference(payload.get("input_digest"), "payload.input_digest"),
        "authorization_context_digest": _digest_reference(
            payload.get("authorization_context_digest"), "payload.authorization_context_digest"
        ),
    }
    if payload.get("input_schema_digest") is not None:
        submission["input_schema_digest"] = _digest_reference(
            payload["input_schema_digest"], "payload.input_schema_digest"
        )
    return submission


def _signal_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"signal_id", "signal_type", "payload_digest", "authorization_context_digest", "wait_id"}
    unknown = sorted(str(key) for key in payload if key not in allowed)
    if unknown:
        raise RuntimeStoreError("signal payload contains unsupported fields: " + ", ".join(unknown))
    signal_type = payload.get("signal_type")
    if signal_type not in SIGNAL_TYPES:
        expected = ", ".join(sorted(SIGNAL_TYPES))
        raise RuntimeStoreError(f"payload.signal_type must be one of: {expected}")
    result = {
        "signal_id": _identifier(payload.get("signal_id"), "payload.signal_id"),
        "signal_type": signal_type,
        "payload_digest": _digest_reference(payload.get("payload_digest"), "payload.payload_digest"),
        "authorization_context_digest": _digest_reference(
            payload.get("authorization_context_digest"), "payload.authorization_context_digest"
        ),
    }
    if payload.get("wait_id") is not None:
        result["wait_id"] = _identifier(payload["wait_id"], "payload.wait_id")
    return result


def _before_or_equal(left: str, right: str) -> bool:
    return datetime.fromisoformat(left.replace("Z", "+00:00")) <= datetime.fromisoformat(right.replace("Z", "+00:00"))


def apply_event(state: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
    """Apply one validated event without I/O or wall-clock reads."""

    _validate_event_shape(event)
    if event["sequence"] != state["sequence"] + 1:
        raise RuntimeStoreError(
            f"non-contiguous sequence: expected {state['sequence'] + 1}, got {event['sequence']}"
        )
    next_state = copy.deepcopy(dict(state))
    next_state["sequence"] = event["sequence"]
    event_type = event["event_type"]
    payload = event["payload"]

    if event_type == "run.started":
        if state["status"] != "created" or state["sequence"] != 0:
            raise RuntimeStoreError("run.started is only valid as the first event")
        for field in ("workflow_id", "definition_version", "policy_revision"):
            if payload.get(field) != state[field]:
                raise RuntimeStoreError(f"run.started payload does not match {field}")
        next_state["status"] = "running"
        next_state["started_at"] = event["occurred_at"]
        return next_state

    if state["status"] in RUN_TERMINAL:
        raise RuntimeStoreError(f"{event_type} is invalid after run status {state['status']}")

    if event_type == "run.paused":
        _require_status(state, {"running"}, event_type)
        next_state["status"] = "paused"
    elif event_type == "run.resumed":
        _require_status(state, {"paused"}, event_type)
        next_state["status"] = "running"
    elif event_type == "run.cancel_requested":
        _require_status(state, {"running", "paused", "input_required"}, event_type)
        allowed = {"reason_ref", "authorization_context_digest"}
        unknown = sorted(str(key) for key in payload if key not in allowed)
        if unknown:
            raise RuntimeStoreError("cancellation request contains unsupported fields: " + ", ".join(unknown))
        next_state["status"] = "cancelling"
        next_state["cancel_requested_at"] = event["occurred_at"]
        if "reason_ref" in payload:
            next_state["cancel_reason_ref"] = _text(payload["reason_ref"], "payload.reason_ref")
        if "authorization_context_digest" in payload:
            next_state["cancel_authorization_context_digest"] = _digest_reference(
                payload["authorization_context_digest"], "payload.authorization_context_digest"
            )
        for wait in next_state["waits"].values():
            if wait["status"] == "input_required":
                wait["status"] = "cancel_requested"
    elif event_type == "cancel.acknowledged":
        _require_status(state, {"cancelling"}, event_type)
        allowed = {"ack_ref", "authorization_context_digest"}
        unknown = sorted(str(key) for key in payload if key not in allowed)
        if unknown:
            raise RuntimeStoreError("cancellation acknowledgement contains unsupported fields: " + ", ".join(unknown))
        if "ack_ref" in payload:
            next_state["cancel_ack_ref"] = _digest_reference(payload["ack_ref"], "payload.ack_ref")
        if "authorization_context_digest" in payload:
            authorization_context_digest = _digest_reference(
                payload["authorization_context_digest"], "payload.authorization_context_digest"
            )
            requested_digest = state.get("cancel_authorization_context_digest")
            if requested_digest is not None and requested_digest != authorization_context_digest:
                raise RuntimeStoreError("cancellation acknowledgement authorization context mismatch")
            next_state["cancel_authorization_context_digest"] = authorization_context_digest
        next_state["cancel_acknowledged"] = True
        next_state["cancel_acknowledged_at"] = event["occurred_at"]
    elif event_type == "run.cancelled":
        _require_status(state, {"cancelling"}, event_type)
        if not state["cancel_acknowledged"]:
            raise RuntimeStoreError("run.cancelled requires cancel.acknowledged evidence")
        next_state["status"] = "cancelled"
        for wait in next_state["waits"].values():
            if wait["status"] in {"input_required", "cancel_requested", "expired"}:
                wait["status"] = "cancelled"
                wait["cancelled_at"] = event["occurred_at"]
        for task in next_state["tasks"].values():
            if task["status"] not in TASK_TERMINAL:
                task["status"] = "cancelled"
                task.pop("retryable", None)
    elif event_type == "run.failed":
        _require_status(state, {"running", "paused", "input_required", "cancelling"}, event_type)
        next_state["status"] = "failed"
        if "error_ref" in payload:
            next_state["error_ref"] = _text(payload["error_ref"], "payload.error_ref")
        for wait in next_state["waits"].values():
            if wait["status"] in {"input_required", "cancel_requested"}:
                wait["status"] = "cancelled"
    elif event_type == "run.completed":
        _require_status(state, {"running"}, event_type)
        unfinished = [
            task_id
            for task_id, task in state["tasks"].items()
            if task["status"] not in TASK_TERMINAL or (task["status"] == "failed" and task["retryable"])
        ]
        if unfinished:
            raise RuntimeStoreError("run.completed requires all tasks to be terminal: " + ", ".join(unfinished))
        next_state["status"] = "completed"
    elif event_type == "wait.created":
        _require_status(state, {"running"}, event_type)
        wait = _wait_descriptor(payload)
        if wait["policy_revision"] != state["policy_revision"]:
            raise RuntimeStoreError("wait policy revision does not match run policy revision")
        if wait["checkpoint_sequence"] != state["sequence"]:
            raise RuntimeStoreError("wait checkpoint must bind the current verified event boundary")
        if _before_or_equal(wait["expires_at"], event["occurred_at"]):
            raise RuntimeStoreError("wait expiry must be after wait creation")
        current_task = state["tasks"].get(wait["task_id"])
        if current_task is None or current_task["status"] != "started":
            raise RuntimeStoreError(f"wait task must be started: {wait['task_id']}")
        if wait["wait_id"] in state["waits"]:
            raise RuntimeStoreError(f"wait already exists: {wait['wait_id']}")
        active_waits = [item for item in state["waits"].values() if item["status"] == "input_required"]
        if len(active_waits) >= MAX_ACTIVE_WAITS:
            raise RuntimeStoreError("run already has the maximum number of active waits")
        next_state["status"] = "input_required"
        next_state["waits"][wait["wait_id"]] = {
            **wait,
            "status": "input_required",
            "created_at": event["occurred_at"],
            "created_sequence": event["sequence"],
        }
    elif event_type == "wait.input_submitted":
        _require_status(state, {"input_required"}, event_type)
        submission = _input_submission(payload)
        wait = next_state["waits"].get(submission["wait_id"])
        if wait is None:
            raise RuntimeStoreError(f"unknown wait: {submission['wait_id']}")
        if wait["status"] != "input_required":
            raise RuntimeStoreError(f"wait is not accepting input: {submission['wait_id']}")
        if submission.get("input_schema_digest") != wait["input_schema_digest"]:
            raise RuntimeStoreError(f"wait input schema mismatch: {submission['wait_id']}")
        if submission["authorization_context_digest"] != wait["authorization_context_digest"]:
            raise RuntimeStoreError(f"wait authorization context mismatch: {submission['wait_id']}")
        wait.update(
            {
                "status": "submitted",
                "submission_id": submission["submission_id"],
                "input_digest": submission["input_digest"],
                "submitted_at": event["occurred_at"],
            }
        )
        next_state["status"] = "running"
    elif event_type == "wait.expired":
        _require_status(state, {"input_required"}, event_type)
        allowed = {"wait_id", "expiration_outcome", "error_ref"}
        unknown = sorted(str(key) for key in payload if key not in allowed)
        if unknown:
            raise RuntimeStoreError("expiration payload contains unsupported fields: " + ", ".join(unknown))
        wait_id = _identifier(payload.get("wait_id"), "payload.wait_id")
        wait = next_state["waits"].get(wait_id)
        if wait is None:
            raise RuntimeStoreError(f"unknown wait: {wait_id}")
        if wait["status"] != "input_required":
            raise RuntimeStoreError(f"wait is not expirable: {wait_id}")
        if not _before_or_equal(wait["expires_at"], event["occurred_at"]):
            raise RuntimeStoreError(f"wait has not expired: {wait_id}")
        if payload.get("expiration_outcome") != wait["expiration_outcome"]:
            raise RuntimeStoreError(f"wait expiration policy mismatch: {wait_id}")
        wait["status"] = "expired"
        wait["expired_at"] = event["occurred_at"]
        if wait["expiration_outcome"] == "fail_run":
            next_state["status"] = "failed"
            next_state["error_ref"] = _text(
                payload.get("error_ref", _error_ref(f"wait-expired:{wait_id}")), "payload.error_ref"
            )
            task = next_state["tasks"].get(wait["task_id"])
            if task is not None and task["status"] not in TASK_TERMINAL:
                task["status"] = "failed"
                task["retryable"] = False
                task["error_ref"] = next_state["error_ref"]
        else:
            next_state["status"] = "cancelling"
            next_state["cancel_requested_at"] = event["occurred_at"]
            wait["status"] = "expired"
    elif event_type == "signal.received":
        _require_status(state, {"running", "paused", "input_required", "cancelling"}, event_type)
        signal = _signal_payload(payload)
        if signal["signal_id"] in state["signals"]:
            raise RuntimeStoreError(f"signal already exists: {signal['signal_id']}")
        if len(state["signals"]) >= MAX_SIGNALS_PER_RUN:
            raise RuntimeStoreError("run has reached the maximum number of signals")
        if "wait_id" in signal:
            wait = state["waits"].get(signal["wait_id"])
            if wait is None:
                raise RuntimeStoreError(f"unknown wait: {signal['wait_id']}")
            if wait["status"] not in {"input_required", "cancel_requested"}:
                raise RuntimeStoreError(f"signal target wait is no longer active: {signal['wait_id']}")
            if signal["authorization_context_digest"] != wait["authorization_context_digest"]:
                raise RuntimeStoreError(f"signal authorization context mismatch: {signal['wait_id']}")
        next_state["signals"][signal["signal_id"]] = {
            **signal,
            "received_at": event["occurred_at"],
            "received_sequence": event["sequence"],
        }
    elif event_type.startswith("task."):
        _require_status(state, {"running"}, event_type)
        payload, task_id = _task_payload(event)
        tasks = next_state["tasks"]
        current = tasks.get(task_id)
        if event_type == "task.scheduled":
            if current is not None:
                raise RuntimeStoreError(f"task already exists: {task_id}")
            dependencies = payload.get("depends_on", [])
            if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
                raise RuntimeStoreError("payload.depends_on must be a list of task identifiers")
            normalized_dependencies = sorted({_identifier(item, "payload.depends_on") for item in dependencies})
            if task_id in normalized_dependencies:
                raise RuntimeStoreError("task cannot depend on itself")
            task = {
                "status": "scheduled",
                "attempt": 0,
                "depends_on": normalized_dependencies,
            }
            if "title" in payload:
                task["title"] = _text(payload["title"], "payload.title")
            tasks[task_id] = task
        elif current is None:
            raise RuntimeStoreError(f"unknown task: {task_id}")
        elif event_type == "task.started":
            if current["status"] == "failed" and not current["retryable"]:
                raise RuntimeStoreError(f"non-retryable task cannot restart: {task_id}")
            if current["status"] not in {"scheduled", "failed"}:
                raise RuntimeStoreError(f"task.started is invalid while task is {current['status']}")
            attempt = payload.get("attempt", current["attempt"] + 1)
            if not isinstance(attempt, int) or attempt < 1 or attempt <= current["attempt"]:
                raise RuntimeStoreError("payload.attempt must increase monotonically")
            current["status"] = "started"
            current["attempt"] = attempt
            current.pop("retryable", None)
        elif event_type == "task.completed":
            if current["status"] != "started":
                raise RuntimeStoreError(f"task.completed is invalid while task is {current['status']}")
            current["status"] = "completed"
            if "output_ref" in payload:
                current["output_ref"] = _text(payload["output_ref"], "payload.output_ref")
        elif event_type == "task.failed":
            if current["status"] != "started":
                raise RuntimeStoreError(f"task.failed is invalid while task is {current['status']}")
            current["status"] = "failed"
            current["retryable"] = bool(payload.get("retryable", False))
            if "error_ref" in payload:
                current["error_ref"] = _text(payload["error_ref"], "payload.error_ref")
        elif event_type == "task.cancelled":
            if current["status"] not in {"scheduled", "started", "failed"}:
                raise RuntimeStoreError(f"task.cancelled is invalid while task is {current['status']}")
            current["status"] = "cancelled"
            current.pop("retryable", None)
        else:  # pragma: no cover - EVENT_TYPES and the branch above stay in lockstep.
            raise RuntimeStoreError(f"unsupported task event type: {event_type}")
    else:  # pragma: no cover - _validate_event_shape rejects this first.
        raise RuntimeStoreError(f"unsupported event type: {event_type}")

    return next_state


def _replay_prefix(
    run: Mapping[str, Any], events: list[Mapping[str, Any]]
) -> tuple[dict[str, Any], int, str | None]:
    """Replay as far as possible and return the last verified sequence and error."""

    state = _run_state(run)
    previous_hash = GENESIS_HASH
    if events:
        first = events[0]
        if "_decode_error" in first:
            return state, 0, f"invalid event at sequence {first.get('sequence')}: {first['_decode_error']}"
        if first["event_type"] != "run.started":
            return state, 0, "run history must begin with run.started"
        if run["started_at"] != first["occurred_at"]:
            return state, 0, "run metadata started_at does not match run.started"
    for event in events:
        if "_decode_error" in event:
            return state, state["sequence"], f"invalid event at sequence {event.get('sequence')}: {event['_decode_error']}"
        try:
            _validate_event_shape(event)
            if event["run_id"] != run["run_id"]:
                raise RuntimeStoreError("event run_id does not match its stream")
            if event["previous_hash"] != previous_hash:
                raise RuntimeStoreError(f"broken hash chain at sequence {event['sequence']}")
            expected_hash = _hash_event(event)
            if event["event_hash"] != expected_hash:
                raise RuntimeStoreError(f"event hash mismatch at sequence {event['sequence']}")
            state = apply_event(state, event)
            previous_hash = event["event_hash"]
        except (RuntimeStoreError, KeyError, TypeError, ValueError) as exc:
            return state, state["sequence"], str(exc)
    return state, state["sequence"], None


def replay(run: Mapping[str, Any], events: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Verify the hash chain and rebuild state from the event prefix."""

    state, _sequence, error = _replay_prefix(run, events)
    if error is not None:
        raise RuntimeStoreError(error)
    return state


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runtime_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_runs (
    run_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    policy_revision TEXT NOT NULL,
    started_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_events (
    run_id TEXT NOT NULL REFERENCES runtime_runs(run_id),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence),
    UNIQUE (run_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS runtime_events_run_sequence
    ON runtime_events(run_id, sequence);
CREATE TABLE IF NOT EXISTS runtime_outbox (
    effect_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runtime_runs(run_id),
    source_event_id TEXT NOT NULL UNIQUE REFERENCES runtime_events(event_id),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    effect_type TEXT NOT NULL,
    task_id TEXT NOT NULL,
    activity_id TEXT NOT NULL,
    activity_attempt INTEGER NOT NULL CHECK (activity_attempt > 0),
    effect_definition_revision TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    effect_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'leased', 'retry', 'succeeded', 'dead_letter')),
    available_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivery_attempts INTEGER NOT NULL DEFAULT 0 CHECK (delivery_attempts >= 0),
    last_attempt_at TEXT,
    lease_owner TEXT,
    lease_expires_at TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
    lease_started_at TEXT,
    lease_deadline_at TEXT,
    lease_seconds INTEGER CHECK (lease_seconds IS NULL OR lease_seconds > 0),
    max_lease_seconds INTEGER CHECK (max_lease_seconds IS NULL OR max_lease_seconds > 0),
    heartbeat_seconds INTEGER CHECK (heartbeat_seconds IS NULL OR heartbeat_seconds > 0),
    last_heartbeat_at TEXT,
    heartbeat_count INTEGER NOT NULL DEFAULT 0 CHECK (heartbeat_count >= 0),
    lease_policy_json TEXT NOT NULL DEFAULT '{}',
    last_error_ref TEXT
);
CREATE INDEX IF NOT EXISTS runtime_outbox_ready
    ON runtime_outbox(status, available_at, effect_id);
CREATE INDEX IF NOT EXISTS runtime_outbox_run
    ON runtime_outbox(run_id, created_at, effect_id);
CREATE TABLE IF NOT EXISTS runtime_outbox_attempts (
    effect_id TEXT NOT NULL REFERENCES runtime_outbox(effect_id),
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    worker_id TEXT NOT NULL,
    lease_generation INTEGER NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
    claimed_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('leased', 'reclaimed', 'succeeded', 'retry', 'dead_letter')),
    error_ref TEXT,
    PRIMARY KEY (effect_id, attempt)
);
CREATE INDEX IF NOT EXISTS runtime_outbox_attempts_effect
    ON runtime_outbox_attempts(effect_id, attempt);
CREATE TABLE IF NOT EXISTS runtime_outbox_lease_events (
    effect_id TEXT NOT NULL REFERENCES runtime_outbox(effect_id),
    event_sequence INTEGER NOT NULL CHECK (event_sequence > 0),
    event_id TEXT NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    event_type TEXT NOT NULL CHECK (event_type IN ('claimed', 'heartbeat', 'lease_lost')),
    lease_generation INTEGER NOT NULL CHECK (lease_generation > 0),
    worker_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    lease_expires_at TEXT,
    lease_deadline_at TEXT,
    details_json TEXT NOT NULL,
    PRIMARY KEY (effect_id, event_sequence)
);
CREATE INDEX IF NOT EXISTS runtime_outbox_lease_events_effect
    ON runtime_outbox_lease_events(effect_id, event_sequence);
CREATE TABLE IF NOT EXISTS runtime_checkpoints (
    run_id TEXT NOT NULL REFERENCES runtime_runs(run_id),
    checkpoint_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    runtime_schema_version INTEGER NOT NULL CHECK (runtime_schema_version IN (2, 3)),
    event_sequence INTEGER NOT NULL CHECK (event_sequence > 0),
    event_hash TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    policy_revision TEXT NOT NULL,
    state_json TEXT NOT NULL,
    state_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, checkpoint_id),
    UNIQUE (run_id, event_sequence, event_hash, runtime_schema_version)
);
CREATE INDEX IF NOT EXISTS runtime_checkpoints_run_sequence
    ON runtime_checkpoints(run_id, event_sequence DESC, checkpoint_id);
CREATE TABLE IF NOT EXISTS runtime_migrations (
    migration_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    source_version INTEGER NOT NULL,
    target_version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('started', 'applied', 'failed')),
    preconditions_json TEXT NOT NULL,
    rollback_instructions TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    result_digest TEXT,
    error_ref TEXT
);
CREATE INDEX IF NOT EXISTS runtime_migrations_status
    ON runtime_migrations(status, target_version, migration_id);
CREATE TABLE IF NOT EXISTS runtime_inbox (
    idempotency_key TEXT PRIMARY KEY,
    effect_id TEXT NOT NULL UNIQUE REFERENCES runtime_outbox(effect_id),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    receipt_json TEXT NOT NULL,
    received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runtime_inbox_effect
    ON runtime_inbox(effect_id);
"""


class RuntimeStore:
    """SQLite/WAL event store with serialized writers and deterministic replay."""

    def __init__(self, path: Path, *, timeout: float = 5.0, auto_migrate: bool = False) -> None:
        self.path = Path(path)
        self.auto_migrate = auto_migrate
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=timeout, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute(f"PRAGMA busy_timeout = {max(1, int(timeout * 1000))}")
        journal_mode = str(self.connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
        if journal_mode not in {"wal", "memory"}:
            self.close()
            raise RuntimeStoreError(f"SQLite WAL is unavailable; got journal mode {journal_mode}")
        self.connection.executescript(SCHEMA_SQL)
        self._ensure_effect_columns()
        row = self.connection.execute("SELECT value FROM runtime_meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            self.database_schema_version = DATABASE_SCHEMA_VERSION
            self.connection.execute(
                "INSERT INTO runtime_meta(key, value) VALUES ('schema_version', ?)",
                (str(DATABASE_SCHEMA_VERSION),),
            )
        else:
            try:
                self.database_schema_version = int(row["value"])
            except (TypeError, ValueError) as exc:
                self.close()
                raise RuntimeStoreError(f"invalid runtime database schema: {row['value']}") from exc
            if self.database_schema_version > DATABASE_SCHEMA_VERSION:
                self.close()
                raise RuntimeStoreError(
                    f"unsupported runtime database schema: {self.database_schema_version}; "
                    f"latest supported version is {DATABASE_SCHEMA_VERSION}"
                )
        effect_row = self.connection.execute(
            "SELECT value FROM runtime_meta WHERE key = 'effects_schema_version'"
        ).fetchone()
        if effect_row is None:
            self.connection.execute(
                "INSERT INTO runtime_meta(key, value) VALUES ('effects_schema_version', ?)",
                (str(EFFECT_SCHEMA_VERSION),),
            )
        elif effect_row["value"] != str(EFFECT_SCHEMA_VERSION):
            self.close()
            raise RuntimeStoreError(f"unsupported runtime effects schema: {effect_row['value']}")
        if self.database_schema_version < DATABASE_SCHEMA_VERSION and self.auto_migrate:
            self.migrate()

    def close(self) -> None:
        self.connection.close()

    def _require_database_schema(self) -> None:
        if self.database_schema_version != DATABASE_SCHEMA_VERSION:
            raise RuntimeStoreError(
                f"runtime database schema {self.database_schema_version} requires migration; "
                "run `python3 scripts/forge-runtime.py migrate` with a verified backup"
            )

    def _ensure_effect_columns(self) -> None:
        """Add lease controls to databases created before heartbeat support."""

        additions = {
            "runtime_outbox": {
                "lease_generation": "INTEGER NOT NULL DEFAULT 0 CHECK (lease_generation >= 0)",
                "lease_started_at": "TEXT",
                "lease_deadline_at": "TEXT",
                "lease_seconds": "INTEGER CHECK (lease_seconds IS NULL OR lease_seconds > 0)",
                "max_lease_seconds": "INTEGER CHECK (max_lease_seconds IS NULL OR max_lease_seconds > 0)",
                "heartbeat_seconds": "INTEGER CHECK (heartbeat_seconds IS NULL OR heartbeat_seconds > 0)",
                "last_heartbeat_at": "TEXT",
                "heartbeat_count": "INTEGER NOT NULL DEFAULT 0 CHECK (heartbeat_count >= 0)",
                "lease_policy_json": "TEXT NOT NULL DEFAULT '{}'",
            },
            "runtime_outbox_attempts": {
                "lease_generation": "INTEGER NOT NULL DEFAULT 0 CHECK (lease_generation >= 0)",
            },
        }
        for table, columns in additions.items():
            present = {
                row["name"]
                for row in self.connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for name, definition in columns.items():
                if name not in present:
                    self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

        self.connection.execute(
            "UPDATE runtime_outbox SET lease_generation = delivery_attempts, "
            "lease_started_at = COALESCE(lease_started_at, last_attempt_at), "
            "lease_deadline_at = COALESCE(lease_deadline_at, lease_expires_at) "
            "WHERE status = 'leased' AND lease_generation = 0 AND delivery_attempts > 0",
        )
        self.connection.execute(
            "UPDATE runtime_outbox_attempts SET lease_generation = attempt "
            "WHERE lease_generation = 0",
        )

    @staticmethod
    def _row_migration(row: sqlite3.Row) -> dict[str, Any]:
        if row["schema_version"] != MIGRATION_SCHEMA_VERSION:
            raise RuntimeStoreError(f"unsupported migration evidence schema: {row['schema_version']}")
        if row["status"] not in MIGRATION_STATUSES:
            raise RuntimeStoreError(f"unsupported migration status: {row['status']}")
        return {
            "schema_version": row["schema_version"],
            "migration_id": row["migration_id"],
            "source_version": row["source_version"],
            "target_version": row["target_version"],
            "status": row["status"],
            "preconditions": json.loads(row["preconditions_json"]),
            "rollback_instructions": row["rollback_instructions"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "result_digest": row["result_digest"],
            "error_ref": row["error_ref"],
        }

    def _history_result_digest(self) -> str:
        materials: list[dict[str, Any]] = []
        rows = self.connection.execute(
            "SELECT run_id, workflow_id, definition_version, policy_revision, started_at "
            "FROM runtime_runs ORDER BY run_id"
        ).fetchall()
        for row in rows:
            run = dict(row)
            events = self._events(run["run_id"], require_ready=False)
            state = replay(run, events)
            materials.append(
                {
                    "run_id": run["run_id"],
                    "sequence": state["sequence"],
                    "event_hash": events[-1]["event_hash"] if events else GENESIS_HASH,
                    "state_digest": _digest(state),
                }
            )
        return _digest(materials)

    def _upgrade_checkpoint_table_locked(self) -> None:
        """Make legacy checkpoint rows coexist with v3 checkpoints during migration."""

        row = self.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'runtime_checkpoints'"
        ).fetchone()
        definition = str(row["sql"] or "") if row is not None else ""
        if re.search(r"IN\s*\(\s*2\s*,\s*3\s*\)", definition, re.IGNORECASE) and re.search(
            r"UNIQUE\s*\(\s*run_id\s*,\s*event_sequence\s*,\s*event_hash\s*,\s*runtime_schema_version\s*\)",
            definition,
            re.IGNORECASE,
        ):
            return
        self.connection.execute(
            """CREATE TABLE runtime_checkpoints_v3 (
                run_id TEXT NOT NULL REFERENCES runtime_runs(run_id),
                checkpoint_id TEXT NOT NULL,
                schema_version INTEGER NOT NULL CHECK (schema_version = 1),
                runtime_schema_version INTEGER NOT NULL CHECK (runtime_schema_version IN (2, 3)),
                event_sequence INTEGER NOT NULL CHECK (event_sequence > 0),
                event_hash TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                definition_version TEXT NOT NULL,
                policy_revision TEXT NOT NULL,
                state_json TEXT NOT NULL,
                state_digest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (run_id, checkpoint_id),
                UNIQUE (run_id, event_sequence, event_hash, runtime_schema_version)
            )"""
        )
        self.connection.execute(
            "INSERT INTO runtime_checkpoints_v3 SELECT run_id, checkpoint_id, schema_version, "
            "runtime_schema_version, event_sequence, event_hash, workflow_id, definition_version, "
            "policy_revision, state_json, state_digest, created_at FROM runtime_checkpoints"
        )
        self.connection.execute("DROP TABLE runtime_checkpoints")
        self.connection.execute("ALTER TABLE runtime_checkpoints_v3 RENAME TO runtime_checkpoints")
        self.connection.execute(
            "CREATE INDEX runtime_checkpoints_run_sequence "
            "ON runtime_checkpoints(run_id, event_sequence DESC, checkpoint_id)"
        )

    def _migration_plan(self, source_version: int) -> dict[str, Any]:
        plan = MIGRATION_REGISTRY.get(source_version)
        if plan is None:
            raise RuntimeStoreError(
                f"no reviewed migration from runtime database schema {source_version} "
                f"to {DATABASE_SCHEMA_VERSION}; restore a compatible backup"
            )
        return plan

    def migration_status(self) -> dict[str, Any]:
        current = self.database_schema_version
        pending: list[dict[str, Any]] = []
        cursor = current
        while cursor < DATABASE_SCHEMA_VERSION:
            plan = self._migration_plan(cursor)
            evidence_row = self.connection.execute(
                "SELECT * FROM runtime_migrations WHERE migration_id = ?",
                (plan["migration_id"],),
            ).fetchone()
            evidence = self._row_migration(evidence_row) if evidence_row is not None else None
            pending.append(
                {
                    "migration_id": plan["migration_id"],
                    "source_version": plan["source_version"],
                    "target_version": plan["target_version"],
                    "preconditions": list(plan["preconditions"]),
                    "rollback_instructions": plan["rollback_instructions"],
                    "status": evidence["status"] if evidence is not None else "pending",
                    "evidence": evidence,
                }
            )
            cursor = plan["target_version"]
        applied_rows = self.connection.execute(
            "SELECT * FROM runtime_migrations ORDER BY target_version, migration_id"
        ).fetchall()
        return {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "current_version": current,
            "target_version": DATABASE_SCHEMA_VERSION,
            "requires_migration": current < DATABASE_SCHEMA_VERSION,
            "pending": pending,
            "applied": [self._row_migration(row) for row in applied_rows],
        }

    def migrate(self, *, target_version: int | None = None, dry_run: bool = False) -> dict[str, Any]:
        target_version = DATABASE_SCHEMA_VERSION if target_version is None else target_version
        if isinstance(target_version, bool) or not isinstance(target_version, int):
            raise RuntimeStoreError("target_version must be an integer")
        if target_version < self.database_schema_version or target_version > DATABASE_SCHEMA_VERSION:
            raise RuntimeStoreError(
                f"target_version must be between {self.database_schema_version} and {DATABASE_SCHEMA_VERSION}"
            )
        if dry_run:
            result = self.migration_status()
            result["dry_run"] = True
            return result
        while self.database_schema_version < target_version:
            source_version = self.database_schema_version
            plan = self._migration_plan(source_version)
            started_at = utc_now()
            with self._transaction(require_ready=False):
                existing = self.connection.execute(
                    "SELECT migration_id, status FROM runtime_migrations WHERE migration_id = ?",
                    (plan["migration_id"],),
                ).fetchone()
                if existing is not None and existing["status"] == "applied":
                    raise RuntimeStoreError(
                        f"migration evidence is applied but runtime schema is still {source_version}: "
                        f"{plan['migration_id']}"
                    )
                if existing is None:
                    self.connection.execute(
                        "INSERT INTO runtime_migrations(migration_id, schema_version, source_version, target_version, "
                        "status, preconditions_json, rollback_instructions, started_at) VALUES (?, ?, ?, ?, 'started', ?, ?, ?)",
                        (
                            plan["migration_id"],
                            MIGRATION_SCHEMA_VERSION,
                            plan["source_version"],
                            plan["target_version"],
                            canonical_json(plan["preconditions"]),
                            plan["rollback_instructions"],
                            started_at,
                        ),
                    )
                else:
                    self.connection.execute(
                        "UPDATE runtime_migrations SET status = 'started', started_at = ?, completed_at = NULL, "
                        "result_digest = NULL, error_ref = NULL WHERE migration_id = ?",
                        (started_at, plan["migration_id"]),
                    )
            try:
                # Hold the writer lock through validation and promotion so a concurrent
                # append cannot land between the history digest and schema update.
                with self._transaction(require_ready=False):
                    result_digest = self._history_result_digest()
                    meta = self.connection.execute(
                        "SELECT value FROM runtime_meta WHERE key = 'schema_version'"
                    ).fetchone()
                    try:
                        current_version = int(meta["value"]) if meta is not None else None
                    except (TypeError, ValueError) as exc:
                        raise RuntimeStoreError("runtime schema version changed to an invalid value") from exc
                    if current_version != source_version:
                        raise RuntimeStoreError(
                            f"runtime schema changed during migration {plan['migration_id']}; "
                            "retry from a fresh connection"
                        )
                    if plan["source_version"] == 2:
                        self._upgrade_checkpoint_table_locked()
                    completed_at = utc_now()
                    self.connection.execute(
                        "UPDATE runtime_meta SET value = ? WHERE key = 'schema_version'",
                        (str(plan["target_version"]),),
                    )
                    self.connection.execute(
                        "UPDATE runtime_migrations SET status = 'applied', completed_at = ?, result_digest = ?, "
                        "error_ref = NULL WHERE migration_id = ?",
                        (completed_at, result_digest, plan["migration_id"]),
                    )
            except (RuntimeStoreError, TypeError, ValueError, sqlite3.Error) as exc:
                error_ref = _error_ref(exc)
                with self._transaction(require_ready=False):
                    self.connection.execute(
                        "UPDATE runtime_migrations SET status = 'failed', completed_at = ?, error_ref = ? "
                        "WHERE migration_id = ?",
                        (utc_now(), error_ref, plan["migration_id"]),
                    )
                raise RuntimeStoreError(
                    f"migration {plan['migration_id']} rejected by precondition: {exc}; "
                    f"restore a verified backup or repair history before retrying ({error_ref})"
                ) from exc
            self.database_schema_version = plan["target_version"]
        return self.migration_status()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @contextlib.contextmanager
    def _transaction(self, *, require_ready: bool = True) -> Iterator[None]:
        if require_ready:
            self._require_database_schema()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    @contextlib.contextmanager
    def _read_transaction(self) -> Iterator[None]:
        self._require_database_schema()
        self.connection.execute("BEGIN")
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def _run(self, run_id: str, *, require_ready: bool = True) -> dict[str, Any]:
        if require_ready:
            self._require_database_schema()
        row = self.connection.execute(
            "SELECT run_id, workflow_id, definition_version, policy_revision, started_at "
            "FROM runtime_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise RuntimeStoreError(f"unknown run: {run_id}")
        return dict(row)

    def _events(self, run_id: str, *, require_ready: bool = True) -> list[dict[str, Any]]:
        if require_ready:
            self._require_database_schema()
        rows = self._event_rows(run_id)
        return [self._row_event(row) for row in rows]

    def _event_rows(self, run_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT run_id, sequence, event_id, event_type, idempotency_key, occurred_at, "
            "payload_json, previous_hash, event_hash FROM runtime_events "
            "WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()

    def _events_for_restore(self, run_id: str) -> list[dict[str, Any]]:
        self._require_database_schema()
        events: list[dict[str, Any]] = []
        for row in self._event_rows(run_id):
            try:
                events.append(self._row_event(row))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                events.append(
                    {
                        "_decode_error": str(exc),
                        "sequence": row["sequence"],
                        "event_id": row["event_id"],
                    }
                )
        return events

    def _validate_wait_checkpoint_locked(
        self,
        run_id: str,
        state: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> None:
        """Require a wait to reference the exact verified checkpoint it pauses on."""

        wait = _wait_descriptor(payload)
        row = self.connection.execute(
            "SELECT * FROM runtime_checkpoints WHERE run_id = ? AND checkpoint_id = ?",
            (run_id, wait["checkpoint_id"]),
        ).fetchone()
        if row is None:
            raise RuntimeStoreError(f"wait checkpoint does not exist: {wait['checkpoint_id']}")
        checkpoint = self._row_checkpoint(row)
        if checkpoint["event_sequence"] != wait["checkpoint_sequence"]:
            raise RuntimeStoreError("wait checkpoint sequence does not match checkpoint metadata")
        if checkpoint["event_hash"] != wait["checkpoint_event_hash"]:
            raise RuntimeStoreError("wait checkpoint hash does not match checkpoint metadata")
        if checkpoint["event_sequence"] != state["sequence"]:
            raise RuntimeStoreError("wait checkpoint is not the current verified event boundary")
        if checkpoint["state"] != state or checkpoint["state_digest"] != _digest(state):
            raise RuntimeStoreError("wait checkpoint state does not match the current verified state")

    def _append_locked(
        self,
        run_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        occurred_at: str,
        effect: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_payload = _payload(payload)
        existing_row = self.connection.execute(
            "SELECT run_id, sequence, event_id, event_type, idempotency_key, occurred_at, "
            "payload_json, previous_hash, event_hash FROM runtime_events "
            "WHERE run_id = ? AND idempotency_key = ?",
            (run_id, idempotency_key),
        ).fetchone()
        if existing_row is not None:
            existing = self._row_event(existing_row)
            if existing["event_type"] != event_type or existing["payload"] != normalized_payload:
                raise RuntimeStoreError(f"idempotency key was reused with different event data: {idempotency_key}")
            if effect is not None:
                effect_row = self.connection.execute(
                    "SELECT * FROM runtime_outbox WHERE source_event_id = ?",
                    (existing["event_id"],),
                ).fetchone()
                if effect_row is None or not self._effect_matches(effect_row, effect):
                    raise RuntimeStoreError(f"effect intent is missing or conflicting: {effect['effect_id']}")
            replay(self._run(run_id), self._events(run_id))
            return existing

        run = self._run(run_id)
        events = self._events(run_id)
        state = replay(run, events)
        if event_type not in EVENT_TYPES:
            raise RuntimeStoreError(f"unsupported event type: {event_type}")
        if event_type == "run.started" and events:
            raise RuntimeStoreError("run.started is only valid when creating a run")
        if effect is not None and event_type.startswith("task.") and normalized_payload.get("task_id") != effect["task_id"]:
            raise RuntimeStoreError("effect.task_id must match payload.task_id")
        sequence = len(events) + 1
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "event_id": _event_id(run_id, idempotency_key),
            "event_type": event_type,
            "run_id": run_id,
            "sequence": sequence,
            "occurred_at": _timestamp(occurred_at),
            "idempotency_key": _text(idempotency_key, "idempotency_key"),
            "payload": normalized_payload,
            "previous_hash": events[-1]["event_hash"] if events else GENESIS_HASH,
            "event_hash": "",
        }
        event["event_hash"] = _hash_event(event)
        if event_type == "wait.created":
            self._validate_wait_checkpoint_locked(run_id, state, normalized_payload)
        apply_event(state, event)
        self.connection.execute(
            "INSERT INTO runtime_events(run_id, sequence, event_id, event_type, idempotency_key, "
            "occurred_at, payload_json, previous_hash, event_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                sequence,
                event["event_id"],
                event_type,
                idempotency_key,
                event["occurred_at"],
                canonical_json(normalized_payload),
                event["previous_hash"],
                event["event_hash"],
            ),
        )
        if effect is not None:
            self._insert_outbox_locked(event, effect)
        return event

    @staticmethod
    def _row_event(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": row["run_id"],
            "sequence": row["sequence"],
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "idempotency_key": row["idempotency_key"],
            "occurred_at": row["occurred_at"],
            "payload": json.loads(row["payload_json"]),
            "previous_hash": row["previous_hash"],
            "event_hash": row["event_hash"],
        }

    @staticmethod
    def _row_outbox(row: sqlite3.Row) -> dict[str, Any]:
        RuntimeStore._validate_outbox_row(row)
        lease_policy = _lease_policy(json.loads(row["lease_policy_json"]))
        return {
            "schema_version": row["schema_version"],
            "effect_id": row["effect_id"],
            "run_id": row["run_id"],
            "source_event_id": row["source_event_id"],
            "effect_type": row["effect_type"],
            "task_id": row["task_id"],
            "activity_id": row["activity_id"],
            "activity_attempt": row["activity_attempt"],
            "effect_definition_revision": row["effect_definition_revision"],
            "idempotency_key": row["idempotency_key"],
            "effect_hash": row["effect_hash"],
            "payload": json.loads(row["payload_json"]),
            "status": row["status"],
            "available_at": row["available_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "delivery_attempts": row["delivery_attempts"],
            "last_attempt_at": row["last_attempt_at"],
            "lease_owner": row["lease_owner"],
            "lease_expires_at": row["lease_expires_at"],
            "lease_generation": row["lease_generation"],
            "lease": {
                "schema_version": LEASE_SCHEMA_VERSION,
                "owner": row["lease_owner"],
                "generation": row["lease_generation"],
                "started_at": row["lease_started_at"],
                "expires_at": row["lease_expires_at"],
                "deadline_at": row["lease_deadline_at"],
                "lease_seconds": row["lease_seconds"],
                "max_lease_seconds": row["max_lease_seconds"],
                "heartbeat_seconds": row["heartbeat_seconds"],
                "last_heartbeat_at": row["last_heartbeat_at"],
                "heartbeat_count": row["heartbeat_count"],
                "policy_revisions": lease_policy["policy_revisions"],
            },
            "last_error_ref": row["last_error_ref"],
        }

    @staticmethod
    def _validate_outbox_row(row: sqlite3.Row) -> None:
        if row["schema_version"] != EFFECT_SCHEMA_VERSION:
            raise RuntimeStoreError(f"unsupported runtime effects schema: {row['schema_version']}")
        try:
            _lease_policy(json.loads(row["lease_policy_json"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeStoreError(f"invalid lease policy: {row['effect_id']}") from exc
        if row["lease_generation"] < 0 or row["heartbeat_count"] < 0:
            raise RuntimeStoreError(f"invalid lease counters: {row['effect_id']}")
        effect = {
            "schema_version": row["schema_version"],
            "effect_id": row["effect_id"],
            "run_id": row["run_id"],
            "effect_type": row["effect_type"],
            "task_id": row["task_id"],
            "activity_id": row["activity_id"],
            "activity_attempt": row["activity_attempt"],
            "effect_definition_revision": row["effect_definition_revision"],
            "idempotency_key": row["idempotency_key"],
            "payload": json.loads(row["payload_json"]),
        }
        expected_hash = _hash_outbox(effect, row["source_event_id"])
        if row["effect_hash"] != expected_hash:
            raise RuntimeStoreError(f"outbox effect hash mismatch: {row['effect_id']}")

    @staticmethod
    def _row_attempt(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "effect_id": row["effect_id"],
            "attempt": row["attempt"],
            "schema_version": row["schema_version"],
            "worker_id": row["worker_id"],
            "lease_generation": row["lease_generation"],
            "claimed_at": row["claimed_at"],
            "finished_at": row["finished_at"],
            "outcome": row["outcome"],
            "error_ref": row["error_ref"],
        }

    @staticmethod
    def _row_lease_event(row: sqlite3.Row) -> dict[str, Any]:
        if row["schema_version"] != LEASE_SCHEMA_VERSION:
            raise RuntimeStoreError(f"unsupported lease event schema: {row['schema_version']}")
        if row["event_type"] not in LEASE_EVENT_TYPES:
            raise RuntimeStoreError(f"unsupported lease event type: {row['event_type']}")
        details = json.loads(row["details_json"])
        if not isinstance(details, dict):
            raise RuntimeStoreError(f"lease event details must be an object: {row['event_id']}")
        _validate_payload_keys(details, "lease_event.details")
        return {
            "schema_version": row["schema_version"],
            "effect_id": row["effect_id"],
            "sequence": row["event_sequence"],
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "lease_generation": row["lease_generation"],
            "worker_id": row["worker_id"],
            "occurred_at": row["occurred_at"],
            "lease_expires_at": row["lease_expires_at"],
            "lease_deadline_at": row["lease_deadline_at"],
            "details": details,
        }

    @staticmethod
    def _row_checkpoint(row: sqlite3.Row) -> dict[str, Any]:
        if row["schema_version"] != CHECKPOINT_SCHEMA_VERSION:
            raise RuntimeStoreError(f"unsupported checkpoint schema: {row['schema_version']}")
        if row["runtime_schema_version"] not in {2, DATABASE_SCHEMA_VERSION}:
            raise RuntimeStoreError(
                f"checkpoint {row['checkpoint_id']} targets unsupported runtime schema "
                f"{row['runtime_schema_version']}"
            )
        if not HASH_RE.fullmatch(str(row["event_hash"])) or not HASH_RE.fullmatch(str(row["state_digest"])):
            raise RuntimeStoreError(f"checkpoint hashes are invalid: {row['checkpoint_id']}")
        state = json.loads(row["state_json"])
        if not isinstance(state, dict):
            raise RuntimeStoreError(f"checkpoint state must be an object: {row['checkpoint_id']}")
        _payload(state, "checkpoint.state")
        if _digest(state) != row["state_digest"]:
            raise RuntimeStoreError(f"checkpoint state digest mismatch: {row['checkpoint_id']}")
        return {
            "schema_version": row["schema_version"],
            "run_id": row["run_id"],
            "checkpoint_id": row["checkpoint_id"],
            "runtime_schema_version": row["runtime_schema_version"],
            "event_sequence": row["event_sequence"],
            "event_hash": row["event_hash"],
            "workflow_id": row["workflow_id"],
            "definition_version": row["definition_version"],
            "policy_revision": row["policy_revision"],
            "state": state,
            "state_digest": row["state_digest"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _row_inbox(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": row["schema_version"],
            "idempotency_key": row["idempotency_key"],
            "effect_id": row["effect_id"],
            "run_id": row["run_id"],
            "receipt": json.loads(row["receipt_json"]),
            "received_at": row["received_at"],
        }

    def _outbox_locked(self, effect_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM runtime_outbox WHERE effect_id = ?",
            (effect_id,),
        ).fetchone()
        if row is None:
            raise RuntimeStoreError(f"unknown effect: {effect_id}")
        self._validate_outbox_row(row)
        return row

    def _append_lease_event_locked(
        self,
        row: sqlite3.Row,
        event_type: str,
        *,
        worker_id: str,
        occurred_at: str,
        details: Mapping[str, Any] | None = None,
        lease_expires_at: str | None = None,
        lease_deadline_at: str | None = None,
    ) -> None:
        if event_type not in LEASE_EVENT_TYPES:
            raise RuntimeStoreError(f"unsupported lease event type: {event_type}")
        worker_id = _identifier(worker_id, "worker_id")
        generation = _positive_int(row["lease_generation"], "lease_generation")
        normalized_details = _payload(details or {})
        event_sequence = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(event_sequence), 0) + 1 FROM runtime_outbox_lease_events "
                "WHERE effect_id = ?",
                (row["effect_id"],),
            ).fetchone()[0]
        )
        event_material = canonical_json(
            {
                "effect_id": row["effect_id"],
                "event_sequence": event_sequence,
                "event_type": event_type,
                "lease_generation": generation,
                "worker_id": worker_id,
                "occurred_at": occurred_at,
                "details": normalized_details,
            }
        )
        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"forge-lease:{event_material}"))
        self.connection.execute(
            "INSERT INTO runtime_outbox_lease_events(effect_id, event_sequence, event_id, schema_version, "
            "event_type, lease_generation, worker_id, occurred_at, lease_expires_at, lease_deadline_at, details_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["effect_id"],
                event_sequence,
                event_id,
                LEASE_SCHEMA_VERSION,
                event_type,
                generation,
                worker_id,
                occurred_at,
                lease_expires_at,
                lease_deadline_at,
                canonical_json(normalized_details),
            ),
        )

    def _require_current_lease_locked(
        self,
        row: sqlite3.Row,
        worker_id: str,
        lease_generation: int,
        now: str,
    ) -> sqlite3.Row:
        if lease_generation != row["lease_generation"]:
            raise RuntimeStoreError(
                f"lease generation mismatch for effect {row['effect_id']}: "
                f"expected {row['lease_generation']}, got {lease_generation}"
            )
        if row["status"] != "leased" or row["lease_owner"] != worker_id:
            raise RuntimeStoreError(f"effect is not leased to worker: {row['effect_id']}")
        if not row["lease_expires_at"] or _utc_timestamp(now) >= row["lease_expires_at"]:
            raise RuntimeStoreError(f"lease has expired: {row['effect_id']}")
        if row["lease_deadline_at"] and _utc_timestamp(now) >= row["lease_deadline_at"]:
            raise RuntimeStoreError(f"lease deadline has passed: {row['effect_id']}")
        return row

    def _inbox_for_effect_locked(self, effect_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT i.*, o.run_id FROM runtime_inbox AS i "
            "JOIN runtime_outbox AS o ON o.effect_id = i.effect_id "
            "WHERE i.effect_id = ?",
            (effect_id,),
        ).fetchone()

    @staticmethod
    def _effect_matches(row: sqlite3.Row, effect: Mapping[str, Any]) -> bool:
        for field in (
            "effect_id",
            "run_id",
            "idempotency_key",
            "effect_type",
            "task_id",
            "activity_id",
            "effect_definition_revision",
        ):
            if row[field] != effect[field]:
                return False
        return row["activity_attempt"] == effect["activity_attempt"] and json.loads(
            row["payload_json"]
        ) == effect["payload"]

    def _insert_outbox_locked(self, event: Mapping[str, Any], effect: Mapping[str, Any]) -> None:
        existing = self.connection.execute(
            "SELECT * FROM runtime_outbox WHERE effect_id = ? OR idempotency_key = ? "
            "OR source_event_id = ?",
            (effect["effect_id"], effect["idempotency_key"], event["event_id"]),
        ).fetchone()
        if existing is not None:
            self._validate_outbox_row(existing)
            if existing["source_event_id"] == event["event_id"] and self._effect_matches(existing, effect):
                return
            raise RuntimeStoreError(f"effect identity already exists: {effect['effect_id']}")
        created_at = _utc_timestamp(event["occurred_at"])
        try:
            self.connection.execute(
                "INSERT INTO runtime_outbox(effect_id, run_id, source_event_id, schema_version, "
                "effect_type, task_id, activity_id, activity_attempt, effect_definition_revision, "
                "idempotency_key, effect_hash, payload_json, status, available_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (
                    effect["effect_id"],
                    effect["run_id"],
                    event["event_id"],
                    EFFECT_SCHEMA_VERSION,
                    effect["effect_type"],
                    effect["task_id"],
                    effect["activity_id"],
                    effect["activity_attempt"],
                    effect["effect_definition_revision"],
                    effect["idempotency_key"],
                    _hash_outbox(effect, event["event_id"]),
                    canonical_json(effect["payload"]),
                    created_at,
                    created_at,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise RuntimeStoreError(f"effect identity already exists: {effect['effect_id']}") from exc

    def start_run(
        self,
        run_id: str,
        workflow_id: str,
        definition_version: str,
        policy_revision: str,
        *,
        idempotency_key: str = "run.started",
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        run_id = _identifier(run_id, "run_id")
        workflow_id = _identifier(workflow_id, "workflow_id")
        definition_version = _text(definition_version, "definition_version")
        policy_revision = _text(policy_revision, "policy_revision")
        idempotency_key = _text(idempotency_key, "idempotency_key")
        occurred_at = _timestamp(occurred_at or utc_now())
        with self._transaction():
            existing = self.connection.execute(
                "SELECT run_id, workflow_id, definition_version, policy_revision, started_at "
                "FROM runtime_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if existing is None:
                self.connection.execute(
                    "INSERT INTO runtime_runs(run_id, workflow_id, definition_version, policy_revision, started_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (run_id, workflow_id, definition_version, policy_revision, occurred_at),
                )
            else:
                if any(
                    existing[field] != expected
                    for field, expected in (
                        ("workflow_id", workflow_id),
                        ("definition_version", definition_version),
                        ("policy_revision", policy_revision),
                    )
                ):
                    raise RuntimeStoreError(f"run already exists with different definition: {run_id}")
                if not self._events(run_id):
                    raise RuntimeStoreError(f"run has no start event; refusing to reconstruct history: {run_id}")
            return self._append_locked(
                run_id,
                "run.started",
                {
                    "workflow_id": workflow_id,
                    "definition_version": definition_version,
                    "policy_revision": policy_revision,
                },
                idempotency_key,
                occurred_at,
            )

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str,
        occurred_at: str | None = None,
        effect: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = _identifier(run_id, "run_id")
        if event_type == "run.started":
            raise RuntimeStoreError("use start_run for run.started")
        normalized_effect = _normalize_effect(run_id, effect) if effect is not None else None
        with self._transaction():
            return self._append_locked(
                run_id,
                event_type,
                payload or {},
                idempotency_key,
                _timestamp(occurred_at or utc_now()),
                normalized_effect,
            )

    def create_wait(
        self,
        run_id: str,
        task_id: str,
        input_schema_digest: str,
        authorization_context_digest: str,
        *,
        wait_id: str,
        resume_contract: str,
        ttl_seconds: int,
        poll_interval_ms: int,
        expiration_outcome: str = "fail_run",
        policy_revision: str | None = None,
        idempotency_key: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        """Checkpoint a run and atomically create one durable input wait."""

        run_id = _identifier(run_id, "run_id")
        task_id = _identifier(task_id, "task_id")
        wait_id = _identifier(wait_id, "wait_id")
        input_schema_digest = _digest_reference(input_schema_digest, "input_schema_digest")
        authorization_context_digest = _digest_reference(
            authorization_context_digest, "authorization_context_digest"
        )
        resume_contract = _text(resume_contract, "resume_contract")
        ttl_seconds = _positive_int(ttl_seconds, "ttl_seconds", maximum=2_592_000)
        poll_interval_ms = _positive_int(poll_interval_ms, "poll_interval_ms", maximum=3_600_000)
        if expiration_outcome not in EXPIRATION_OUTCOMES:
            expected = ", ".join(sorted(EXPIRATION_OUTCOMES))
            raise RuntimeStoreError(f"expiration_outcome must be one of: {expected}")
        occurred_at = _utc_timestamp(occurred_at or utc_now())
        idempotency_key = _text(
            idempotency_key or _derived_idempotency_key("wait.created", wait_id), "idempotency_key"
        )
        with self._transaction():
            run = self._run(run_id)
            expected_policy_revision = policy_revision or run["policy_revision"]
            expected_expires_at = _after_seconds(occurred_at, ttl_seconds)
            existing_row = self.connection.execute(
                "SELECT run_id, sequence, event_id, event_type, idempotency_key, occurred_at, "
                "payload_json, previous_hash, event_hash FROM runtime_events "
                "WHERE run_id = ? AND idempotency_key = ?",
                (run_id, idempotency_key),
            ).fetchone()
            if existing_row is not None:
                existing = self._row_event(existing_row)
                expected = {
                    "wait_id": wait_id,
                    "task_id": task_id,
                    "input_schema_digest": input_schema_digest,
                    "authorization_context_digest": authorization_context_digest,
                    "policy_revision": expected_policy_revision,
                    "expiration_outcome": expiration_outcome,
                    "resume_contract": resume_contract,
                    "ttl_seconds": ttl_seconds,
                    "poll_interval_ms": poll_interval_ms,
                }
                if existing["event_type"] != "wait.created" or any(
                    existing["payload"].get(key) != value for key, value in expected.items()
                ):
                    raise RuntimeStoreError(f"idempotency key was reused with different wait data: {idempotency_key}")
                replay(self._run(run_id), self._events(run_id))
                return existing
            state = replay(run, self._events(run_id))
            if state["status"] != "running":
                raise RuntimeStoreError(f"wait.created is invalid while run is {state['status']}")
            if policy_revision is None:
                policy_revision = state["policy_revision"]
            policy_revision = _text(policy_revision, "policy_revision")
            if policy_revision != state["policy_revision"]:
                raise RuntimeStoreError("wait policy revision does not match run policy revision")
            current_task = state["tasks"].get(task_id)
            if current_task is None or current_task["status"] != "started":
                raise RuntimeStoreError(f"wait task must be started: {task_id}")
            if any(item["status"] == "input_required" for item in state["waits"].values()):
                raise RuntimeStoreError("run already has an active input wait")
            checkpoint = self._checkpoint_locked(run_id, created_at=occurred_at)
            payload = {
                "wait_id": wait_id,
                "task_id": task_id,
                "checkpoint_id": checkpoint["checkpoint_id"],
                "checkpoint_sequence": checkpoint["event_sequence"],
                "checkpoint_event_hash": checkpoint["event_hash"],
                "input_schema_digest": input_schema_digest,
                "policy_revision": policy_revision,
                "authorization_context_digest": authorization_context_digest,
                "expires_at": expected_expires_at,
                "ttl_seconds": ttl_seconds,
                "poll_interval_ms": poll_interval_ms,
                "expiration_outcome": expiration_outcome,
                "resume_contract": resume_contract,
            }
            return self._append_locked(run_id, "wait.created", payload, idempotency_key, occurred_at)

    def submit_input(
        self,
        run_id: str,
        wait_id: str,
        submission_id: str,
        input_digest: str,
        authorization_context_digest: str,
        *,
        input_schema_digest: str,
        idempotency_key: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        wait_id = _identifier(wait_id, "wait_id")
        return self.append_event(
            run_id,
            "wait.input_submitted",
            {
                "wait_id": wait_id,
                "submission_id": _identifier(submission_id, "submission_id"),
                "input_digest": _digest_reference(input_digest, "input_digest"),
                "input_schema_digest": _digest_reference(input_schema_digest, "input_schema_digest"),
                "authorization_context_digest": _digest_reference(
                    authorization_context_digest, "authorization_context_digest"
                ),
            },
            idempotency_key=idempotency_key or _derived_idempotency_key("wait.input_submitted", wait_id),
            occurred_at=occurred_at,
        )

    def receive_signal(
        self,
        run_id: str,
        signal_id: str,
        signal_type: str,
        payload_digest: str,
        authorization_context_digest: str,
        *,
        wait_id: str | None = None,
        idempotency_key: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        signal_id = _identifier(signal_id, "signal_id")
        if signal_type not in SIGNAL_TYPES:
            expected = ", ".join(sorted(SIGNAL_TYPES))
            raise RuntimeStoreError(f"signal_type must be one of: {expected}")
        payload = {
            "signal_id": signal_id,
            "signal_type": signal_type,
            "payload_digest": _digest_reference(payload_digest, "payload_digest"),
            "authorization_context_digest": _digest_reference(
                authorization_context_digest, "authorization_context_digest"
            ),
        }
        if wait_id is not None:
            payload["wait_id"] = _identifier(wait_id, "wait_id")
        return self.append_event(
            run_id,
            "signal.received",
            payload,
            idempotency_key=idempotency_key or _derived_idempotency_key("signal.received", signal_id),
            occurred_at=occurred_at,
        )

    def expire_wait(
        self,
        run_id: str,
        wait_id: str,
        *,
        error_ref: str | None = None,
        idempotency_key: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        run_id = _identifier(run_id, "run_id")
        wait_id = _identifier(wait_id, "wait_id")
        wait = self.state(run_id)["waits"].get(wait_id)
        if wait is None:
            raise RuntimeStoreError(f"unknown wait: {wait_id}")
        payload: dict[str, Any] = {
            "wait_id": wait_id,
            "expiration_outcome": wait["expiration_outcome"],
        }
        if error_ref is not None:
            payload["error_ref"] = _text(error_ref, "error_ref")
        return self.append_event(
            run_id,
            "wait.expired",
            payload,
            idempotency_key=idempotency_key or _derived_idempotency_key("wait.expired", wait_id),
            occurred_at=occurred_at,
        )

    def request_cancel(
        self,
        run_id: str,
        *,
        reason_ref: str | None = None,
        authorization_context_digest: str | None = None,
        idempotency_key: str = "run.cancel_requested",
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if reason_ref is not None:
            payload["reason_ref"] = _text(reason_ref, "reason_ref")
        if authorization_context_digest is not None:
            payload["authorization_context_digest"] = _digest_reference(
                authorization_context_digest, "authorization_context_digest"
            )
        return self.append_event(
            run_id, "run.cancel_requested", payload, idempotency_key=idempotency_key, occurred_at=occurred_at
        )

    def acknowledge_cancel(
        self,
        run_id: str,
        *,
        ack_ref: str | None = None,
        authorization_context_digest: str | None = None,
        idempotency_key: str = "cancel.acknowledged",
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if ack_ref is not None:
            payload["ack_ref"] = _digest_reference(ack_ref, "ack_ref")
        if authorization_context_digest is not None:
            payload["authorization_context_digest"] = _digest_reference(
                authorization_context_digest, "authorization_context_digest"
            )
        return self.append_event(
            run_id, "cancel.acknowledged", payload, idempotency_key=idempotency_key, occurred_at=occurred_at
        )

    def cancel_run(
        self,
        run_id: str,
        *,
        idempotency_key: str = "run.cancelled",
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        return self.append_event(run_id, "run.cancelled", idempotency_key=idempotency_key, occurred_at=occurred_at)

    def cancel_confirmed(
        self,
        run_id: str,
        wait_id: str,
        authorization_context_digest: str,
        *,
        idempotency_prefix: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        """Atomically record MCP-style request, acknowledgement, and cancellation evidence."""

        run_id = _identifier(run_id, "run_id")
        wait_id = _identifier(wait_id, "wait_id")
        authorization_context_digest = _digest_reference(
            authorization_context_digest, "authorization_context_digest"
        )
        occurred_at = _utc_timestamp(occurred_at or utc_now())
        prefix = _text(
            idempotency_prefix
            or _derived_idempotency_key("mcp.cancel", _digest({"run_id": run_id, "wait_id": wait_id})),
            "idempotency_prefix",
        )
        with self._transaction():
            run = self._run(run_id)
            state = replay(run, self._events(run_id))
            wait = state["waits"].get(wait_id)
            if wait is None:
                raise RuntimeStoreError(f"unknown wait: {wait_id}")
            if wait["status"] not in {"input_required", "cancel_requested"}:
                raise RuntimeStoreError(f"wait is not cancellable: {wait_id}")
            if wait["authorization_context_digest"] != authorization_context_digest:
                raise RuntimeStoreError(f"wait authorization context mismatch: {wait_id}")
            if state["status"] != "cancelling":
                self._append_locked(
                    run_id,
                    "run.cancel_requested",
                    {"authorization_context_digest": authorization_context_digest},
                    f"{prefix}:requested",
                    occurred_at,
                )
                state = replay(run, self._events(run_id))
            if not state["cancel_acknowledged"]:
                self._append_locked(
                    run_id,
                    "cancel.acknowledged",
                    {
                        "ack_ref": _error_ref(f"{prefix}:ack"),
                        "authorization_context_digest": authorization_context_digest,
                    },
                    f"{prefix}:acknowledged",
                    occurred_at,
                )
            return self._append_locked(
                run_id,
                "run.cancelled",
                {},
                f"{prefix}:cancelled",
                occurred_at,
            )

    def list_waits(self, run_id: str) -> list[dict[str, Any]]:
        state = self.state(run_id)
        return [
            {"wait_id": wait_id, **wait}
            for wait_id, wait in sorted(state["waits"].items())
        ]

    def state(self, run_id: str) -> dict[str, Any]:
        run_id = _identifier(run_id, "run_id")
        run = self._run(run_id)
        return replay(run, self._events(run_id))

    def history(self, run_id: str) -> list[dict[str, Any]]:
        run_id = _identifier(run_id, "run_id")
        run = self._run(run_id)
        events = self._events(run_id)
        replay(run, events)
        return events

    def _checkpoint_locked(
        self,
        run_id: str,
        *,
        upto_sequence: int | None = None,
        created_at: str,
    ) -> dict[str, Any]:
        run = self._run(run_id)
        events = self._events(run_id)
        replay(run, events)
        sequence = len(events) if upto_sequence is None else upto_sequence
        if sequence < 1:
            raise RuntimeStoreError("cannot checkpoint an empty run history")
        if sequence > len(events):
            raise RuntimeStoreError(f"checkpoint sequence {sequence} is beyond verified history head {len(events)}")
        checkpoint_event = events[sequence - 1]
        state = _payload(replay(run, events[:sequence]), "checkpoint.state")
        state_digest = _digest(state)
        checkpoint_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "forge-checkpoint:" + canonical_json(
                    {
                        "run_id": run_id,
                        "event_sequence": sequence,
                        "event_hash": checkpoint_event["event_hash"],
                        "state_digest": state_digest,
                        "definition_version": run["definition_version"],
                        "policy_revision": run["policy_revision"],
                    }
                ),
            )
        )
        existing = self.connection.execute(
            "SELECT * FROM runtime_checkpoints WHERE run_id = ? AND checkpoint_id = ?",
            (run_id, checkpoint_id),
        ).fetchone()
        if existing is not None:
            checkpoint = self._row_checkpoint(existing)
            if checkpoint["state_digest"] != state_digest or checkpoint["event_hash"] != checkpoint_event["event_hash"]:
                raise RuntimeStoreError(f"conflicting checkpoint identity: {checkpoint_id}")
            return checkpoint
        try:
            self.connection.execute(
                "INSERT INTO runtime_checkpoints(run_id, checkpoint_id, schema_version, runtime_schema_version, "
                "event_sequence, event_hash, workflow_id, definition_version, policy_revision, state_json, "
                "state_digest, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    checkpoint_id,
                    CHECKPOINT_SCHEMA_VERSION,
                    DATABASE_SCHEMA_VERSION,
                    sequence,
                    checkpoint_event["event_hash"],
                    run["workflow_id"],
                    run["definition_version"],
                    run["policy_revision"],
                    canonical_json(state),
                    state_digest,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise RuntimeStoreError(f"checkpoint identity already exists: {checkpoint_id}") from exc
        return self._row_checkpoint(
            self.connection.execute(
                "SELECT * FROM runtime_checkpoints WHERE run_id = ? AND checkpoint_id = ?",
                (run_id, checkpoint_id),
            ).fetchone()
        )

    def checkpoint_run(
        self,
        run_id: str,
        *,
        upto_sequence: int | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        """Persist a deterministic, hash-bound state snapshot at an event boundary."""

        run_id = _identifier(run_id, "run_id")
        if upto_sequence is not None:
            _positive_int(upto_sequence, "upto_sequence")
        created_at = _utc_timestamp(created_at or utc_now())
        with self._transaction():
            return self._checkpoint_locked(run_id, upto_sequence=upto_sequence, created_at=created_at)

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        run_id = _identifier(run_id, "run_id")
        self._run(run_id)
        rows = self.connection.execute(
            "SELECT * FROM runtime_checkpoints WHERE run_id = ? ORDER BY event_sequence DESC, checkpoint_id",
            (run_id,),
        ).fetchall()
        return [self._row_checkpoint(row) for row in rows]

    def _validate_checkpoint_candidate(
        self,
        row: sqlite3.Row,
        run: Mapping[str, Any],
        events: list[Mapping[str, Any]],
        valid_sequence: int,
    ) -> dict[str, Any]:
        checkpoint = self._row_checkpoint(row)
        if checkpoint["runtime_schema_version"] != DATABASE_SCHEMA_VERSION:
            raise RuntimeStoreError(
                f"checkpoint {checkpoint['checkpoint_id']} targets legacy runtime schema "
                f"{checkpoint['runtime_schema_version']}; create a v{DATABASE_SCHEMA_VERSION} checkpoint"
            )
        if checkpoint["run_id"] != run["run_id"]:
            raise RuntimeStoreError("checkpoint run_id does not match its stream")
        if any(
            checkpoint[field] != run[field]
            for field in ("workflow_id", "definition_version", "policy_revision")
        ):
            raise RuntimeStoreError(f"checkpoint metadata is incompatible with run {run['run_id']}")
        sequence = checkpoint["event_sequence"]
        if sequence < 1 or sequence > valid_sequence or sequence > len(events):
            raise RuntimeStoreError(f"checkpoint sequence is outside the verified history: {sequence}")
        event = events[sequence - 1]
        if event.get("sequence") != sequence or event.get("event_hash") != checkpoint["event_hash"]:
            raise RuntimeStoreError(f"checkpoint event head does not match history at sequence {sequence}")
        prefix_state = replay(run, list(events[:sequence]))
        if checkpoint["state"] != prefix_state or checkpoint["state_digest"] != _digest(prefix_state):
            raise RuntimeStoreError(f"checkpoint state digest mismatch: {checkpoint['checkpoint_id']}")
        return checkpoint

    def restore_state(self, run_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
        with self._read_transaction():
            return self._restore_state(run_id, checkpoint_id)

    def _restore_state(self, run_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
        """Restore from the newest valid checkpoint and replay only a verified suffix."""

        run_id = _identifier(run_id, "run_id")
        checkpoint_id = _text(checkpoint_id, "checkpoint_id") if checkpoint_id is not None else None
        run = self._run(run_id)
        events = self._events_for_restore(run_id)
        prefix_state, valid_sequence, history_error = _replay_prefix(run, events)
        if checkpoint_id is None:
            rows = self.connection.execute(
                "SELECT * FROM runtime_checkpoints WHERE run_id = ? ORDER BY event_sequence DESC, checkpoint_id",
                (run_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM runtime_checkpoints WHERE run_id = ? AND checkpoint_id = ?",
                (run_id, checkpoint_id),
            ).fetchall()
            if not rows:
                raise RuntimeStoreError(f"unknown checkpoint: {checkpoint_id}")
        invalid_reasons: list[str] = []
        selected: dict[str, Any] | None = None
        for row in rows:
            try:
                selected = self._validate_checkpoint_candidate(row, run, events, valid_sequence)
                break
            except (RuntimeStoreError, TypeError, ValueError, json.JSONDecodeError) as exc:
                reason = f"{row['checkpoint_id']}: {exc}"
                invalid_reasons.append(reason)
                if checkpoint_id is not None:
                    raise RuntimeStoreError(
                        f"checkpoint {checkpoint_id} is invalid; restore from a verified history prefix "
                        f"or migrate the checkpoint ({_error_ref(reason)})"
                    ) from exc
        if selected is None:
            state = prefix_state
            checkpoint_sequence = 0
            used_checkpoint_id = None
        else:
            state = selected["state"]
            checkpoint_sequence = selected["event_sequence"]
            used_checkpoint_id = selected["checkpoint_id"]
            for event in events[checkpoint_sequence:valid_sequence]:
                try:
                    state = apply_event(state, event)
                except (RuntimeStoreError, KeyError, TypeError, ValueError) as exc:
                    invalid_reasons.append(f"suffix sequence {event.get('sequence')}: {exc}")
                    break
        recovery_reasons = invalid_reasons[:]
        if history_error is not None:
            recovery_reasons.insert(0, history_error)
        recovery_error_ref = _error_ref("; ".join(recovery_reasons)) if recovery_reasons else None
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "run_id": run_id,
            "checkpoint_id": used_checkpoint_id,
            "checkpoint_sequence": checkpoint_sequence,
            "replayed_sequence": state["sequence"],
            "history_sequence": len(events),
            "history_head_hash": events[valid_sequence - 1]["event_hash"] if valid_sequence else GENESIS_HASH,
            "state": state,
            "state_digest": _digest(state),
            "recovered": bool(recovery_reasons),
            "recovery_error_ref": recovery_error_ref,
        }

    def list_outbox(self, run_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        self._require_database_schema()
        conditions = []
        parameters: list[Any] = []
        if run_id is not None:
            conditions.append("run_id = ?")
            parameters.append(_identifier(run_id, "run_id"))
        if status is not None:
            if status not in EFFECT_STATUSES:
                expected = ", ".join(sorted(EFFECT_STATUSES))
                raise RuntimeStoreError(f"status must be one of: {expected}")
            conditions.append("status = ?")
            parameters.append(status)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        rows = self.connection.execute(
            f"SELECT * FROM runtime_outbox{where} ORDER BY created_at, effect_id",
            parameters,
        ).fetchall()
        return [self._row_outbox(row) for row in rows]

    def list_inbox(self, run_id: str | None = None) -> list[dict[str, Any]]:
        self._require_database_schema()
        parameters: list[Any] = []
        where = ""
        if run_id is not None:
            where = " WHERE o.run_id = ?"
            parameters.append(_identifier(run_id, "run_id"))
        rows = self.connection.execute(
            "SELECT i.*, o.run_id FROM runtime_inbox AS i "
            "JOIN runtime_outbox AS o ON o.effect_id = i.effect_id"
            f"{where} ORDER BY i.received_at, i.idempotency_key",
            parameters,
        ).fetchall()
        results = []
        for row in rows:
            self._outbox_locked(row["effect_id"])
            results.append(self._row_inbox(row))
        return results

    def outbox_attempts(self, effect_id: str) -> list[dict[str, Any]]:
        effect_id = _text(effect_id, "effect_id")
        self._outbox_locked(effect_id)
        rows = self.connection.execute(
            "SELECT * FROM runtime_outbox_attempts WHERE effect_id = ? ORDER BY attempt",
            (effect_id,),
        ).fetchall()
        return [self._row_attempt(row) for row in rows]

    def lease_events(self, effect_id: str) -> list[dict[str, Any]]:
        effect_id = _text(effect_id, "effect_id")
        self._outbox_locked(effect_id)
        rows = self.connection.execute(
            "SELECT * FROM runtime_outbox_lease_events WHERE effect_id = ? ORDER BY event_sequence",
            (effect_id,),
        ).fetchall()
        return [self._row_lease_event(row) for row in rows]

    def claim_outbox(
        self,
        worker_id: str,
        *,
        limit: int = 1,
        lease_seconds: int = 60,
        max_lease_seconds: int | None = None,
        heartbeat_seconds: int | None = None,
        policy_revisions: Mapping[str, Any] | None = None,
        now: str | None = None,
    ) -> list[dict[str, Any]]:
        worker_id = _identifier(worker_id, "worker_id")
        limit = _positive_int(limit, "limit", maximum=100)
        lease_seconds = _positive_int(lease_seconds, "lease_seconds", maximum=86_400)
        max_lease_seconds = (
            lease_seconds
            if max_lease_seconds is None
            else _positive_int(max_lease_seconds, "max_lease_seconds", maximum=86_400)
        )
        if max_lease_seconds < lease_seconds:
            raise RuntimeStoreError("max_lease_seconds must be at least lease_seconds")
        heartbeat_seconds = (
            lease_seconds
            if heartbeat_seconds is None
            else _positive_int(heartbeat_seconds, "heartbeat_seconds", maximum=86_400)
        )
        if heartbeat_seconds > max_lease_seconds:
            raise RuntimeStoreError("heartbeat_seconds must be at most max_lease_seconds")
        now = _utc_timestamp(now or utc_now())
        lease_expires_at = _after_seconds(now, lease_seconds)
        lease_deadline_at = _after_seconds(now, max_lease_seconds)
        claimed: list[dict[str, Any]] = []
        with self._transaction():
            rows = self.connection.execute(
                "SELECT * FROM runtime_outbox WHERE "
                "(status IN ('pending', 'retry') AND available_at <= ?) OR "
                "(status = 'leased' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?) "
                "ORDER BY available_at, effect_id LIMIT ?",
                (now, now, limit),
            ).fetchall()
            for row in rows:
                if row["status"] == "leased":
                    closed = self.connection.execute(
                        "UPDATE runtime_outbox_attempts SET finished_at = ?, outcome = 'reclaimed' "
                        "WHERE effect_id = ? AND attempt = ? AND lease_generation = ? AND outcome = 'leased'",
                        (now, row["effect_id"], row["delivery_attempts"], row["lease_generation"]),
                    )
                    if closed.rowcount != 1:
                        raise RuntimeStoreError(f"leased effect attempt is missing: {row['effect_id']}")
                    self._append_lease_event_locked(
                        row,
                        "lease_lost",
                        worker_id=row["lease_owner"],
                        occurred_at=now,
                        details={"reason": "lease-expired", "reclaimed_by": worker_id},
                        lease_expires_at=row["lease_expires_at"],
                        lease_deadline_at=row["lease_deadline_at"],
                    )
                raw_policy = json.loads(row["lease_policy_json"])
                if raw_policy == {}:
                    pinned_policy = _lease_policy(
                        {
                            "schema_version": LEASE_SCHEMA_VERSION,
                            "policy_revisions": _policy_revisions(policy_revisions),
                        }
                    )
                else:
                    pinned_policy = _lease_policy(raw_policy)
                    if (
                        policy_revisions is not None
                        and pinned_policy["policy_revisions"] != _policy_revisions(policy_revisions)
                    ):
                        raise RuntimeStoreError(f"lease policy revision conflict: {row['effect_id']}")
                attempt = row["delivery_attempts"] + 1
                generation = max(row["lease_generation"] + 1, 1)
                self.connection.execute(
                    "UPDATE runtime_outbox SET status = 'leased', lease_owner = ?, "
                    "lease_expires_at = ?, delivery_attempts = ?, last_attempt_at = ?, "
                    "lease_generation = ?, lease_started_at = ?, lease_deadline_at = ?, "
                    "lease_seconds = ?, max_lease_seconds = ?, heartbeat_seconds = ?, "
                    "last_heartbeat_at = NULL, heartbeat_count = 0, lease_policy_json = ?, updated_at = ? "
                    "WHERE effect_id = ?",
                    (
                        worker_id,
                        lease_expires_at,
                        attempt,
                        now,
                        generation,
                        now,
                        lease_deadline_at,
                        lease_seconds,
                        max_lease_seconds,
                        heartbeat_seconds,
                        canonical_json(pinned_policy),
                        now,
                        row["effect_id"],
                    ),
                )
                self.connection.execute(
                    "INSERT INTO runtime_outbox_attempts(effect_id, attempt, schema_version, worker_id, "
                    "lease_generation, claimed_at, outcome) VALUES (?, ?, ?, ?, ?, ?, 'leased')",
                    (row["effect_id"], attempt, EFFECT_SCHEMA_VERSION, worker_id, generation, now),
                )
                current = self._outbox_locked(row["effect_id"])
                self._append_lease_event_locked(
                    current,
                    "claimed",
                    worker_id=worker_id,
                    occurred_at=now,
                    details={"attempt": attempt},
                    lease_expires_at=lease_expires_at,
                    lease_deadline_at=lease_deadline_at,
                )
                claimed.append(self._row_outbox(current))
        return claimed

    def _mark_outbox_succeeded_locked(self, row: sqlite3.Row, received_at: str) -> None:
        if row["status"] == "leased":
            updated_attempt = self.connection.execute(
                "UPDATE runtime_outbox_attempts SET finished_at = ?, outcome = 'succeeded' "
                "WHERE effect_id = ? AND attempt = ? AND lease_generation = ? AND outcome = 'leased'",
                (received_at, row["effect_id"], row["delivery_attempts"], row["lease_generation"]),
            )
            if updated_attempt.rowcount != 1:
                raise RuntimeStoreError(f"leased effect attempt is missing: {row['effect_id']}")
        self.connection.execute(
            "UPDATE runtime_outbox SET status = 'succeeded', lease_owner = NULL, "
            "lease_expires_at = NULL, lease_started_at = NULL, lease_deadline_at = NULL, "
            "lease_seconds = NULL, max_lease_seconds = NULL, heartbeat_seconds = NULL, updated_at = ? "
            "WHERE effect_id = ?",
            (received_at, row["effect_id"]),
        )

    def heartbeat_outbox(
        self,
        effect_id: str,
        worker_id: str,
        *,
        lease_generation: int,
        now: str | None = None,
    ) -> dict[str, Any]:
        effect_id = _text(effect_id, "effect_id")
        worker_id = _identifier(worker_id, "worker_id")
        lease_generation = _positive_int(lease_generation, "lease_generation")
        now = _utc_timestamp(now or utc_now())
        with self._transaction():
            row = self._outbox_locked(effect_id)
            self._require_current_lease_locked(row, worker_id, lease_generation, now)
            if row["heartbeat_seconds"] is None or row["lease_deadline_at"] is None:
                raise RuntimeStoreError(f"heartbeat policy is not pinned: {effect_id}")
            requested_expires_at = _after_seconds(now, row["heartbeat_seconds"])
            lease_expires_at = min(requested_expires_at, row["lease_deadline_at"])
            updated = self.connection.execute(
                "UPDATE runtime_outbox SET lease_expires_at = ?, last_heartbeat_at = ?, "
                "heartbeat_count = heartbeat_count + 1, updated_at = ? "
                "WHERE effect_id = ? AND status = 'leased' AND lease_owner = ? "
                "AND lease_generation = ? AND lease_expires_at > ? AND lease_deadline_at > ?",
                (
                    lease_expires_at,
                    now,
                    now,
                    effect_id,
                    worker_id,
                    lease_generation,
                    now,
                    now,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeStoreError(f"lease was lost before heartbeat: {effect_id}")
            current = self._outbox_locked(effect_id)
            self._append_lease_event_locked(
                current,
                "heartbeat",
                worker_id=worker_id,
                occurred_at=now,
                details={
                    "extension_seconds": row["heartbeat_seconds"],
                    "bounded_by_deadline": lease_expires_at == row["lease_deadline_at"],
                },
                lease_expires_at=lease_expires_at,
                lease_deadline_at=row["lease_deadline_at"],
            )
            return self._row_outbox(current)

    def authorize_outbox_effect(
        self,
        effect_id: str,
        worker_id: str,
        *,
        lease_generation: int,
        now: str | None = None,
    ) -> dict[str, Any]:
        """Validate the lease context immediately before an adapter calls a provider."""

        effect_id = _text(effect_id, "effect_id")
        worker_id = _identifier(worker_id, "worker_id")
        lease_generation = _positive_int(lease_generation, "lease_generation")
        now = _utc_timestamp(now or utc_now())
        with self._transaction():
            row = self._outbox_locked(effect_id)
            self._require_current_lease_locked(row, worker_id, lease_generation, now)
            return {
                "effect_id": row["effect_id"],
                "idempotency_key": row["idempotency_key"],
                "worker_id": worker_id,
                "lease_generation": lease_generation,
                "lease_expires_at": row["lease_expires_at"],
                "lease_deadline_at": row["lease_deadline_at"],
            }

    def _record_inbox_locked(
        self, row: sqlite3.Row, receipt: Mapping[str, Any], received_at: str
    ) -> dict[str, Any]:
        existing = self.connection.execute(
            "SELECT i.*, o.run_id FROM runtime_inbox AS i "
            "JOIN runtime_outbox AS o ON o.effect_id = i.effect_id "
            "WHERE i.idempotency_key = ?",
            (row["idempotency_key"],),
        ).fetchone()
        if existing is not None:
            stored = self._row_inbox(existing)
            if stored["effect_id"] != row["effect_id"] or stored["receipt"] != receipt:
                raise RuntimeStoreError(f"conflicting inbox receipt: {row['idempotency_key']}")
            if row["status"] != "succeeded":
                self._mark_outbox_succeeded_locked(row, received_at)
            return stored["receipt"]
        if row["status"] == "succeeded":
            raise RuntimeStoreError(f"succeeded effect is missing its inbox receipt: {row['effect_id']}")
        try:
            self.connection.execute(
                "INSERT INTO runtime_inbox(idempotency_key, effect_id, schema_version, receipt_json, received_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    row["idempotency_key"],
                    row["effect_id"],
                    EFFECT_SCHEMA_VERSION,
                    canonical_json(receipt),
                    received_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise RuntimeStoreError(f"conflicting inbox receipt: {row['idempotency_key']}") from exc
        self._mark_outbox_succeeded_locked(row, received_at)
        return dict(receipt)

    def acknowledge_outbox(
        self,
        effect_id: str,
        worker_id: str,
        receipt: Mapping[str, Any],
        *,
        lease_generation: int,
        received_at: str | None = None,
    ) -> dict[str, Any]:
        effect_id = _text(effect_id, "effect_id")
        worker_id = _identifier(worker_id, "worker_id")
        lease_generation = _positive_int(lease_generation, "lease_generation")
        receipt = _receipt(receipt)
        received_at = _utc_timestamp(received_at or utc_now())
        with self._transaction():
            row = self._outbox_locked(effect_id)
            if lease_generation != row["lease_generation"]:
                raise RuntimeStoreError(
                    f"lease generation mismatch for effect {effect_id}: "
                    f"expected {row['lease_generation']}, got {lease_generation}"
                )
            if row["status"] == "succeeded":
                existing = self._inbox_for_effect_locked(effect_id)
                if existing is None or self._row_inbox(existing)["receipt"] != receipt:
                    raise RuntimeStoreError(f"conflicting inbox receipt: {row['idempotency_key']}")
                return dict(receipt)
            self._require_current_lease_locked(row, worker_id, lease_generation, received_at)
            return self._record_inbox_locked(row, receipt, received_at)

    def record_inbox(
        self,
        effect_id: str,
        receipt: Mapping[str, Any],
        *,
        received_at: str | None = None,
    ) -> dict[str, Any]:
        effect_id = _text(effect_id, "effect_id")
        receipt = _receipt(receipt)
        received_at = _utc_timestamp(received_at or utc_now())
        with self._transaction():
            return self._record_inbox_locked(self._outbox_locked(effect_id), receipt, received_at)

    def fail_outbox(
        self,
        effect_id: str,
        worker_id: str,
        *,
        lease_generation: int,
        error_ref: str,
        retryable: bool,
        next_attempt_at: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        effect_id = _text(effect_id, "effect_id")
        worker_id = _identifier(worker_id, "worker_id")
        lease_generation = _positive_int(lease_generation, "lease_generation")
        error_ref = _text(error_ref, "error_ref")
        if not isinstance(retryable, bool):
            raise RuntimeStoreError("retryable must be a boolean")
        now = _utc_timestamp(now or utc_now())
        with self._transaction():
            row = self._outbox_locked(effect_id)
            if lease_generation != row["lease_generation"]:
                raise RuntimeStoreError(
                    f"lease generation mismatch for effect {effect_id}: "
                    f"expected {row['lease_generation']}, got {lease_generation}"
                )
            self._require_current_lease_locked(row, worker_id, lease_generation, now)
            status = "retry" if retryable else "dead_letter"
            available_at = _utc_timestamp(next_attempt_at) if retryable and next_attempt_at else now
            outcome = "retry" if retryable else "dead_letter"
            updated_attempt = self.connection.execute(
                "UPDATE runtime_outbox_attempts SET finished_at = ?, outcome = ?, error_ref = ? "
                "WHERE effect_id = ? AND attempt = ? AND lease_generation = ? AND outcome = 'leased'",
                (now, outcome, error_ref, effect_id, row["delivery_attempts"], lease_generation),
            )
            if updated_attempt.rowcount != 1:
                raise RuntimeStoreError(f"leased effect attempt is missing: {effect_id}")
            self.connection.execute(
                "UPDATE runtime_outbox SET status = ?, available_at = ?, lease_owner = NULL, "
                "lease_expires_at = NULL, lease_started_at = NULL, lease_deadline_at = NULL, "
                "lease_seconds = NULL, max_lease_seconds = NULL, heartbeat_seconds = NULL, "
                "last_error_ref = ?, updated_at = ? WHERE effect_id = ?",
                (status, available_at, error_ref, now, effect_id),
            )
            return self._row_outbox(self._outbox_locked(effect_id))

    def list_runs(self) -> list[dict[str, Any]]:
        self._require_database_schema()
        rows = self.connection.execute(
            "SELECT run_id, workflow_id, definition_version, policy_revision, started_at "
            "FROM runtime_runs ORDER BY started_at, run_id"
        ).fetchall()
        results = []
        for row in rows:
            state = self.state(row["run_id"])
            results.append({**dict(row), "status": state["status"], "sequence": state["sequence"]})
        return results


def _parse_payload(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeStoreError(f"invalid --payload-json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeStoreError("--payload-json must contain a JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Forge local durable run history and deterministic replay")
    parser.add_argument("--db", type=Path, default=Path(".forge/runtime.sqlite3"), help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start a new run")
    start.add_argument("--run-id", required=True)
    start.add_argument("--workflow-id", required=True)
    start.add_argument("--definition-version", required=True)
    start.add_argument("--policy-revision", required=True)
    start.add_argument("--idempotency-key", default="run.started")
    start.add_argument("--occurred-at")

    append = sub.add_parser("append", help="append a lifecycle event")
    append.add_argument("--run-id", required=True)
    append.add_argument("--event-type", choices=[item for item in EVENT_TYPES if item != "run.started"], required=True)
    append.add_argument("--idempotency-key", required=True)
    append.add_argument("--payload-json", default="{}")
    append.add_argument("--effect-json", help="durable outbox effect descriptor as a JSON object")
    append.add_argument("--occurred-at")

    wait = sub.add_parser("wait", help="checkpoint a run and wait for one authorized input")
    wait.add_argument("--run-id", required=True)
    wait.add_argument("--task-id", required=True)
    wait.add_argument("--wait-id", required=True)
    wait.add_argument("--input-schema-digest", required=True)
    wait.add_argument("--authorization-context-digest", required=True)
    wait.add_argument("--resume-contract", required=True)
    wait.add_argument("--ttl-seconds", type=int, required=True)
    wait.add_argument("--poll-interval-ms", type=int, required=True)
    wait.add_argument("--expiration-outcome", choices=sorted(EXPIRATION_OUTCOMES), default="fail_run")
    wait.add_argument("--policy-revision")
    wait.add_argument("--idempotency-key")
    wait.add_argument("--occurred-at")

    waits = sub.add_parser("waits", help="list durable waits for a run")
    waits.add_argument("--run-id", required=True)
    submit = sub.add_parser("submit-input", help="submit one reference-only input response")
    submit.add_argument("--run-id", required=True)
    submit.add_argument("--wait-id", required=True)
    submit.add_argument("--submission-id", required=True)
    submit.add_argument("--input-digest", required=True)
    submit.add_argument("--input-schema-digest", required=True)
    submit.add_argument("--authorization-context-digest", required=True)
    submit.add_argument("--idempotency-key")
    submit.add_argument("--occurred-at")
    signal = sub.add_parser("signal", help="record one reference-only external signal")
    signal.add_argument("--run-id", required=True)
    signal.add_argument("--signal-id", required=True)
    signal.add_argument("--signal-type", choices=sorted(SIGNAL_TYPES), required=True)
    signal.add_argument("--payload-digest", required=True)
    signal.add_argument("--authorization-context-digest", required=True)
    signal.add_argument("--wait-id")
    signal.add_argument("--idempotency-key")
    signal.add_argument("--occurred-at")
    expire = sub.add_parser("expire-wait", help="record an expired wait after its persisted deadline")
    expire.add_argument("--run-id", required=True)
    expire.add_argument("--wait-id", required=True)
    expire.add_argument("--error-ref")
    expire.add_argument("--idempotency-key")
    expire.add_argument("--occurred-at")
    cancel_request = sub.add_parser("cancel-request", help="request durable run cancellation")
    cancel_request.add_argument("--run-id", required=True)
    cancel_request.add_argument("--reason-ref")
    cancel_request.add_argument("--authorization-context-digest")
    cancel_request.add_argument("--idempotency-key", default="run.cancel_requested")
    cancel_request.add_argument("--occurred-at")
    cancel_ack = sub.add_parser("cancel-ack", help="acknowledge cancellation handling")
    cancel_ack.add_argument("--run-id", required=True)
    cancel_ack.add_argument("--ack-ref")
    cancel_ack.add_argument("--authorization-context-digest")
    cancel_ack.add_argument("--idempotency-key", default="cancel.acknowledged")
    cancel_ack.add_argument("--occurred-at")
    cancel = sub.add_parser("cancel", help="record terminal run cancellation")
    cancel.add_argument("--run-id", required=True)
    cancel.add_argument("--idempotency-key", default="run.cancelled")
    cancel.add_argument("--occurred-at")

    for name in ("state", "history", "verify"):
        command = sub.add_parser(name, help=f"{name} a run")
        command.add_argument("--run-id", required=True)
    checkpoint = sub.add_parser("checkpoint", help="persist a deterministic verified run checkpoint")
    checkpoint.add_argument("--run-id", required=True)
    checkpoint.add_argument("--upto-sequence", type=int)
    checkpoint.add_argument("--created-at")
    checkpoints = sub.add_parser("checkpoints", help="list verified run checkpoints")
    checkpoints.add_argument("--run-id", required=True)
    restore = sub.add_parser("restore", help="restore from the newest valid checkpoint and event suffix")
    restore.add_argument("--run-id", required=True)
    restore.add_argument("--checkpoint-id")
    migrations = sub.add_parser("migrations", help="show the reviewed database migration registry")
    migrations.add_argument("--dry-run", action="store_true", help="show pending work without applying it")
    migrate = sub.add_parser("migrate", help="apply reviewed database migrations")
    migrate.add_argument("--target-version", type=int)
    migrate.add_argument("--dry-run", action="store_true", help="show pending work without applying it")
    outbox = sub.add_parser("outbox", help="list durable external-effect intents")
    outbox.add_argument("--run-id")
    outbox.add_argument("--status", choices=sorted(EFFECT_STATUSES))
    inbox = sub.add_parser("inbox", help="list durable external-effect receipts")
    inbox.add_argument("--run-id")
    attempts = sub.add_parser("attempts", help="list delivery attempts for an effect")
    attempts.add_argument("--effect-id", required=True)
    lease_events = sub.add_parser("lease-events", help="list lease and heartbeat evidence for an effect")
    lease_events.add_argument("--effect-id", required=True)
    sub.add_parser("list", help="list runs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store: RuntimeStore | None = None
    try:
        store = RuntimeStore(args.db, auto_migrate=False)
        if args.command == "start":
            result = store.start_run(
                args.run_id,
                args.workflow_id,
                args.definition_version,
                args.policy_revision,
                idempotency_key=args.idempotency_key,
                occurred_at=args.occurred_at,
            )
        elif args.command == "append":
            result = store.append_event(
                args.run_id,
                args.event_type,
                _parse_payload(args.payload_json),
                idempotency_key=args.idempotency_key,
                occurred_at=args.occurred_at,
                effect=_parse_payload(args.effect_json) if args.effect_json else None,
            )
        elif args.command == "wait":
            result = store.create_wait(
                args.run_id,
                args.task_id,
                args.input_schema_digest,
                args.authorization_context_digest,
                wait_id=args.wait_id,
                resume_contract=args.resume_contract,
                ttl_seconds=args.ttl_seconds,
                poll_interval_ms=args.poll_interval_ms,
                expiration_outcome=args.expiration_outcome,
                policy_revision=args.policy_revision,
                idempotency_key=args.idempotency_key,
                occurred_at=args.occurred_at,
            )
        elif args.command == "waits":
            result = store.list_waits(args.run_id)
        elif args.command == "submit-input":
            result = store.submit_input(
                args.run_id,
                args.wait_id,
                args.submission_id,
                args.input_digest,
                args.authorization_context_digest,
                input_schema_digest=args.input_schema_digest,
                idempotency_key=args.idempotency_key,
                occurred_at=args.occurred_at,
            )
        elif args.command == "signal":
            result = store.receive_signal(
                args.run_id,
                args.signal_id,
                args.signal_type,
                args.payload_digest,
                args.authorization_context_digest,
                wait_id=args.wait_id,
                idempotency_key=args.idempotency_key,
                occurred_at=args.occurred_at,
            )
        elif args.command == "expire-wait":
            result = store.expire_wait(
                args.run_id,
                args.wait_id,
                error_ref=args.error_ref,
                idempotency_key=args.idempotency_key,
                occurred_at=args.occurred_at,
            )
        elif args.command == "cancel-request":
            result = store.request_cancel(
                args.run_id,
                reason_ref=args.reason_ref,
                authorization_context_digest=args.authorization_context_digest,
                idempotency_key=args.idempotency_key,
                occurred_at=args.occurred_at,
            )
        elif args.command == "cancel-ack":
            result = store.acknowledge_cancel(
                args.run_id,
                ack_ref=args.ack_ref,
                authorization_context_digest=args.authorization_context_digest,
                idempotency_key=args.idempotency_key,
                occurred_at=args.occurred_at,
            )
        elif args.command == "cancel":
            result = store.cancel_run(
                args.run_id,
                idempotency_key=args.idempotency_key,
                occurred_at=args.occurred_at,
            )
        elif args.command == "state":
            result = store.state(args.run_id)
        elif args.command == "history":
            result = store.history(args.run_id)
        elif args.command == "verify":
            result = {"run_id": args.run_id, "state": store.state(args.run_id), "verified": True}
        elif args.command == "checkpoint":
            result = store.checkpoint_run(
                args.run_id,
                upto_sequence=args.upto_sequence,
                created_at=args.created_at,
            )
        elif args.command == "checkpoints":
            result = store.list_checkpoints(args.run_id)
        elif args.command == "restore":
            result = store.restore_state(args.run_id, args.checkpoint_id)
        elif args.command == "migrations":
            result = store.migration_status()
            result["dry_run"] = args.dry_run
        elif args.command == "migrate":
            result = store.migrate(target_version=args.target_version, dry_run=args.dry_run)
        elif args.command == "outbox":
            result = store.list_outbox(args.run_id, args.status)
        elif args.command == "inbox":
            result = store.list_inbox(args.run_id)
        elif args.command == "attempts":
            result = store.outbox_attempts(args.effect_id)
        elif args.command == "lease-events":
            result = store.lease_events(args.effect_id)
        else:
            result = store.list_runs()
        print(canonical_json(result))
        return 0
    except (RuntimeStoreError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"forge-runtime: {exc}", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
