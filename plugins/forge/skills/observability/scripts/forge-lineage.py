#!/usr/bin/env python3
"""Export and verify privacy-safe, offline Forge execution lineage."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import uuid
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any


LINEAGE_SCHEMA_VERSION = 1
RECEIPT_SCHEMA_VERSION = 1
RUNTIME_SCHEMA_VERSION = 2
OTEL_MAPPING_VERSION = "forge-otel-1"
OTEL_SPEC_VERSION = "1.59.0"
GEN_AI_SEMCONV_VERSION = "1.42.0"
GENESIS_HASH = "0" * 64
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RECEIPT_TYPES = {"effect.outcome", "effect.receipt", "policy.decision", "adapter.outcome"}
EFFECT_OUTCOMES = {"leased", "reclaimed", "succeeded", "retry", "dead_letter"}
PROVIDER_REFERENCE_KEYS = ("provider_request_id", "resource_ref", "result_ref", "result_digest", "error_ref")
SAFE_REFERENCE_KEYS = set(PROVIDER_REFERENCE_KEYS)
POLICY_ATTRIBUTE_KEYS = {
    "action_digest",
    "approval_id",
    "committed_effect",
    "decision",
    "effective_action_digest",
    "policy_revision",
    "principal",
    "profile",
    "rule_id",
    "status",
}
FORBIDDEN_PARTS = {
    "argument",
    "body",
    "content",
    "credential",
    "password",
    "prompt",
    "raw",
    "result",
    "secret",
    "token",
}
MANIFEST_FIELDS = {
    "schema_version",
    "runtime_schema_version",
    "mapping",
    "runs",
    "effects",
    "receipts",
    "edges",
    "extensions",
    "manifest_digest",
}
MAPPING_FIELDS = {"version", "otel_spec_version", "gen_ai_semconv_version"}
RUN_FIELDS = {
    "run_id",
    "workflow_id",
    "definition_version",
    "policy_revision",
    "status",
    "sequence",
    "events",
    "head_sequence",
    "head_hash",
}
EVENT_FIELDS = {
    "schema_version",
    "event_id",
    "event_type",
    "run_id",
    "sequence",
    "occurred_at",
    "idempotency_key",
    "previous_hash",
    "event_hash",
}
EFFECT_FIELDS = {
    "effect_id",
    "run_id",
    "task_id",
    "activity_id",
    "activity_attempt",
    "effect_definition_revision",
    "idempotency_key",
    "effect_hash",
    "status",
    "source_event_id",
    "source_sequence",
    "source_event_hash",
    "attempts",
    "lease_events",
}
ATTEMPT_FIELDS = {
    "attempt_id",
    "attempt",
    "worker_id",
    "lease_generation",
    "claimed_at",
    "finished_at",
    "outcome",
    "error_ref",
}
LEASE_EVENT_FIELDS = {
    "sequence",
    "event_id",
    "event_type",
    "lease_generation",
    "worker_id",
    "occurred_at",
    "lease_expires_at",
    "lease_deadline_at",
}
EDGE_FIELDS = {"edge_id", "from", "relation", "to"}
RECEIPT_FIELDS = {
    "schema_version",
    "receipt_id",
    "receipt_type",
    "run_id",
    "task_id",
    "source",
    "effect_id",
    "provider_idempotency_key",
    "attempt_id",
    "attempt",
    "lease_generation",
    "adapter_contract_revision",
    "provider_request_ref",
    "status",
    "occurred_at",
    "payload",
    "parent_receipt_id",
    "receipt_digest",
}


class LineageError(ValueError):
    """Raised when evidence cannot be exported or verified safely."""


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LineageError(f"value is not canonical JSON: {exc}") from exc


def digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest_ref(value: Any) -> str:
    return "sha256:" + digest(value)


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise LineageError(f"could not load Forge module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _runtime_module() -> Any:
    path = Path(__file__).resolve().parents[2] / "orchestration" / "scripts" / "forge-runtime.py"
    return _load_module("forge_runtime_for_lineage", path)


def _receipts_module() -> Any:
    path = Path(__file__).resolve().parent / "forge-receipts.py"
    return _load_module("forge_receipts_for_lineage", path)


def _bounded_text(value: Any, field: str, *, allow_none: bool = False, limit: int = 512) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value or len(value) > limit:
        raise LineageError(f"{field} must be a non-empty string of at most {limit} characters")
    return value


def _assert_known_fields(value: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise LineageError(f"{field} has unsupported fields: {', '.join(unknown)}")


def _hash(value: Any, field: str) -> str:
    value = _bounded_text(value, field, limit=64)
    if not HASH_RE.fullmatch(value or ""):
        raise LineageError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _ref(value: Any, field: str, *, allow_none: bool = False) -> str | None:
    value = _bounded_text(value, field, allow_none=allow_none, limit=80)
    if value is not None and not REF_RE.fullmatch(value):
        raise LineageError(f"{field} must be a sha256 reference")
    return value


def _safe_value(value: Any, key: str = "") -> Any:
    """Keep scalar evidence bounded and replace nested/content values with digests."""

    normalized = key.lower().replace("-", "_")
    if normalized in SAFE_REFERENCE_KEYS and isinstance(value, str) and 0 < len(value) <= 512:
        return value
    if any(part in normalized.split("_") for part in FORBIDDEN_PARTS):
        return {"redacted": True, "sha256": digest_ref(value)}
    if isinstance(value, Mapping) or isinstance(value, (list, tuple)):
        return {"redacted": True, "sha256": digest_ref(value)}
    if isinstance(value, str) and len(value) > 512:
        return {"redacted": True, "sha256": digest_ref(value)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {"redacted": True, "sha256": digest_ref(str(value))}


def _assert_private(value: Any, path: str = "evidence") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in SAFE_REFERENCE_KEYS:
                if child is not None and (not isinstance(child, str) or not child or len(child) > 512):
                    raise LineageError(f"{path}.{key} must be a bounded reference")
                continue
            if any(part in normalized.split("_") for part in FORBIDDEN_PARTS):
                if not (isinstance(child, Mapping) and child.get("redacted") is True):
                    raise LineageError(f"{path}.{key} contains forbidden raw content")
            _assert_private(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_private(child, f"{path}[{index}]")


def _event_summary(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": event["schema_version"],
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "run_id": event["run_id"],
        "sequence": event["sequence"],
        "occurred_at": event["occurred_at"],
        "idempotency_key": event["idempotency_key"],
        "previous_hash": event["previous_hash"],
        "event_hash": event["event_hash"],
    }


def _runtime_source(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "runtime_event",
        "event_id": event["event_id"],
        "sequence": event["sequence"],
        "event_hash": event["event_hash"],
    }


def _receipt_source(event: Mapping[str, Any]) -> dict[str, Any]:
    record = {
        "schema_version": event.get("schema_version"),
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "run_id": event.get("run_id"),
        "sequence": event.get("sequence"),
        "occurred_at": event.get("occurred_at"),
        "idempotency_key": event.get("idempotency_key"),
    }
    return {
        "kind": "receipt_event",
        "event_id": record["event_id"],
        "sequence": record["sequence"],
        "idempotency_key": record["idempotency_key"],
        "record": record,
        "event_digest": digest_ref(record),
    }


def _make_receipt(
    receipt_type: str,
    *,
    run_id: str,
    task_id: str | None,
    source: Mapping[str, Any],
    effect_id: str | None = None,
    provider_idempotency_key: str | None = None,
    attempt_id: str | None = None,
    attempt: int | None = None,
    lease_generation: int | None = None,
    adapter_contract_revision: str | None = None,
    provider_request_ref: str | None = None,
    status: str,
    occurred_at: str,
    payload: Mapping[str, Any] | None = None,
    parent_receipt_id: str | None = None,
) -> dict[str, Any]:
    if receipt_type not in RECEIPT_TYPES:
        raise LineageError(f"unsupported receipt type: {receipt_type}")
    body = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_type": receipt_type,
        "run_id": run_id,
        "task_id": task_id,
        "source": dict(source),
        "effect_id": effect_id,
        "provider_idempotency_key": provider_idempotency_key,
        "attempt_id": attempt_id,
        "attempt": attempt,
        "lease_generation": lease_generation,
        "adapter_contract_revision": adapter_contract_revision,
        "provider_request_ref": provider_request_ref,
        "status": status,
        "occurred_at": occurred_at,
        "payload": dict(payload or {}),
    }
    if parent_receipt_id is not None:
        body["parent_receipt_id"] = parent_receipt_id
    receipt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "forge-receipt:" + canonical_json(body)))
    return {
        **body,
        "receipt_id": receipt_id,
        "receipt_digest": digest_ref(body),
    }


def _provider_reference(receipt: Mapping[str, Any]) -> tuple[str | None, dict[str, Any]]:
    payload = {
        key: _safe_value(receipt[key], key)
        for key in PROVIDER_REFERENCE_KEYS
        if key in receipt and receipt[key] is not None
    }
    reference = next((payload[key] for key in PROVIDER_REFERENCE_KEYS if key in payload), None)
    if reference is not None and not isinstance(reference, str):
        reference = None
    return reference, payload


def _effect_record(
    effect: Mapping[str, Any],
    source_event: Mapping[str, Any],
    attempts: list[Mapping[str, Any]],
    lease_events: list[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "effect_id": effect["effect_id"],
        "run_id": effect["run_id"],
        "task_id": effect["task_id"],
        "activity_id": effect["activity_id"],
        "activity_attempt": effect["activity_attempt"],
        "effect_definition_revision": effect["effect_definition_revision"],
        "idempotency_key": effect["idempotency_key"],
        "effect_hash": effect["effect_hash"],
        "status": effect["status"],
        "source_event_id": source_event["event_id"],
        "source_sequence": source_event["sequence"],
        "source_event_hash": source_event["event_hash"],
        "attempts": [
            {
                "attempt_id": f"{effect['effect_id']}:{attempt['attempt']}",
                "attempt": attempt["attempt"],
                "worker_id": attempt["worker_id"],
                "lease_generation": attempt["lease_generation"],
                "claimed_at": attempt["claimed_at"],
                "finished_at": attempt["finished_at"],
                "outcome": attempt["outcome"],
                "error_ref": attempt["error_ref"],
            }
            for attempt in attempts
        ],
        "lease_events": [
            {
                "sequence": event["sequence"],
                "event_id": event["event_id"],
                "event_type": event["event_type"],
                "lease_generation": event["lease_generation"],
                "worker_id": event["worker_id"],
                "occurred_at": event["occurred_at"],
                "lease_expires_at": event["lease_expires_at"],
                "lease_deadline_at": event["lease_deadline_at"],
            }
            for event in lease_events
        ],
    }


def _runtime_evidence(database: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    runtime = _runtime_module()
    store = runtime.RuntimeStore(database, auto_migrate=False)
    try:
        runs: list[dict[str, Any]] = []
        events_by_id: dict[tuple[str, str], dict[str, Any]] = {}
        for run in store.list_runs():
            events = [_event_summary(event) for event in store.history(run["run_id"])]
            head_sequence = events[-1]["sequence"] if events else 0
            head_hash = events[-1]["event_hash"] if events else GENESIS_HASH
            runs.append(
                {
                    "run_id": run["run_id"],
                    "workflow_id": run["workflow_id"],
                    "definition_version": run["definition_version"],
                    "policy_revision": run["policy_revision"],
                    "status": run["status"],
                    "sequence": run["sequence"],
                    "events": events,
                    "head_sequence": head_sequence,
                    "head_hash": head_hash,
                }
            )
            for event in events:
                events_by_id[(run["run_id"], event["event_id"])] = event

        effects: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []
        receipt_by_attempt: dict[tuple[str, int], dict[str, Any]] = {}
        inbox_by_effect = {
            receipt["effect_id"]: receipt
            for run in runs
            for receipt in store.list_inbox(run["run_id"])
        }
        for run in runs:
            for effect in store.list_outbox(run["run_id"]):
                source_event = events_by_id.get((run["run_id"], effect["source_event_id"]))
                if source_event is None:
                    raise LineageError(f"effect {effect['effect_id']} has no scheduling event evidence")
                attempts = store.outbox_attempts(effect["effect_id"])
                lease_events = store.lease_events(effect["effect_id"])
                record = _effect_record(effect, source_event, attempts, lease_events)
                effects.append(record)
                for attempt in record["attempts"]:
                    payload = {}
                    if attempt["error_ref"] is not None:
                        payload["error_ref"] = attempt["error_ref"]
                    outcome_receipt = _make_receipt(
                        "effect.outcome",
                        run_id=record["run_id"],
                        task_id=record["task_id"],
                        source=_runtime_source(source_event),
                        effect_id=record["effect_id"],
                        provider_idempotency_key=record["idempotency_key"],
                        attempt_id=attempt["attempt_id"],
                        attempt=attempt["attempt"],
                        lease_generation=attempt["lease_generation"],
                        adapter_contract_revision=record["effect_definition_revision"],
                        status=attempt["outcome"],
                        occurred_at=attempt["finished_at"] or attempt["claimed_at"],
                        payload=payload,
                    )
                    receipts.append(outcome_receipt)
                    receipt_by_attempt[(record["effect_id"], attempt["attempt"])] = outcome_receipt
                inbox = inbox_by_effect.get(record["effect_id"])
                if inbox is not None:
                    successful = [attempt for attempt in record["attempts"] if attempt["outcome"] == "succeeded"]
                    if not successful:
                        raise LineageError(f"inbox receipt for {record['effect_id']} has no succeeded attempt evidence")
                    attempt = successful[-1]
                    provider_ref, payload = _provider_reference(inbox["receipt"])
                    if inbox["receipt"]["status"] in {"accepted", "succeeded"} and provider_ref is None:
                        raise LineageError(f"inbox receipt for {record['effect_id']} has no provider reference")
                    receipts.append(
                        _make_receipt(
                            "effect.receipt",
                            run_id=record["run_id"],
                            task_id=record["task_id"],
                            source=_runtime_source(source_event),
                            effect_id=record["effect_id"],
                            provider_idempotency_key=record["idempotency_key"],
                            attempt_id=attempt["attempt_id"],
                            attempt=attempt["attempt"],
                            lease_generation=attempt["lease_generation"],
                            adapter_contract_revision=record["effect_definition_revision"],
                            provider_request_ref=provider_ref,
                            status=inbox["receipt"]["status"],
                            occurred_at=inbox["received_at"],
                            payload=payload,
                            parent_receipt_id=receipt_by_attempt[(record["effect_id"], attempt["attempt"])]
                            ["receipt_id"],
                        )
                    )
        return runs, effects, receipts
    finally:
        store.close()


def _policy_evidence(receipts_path: Path | None, run_ids: set[str]) -> list[dict[str, Any]]:
    if receipts_path is None:
        return []
    module = _receipts_module()
    events, truncated = module.ReceiptStore(receipts_path).read()
    if truncated:
        raise LineageError("receipt evidence has an incomplete final record")
    result: list[dict[str, Any]] = []
    for event in events:
        run_id = _bounded_text(event.get("run_id"), "receipt.run_id")
        if run_id not in run_ids:
            raise LineageError(f"receipt event {event.get('event_id')} has no runtime run parent")
        attributes = event.get("attributes", {})
        if not isinstance(attributes, Mapping):
            raise LineageError(f"receipt event {event.get('event_id')} attributes are not an object")
        payload = {
            key: _safe_value(attributes[key], key)
            for key in sorted(POLICY_ATTRIBUTE_KEYS & set(attributes))
        }
        receipt_type = "policy.decision" if "action_digest" in payload and "policy_revision" in payload else "adapter.outcome"
        result.append(
            _make_receipt(
                receipt_type,
                run_id=run_id,
                task_id=event.get("task_id"),
                source=_receipt_source(event),
                status=str(attributes.get("status", attributes.get("committed_effect", event["event_type"]))),
                occurred_at=event["occurred_at"],
                payload=payload,
            )
        )
    return result


def _edge(kind_from: str, id_from: str, relation: str, kind_to: str, id_to: str) -> dict[str, Any]:
    body = {
        "from": {"kind": kind_from, "id": id_from},
        "relation": relation,
        "to": {"kind": kind_to, "id": id_to},
    }
    return {**body, "edge_id": digest_ref(body)}


def export_manifest(database: Path, receipts_path: Path | None = None) -> dict[str, Any]:
    runs, effects, receipts = _runtime_evidence(database)
    receipts.extend(_policy_evidence(receipts_path, {run["run_id"] for run in runs}))
    edges: list[dict[str, Any]] = []
    for effect in effects:
        edges.append(_edge("runtime_event", effect["source_event_id"], "schedules", "effect", effect["effect_id"]))
        for receipt in receipts:
            if receipt["effect_id"] != effect["effect_id"]:
                continue
            if receipt["receipt_type"] == "effect.outcome":
                edges.append(_edge("effect", effect["effect_id"], "records", "receipt", receipt["receipt_id"]))
            elif receipt["receipt_type"] == "effect.receipt":
                edges.append(_edge("receipt", receipt["parent_receipt_id"], "confirms", "receipt", receipt["receipt_id"]))
    for receipt in receipts:
        if receipt["receipt_type"] in {"policy.decision", "adapter.outcome"}:
            edges.append(_edge("run", receipt["run_id"], "evidences", "receipt", receipt["receipt_id"]))
    body = {
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
        "mapping": {
            "version": OTEL_MAPPING_VERSION,
            "otel_spec_version": OTEL_SPEC_VERSION,
            "gen_ai_semconv_version": GEN_AI_SEMCONV_VERSION,
        },
        "runs": sorted(runs, key=lambda item: item["run_id"]),
        "effects": sorted(effects, key=lambda item: item["effect_id"]),
        "receipts": sorted(receipts, key=lambda item: item["receipt_id"]),
        "edges": sorted(edges, key=lambda item: item["edge_id"]),
        "extensions": {},
    }
    manifest = {**body, "manifest_digest": digest_ref(body)}
    verify_manifest(manifest)
    return manifest


def _required_mapping(value: Mapping[str, Any], field: str) -> Any:
    if field not in value:
        raise LineageError(f"missing required field: {field}")
    return value[field]


def _verify_receipt(receipt: Mapping[str, Any]) -> None:
    if not isinstance(receipt, Mapping):
        raise LineageError("receipt must be an object")
    _assert_known_fields(receipt, RECEIPT_FIELDS, "receipt")
    required = {
        "schema_version",
        "receipt_id",
        "receipt_type",
        "run_id",
        "task_id",
        "source",
        "effect_id",
        "provider_idempotency_key",
        "attempt_id",
        "attempt",
        "lease_generation",
        "adapter_contract_revision",
        "provider_request_ref",
        "status",
        "occurred_at",
        "payload",
        "receipt_digest",
    }
    missing = sorted(required - set(receipt))
    if missing:
        raise LineageError("receipt is missing: " + ", ".join(missing))
    if receipt["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise LineageError(f"unsupported receipt schema: {receipt['schema_version']}")
    if receipt["receipt_type"] not in RECEIPT_TYPES:
        raise LineageError(f"unsupported receipt type: {receipt['receipt_type']}")
    if not isinstance(receipt["payload"], Mapping):
        raise LineageError(f"receipt payload must be an object: {receipt['receipt_id']}")
    body = {key: value for key, value in receipt.items() if key not in {"receipt_id", "receipt_digest"}}
    if not isinstance(receipt["receipt_id"], str) or not receipt["receipt_id"]:
        raise LineageError("receipt_id must be a non-empty string")
    expected_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "forge-receipt:" + canonical_json(body)))
    if receipt["receipt_id"] != expected_id:
        raise LineageError(f"receipt identity mismatch: {receipt['receipt_id']}")
    if receipt["receipt_digest"] != digest_ref(body):
        raise LineageError(f"receipt digest mismatch: {receipt['receipt_id']}")
    _assert_private(receipt)


def verify_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, Mapping):
        raise LineageError("manifest must be an object")
    _assert_known_fields(manifest, MANIFEST_FIELDS, "manifest")
    required = {"schema_version", "runtime_schema_version", "mapping", "runs", "effects", "receipts", "edges", "extensions", "manifest_digest"}
    missing = sorted(required - set(manifest))
    if missing:
        raise LineageError("manifest is missing: " + ", ".join(missing))
    if manifest["schema_version"] != LINEAGE_SCHEMA_VERSION:
        raise LineageError(f"unsupported lineage schema: {manifest['schema_version']}")
    if manifest["runtime_schema_version"] != RUNTIME_SCHEMA_VERSION:
        raise LineageError(f"unsupported runtime schema in lineage: {manifest['runtime_schema_version']}")
    if not isinstance(manifest["mapping"], Mapping):
        raise LineageError("manifest mapping must be an object")
    _assert_known_fields(manifest["mapping"], MAPPING_FIELDS, "manifest.mapping")
    for field, expected in (
        ("version", OTEL_MAPPING_VERSION),
        ("otel_spec_version", OTEL_SPEC_VERSION),
        ("gen_ai_semconv_version", GEN_AI_SEMCONV_VERSION),
    ):
        if manifest["mapping"].get(field) != expected:
            raise LineageError(f"unsupported {field}: {manifest['mapping'].get(field)}")
    if not isinstance(manifest["extensions"], Mapping):
        raise LineageError("manifest extensions must be an object")
    body = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    if manifest["manifest_digest"] != digest_ref(body):
        raise LineageError("manifest digest mismatch")
    _assert_private(manifest)
    runs = manifest["runs"]
    effects = manifest["effects"]
    receipts = manifest["receipts"]
    edges = manifest["edges"]
    if not all(isinstance(value, list) for value in (runs, effects, receipts, edges)):
        raise LineageError("manifest collections must be arrays")

    run_ids: set[str] = set()
    events: dict[tuple[str, str], Mapping[str, Any]] = {}
    event_ids: set[str] = set()
    for run in runs:
        if not isinstance(run, Mapping):
            raise LineageError("run must be an object")
        _assert_known_fields(run, RUN_FIELDS, "run")
        run_id = _bounded_text(_required_mapping(run, "run_id"), "run.run_id")
        if run_id in run_ids:
            raise LineageError(f"duplicate run: {run_id}")
        run_ids.add(run_id)
        run_events = run.get("events")
        if not isinstance(run_events, list):
            raise LineageError(f"run events must be an array: {run_id}")
        previous_hash = GENESIS_HASH
        for expected_sequence, event in enumerate(run_events, start=1):
            if not isinstance(event, Mapping):
                raise LineageError(f"event must be an object in run {run_id}")
            _assert_known_fields(event, EVENT_FIELDS, f"event in run {run_id}")
            if event.get("sequence") != expected_sequence:
                raise LineageError(f"event sequence gap in run {run_id}")
            if event.get("run_id") != run_id:
                raise LineageError(f"event run mismatch in run {run_id}")
            event_hash = _hash(event.get("event_hash"), "event.event_hash")
            if event.get("previous_hash") != previous_hash:
                raise LineageError(f"event parent hash mismatch in run {run_id} sequence {expected_sequence}")
            event_id = _bounded_text(event.get("event_id"), "event.event_id")
            if event_id in event_ids:
                raise LineageError(f"duplicate event: {event_id}")
            event_ids.add(event_id)
            events[(run_id, event_id)] = event
            previous_hash = event_hash
        head_sequence = run_events[-1]["sequence"] if run_events else 0
        head_hash = run_events[-1]["event_hash"] if run_events else GENESIS_HASH
        if run.get("sequence") != head_sequence:
            raise LineageError(f"run sequence mismatch: {run_id}")
        if run.get("head_sequence") != head_sequence or run.get("head_hash") != head_hash:
            raise LineageError(f"run head mismatch: {run_id}")

    effect_ids: set[str] = set()
    effect_by_id: dict[str, Mapping[str, Any]] = {}
    attempts: dict[tuple[str, int], Mapping[str, Any]] = {}
    receipt_ids: set[str] = set()
    receipt_by_id: dict[str, Mapping[str, Any]] = {}
    for candidate in receipts:
        _verify_receipt(candidate)
        candidate_id = candidate["receipt_id"]
        if candidate_id in receipt_ids:
            raise LineageError(f"duplicate receipt: {candidate_id}")
        receipt_ids.add(candidate_id)
        receipt_by_id[candidate_id] = candidate
    provider_refs: dict[str, str | None] = {}
    effect_idempotency: dict[str, str] = {}
    for effect in effects:
        if not isinstance(effect, Mapping):
            raise LineageError("effect must be an object")
        _assert_known_fields(effect, EFFECT_FIELDS, "effect")
        effect_id = _bounded_text(effect.get("effect_id"), "effect.effect_id")
        if effect_id in effect_ids:
            raise LineageError(f"duplicate effect: {effect_id}")
        effect_ids.add(effect_id)
        effect_by_id[effect_id] = effect
        idempotency_key = _bounded_text(effect.get("idempotency_key"), "effect.idempotency_key")
        previous_effect = effect_idempotency.get(idempotency_key or "")
        if previous_effect is not None and previous_effect != effect_id:
            raise LineageError(f"effect idempotency key reused across effects: {idempotency_key}")
        effect_idempotency[idempotency_key or ""] = effect_id
        if effect.get("status") not in {"pending", "leased", "retry", "succeeded", "dead_letter"}:
            raise LineageError(f"invalid effect status: {effect_id}")
        run_id = _bounded_text(effect.get("run_id"), "effect.run_id")
        source_key = (run_id, effect.get("source_event_id"))
        source = events.get(source_key)
        if source is None:
            raise LineageError(f"effect {effect_id} has no parent event")
        if effect.get("source_sequence") != source["sequence"] or effect.get("source_event_hash") != source["event_hash"]:
            raise LineageError(f"effect source mismatch: {effect_id}")
        _hash(effect.get("effect_hash"), "effect.effect_hash")
        attempts_list = effect.get("attempts")
        if not isinstance(attempts_list, list):
            raise LineageError(f"effect attempts must be an array: {effect_id}")
        attempt_generations: set[int] = set()
        for attempt in attempts_list:
            if not isinstance(attempt, Mapping):
                raise LineageError(f"effect attempt must be an object: {effect_id}")
            _assert_known_fields(attempt, ATTEMPT_FIELDS, f"attempt {effect_id}")
            number = attempt.get("attempt")
            if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                raise LineageError(f"invalid attempt number: {effect_id}")
            key = (effect_id, number)
            if key in attempts:
                raise LineageError(f"duplicate effect attempt: {effect_id}:{number}")
            if attempt.get("attempt_id") != f"{effect_id}:{number}":
                raise LineageError(f"attempt identity mismatch: {effect_id}:{number}")
            generation = attempt.get("lease_generation")
            if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
                raise LineageError(f"invalid lease generation: {effect_id}:{number}")
            if attempt.get("outcome") not in EFFECT_OUTCOMES:
                raise LineageError(f"invalid attempt outcome: {effect_id}:{number}")
            attempts[key] = attempt
            attempt_generations.add(generation)
        lease_events = effect.get("lease_events")
        if not isinstance(lease_events, list):
            raise LineageError(f"effect lease events must be an array: {effect_id}")
        previous_lease_sequence = 0
        lease_event_ids: set[str] = set()
        for lease_event in lease_events:
            if not isinstance(lease_event, Mapping):
                raise LineageError(f"lease event must be an object: {effect_id}")
            _assert_known_fields(lease_event, LEASE_EVENT_FIELDS, f"lease event {effect_id}")
            sequence = lease_event.get("sequence")
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= previous_lease_sequence:
                raise LineageError(f"lease event sequence is not increasing: {effect_id}")
            previous_lease_sequence = sequence
            event_id = _bounded_text(lease_event.get("event_id"), "lease_event.event_id")
            if event_id in lease_event_ids:
                raise LineageError(f"duplicate lease event: {effect_id}:{event_id}")
            lease_event_ids.add(event_id or "")
            if lease_event.get("event_type") not in {"claimed", "heartbeat", "lease_lost"}:
                raise LineageError(f"invalid lease event type: {effect_id}")
            generation = lease_event.get("lease_generation")
            if isinstance(generation, bool) or not isinstance(generation, int) or generation not in attempt_generations:
                raise LineageError(f"lease event has no attempt parent: {effect_id}")

    for receipt in receipts:
        receipt_id = receipt["receipt_id"]
        run_id = _bounded_text(receipt["run_id"], "receipt.run_id")
        if run_id not in run_ids:
            raise LineageError(f"receipt has no run parent: {receipt_id}")
        source = receipt["source"]
        if not isinstance(source, Mapping):
            raise LineageError(f"receipt source must be an object: {receipt_id}")
        if source.get("kind") == "runtime_event":
            event = events.get((run_id, source.get("event_id")))
            if event is None or source.get("sequence") != event["sequence"] or source.get("event_hash") != event["event_hash"]:
                raise LineageError(f"receipt runtime parent mismatch: {receipt_id}")
        elif source.get("kind") == "receipt_event":
            record = source.get("record")
            if not isinstance(record, Mapping) or record.get("run_id") != run_id or source.get("event_digest") != digest_ref(record):
                raise LineageError(f"receipt evidence parent mismatch: {receipt_id}")
        else:
            raise LineageError(f"unsupported receipt source kind: {receipt_id}")
        effect_id = receipt.get("effect_id")
        if effect_id is None:
            if receipt["receipt_type"] == "effect.receipt" or receipt["receipt_type"] == "effect.outcome":
                raise LineageError(f"effect receipt is missing effect parent: {receipt_id}")
            if receipt["receipt_type"] == "policy.decision":
                if "action_digest" not in receipt["payload"] or "policy_revision" not in receipt["payload"]:
                    raise LineageError(f"policy receipt is missing identity: {receipt_id}")
            continue
        effect = effect_by_id.get(effect_id)
        if effect is None or effect["run_id"] != run_id:
            raise LineageError(f"receipt effect parent mismatch: {receipt_id}")
        if receipt.get("provider_idempotency_key") != effect["idempotency_key"]:
            raise LineageError(f"receipt idempotency mismatch: {receipt_id}")
        attempt_key = (effect_id, receipt.get("attempt"))
        attempt = attempts.get(attempt_key)
        if attempt is None or receipt.get("attempt_id") != attempt["attempt_id"]:
            raise LineageError(f"receipt attempt parent mismatch: {receipt_id}")
        if receipt.get("lease_generation") != attempt["lease_generation"]:
            raise LineageError(f"receipt lease generation mismatch: {receipt_id}")
        if receipt["receipt_type"] == "effect.outcome" and receipt["status"] != attempt["outcome"]:
            raise LineageError(f"receipt outcome mismatch: {receipt_id}")
        if receipt["receipt_type"] == "effect.receipt":
            parent_id = receipt.get("parent_receipt_id")
            parent = receipt_by_id.get(parent_id) if isinstance(parent_id, str) else None
            if (
                parent is None
                or parent.get("receipt_type") != "effect.outcome"
                or parent.get("effect_id") != effect_id
                or parent.get("status") != "succeeded"
                or parent.get("attempt") != receipt.get("attempt")
            ):
                raise LineageError(f"inbox receipt has no outcome parent: {receipt_id}")
        provider_ref = receipt.get("provider_request_ref")
        if provider_ref is not None:
            provider_ref = _bounded_text(provider_ref, "receipt.provider_request_ref")
            previous_effect = provider_refs.get(provider_ref)
            if previous_effect is not None and previous_effect != effect_id:
                raise LineageError(f"provider reference reused across effects: {provider_ref}")
            provider_refs[provider_ref] = effect_id
        if receipt["receipt_type"] == "effect.receipt" and receipt["status"] in {"accepted", "succeeded"} and provider_ref is None:
            raise LineageError(f"successful receipt has no provider reference: {receipt_id}")

    known_nodes = {("run", run_id) for run_id in run_ids}
    known_nodes.update(("runtime_event", event_id) for event_id in event_ids)
    known_nodes.update(("effect", effect_id) for effect_id in effect_ids)
    known_nodes.update(("receipt", receipt_id) for receipt_id in receipt_ids)
    edge_ids: set[str] = set()
    for edge in edges:
        if not isinstance(edge, Mapping) or not {"edge_id", "from", "relation", "to"}.issubset(edge):
            raise LineageError("malformed lineage edge")
        _assert_known_fields(edge, EDGE_FIELDS, "lineage edge")
        body = {key: edge[key] for key in ("from", "relation", "to")}
        if edge["edge_id"] != digest_ref(body):
            raise LineageError(f"lineage edge digest mismatch: {edge['edge_id']}")
        if edge["edge_id"] in edge_ids:
            raise LineageError(f"duplicate lineage edge: {edge['edge_id']}")
        edge_ids.add(edge["edge_id"])
        for endpoint in (edge["from"], edge["to"]):
            if not isinstance(endpoint, Mapping) or (endpoint.get("kind"), endpoint.get("id")) not in known_nodes:
                raise LineageError("lineage edge references missing evidence")
    return {
        "verified": True,
        "manifest_digest": manifest["manifest_digest"],
        "runs": len(runs),
        "effects": len(effects),
        "receipts": len(receipts),
        "edges": len(edges),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export and verify offline Forge execution lineage")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="export deterministic lineage from a runtime database")
    export.add_argument("--db", type=Path, required=True)
    export.add_argument("--receipts", type=Path)
    export.add_argument("--output", type=Path)
    verify = sub.add_parser("verify", help="verify a lineage manifest without network access")
    verify.add_argument("--manifest", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "export":
            manifest = export_manifest(args.db, args.receipts)
            rendered = json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered, encoding="utf-8")
            else:
                print(rendered, end="")
            return 0
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = verify_manifest(manifest)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except (LineageError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"forge-lineage: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
