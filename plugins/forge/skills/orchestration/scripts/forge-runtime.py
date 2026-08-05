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
    "task.scheduled",
    "task.started",
    "task.completed",
    "task.failed",
    "task.cancelled",
)
RUN_TERMINAL = {"completed", "failed", "cancelled"}
TASK_TERMINAL = {"completed", "failed", "cancelled"}
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
EFFECT_STATUSES = {"pending", "leased", "retry", "succeeded", "dead_letter"}
RECEIPT_STATUSES = {"accepted", "succeeded"}
ATTEMPT_OUTCOMES = {"leased", "reclaimed", "succeeded", "retry", "dead_letter"}


class RuntimeStoreError(ValueError):
    """Raised when runtime history or a state transition is invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


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


def _payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeStoreError("payload must be a JSON object")
    normalized = json.loads(canonical_json(dict(value)))
    _validate_payload_keys(normalized)
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
        _require_status(state, {"running", "paused"}, event_type)
        next_state["status"] = "cancelling"
    elif event_type == "run.cancelled":
        _require_status(state, {"cancelling"}, event_type)
        next_state["status"] = "cancelled"
    elif event_type == "run.failed":
        _require_status(state, {"running", "paused", "cancelling"}, event_type)
        next_state["status"] = "failed"
        if "error_ref" in payload:
            next_state["error_ref"] = _text(payload["error_ref"], "payload.error_ref")
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


def replay(run: Mapping[str, Any], events: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Verify the hash chain and rebuild state from the event prefix."""

    state = _run_state(run)
    previous_hash = GENESIS_HASH
    if events:
        first = events[0]
        if first["event_type"] != "run.started":
            raise RuntimeStoreError("run history must begin with run.started")
        if run["started_at"] != first["occurred_at"]:
            raise RuntimeStoreError("run metadata started_at does not match run.started")
    for event in events:
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
    claimed_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('leased', 'reclaimed', 'succeeded', 'retry', 'dead_letter')),
    error_ref TEXT,
    PRIMARY KEY (effect_id, attempt)
);
CREATE INDEX IF NOT EXISTS runtime_outbox_attempts_effect
    ON runtime_outbox_attempts(effect_id, attempt);
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

    def __init__(self, path: Path, *, timeout: float = 5.0) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=timeout, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute(f"PRAGMA busy_timeout = {max(1, int(timeout * 1000))}")
        journal_mode = str(self.connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
        if journal_mode != "wal":
            self.close()
            raise RuntimeStoreError(f"SQLite WAL is unavailable; got journal mode {journal_mode}")
        self.connection.executescript(SCHEMA_SQL)
        row = self.connection.execute("SELECT value FROM runtime_meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO runtime_meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        elif row["value"] != str(SCHEMA_VERSION):
            self.close()
            raise RuntimeStoreError(f"unsupported runtime database schema: {row['value']}")
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

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def _run(self, run_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT run_id, workflow_id, definition_version, policy_revision, started_at "
            "FROM runtime_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise RuntimeStoreError(f"unknown run: {run_id}")
        return dict(row)

    def _events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT run_id, sequence, event_id, event_type, idempotency_key, occurred_at, "
            "payload_json, previous_hash, event_hash FROM runtime_events "
            "WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            events.append(self._row_event(row))
        return events

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
            "last_error_ref": row["last_error_ref"],
        }

    @staticmethod
    def _validate_outbox_row(row: sqlite3.Row) -> None:
        if row["schema_version"] != EFFECT_SCHEMA_VERSION:
            raise RuntimeStoreError(f"unsupported runtime effects schema: {row['schema_version']}")
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
            "claimed_at": row["claimed_at"],
            "finished_at": row["finished_at"],
            "outcome": row["outcome"],
            "error_ref": row["error_ref"],
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

    def list_outbox(self, run_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
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

    def claim_outbox(
        self,
        worker_id: str,
        *,
        limit: int = 1,
        lease_seconds: int = 60,
        now: str | None = None,
    ) -> list[dict[str, Any]]:
        worker_id = _identifier(worker_id, "worker_id")
        limit = _positive_int(limit, "limit", maximum=100)
        lease_seconds = _positive_int(lease_seconds, "lease_seconds", maximum=86_400)
        now = _utc_timestamp(now or utc_now())
        lease_expires_at = _after_seconds(now, lease_seconds)
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
                        "WHERE effect_id = ? AND attempt = ? AND outcome = 'leased'",
                        (now, row["effect_id"], row["delivery_attempts"]),
                    )
                    if closed.rowcount != 1:
                        raise RuntimeStoreError(f"leased effect attempt is missing: {row['effect_id']}")
                attempt = row["delivery_attempts"] + 1
                self.connection.execute(
                    "UPDATE runtime_outbox SET status = 'leased', lease_owner = ?, "
                    "lease_expires_at = ?, delivery_attempts = ?, last_attempt_at = ?, updated_at = ? "
                    "WHERE effect_id = ?",
                    (worker_id, lease_expires_at, attempt, now, now, row["effect_id"]),
                )
                self.connection.execute(
                    "INSERT INTO runtime_outbox_attempts(effect_id, attempt, schema_version, worker_id, "
                    "claimed_at, outcome) VALUES (?, ?, ?, ?, ?, 'leased')",
                    (row["effect_id"], attempt, EFFECT_SCHEMA_VERSION, worker_id, now),
                )
                claimed.append(self._row_outbox(self._outbox_locked(row["effect_id"])))
        return claimed

    def _mark_outbox_succeeded_locked(self, row: sqlite3.Row, received_at: str) -> None:
        if row["status"] == "leased":
            updated_attempt = self.connection.execute(
                "UPDATE runtime_outbox_attempts SET finished_at = ?, outcome = 'succeeded' "
                "WHERE effect_id = ? AND attempt = ? AND outcome = 'leased'",
                (received_at, row["effect_id"], row["delivery_attempts"]),
            )
            if updated_attempt.rowcount != 1:
                raise RuntimeStoreError(f"leased effect attempt is missing: {row['effect_id']}")
        self.connection.execute(
            "UPDATE runtime_outbox SET status = 'succeeded', lease_owner = NULL, "
            "lease_expires_at = NULL, updated_at = ? WHERE effect_id = ?",
            (received_at, row["effect_id"]),
        )

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
        received_at: str | None = None,
    ) -> dict[str, Any]:
        effect_id = _text(effect_id, "effect_id")
        worker_id = _identifier(worker_id, "worker_id")
        receipt = _receipt(receipt)
        received_at = _utc_timestamp(received_at or utc_now())
        with self._transaction():
            row = self._outbox_locked(effect_id)
            if row["status"] == "succeeded":
                existing = self._inbox_for_effect_locked(effect_id)
                if existing is None or self._row_inbox(existing)["receipt"] != receipt:
                    raise RuntimeStoreError(f"conflicting inbox receipt: {row['idempotency_key']}")
                return dict(receipt)
            if row["status"] != "leased" or row["lease_owner"] != worker_id:
                raise RuntimeStoreError(f"effect is not leased to worker: {effect_id}")
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
        error_ref: str,
        retryable: bool,
        next_attempt_at: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        effect_id = _text(effect_id, "effect_id")
        worker_id = _identifier(worker_id, "worker_id")
        error_ref = _text(error_ref, "error_ref")
        if not isinstance(retryable, bool):
            raise RuntimeStoreError("retryable must be a boolean")
        now = _utc_timestamp(now or utc_now())
        with self._transaction():
            row = self._outbox_locked(effect_id)
            if row["status"] != "leased" or row["lease_owner"] != worker_id:
                raise RuntimeStoreError(f"effect is not leased to worker: {effect_id}")
            status = "retry" if retryable else "dead_letter"
            available_at = _utc_timestamp(next_attempt_at) if retryable and next_attempt_at else now
            outcome = "retry" if retryable else "dead_letter"
            updated_attempt = self.connection.execute(
                "UPDATE runtime_outbox_attempts SET finished_at = ?, outcome = ?, error_ref = ? "
                "WHERE effect_id = ? AND attempt = ? AND outcome = 'leased'",
                (now, outcome, error_ref, effect_id, row["delivery_attempts"]),
            )
            if updated_attempt.rowcount != 1:
                raise RuntimeStoreError(f"leased effect attempt is missing: {effect_id}")
            self.connection.execute(
                "UPDATE runtime_outbox SET status = ?, available_at = ?, lease_owner = NULL, "
                "lease_expires_at = NULL, last_error_ref = ?, updated_at = ? WHERE effect_id = ?",
                (status, available_at, error_ref, now, effect_id),
            )
            return self._row_outbox(self._outbox_locked(effect_id))

    def list_runs(self) -> list[dict[str, Any]]:
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

    for name in ("state", "history", "verify"):
        command = sub.add_parser(name, help=f"{name} a run")
        command.add_argument("--run-id", required=True)
    outbox = sub.add_parser("outbox", help="list durable external-effect intents")
    outbox.add_argument("--run-id")
    outbox.add_argument("--status", choices=sorted(EFFECT_STATUSES))
    inbox = sub.add_parser("inbox", help="list durable external-effect receipts")
    inbox.add_argument("--run-id")
    attempts = sub.add_parser("attempts", help="list delivery attempts for an effect")
    attempts.add_argument("--effect-id", required=True)
    sub.add_parser("list", help="list runs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store: RuntimeStore | None = None
    try:
        store = RuntimeStore(args.db)
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
        elif args.command == "state":
            result = store.state(args.run_id)
        elif args.command == "history":
            result = store.history(args.run_id)
        elif args.command == "verify":
            result = {"run_id": args.run_id, "state": store.state(args.run_id), "verified": True}
        elif args.command == "outbox":
            result = store.list_outbox(args.run_id, args.status)
        elif args.command == "inbox":
            result = store.list_inbox(args.run_id)
        elif args.command == "attempts":
            result = store.outbox_attempts(args.effect_id)
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
