#!/usr/bin/env python3
"""Negotiate Forge runtime backends and run deterministic conformance fixtures."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

BACKEND_SCHEMA_VERSION = 1
CONFORMANCE_SCHEMA_VERSION = 1
ADAPTER_EVIDENCE_SCHEMA_VERSION = 1
CONTRACT_REVISION = "forge-backend-v1"
BASE_TIME = "2026-08-05T00:00:00Z"
FAULT_POINTS = {"append.before_commit", "append.after_commit"}
CONSISTENCY_LEVELS = {"single_process", "strict_serializable"}
CAPABILITIES = {
    "append_ordering",
    "atomic_event_effect",
    "compare_and_swap",
    "fenced_leases",
    "durable_timers",
    "checkpoint_recovery",
    "inbox_dedupe",
    "migration",
    "backup_restore",
    "history_verification",
    "offline_lineage",
    "privacy_boundary",
}
CASE_CAPABILITIES = {
    "append-ordering": "append_ordering",
    "atomic-event-effect": "atomic_event_effect",
    "compare-and-swap-fencing": "fenced_leases",
    "durable-timer-wait": "durable_timers",
    "checkpoint-restore": "checkpoint_recovery",
    "inbox-dedupe": "inbox_dedupe",
    "migration": "migration",
    "backup-restore": "backup_restore",
    "history-verification": "history_verification",
    "privacy-boundary": "privacy_boundary",
    "ambiguous-commit": "atomic_event_effect",
    "adapter-evidence": "offline_lineage",
}
REFERENCE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class BackendContractError(ValueError):
    """Raised when a backend descriptor or negotiation request is invalid."""


class BackendUnsupported(BackendContractError):
    """Raised when a backend cannot provide a requested operation."""


class BackendFault(RuntimeError):
    """Raised by deterministic fault injection at a named commit boundary."""


def _load_runtime():
    path = Path(__file__).with_name("forge-runtime.py")
    spec = importlib.util.spec_from_file_location("forge_runtime_backend", path)
    if spec is None or spec.loader is None:
        raise BackendContractError(f"cannot load runtime store: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runtime = _load_runtime()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _error_ref(error: BaseException | str) -> str:
    return _digest(str(error))


def _descriptor(
    backend_id: str,
    implementation: str,
    consistency_level: str,
    *,
    degraded_mode: str,
    durable_storage: bool,
) -> dict[str, Any]:
    capabilities = sorted(CAPABILITIES | ({"durable_storage"} if durable_storage else set()))
    return {
        "schema_version": BACKEND_SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "backend_id": backend_id,
        "implementation": implementation,
        "consistency_level": consistency_level,
        "capabilities": capabilities,
        "limits": {
            "max_wait_ttl_seconds": 2_592_000,
            "max_signals_per_run": 256,
            "max_effects_per_append": 1,
        },
        "degraded_mode": degraded_mode,
        "event_identity": "forge-canonical",
        "remote_evidence": "reference-only",
        "provider_execution": "at-least-once-idempotent",
        "evidence_schema_version": ADAPTER_EVIDENCE_SCHEMA_VERSION,
    }


SQLITE_DESCRIPTOR = _descriptor(
    "sqlite-wal",
    "forge-runtime-sqlite",
    "strict_serializable",
    degraded_mode="reject",
    durable_storage=True,
)
MEMORY_DESCRIPTOR = _descriptor(
    "memory-fault",
    "forge-runtime-memory-fault",
    "single_process",
    degraded_mode="explicit",
    durable_storage=False,
)


def descriptor_for(kind: str) -> dict[str, Any]:
    if kind in {"sqlite", "sqlite-wal"}:
        return copy.deepcopy(SQLITE_DESCRIPTOR)
    if kind in {"memory", "memory-fault"}:
        return copy.deepcopy(MEMORY_DESCRIPTOR)
    raise BackendContractError(f"unknown backend: {kind}")


def validate_descriptor(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BackendContractError("backend descriptor must be an object")
    required = {
        "schema_version",
        "contract_revision",
        "backend_id",
        "implementation",
        "consistency_level",
        "capabilities",
        "limits",
        "degraded_mode",
        "event_identity",
        "remote_evidence",
        "provider_execution",
        "evidence_schema_version",
    }
    missing = sorted(required - set(value))
    if missing:
        raise BackendContractError("backend descriptor is missing: " + ", ".join(missing))
    if value["schema_version"] != BACKEND_SCHEMA_VERSION:
        raise BackendContractError(f"unsupported backend schema: {value['schema_version']}")
    for field in (
        "contract_revision",
        "backend_id",
        "implementation",
        "event_identity",
        "remote_evidence",
        "provider_execution",
    ):
        if not isinstance(value[field], str) or not value[field]:
            raise BackendContractError(f"{field} must be a non-empty string")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value["backend_id"]):
        raise BackendContractError("backend_id contains unsupported characters")
    if value["consistency_level"] not in CONSISTENCY_LEVELS:
        raise BackendContractError("unsupported consistency_level")
    capabilities = value["capabilities"]
    if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
        raise BackendContractError("capabilities must be a list of strings")
    if capabilities != sorted(set(capabilities)):
        raise BackendContractError("capabilities must be sorted and unique")
    unknown = sorted(set(capabilities) - CAPABILITIES - {"durable_storage"})
    if unknown:
        raise BackendContractError("capabilities contain unsupported names: " + ", ".join(unknown))
    if value["degraded_mode"] not in {"reject", "explicit"}:
        raise BackendContractError("degraded_mode must be reject or explicit")
    if value["evidence_schema_version"] != ADAPTER_EVIDENCE_SCHEMA_VERSION:
        raise BackendContractError("unsupported adapter evidence schema")
    limits = value["limits"]
    if not isinstance(limits, dict) or any(
        not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in limits.values()
    ):
        raise BackendContractError("limits must contain positive integer values")
    return copy.deepcopy(value)


def negotiate(descriptor: dict[str, Any], requirements: dict[str, Any]) -> dict[str, Any]:
    descriptor = validate_descriptor(descriptor)
    if not isinstance(requirements, dict):
        raise BackendContractError("negotiation requirements must be an object")
    required_capabilities = requirements.get("required_capabilities", requirements.get("capabilities", []))
    if not isinstance(required_capabilities, list) or any(
        not isinstance(item, str) for item in required_capabilities
    ):
        raise BackendContractError("required_capabilities must be a list of strings")
    required_capabilities = sorted(set(required_capabilities))
    required_revision = requirements.get("contract_revision", CONTRACT_REVISION)
    if not isinstance(required_revision, str) or not required_revision:
        raise BackendContractError("contract_revision must be a non-empty string")
    required_consistency = requirements.get("consistency_level")
    if required_consistency is not None and required_consistency not in CONSISTENCY_LEVELS:
        raise BackendContractError("unsupported required consistency_level")
    allow_degraded = requirements.get("allow_degraded", False)
    if not isinstance(allow_degraded, bool):
        raise BackendContractError("allow_degraded must be a boolean")
    available = set(descriptor["capabilities"])
    missing = sorted(set(required_capabilities) - available)
    consistency_mismatch = bool(
        required_consistency is not None and descriptor["consistency_level"] != required_consistency
    )
    revision_mismatch = descriptor["contract_revision"] != required_revision
    reasons = {
        "missing_capabilities": missing,
        "consistency_mismatch": consistency_mismatch,
        "revision_mismatch": revision_mismatch,
    }
    compatible = not missing and not consistency_mismatch and not revision_mismatch
    if compatible:
        status = "accepted"
    elif allow_degraded and descriptor["degraded_mode"] == "explicit":
        status = "degraded"
    else:
        status = "rejected"
    degradation_ref = None if compatible else _digest(reasons)
    return {
        "schema_version": BACKEND_SCHEMA_VERSION,
        "contract_revision": descriptor["contract_revision"],
        "backend_id": descriptor["backend_id"],
        "status": status,
        "required_capabilities": required_capabilities,
        "available_capabilities": descriptor["capabilities"],
        "required_consistency_level": required_consistency,
        "actual_consistency_level": descriptor["consistency_level"],
        "unsupported_capabilities": missing,
        "consistency_mismatch": consistency_mismatch,
        "revision_mismatch": revision_mismatch,
        "degradation_ref": degradation_ref,
    }


def _reference(value: Any, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not REFERENCE_RE.fullmatch(value):
        raise BackendContractError(f"{field} must be a sha256 reference")
    return value


def _short_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise BackendContractError(f"{field} must be a non-empty string of at most 128 characters")
    return value


class BackendAdapter:
    """Provider-neutral facade over the canonical Forge runtime store."""

    def __init__(self, store: Any, descriptor: dict[str, Any]) -> None:
        self.runtime = store
        self._descriptor = validate_descriptor(descriptor)
        self._faults: dict[str, int] = {}

    @property
    def descriptor(self) -> dict[str, Any]:
        return copy.deepcopy(self._descriptor)

    def adapter_evidence(
        self,
        *,
        revision_ref: str,
        transaction_ref: str | None,
        cursor_ref: str | None,
        compaction_ref: str | None,
        cloud_event: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize provider metadata without making it part of Forge history."""

        if not isinstance(cloud_event, dict):
            raise BackendContractError("cloud_event must be an object")
        allowed = {"source", "id", "type", "subject", "time", "data_ref"}
        unknown = sorted(set(cloud_event) - allowed)
        if unknown:
            raise BackendContractError("cloud_event contains unsupported fields: " + ", ".join(unknown))
        source = _short_text(cloud_event.get("source"), "cloud_event.source")
        event_id = _short_text(cloud_event.get("id"), "cloud_event.id")
        event_type = _short_text(cloud_event.get("type"), "cloud_event.type")
        event_time = runtime._timestamp(cloud_event.get("time"))
        normalized_event: dict[str, Any] = {
            "source": source,
            "id": event_id,
            "type": event_type,
            "time": event_time,
            "identity_ref": _digest({"source": source, "id": event_id}),
        }
        if "subject" in cloud_event:
            normalized_event["subject"] = _short_text(cloud_event["subject"], "cloud_event.subject")
        if "data_ref" in cloud_event:
            normalized_event["data_ref"] = _reference(cloud_event["data_ref"], "cloud_event.data_ref")
        return {
            "schema_version": ADAPTER_EVIDENCE_SCHEMA_VERSION,
            "backend_id": self._descriptor["backend_id"],
            "revision_ref": _reference(revision_ref, "revision_ref"),
            "transaction_ref": _reference(transaction_ref, "transaction_ref", allow_none=True),
            "cursor_ref": _reference(cursor_ref, "cursor_ref", allow_none=True),
            "compaction_ref": _reference(compaction_ref, "compaction_ref", allow_none=True),
            "cloud_event": normalized_event,
        }

    def fail_next(self, point: str) -> None:
        if point not in FAULT_POINTS:
            raise BackendContractError(f"unsupported fault point: {point}")
        self._faults[point] = self._faults.get(point, 0) + 1

    def _fault(self, point: str) -> None:
        remaining = self._faults.get(point, 0)
        if remaining < 1:
            return
        self._faults[point] = remaining - 1
        raise BackendFault(f"injected fault at {point}")

    def start_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.runtime.start_run(*args, **kwargs)

    def append_event(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._fault("append.before_commit")
        event = self.runtime.append_event(*args, **kwargs)
        self._fault("append.after_commit")
        return event

    def create_wait(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.runtime.create_wait(*args, **kwargs)

    def expire_wait(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.runtime.expire_wait(*args, **kwargs)

    def state(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.runtime.state(*args, **kwargs)

    def history(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self.runtime.history(*args, **kwargs)

    def checkpoint_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.runtime.checkpoint_run(*args, **kwargs)

    def restore_state(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.runtime.restore_state(*args, **kwargs)

    def list_outbox(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self.runtime.list_outbox(*args, **kwargs)

    def list_inbox(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self.runtime.list_inbox(*args, **kwargs)

    def claim_outbox(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self.runtime.claim_outbox(*args, **kwargs)

    def heartbeat_outbox(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.runtime.heartbeat_outbox(*args, **kwargs)

    def authorize_outbox_effect(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.runtime.authorize_outbox_effect(*args, **kwargs)

    def acknowledge_outbox(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.runtime.acknowledge_outbox(*args, **kwargs)

    def record_inbox(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.runtime.record_inbox(*args, **kwargs)

    def migration_status(self) -> dict[str, Any]:
        return self.runtime.migration_status()

    def migrate(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.runtime.migrate(*args, **kwargs)

    def backup_to(self, destination: Path) -> str:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            destination.unlink()
        target = sqlite3.connect(destination)
        try:
            self.runtime.connection.backup(target)
        finally:
            target.close()
        return _file_digest(destination)

    def restore_from_backup(self, source: Path) -> BackendAdapter:
        raise BackendUnsupported("backend does not expose a restore adapter")

    def close(self) -> None:
        self.runtime.close()


class SQLiteWALBackend(BackendAdapter):
    def __init__(self, path: Path) -> None:
        super().__init__(runtime.RuntimeStore(Path(path)), SQLITE_DESCRIPTOR)

    def restore_from_backup(self, source: Path) -> SQLiteWALBackend:
        return SQLiteWALBackend(Path(source))


class MemoryFaultBackend(BackendAdapter):
    def __init__(self) -> None:
        super().__init__(runtime.RuntimeStore(Path(":memory:")), MEMORY_DESCRIPTOR)

    def restore_from_backup(self, source: Path) -> MemoryFaultBackend:
        restored = MemoryFaultBackend()
        source_connection = sqlite3.connect(source)
        try:
            source_connection.backup(restored.runtime.connection)
        finally:
            source_connection.close()
        row = restored.runtime.connection.execute(
            "SELECT value FROM runtime_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            restored.close()
            raise BackendContractError("backup has no runtime schema version")
        restored.runtime.database_schema_version = int(row[0])
        return restored


def make_backend(kind: str, path: Path | None = None) -> BackendAdapter:
    if kind in {"sqlite", "sqlite-wal"}:
        if path is None:
            raise BackendContractError("sqlite backend requires a path")
        return SQLiteWALBackend(path)
    if kind in {"memory", "memory-fault"}:
        return MemoryFaultBackend()
    raise BackendContractError(f"unknown backend: {kind}")


def _start(adapter: BackendAdapter, run_id: str) -> None:
    adapter.start_run(
        run_id,
        "conformance-flow",
        "definition-v1",
        "policy-v1",
        occurred_at=BASE_TIME,
    )


def _effect(task_id: str = "build") -> dict[str, Any]:
    return {
        "effect_type": "conformance.effect",
        "task_id": task_id,
        "activity_id": "fixture-activity",
        "attempt": 1,
        "effect_definition_revision": "effect-v1",
        "payload": {"target_ref": "fixture:target", "request_digest": "sha256:" + "a" * 64},
    }


def _schedule(adapter: BackendAdapter, run_id: str, *, effect: bool = False) -> dict[str, Any]:
    return adapter.append_event(
        run_id,
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
        idempotency_key=f"{run_id}:task-build-scheduled",
        occurred_at="2026-08-05T00:01:00Z",
        effect=_effect() if effect else None,
    )


def _start_task(adapter: BackendAdapter, run_id: str) -> None:
    adapter.append_event(
        run_id,
        "task.started",
        {"task_id": "build", "attempt": 1},
        idempotency_key=f"{run_id}:task-build-started",
        occurred_at="2026-08-05T00:02:00Z",
    )


def _fixture_append_ordering(adapter: BackendAdapter, run_id: str) -> dict[str, Any]:
    _start(adapter, run_id)
    _schedule(adapter, run_id)
    _start_task(adapter, run_id)
    history = adapter.history(run_id)
    assert [event["sequence"] for event in history] == [1, 2, 3]
    assert history[2]["previous_hash"] == history[1]["event_hash"]
    return {"sequence": [event["sequence"] for event in history], "head": history[-1]["event_hash"]}


def _fixture_atomic_event_effect(adapter: BackendAdapter, run_id: str) -> dict[str, Any]:
    _start(adapter, run_id)
    adapter.fail_next("append.before_commit")
    try:
        _schedule(adapter, run_id, effect=True)
    except BackendFault:
        pass
    assert len(adapter.history(run_id)) == 1
    assert adapter.list_outbox(run_id) == []
    event = _schedule(adapter, run_id, effect=True)
    effects = adapter.list_outbox(run_id)
    assert len(effects) == 1 and effects[0]["source_event_id"] == event["event_id"]
    retry = _schedule(adapter, run_id, effect=True)
    assert retry == event and len(adapter.history(run_id)) == 2
    return {"event": event["event_hash"], "effect": effects[0]["effect_hash"]}


def _fixture_fencing(adapter: BackendAdapter, run_id: str) -> dict[str, Any]:
    _start(adapter, run_id)
    _schedule(adapter, run_id, effect=True)
    effect_id = adapter.list_outbox(run_id)[0]["effect_id"]
    first = adapter.claim_outbox("worker-a", run_id=run_id, now="2026-08-05T00:03:00Z", lease_seconds=10)[0]
    second = adapter.claim_outbox("worker-b", run_id=run_id, now="2026-08-05T00:03:11Z", lease_seconds=10)[0]
    assert second["lease_generation"] > first["lease_generation"]
    try:
        adapter.heartbeat_outbox(
            effect_id,
            "worker-a",
            lease_generation=first["lease_generation"],
            now="2026-08-05T00:03:12Z",
        )
    except runtime.RuntimeStoreError:
        pass
    else:
        raise AssertionError("stale worker heartbeat was accepted")
    context = adapter.authorize_outbox_effect(
        effect_id,
        "worker-b",
        lease_generation=second["lease_generation"],
        now="2026-08-05T00:03:12Z",
    )
    assert context["lease_generation"] == second["lease_generation"]
    lease_events = adapter.runtime.lease_events(effect_id)
    assert any(item["event_type"] == "lease_lost" for item in lease_events)
    return {"generation": second["lease_generation"], "lease_events": len(lease_events)}


def _fixture_timer(adapter: BackendAdapter, run_id: str) -> dict[str, Any]:
    _start(adapter, run_id)
    _schedule(adapter, run_id)
    _start_task(adapter, run_id)
    wait = adapter.create_wait(
        run_id,
        "build",
        "sha256:" + "b" * 64,
        "sha256:" + "c" * 64,
        wait_id=f"{run_id}:wait",
        resume_contract="workflow-v1",
        ttl_seconds=30,
        poll_interval_ms=1000,
        occurred_at="2026-08-05T00:03:00Z",
    )
    assert adapter.state(run_id)["status"] == "input_required"
    adapter.expire_wait(
        run_id,
        f"{run_id}:wait",
        error_ref="sha256:" + "d" * 64,
        occurred_at="2026-08-05T00:03:31Z",
    )
    state = adapter.state(run_id)
    assert state["status"] == "failed"
    return {"wait": wait["event_hash"], "status": state["status"], "expires_at": state["waits"][f"{run_id}:wait"]["expires_at"]}


def _fixture_checkpoint(adapter: BackendAdapter, run_id: str) -> dict[str, Any]:
    _start(adapter, run_id)
    _schedule(adapter, run_id)
    _start_task(adapter, run_id)
    checkpoint = adapter.checkpoint_run(run_id, created_at="2026-08-05T00:03:00Z")
    adapter.append_event(
        run_id,
        "task.completed",
        {"task_id": "build", "output_ref": "sha256:" + "e" * 64},
        idempotency_key=f"{run_id}:task-build-completed",
        occurred_at="2026-08-05T00:04:00Z",
    )
    restored = adapter.restore_state(run_id)
    assert restored["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert restored["state"] == adapter.state(run_id)
    return {"checkpoint": checkpoint["state_digest"], "restored": restored["state_digest"]}


def _fixture_dedupe(adapter: BackendAdapter, run_id: str) -> dict[str, Any]:
    _start(adapter, run_id)
    _schedule(adapter, run_id, effect=True)
    effect_id = adapter.list_outbox(run_id)[0]["effect_id"]
    claimed = adapter.claim_outbox("worker-a", run_id=run_id, now="2026-08-05T00:03:00Z", lease_seconds=60)[0]
    receipt = {"status": "succeeded", "provider_request_id": "fixture:req", "result_ref": "sha256:" + "f" * 64}
    adapter.acknowledge_outbox(
        effect_id,
        "worker-a",
        receipt,
        lease_generation=claimed["lease_generation"],
        received_at="2026-08-05T00:03:01Z",
    )
    assert adapter.record_inbox(effect_id, receipt, received_at="2026-08-05T00:03:02Z") == receipt
    assert len(adapter.list_inbox(run_id)) == 1
    return {"effect": effect_id, "receipt": _digest(receipt)}


def _fixture_migration(adapter: BackendAdapter, run_id: str) -> dict[str, Any]:
    kind = "sqlite" if adapter.descriptor["backend_id"] == "sqlite-wal" else "memory"
    with tempfile.TemporaryDirectory(prefix="forge-migration-") as directory:
        isolated = make_backend(kind, Path(directory) / "runtime.sqlite3" if kind == "sqlite" else None)
        try:
            _start(isolated, run_id)
            isolated.runtime.connection.execute("UPDATE runtime_meta SET value = '2' WHERE key = 'schema_version'")
            isolated.runtime.database_schema_version = 2
            preview = isolated.migrate(dry_run=True)
            assert preview["requires_migration"] is True
            result = isolated.migrate()
            assert result["current_version"] == runtime.DATABASE_SCHEMA_VERSION
            assert result["applied"][-1]["status"] == "applied"
            return {
                "from": preview["current_version"],
                "to": result["current_version"],
                "migration_id": result["applied"][-1]["migration_id"],
            }
        finally:
            isolated.close()


def _fixture_backup(adapter: BackendAdapter, run_id: str, directory: Path) -> dict[str, Any]:
    _start(adapter, run_id)
    _schedule(adapter, run_id, effect=True)
    source_history = adapter.history(run_id)
    backup = directory / f"{run_id}.sqlite3"
    adapter.backup_to(backup)
    restored = adapter.restore_from_backup(backup)
    try:
        assert restored.history(run_id) == source_history
        return {"backup": _digest({"backend": adapter.descriptor["backend_id"], "history": source_history}), "history": _digest(source_history)}
    finally:
        restored.close()


def _fixture_history(adapter: BackendAdapter, run_id: str) -> dict[str, Any]:
    _start(adapter, run_id)
    _schedule(adapter, run_id)
    assert adapter.state(run_id)["sequence"] == 2
    return {"history": _digest(adapter.history(run_id)), "state": _digest(adapter.state(run_id))}


def _fixture_privacy(adapter: BackendAdapter, run_id: str) -> dict[str, Any]:
    _start(adapter, run_id)
    try:
        adapter.append_event(
            run_id,
            "task.scheduled",
            {"task_id": "private", "depends_on": [], "prompt": "do not persist"},
            idempotency_key=f"{run_id}:private",
            occurred_at="2026-08-05T00:01:00Z",
        )
    except runtime.RuntimeStoreError:
        pass
    else:
        raise AssertionError("raw prompt crossed the durable state boundary")
    assert len(adapter.history(run_id)) == 1
    return {"history": _digest(adapter.history(run_id)), "rejected": True}


def _fixture_ambiguous_commit(adapter: BackendAdapter, run_id: str) -> dict[str, Any]:
    _start(adapter, run_id)
    adapter.fail_next("append.after_commit")
    try:
        _schedule(adapter, run_id, effect=True)
    except BackendFault:
        pass
    else:
        raise AssertionError("after-commit fault was not injected")
    retry = _schedule(adapter, run_id, effect=True)
    assert retry["sequence"] == 2
    assert len(adapter.history(run_id)) == 2
    assert len(adapter.list_outbox(run_id)) == 1
    return {"event": retry["event_hash"], "history_length": 2}


def _fixture_adapter_evidence(adapter: BackendAdapter) -> dict[str, Any]:
    evidence = adapter.adapter_evidence(
        revision_ref="sha256:" + "1" * 64,
        transaction_ref="sha256:" + "2" * 64,
        cursor_ref="sha256:" + "3" * 64,
        compaction_ref="sha256:" + "4" * 64,
        cloud_event={
            "source": "urn:forge:backend",
            "id": "fixture-1",
            "type": "forge.adapter.commit",
            "subject": "case-commit",
            "time": "2026-08-05T00:00:00Z",
            "data_ref": "sha256:" + "5" * 64,
        },
    )
    assert evidence["cloud_event"]["identity_ref"].startswith("sha256:")
    try:
        adapter.adapter_evidence(
            revision_ref="sha256:" + "1" * 64,
            transaction_ref=None,
            cursor_ref=None,
            compaction_ref=None,
            cloud_event={
                "source": "urn:forge:backend",
                "id": "fixture-1",
                "type": "bad",
                "time": BASE_TIME,
                "data": "raw",
            },
        )
    except BackendContractError:
        pass
    else:
        raise AssertionError("raw CloudEvent data crossed the adapter evidence boundary")
    return {"evidence": _digest(evidence), "identity": evidence["cloud_event"]["identity_ref"]}


def _case_result(
    adapter: BackendAdapter,
    case_id: str,
    fixture: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    capability = CASE_CAPABILITIES[case_id]
    if capability not in adapter.descriptor["capabilities"]:
        reason = f"{adapter.descriptor['backend_id']} does not advertise {capability}"
        return {
            "case_id": case_id,
            "capability": capability,
            "status": "unsupported",
            "error_ref": _error_ref(reason),
            "evidence_digest": None,
        }
    try:
        evidence = fixture()
    except BackendUnsupported as exc:
        return {
            "case_id": case_id,
            "capability": capability,
            "status": "unsupported",
            "error_ref": _error_ref(exc),
            "evidence_digest": None,
        }
    except (
        AssertionError,
        BackendContractError,
        BackendFault,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        sqlite3.Error,
        runtime.RuntimeStoreError,
    ) as exc:  # pragma: no cover - exercised through result classification
        return {
            "case_id": case_id,
            "capability": capability,
            "status": "failed",
            "error_ref": _error_ref(exc),
            "evidence_digest": None,
        }
    return {
        "case_id": case_id,
        "capability": capability,
        "status": "passed",
        "error_ref": None,
        "evidence_digest": _digest(evidence),
    }


def run_conformance(adapter: BackendAdapter) -> dict[str, Any]:
    """Run the same deterministic fixture matrix against one backend."""

    with tempfile.TemporaryDirectory(prefix="forge-conformance-") as directory:
        conformance_directory = Path(directory)
        fixtures: list[tuple[str, Callable[[], dict[str, Any]]]] = [
            ("append-ordering", lambda: _fixture_append_ordering(adapter, "case-append-ordering")),
            ("atomic-event-effect", lambda: _fixture_atomic_event_effect(adapter, "case-atomic-effect")),
            ("compare-and-swap-fencing", lambda: _fixture_fencing(adapter, "case-fencing")),
            ("durable-timer-wait", lambda: _fixture_timer(adapter, "case-timer")),
            ("checkpoint-restore", lambda: _fixture_checkpoint(adapter, "case-checkpoint")),
            ("inbox-dedupe", lambda: _fixture_dedupe(adapter, "case-dedupe")),
            ("migration", lambda: _fixture_migration(adapter, "case-migration")),
            ("backup-restore", lambda: _fixture_backup(adapter, "case-backup", conformance_directory)),
            ("history-verification", lambda: _fixture_history(adapter, "case-history")),
            ("privacy-boundary", lambda: _fixture_privacy(adapter, "case-privacy")),
            ("ambiguous-commit", lambda: _fixture_ambiguous_commit(adapter, "case-ambiguous")),
            ("adapter-evidence", lambda: _fixture_adapter_evidence(adapter)),
        ]
        cases = [_case_result(adapter, case_id, fixture) for case_id, fixture in fixtures]
    statuses = {item["status"] for item in cases}
    if "failed" in statuses:
        status = "failed"
    elif "degraded" in statuses:
        status = "degraded"
    elif "unsupported" in statuses:
        status = "unsupported"
    else:
        status = "passed"
    result = {
        "schema_version": CONFORMANCE_SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "backend": adapter.descriptor,
        "status": status,
        "cases": cases,
        "summary": {
            "total": len(cases),
            "passed": sum(item["status"] == "passed" for item in cases),
            "unsupported": sum(item["status"] == "unsupported" for item in cases),
            "degraded": sum(item["status"] == "degraded" for item in cases),
            "failed": sum(item["status"] == "failed" for item in cases),
        },
    }
    result["result_digest"] = _digest(result)
    return result


def _requirements(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BackendContractError(f"invalid requirements JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise BackendContractError("requirements JSON must be an object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Negotiate and verify Forge runtime backends")
    sub = parser.add_subparsers(dest="command", required=True)

    describe = sub.add_parser("describe", help="print a backend capability descriptor")
    describe.add_argument("--backend", choices=["sqlite", "memory"], required=True)

    negotiation = sub.add_parser("negotiate", help="negotiate capabilities and consistency")
    negotiation.add_argument("--backend", choices=["sqlite", "memory"], required=True)
    negotiation.add_argument("--requirements-json", default="{}")

    conformance = sub.add_parser("conformance", help="run the deterministic offline fixture matrix")
    conformance.add_argument("--backend", choices=["sqlite", "memory", "all"], default="all")
    conformance.add_argument("--db", type=Path, help="optional disposable SQLite path for the SQLite adapter")
    return parser


def _run_one(kind: str, path: Path | None) -> dict[str, Any]:
    if kind == "sqlite" and path is None:
        path = Path(tempfile.mkdtemp(prefix="forge-conformance-db-")) / "runtime.sqlite3"
    adapter = make_backend(kind, path)
    try:
        return run_conformance(adapter)
    finally:
        adapter.close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "describe":
            print(json.dumps(descriptor_for(args.backend), indent=2, sort_keys=True))
            return 0
        if args.command == "negotiate":
            print(json.dumps(negotiate(descriptor_for(args.backend), _requirements(args.requirements_json)), indent=2, sort_keys=True))
            return 0
        if args.backend == "all":
            sqlite_path = None if args.db is None else Path(str(args.db) + ".sqlite")
            results = [_run_one("sqlite", sqlite_path), _run_one("memory", None)]
            output: dict[str, Any] = {
                "schema_version": CONFORMANCE_SCHEMA_VERSION,
                "contract_revision": CONTRACT_REVISION,
                "status": (
                    "failed"
                    if any(item["status"] == "failed" for item in results)
                    else "degraded"
                    if any(item["status"] == "degraded" for item in results)
                    else "unsupported"
                    if any(item["status"] == "unsupported" for item in results)
                    else "passed"
                ),
                "results": results,
            }
            output["result_digest"] = _digest(output)
            print(json.dumps(output, indent=2, sort_keys=True))
            return 0 if output["status"] == "passed" else 1
        result = _run_one(args.backend, args.db)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "passed" else 1
    except (BackendContractError, runtime.RuntimeStoreError, sqlite3.Error) as exc:
        print(json.dumps({"status": "failed", "error_ref": _error_ref(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
