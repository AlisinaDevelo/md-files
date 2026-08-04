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
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

try:
    from typing import Self
except ImportError:  # pragma: no cover - Python 3.10 and earlier
    Self = Any

SCHEMA_VERSION = 1
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
}
SENSITIVE_PAYLOAD_PARTS = {"authorization", "credential", "password", "prompt", "secret", "token"}


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


def _payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeStoreError("payload must be a JSON object")
    normalized = json.loads(canonical_json(dict(value)))
    _validate_payload_keys(normalized)
    return normalized


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
    ) -> dict[str, Any]:
        existing_row = self.connection.execute(
            "SELECT run_id, sequence, event_id, event_type, idempotency_key, occurred_at, "
            "payload_json, previous_hash, event_hash FROM runtime_events "
            "WHERE run_id = ? AND idempotency_key = ?",
            (run_id, idempotency_key),
        ).fetchone()
        normalized_payload = _payload(payload)
        if existing_row is not None:
            existing = self._row_event(existing_row)
            if existing["event_type"] != event_type or existing["payload"] != normalized_payload:
                raise RuntimeStoreError(f"idempotency key was reused with different event data: {idempotency_key}")
            replay(self._run(run_id), self._events(run_id))
            return existing

        run = self._run(run_id)
        events = self._events(run_id)
        state = replay(run, events)
        if event_type not in EVENT_TYPES:
            raise RuntimeStoreError(f"unsupported event type: {event_type}")
        if event_type == "run.started" and events:
            raise RuntimeStoreError("run.started is only valid when creating a run")
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
    ) -> dict[str, Any]:
        run_id = _identifier(run_id, "run_id")
        if event_type == "run.started":
            raise RuntimeStoreError("use start_run for run.started")
        with self._transaction():
            return self._append_locked(
                run_id,
                event_type,
                payload or {},
                idempotency_key,
                _timestamp(occurred_at or utc_now()),
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
    append.add_argument("--occurred-at")

    for name in ("state", "history", "verify"):
        command = sub.add_parser(name, help=f"{name} a run")
        command.add_argument("--run-id", required=True)
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
            )
        elif args.command == "state":
            result = store.state(args.run_id)
        elif args.command == "history":
            result = store.history(args.run_id)
        elif args.command == "verify":
            result = {"run_id": args.run_id, "state": store.state(args.run_id), "verified": True}
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
