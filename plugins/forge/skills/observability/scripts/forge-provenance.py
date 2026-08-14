#!/usr/bin/env python3
"""Export and verify signed, privacy-safe Forge trace/provenance bundles offline."""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import importlib.util
import json
import re
import sys
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CONTRACT_REVISION = "forge-provenance-v1"
TRACE_CONTEXT_VERSION = "w3c-trace-context-00"
OTEL_MAPPING_VERSION = "forge-otel-1"
OTEL_SPEC_VERSION = "1.59.0"
GEN_AI_SEMCONV_VERSION = "1.42.0"
PAYLOAD_TYPE = "application/vnd.in-toto+json"
PROVENANCE_TYPE = "https://slsa.dev/provenance/v1"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
BUILD_TYPE = "https://github.com/AlisinaDevelo/md-files/forge/provenance/v1"
BUILDER_ID = "https://github.com/AlisinaDevelo/md-files"
MAX_TRACEPARENT = 512
MAX_TRACESTATE = 512
MAX_ATTRIBUTE_LENGTH = 512
MIN_KEY_LENGTH = 16
TRACEPARENT_PART_RE = re.compile(r"^[0-9a-f]{2,}$")
TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SPAN_ID_RE = re.compile(r"^[0-9a-f]{16}$")
TRACE_FLAGS_RE = re.compile(r"^[0-9a-f]{2}$")
TRACESTATE_KEY_RE = re.compile(r"^[a-z][a-z0-9_*/-]{0,255}$")
TRACESTATE_VALUE_RE = re.compile(r"^[\x21-\x2b\x2d-\x3c\x3e-\x7e]{1,256}$")
KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
SIGNATURE_ALGORITHM = "hmac-sha256"

SENSITIVE_PARTS = {
    "api_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
}
CONTENT_PARTS = {
    "argument",
    "arguments",
    "body",
    "content",
    "input",
    "output",
    "prompt",
    "raw",
    "result",
    "response",
    "tool_args",
}
SAFE_REFERENCE_KEYS = {
    "error_ref",
    "provider_request_ref",
    "resource_ref",
    "result_digest",
    "result_ref",
}
EVENT_SPAN_NAMES = {
    "run.started": "invoke_workflow",
    "run.paused": "workflow.pause",
    "run.resumed": "workflow.resume",
    "run.cancel_requested": "workflow.cancel.request",
    "run.cancelled": "workflow.cancel",
    "run.completed": "workflow.complete",
    "run.failed": "workflow.fail",
    "wait.created": "workflow.wait",
    "wait.input_submitted": "workflow.wait.submit",
    "wait.expired": "workflow.wait.expire",
    "signal.received": "workflow.signal",
    "cancel.acknowledged": "workflow.cancel.ack",
    "task.scheduled": "workflow.task.schedule",
    "task.started": "workflow.task",
    "task.completed": "workflow.task.complete",
    "task.failed": "workflow.task.fail",
    "task.cancelled": "workflow.task.cancel",
    "agent.started": "invoke_agent",
    "agent.finished": "invoke_agent",
    "model.called": "chat",
    "tool.called": "execute_tool",
}
GEN_AI_COST_FIELDS = {
    "input_tokens": "gen_ai.usage.input_tokens",
    "output_tokens": "gen_ai.usage.output_tokens",
    "total_tokens": "gen_ai.usage.total_tokens",
    "cost_usd": "gen_ai.cost.total_usd",
    "total_cost_usd": "gen_ai.cost.total_usd",
}
BUNDLE_FIELDS = {
    "schema_version",
    "contract_revision",
    "mapping",
    "trace_context",
    "traces",
    "evidence",
    "provenance",
    "signature",
    "privacy",
    "bundle_digest",
}
TRACE_CONTEXT_FIELDS = {
    "schema_version",
    "source",
    "traceparent",
    "tracestate",
    "unknown_fields",
}
TRACE_FIELDS = {"run_id", "trace_id", "root_span_id", "traceparent", "tracestate", "spans"}
SPAN_FIELDS = {
    "span_id",
    "trace_id",
    "parent_span_id",
    "name",
    "kind",
    "start_time",
    "end_time",
    "status",
    "attributes",
}
EVIDENCE_FIELDS = {"lineage"}
SIGNATURE_FIELDS = {"schema_version", "key_id", "algorithm", "payload_type", "payload_digest", "signature"}
PRIVACY_FIELDS = {"schema_version", "mode", "policy_digest", "export_enabled", "max_length"}
TRUST_POLICY_FIELDS = {"schema_version", "policy_revision", "keys", "revoked_key_ids"}
TRUST_KEY_FIELDS = {"key_id", "algorithm", "key_b64", "status"}
PROVENANCE_FIELDS = {"_type", "subject", "predicateType", "predicate"}
PREDICATE_FIELDS = {"buildDefinition", "runDetails"}
BUILD_DEFINITION_FIELDS = {"buildType", "externalParameters", "internalParameters"}
EXTERNAL_PARAMETER_FIELDS = {"source_revision", "policy_revision"}
INTERNAL_PARAMETER_FIELDS = {"mapping_revision", "evidence_inputs"}
RUN_DETAILS_FIELDS = {"builder", "metadata"}


class ProvenanceError(ValueError):
    """Raised when a provenance bundle or trust policy is invalid."""


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ProvenanceError(f"value is not canonical JSON: {exc}") from exc


def digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest_ref(value: Any) -> str:
    return "sha256:" + digest(value)


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ProvenanceError(f"could not load Forge module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _lineage_module() -> Any:
    return _load_module("forge_lineage_for_provenance", Path(__file__).with_name("forge-lineage.py"))


def _bounded_text(value: Any, field: str, *, allow_none: bool = False, limit: int = 512) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ProvenanceError(f"{field} must be a non-empty string of at most {limit} characters")
    return value


def _assert_known_fields(value: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise ProvenanceError(f"{field} has unsupported fields: {', '.join(unknown)}")


def _redacted(value: Any) -> dict[str, Any]:
    return {"redacted": True, "sha256": digest_ref(value)}


def _normalized_key(key: Any) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
    value = re.sub(r"[^A-Za-z0-9]+", "_", value)
    return value.strip("_").lower()


def _is_forbidden_key(key: Any) -> bool:
    if str(key) in EVENT_SPAN_NAMES:
        return False
    normalized = _normalized_key(key)
    if normalized in SAFE_REFERENCE_KEYS:
        return False
    return normalized in SENSITIVE_PARTS or any(part in SENSITIVE_PARTS | CONTENT_PARTS for part in normalized.split("_"))


def _privacy_policy(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        value = {
            "schema_version": 1,
            "allow_content": False,
            "export_enabled": False,
            "allowed_keys": [],
            "max_length": 256,
        }
    if not isinstance(value, Mapping):
        raise ProvenanceError("privacy policy must be an object")
    allowed = {"schema_version", "allow_content", "export_enabled", "allowed_keys", "max_length"}
    _assert_known_fields(value, allowed, "privacy policy")
    if value.get("schema_version") != 1:
        raise ProvenanceError("privacy policy schema_version must be 1")
    allow_content = value.get("allow_content") is True
    export_enabled = value.get("export_enabled") is True
    allowed_keys = value.get("allowed_keys", [])
    if not isinstance(allowed_keys, list) or not all(isinstance(key, str) and key for key in allowed_keys):
        raise ProvenanceError("privacy policy allowed_keys must be a string array")
    if len(set(allowed_keys)) != len(allowed_keys):
        raise ProvenanceError("privacy policy allowed_keys must be unique")
    if any(_is_forbidden_key(key) for key in allowed_keys):
        raise ProvenanceError("privacy policy cannot allow sensitive or content keys")
    max_length = value.get("max_length", 256)
    if isinstance(max_length, bool) or not isinstance(max_length, int) or not 1 <= max_length <= MAX_ATTRIBUTE_LENGTH:
        raise ProvenanceError(f"privacy policy max_length must be between 1 and {MAX_ATTRIBUTE_LENGTH}")
    if allowed_keys and not export_enabled:
        raise ProvenanceError("privacy policy export_enabled must be true when keys are allowed")
    if allowed_keys and not allow_content:
        raise ProvenanceError("privacy policy allow_content must be true when keys are allowed")
    return {
        "schema_version": 1,
        "allow_content": allow_content,
        "export_enabled": export_enabled,
        "allowed_keys": sorted(allowed_keys),
        "max_length": max_length,
    }


def _sanitize_value(value: Any, key: str, policy: Mapping[str, Any]) -> Any:
    normalized = _normalized_key(key)
    explicitly_allowed = key in policy["allowed_keys"] and policy["allow_content"] and policy["export_enabled"]
    if _is_forbidden_key(key) or isinstance(value, (Mapping, list, tuple)):
        return _redacted(value)
    if isinstance(value, str):
        if explicitly_allowed:
            maximum = policy["max_length"]
            if len(value) > maximum:
                return {
                    "value": value[:maximum],
                    "truncated": True,
                    "sha256": digest_ref(value),
                }
            return value
        if len(value) > MAX_ATTRIBUTE_LENGTH:
            return _redacted(value)
        if normalized in SAFE_REFERENCE_KEYS:
            return value
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _redacted(value)


def sanitize_attributes(attributes: Mapping[str, Any], policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Sanitize attributes, allowing raw content only under an explicit policy."""

    if not isinstance(attributes, Mapping):
        raise ProvenanceError("attributes must be an object")
    normalized_policy = _privacy_policy(policy)
    return {
        str(key): _sanitize_value(value, str(key), normalized_policy)
        for key, value in sorted(attributes.items(), key=lambda item: str(item[0]))
    }


def _assert_private(value: Any, path: str = "bundle") -> None:
    if isinstance(value, Mapping):
        if path == "bundle.mapping":
            return
        if value.get("redacted") is True and set(value) == {"redacted", "sha256"}:
            if not isinstance(value["sha256"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["sha256"]):
                raise ProvenanceError(f"{path} has an invalid redaction digest")
            return
        for key, child in value.items():
            if _is_forbidden_key(key):
                raise ProvenanceError(f"{path}.{key} contains forbidden raw content")
            _assert_private(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_private(child, f"{path}[{index}]")


def _parse_tracestate(tracestate: str | None) -> str | None:
    if tracestate is None:
        return None
    if not isinstance(tracestate, str) or not tracestate or len(tracestate) > MAX_TRACESTATE:
        raise ProvenanceError(f"tracestate must be a non-empty string of at most {MAX_TRACESTATE} characters")
    members = [member.strip() for member in tracestate.split(",")]
    if not members or any(not member or member.count("=") != 1 for member in members):
        raise ProvenanceError("tracestate contains malformed list-members")
    for member in members:
        key, value = member.split("=", 1)
        if not TRACESTATE_KEY_RE.fullmatch(key) or not TRACESTATE_VALUE_RE.fullmatch(value):
            raise ProvenanceError("tracestate contains an invalid key or value")
    return tracestate


def parse_trace_context(traceparent: str | None, tracestate: str | None = None) -> dict[str, Any]:
    """Parse W3C Trace Context and retain future traceparent fields verbatim."""

    state = _parse_tracestate(tracestate)
    if traceparent is None:
        if state is not None:
            raise ProvenanceError("tracestate requires a valid traceparent")
        return {
            "source": "derived",
            "traceparent": None,
            "trace_id": None,
            "parent_span_id": None,
            "trace_flags": None,
            "version": None,
            "unknown_fields": [],
            "tracestate": None,
        }
    if not isinstance(traceparent, str) or not traceparent or len(traceparent) > MAX_TRACEPARENT:
        raise ProvenanceError(f"traceparent must be a string of at most {MAX_TRACEPARENT} characters")
    fields = traceparent.split("-")
    if len(fields) < 4 or any(not field for field in fields):
        raise ProvenanceError("traceparent has malformed fields")
    version, trace_id, parent_span_id, trace_flags = fields[:4]
    unknown_fields = fields[4:]
    if not re.fullmatch(r"[0-9a-f]{2}", version) or version == "ff":
        raise ProvenanceError("traceparent has an invalid version")
    if version == "00" and unknown_fields:
        raise ProvenanceError("traceparent version 00 cannot contain future fields")
    if any(not TRACEPARENT_PART_RE.fullmatch(field) for field in unknown_fields):
        raise ProvenanceError("traceparent contains malformed future fields")
    if not TRACE_ID_RE.fullmatch(trace_id) or trace_id == "0" * 32:
        raise ProvenanceError("traceparent has an invalid trace id")
    if not SPAN_ID_RE.fullmatch(parent_span_id) or parent_span_id == "0" * 16:
        raise ProvenanceError("traceparent has an invalid parent span id")
    if not TRACE_FLAGS_RE.fullmatch(trace_flags):
        raise ProvenanceError("traceparent has invalid trace flags")
    return {
        "source": "incoming",
        "traceparent": traceparent,
        "trace_id": trace_id,
        "parent_span_id": parent_span_id,
        "trace_flags": trace_flags,
        "version": version,
        "unknown_fields": unknown_fields,
        "tracestate": state,
    }


def _stable_span_id(kind: str, identifier: str) -> str:
    return sha256(f"forge-span:{kind}:{identifier}".encode()).hexdigest()[:16]


def _trace_for_run(run_id: str, incoming: Mapping[str, Any]) -> dict[str, Any]:
    trace_id = incoming["trace_id"] or sha256(f"forge-trace:{run_id}".encode()).hexdigest()[:32]
    root_span_id = _stable_span_id("run", run_id)
    trace_flags = incoming["trace_flags"] or "01"
    result = {
        "run_id": run_id,
        "trace_id": trace_id,
        "root_span_id": root_span_id,
        "traceparent": f"00-{trace_id}-{root_span_id}-{trace_flags}",
        "spans": [],
    }
    if incoming["tracestate"] is not None:
        result["tracestate"] = incoming["tracestate"]
    return result


def _mapping() -> dict[str, Any]:
    return {
        "version": OTEL_MAPPING_VERSION,
        "trace_context_version": TRACE_CONTEXT_VERSION,
        "otel_spec_version": OTEL_SPEC_VERSION,
        "gen_ai_semconv_version": GEN_AI_SEMCONV_VERSION,
        "event_span_names": dict(sorted(EVENT_SPAN_NAMES.items())),
        "attributes": {
            "run": {
                "forge.run.id": "runs[].run_id",
                "forge.workflow.id": "runs[].workflow_id",
                "forge.definition.version": "runs[].definition_version",
                "forge.policy.revision": "runs[].policy_revision",
                "forge.lineage.manifest.ref": "evidence.lineage.manifest_digest",
            },
            "event": {
                "forge.event.id": "runs[].events[].event_id",
                "forge.event.type": "runs[].events[].event_type",
                "forge.event.sequence": "runs[].events[].sequence",
                "forge.event.hash": "runs[].events[].event_hash",
            },
            "effect": {
                "forge.effect.id": "effects[].effect_id",
                "forge.effect.attempt": "effects[].attempts[].attempt",
                "forge.lease.generation": "effects[].attempts[].lease_generation",
                "forge.provider.request.ref": "receipts[].provider_request_ref",
            },
            "wait": {
                "forge.wait.event.id": "runs[].events[] where event_type starts wait.",
                "forge.signal.event.id": "runs[].events[] where event_type is signal.received",
            },
            "gen_ai": {
                "gen_ai.system": "forge",
                "gen_ai.operation.name": "event span name",
                "gen_ai.usage.input_tokens": "receipt.payload.input_tokens when bounded numeric",
                "gen_ai.usage.output_tokens": "receipt.payload.output_tokens when bounded numeric",
                "gen_ai.usage.total_tokens": "receipt.payload.total_tokens when bounded numeric",
                "gen_ai.cost.total_usd": "receipt.payload.cost_usd when bounded numeric",
            },
        },
    }


def _timestamp(value: Any, field: str) -> str:
    return _bounded_text(value, field, limit=64) or ""


def _span(
    trace: Mapping[str, Any],
    span_id: str,
    name: str,
    start_time: str,
    end_time: str,
    parent_span_id: str | None,
    attributes: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    kind: str = "internal",
    status: str = "ok",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "span_id": span_id,
        "trace_id": trace["trace_id"],
        "name": name,
        "kind": kind,
        "start_time": start_time,
        "end_time": end_time,
        "status": status,
        "attributes": sanitize_attributes(attributes, policy),
    }
    if parent_span_id is not None:
        result["parent_span_id"] = parent_span_id
    return result


def _cost_attributes(receipt: Mapping[str, Any]) -> dict[str, Any]:
    payload = receipt.get("payload")
    if not isinstance(payload, Mapping):
        return {}
    result: dict[str, Any] = {}
    for source_key, target_key in GEN_AI_COST_FIELDS.items():
        value = payload.get(source_key, payload.get(target_key))
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            continue
        result[target_key] = value
    return result


def _trace_projection(
    run: Mapping[str, Any],
    effects: list[Mapping[str, Any]],
    receipts: list[Mapping[str, Any]],
    lineage_digest: str,
    incoming: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    trace = _trace_for_run(run["run_id"], incoming)
    events = list(run["events"])
    event_span_ids = {event["event_id"]: _stable_span_id("event", event["event_id"]) for event in events}
    root_span_id = trace["root_span_id"]
    first_time = _timestamp(events[0]["occurred_at"] if events else "1970-01-01T00:00:00Z", "event.occurred_at")
    last_time = _timestamp(events[-1]["occurred_at"] if events else first_time, "event.occurred_at")
    trace["spans"].append(
        _span(
            trace,
            root_span_id,
            "invoke_workflow",
            first_time,
            last_time,
            incoming["parent_span_id"],
            {
                "forge.run.id": run["run_id"],
                "forge.workflow.id": run["workflow_id"],
                "forge.definition.version": run["definition_version"],
                "forge.policy.revision": run["policy_revision"],
                "forge.run.status": run["status"],
                "forge.run.sequence": run["sequence"],
                "forge.lineage.manifest.ref": lineage_digest,
            },
            policy,
        )
    )
    for event in events:
        event_type = event["event_type"]
        attributes: dict[str, Any] = {
            "forge.run.id": run["run_id"],
            "forge.event.id": event["event_id"],
            "forge.event.type": event_type,
            "forge.event.sequence": event["sequence"],
            "forge.event.idempotency.ref": digest_ref(event["idempotency_key"]),
            "forge.event.hash": event["event_hash"],
        }
        if event_type.startswith("wait."):
            attributes["forge.wait.event.id"] = event["event_id"]
        if event_type == "signal.received":
            attributes["forge.signal.event.id"] = event["event_id"]
        if event_type.startswith("agent."):
            attributes["gen_ai.system"] = "forge"
            attributes["gen_ai.operation.name"] = "invoke_agent"
        if event_type == "model.called":
            attributes["gen_ai.system"] = "forge"
            attributes["gen_ai.operation.name"] = "chat"
        if event_type == "tool.called":
            attributes["gen_ai.system"] = "forge"
            attributes["gen_ai.operation.name"] = "execute_tool"
        trace["spans"].append(
            _span(
                trace,
                event_span_ids[event["event_id"]],
                EVENT_SPAN_NAMES.get(event_type, "workflow.event"),
                _timestamp(event["occurred_at"], "event.occurred_at"),
                _timestamp(event["occurred_at"], "event.occurred_at"),
                root_span_id,
                attributes,
                policy,
            )
        )

    for effect in sorted((item for item in effects if item["run_id"] == run["run_id"]), key=lambda item: item["effect_id"]):
        effect_span_id = _stable_span_id("effect", effect["effect_id"])
        source_span_id = event_span_ids.get(effect["source_event_id"], root_span_id)
        attempts = sorted(effect["attempts"], key=lambda item: item["attempt"])
        effect_start = _timestamp(
            attempts[0]["claimed_at"] if attempts else next(
                event["occurred_at"] for event in events if event["event_id"] == effect["source_event_id"]
            ),
            "effect.start_time",
        )
        effect_end = _timestamp(
            (attempts[-1]["finished_at"] or attempts[-1]["claimed_at"]) if attempts else effect_start,
            "effect.end_time",
        )
        trace["spans"].append(
            _span(
                trace,
                effect_span_id,
                "execute_effect",
                effect_start,
                effect_end,
                source_span_id,
                {
                    "forge.run.id": run["run_id"],
                    "forge.effect.id": effect["effect_id"],
                    "forge.task.id": effect["task_id"],
                    "forge.activity.id": effect["activity_id"],
                    "forge.effect.definition.revision": effect["effect_definition_revision"],
                    "forge.effect.hash": effect["effect_hash"],
                    "forge.effect.idempotency.ref": digest_ref(effect["idempotency_key"]),
                    "forge.effect.status": effect["status"],
                },
                policy,
                kind="client",
                status="error" if effect["status"] in {"dead_letter", "retry"} else "ok",
            )
        )
        attempt_span_ids: dict[str, str] = {}
        for attempt in attempts:
            attempt_id = attempt["attempt_id"]
            attempt_span_id = _stable_span_id("attempt", attempt_id)
            attempt_span_ids[attempt_id] = attempt_span_id
            start = _timestamp(attempt["claimed_at"], "attempt.claimed_at")
            end = _timestamp(attempt["finished_at"] or attempt["claimed_at"], "attempt.finished_at")
            trace["spans"].append(
                _span(
                    trace,
                    attempt_span_id,
                    "execute_effect.attempt",
                    start,
                    end,
                    effect_span_id,
                    {
                        "forge.effect.id": effect["effect_id"],
                        "forge.effect.attempt": attempt["attempt"],
                        "forge.lease.generation": attempt["lease_generation"],
                        "forge.worker.id": digest_ref(attempt["worker_id"]),
                        "forge.attempt.outcome": attempt["outcome"],
                        "forge.error.ref": attempt["error_ref"],
                        "forge.retry.count": attempt["attempt"] - 1,
                    },
                    policy,
                    kind="client",
                    status="error" if attempt["outcome"] in {"dead_letter", "retry", "reclaimed"} else "ok",
                )
            )
        for receipt in sorted((item for item in receipts if item.get("effect_id") == effect["effect_id"]), key=lambda item: item["receipt_id"]):
            parent_span_id = attempt_span_ids.get(receipt.get("attempt_id"), effect_span_id)
            receipt_attributes: dict[str, Any] = {
                "forge.effect.id": effect["effect_id"],
                "forge.receipt.id": receipt["receipt_id"],
                "forge.receipt.type": receipt["receipt_type"],
                "forge.receipt.digest": receipt["receipt_digest"],
                "forge.receipt.status": receipt["status"],
                "forge.provider.request.ref": receipt["provider_request_ref"],
                **_cost_attributes(receipt),
            }
            trace["spans"].append(
                _span(
                    trace,
                    _stable_span_id("receipt", receipt["receipt_id"]),
                    "forge.effect.receipt",
                    _timestamp(receipt["occurred_at"], "receipt.occurred_at"),
                    _timestamp(receipt["occurred_at"], "receipt.occurred_at"),
                    parent_span_id,
                    receipt_attributes,
                    policy,
                    kind="client",
                    status="error" if receipt["status"] not in {"accepted", "succeeded"} else "ok",
                )
            )

    for receipt in sorted(
        (item for item in receipts if item.get("run_id") == run["run_id"] and item.get("effect_id") is None),
        key=lambda item: item["receipt_id"],
    ):
        trace["spans"].append(
            _span(
                trace,
                _stable_span_id("receipt", receipt["receipt_id"]),
                "forge.policy.receipt",
                _timestamp(receipt["occurred_at"], "receipt.occurred_at"),
                _timestamp(receipt["occurred_at"], "receipt.occurred_at"),
                root_span_id,
                {
                    "forge.receipt.id": receipt["receipt_id"],
                    "forge.receipt.type": receipt["receipt_type"],
                    "forge.receipt.digest": receipt["receipt_digest"],
                    "forge.receipt.status": receipt["status"],
                    **_cost_attributes(receipt),
                },
                policy,
                status="error" if receipt["status"] in {"denied", "failed"} else "ok",
            )
        )
    trace["spans"] = sorted(trace["spans"], key=lambda item: (item["start_time"], item["span_id"]))
    return trace


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read {label}: {exc}") from exc


def _load_trust_policy(path: Path) -> dict[str, Any]:
    value = _load_json(path, "trust policy")
    if not isinstance(value, Mapping):
        raise ProvenanceError("trust policy must be an object")
    _assert_known_fields(value, TRUST_POLICY_FIELDS, "trust policy")
    if value.get("schema_version") != 1:
        raise ProvenanceError("trust policy schema_version must be 1")
    revision = _bounded_text(value.get("policy_revision"), "trust policy.policy_revision")
    keys = value.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ProvenanceError("trust policy keys must be a non-empty array")
    revoked_ids = value.get("revoked_key_ids", [])
    if not isinstance(revoked_ids, list) or not all(isinstance(key_id, str) for key_id in revoked_ids):
        raise ProvenanceError("trust policy revoked_key_ids must be a string array")
    key_map: dict[str, dict[str, Any]] = {}
    for key in keys:
        if not isinstance(key, Mapping):
            raise ProvenanceError("trust policy key must be an object")
        _assert_known_fields(key, TRUST_KEY_FIELDS, "trust policy key")
        key_id = _bounded_text(key.get("key_id"), "trust policy key.key_id", limit=128)
        if not KEY_ID_RE.fullmatch(key_id or ""):
            raise ProvenanceError("trust policy key.key_id has an invalid format")
        if key_id in key_map:
            raise ProvenanceError(f"trust policy has duplicate key: {key_id}")
        if key.get("algorithm") != SIGNATURE_ALGORITHM:
            raise ProvenanceError(f"unsupported signature algorithm for key {key_id}")
        status = key.get("status")
        if status not in {"active", "retired", "revoked"}:
            raise ProvenanceError(f"trust policy key {key_id} has an invalid status")
        encoded = key.get("key_b64")
        if not isinstance(encoded, str) or not encoded:
            raise ProvenanceError(f"trust policy key {key_id} is missing key_b64")
        try:
            raw_key = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ProvenanceError(f"trust policy key {key_id} has invalid base64 key material") from exc
        if len(raw_key) < MIN_KEY_LENGTH:
            raise ProvenanceError(f"trust policy key {key_id} must be at least {MIN_KEY_LENGTH} bytes")
        key_map[key_id] = {"algorithm": SIGNATURE_ALGORITHM, "status": status, "key": raw_key}
    for key_id in revoked_ids:
        if key_id not in key_map:
            raise ProvenanceError(f"trust policy revokes unknown key: {key_id}")
        key_map[key_id]["status"] = "revoked"
    return {"schema_version": 1, "policy_revision": revision, "keys": key_map}


def _key_for_export(policy: Mapping[str, Any], key_id: str, key_path: Path) -> bytes:
    key = policy["keys"].get(key_id)
    if key is None:
        raise ProvenanceError(f"signing key is not present in trust policy: {key_id}")
    if key["status"] != "active":
        raise ProvenanceError(f"signing key is not active: {key_id}")
    try:
        raw_key = key_path.read_bytes()
    except OSError as exc:
        raise ProvenanceError(f"cannot read signing key: {exc}") from exc
    if not hmac.compare_digest(raw_key, key["key"]):
        raise ProvenanceError(f"signing key material does not match trust policy: {key_id}")
    return raw_key


def _pae(payload_type: str, payload: bytes) -> bytes:
    encoded_type = payload_type.encode("utf-8")
    return (
        b"DSSEv1 "
        + str(len(encoded_type)).encode("ascii")
        + b" "
        + encoded_type
        + b" "
        + str(len(payload)).encode("ascii")
        + b" "
        + payload
    )


def _signature(provenance: Mapping[str, Any], key_id: str, raw_key: bytes) -> dict[str, Any]:
    payload = canonical_json(provenance).encode("utf-8")
    signed = hmac.new(raw_key, _pae(PAYLOAD_TYPE, payload), sha256).digest()
    return {
        "schema_version": SCHEMA_VERSION,
        "key_id": key_id,
        "algorithm": SIGNATURE_ALGORITHM,
        "payload_type": PAYLOAD_TYPE,
        "payload_digest": digest_ref(provenance),
        "signature": base64.b64encode(signed).decode("ascii"),
    }


def _privacy_metadata(policy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "opt-in-content" if policy["allow_content"] and policy["export_enabled"] else "digest-only",
        "policy_digest": digest_ref(policy),
        "export_enabled": policy["export_enabled"],
        "max_length": policy["max_length"],
    }


def _statement(
    lineage_manifest: Mapping[str, Any],
    traces: list[Mapping[str, Any]],
    trace_context: Mapping[str, Any],
    mapping: Mapping[str, Any],
    source_revision: str,
    policy_revision: str,
) -> dict[str, Any]:
    subject_digest = lineage_manifest["manifest_digest"]
    evidence_inputs = [
        {"name": "runtime-lineage", "digest": subject_digest},
        {"name": "trace-projection", "digest": digest_ref(traces)},
        {"name": "trace-context", "digest": digest_ref(trace_context)},
        {"name": "mapping", "digest": digest_ref(mapping)},
    ]
    invocation_id = digest_ref(
        {"subject_digest": subject_digest, "source_revision": source_revision, "policy_revision": policy_revision}
    )
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": "forge-runtime-lineage", "digest": {"sha256": subject_digest.split(":", 1)[1]}}],
        "predicateType": PROVENANCE_TYPE,
        "predicate": {
            "buildDefinition": {
                "buildType": BUILD_TYPE,
                "externalParameters": {
                    "source_revision": source_revision,
                    "policy_revision": policy_revision,
                },
                "internalParameters": {
                    "mapping_revision": mapping["version"],
                    "evidence_inputs": evidence_inputs,
                },
            },
            "runDetails": {
                "builder": {"id": BUILDER_ID},
                "metadata": {"invocation_id": invocation_id},
            },
        },
    }


def _assert_policy_revision_matches_lineage(manifest: Mapping[str, Any], policy_revision: str) -> None:
    revisions = {run["policy_revision"] for run in manifest["runs"]}
    if revisions != {policy_revision}:
        rendered = ", ".join(sorted(revisions)) or "<none>"
        raise ProvenanceError(
            f"policy_revision does not match lineage evidence: expected {policy_revision}, found {rendered}"
        )


def export_bundle(
    database: Path,
    *,
    source_revision: str,
    policy_revision: str,
    signing_key_path: Path,
    trust_policy_path: Path,
    key_id: str,
    receipts_path: Path | None = None,
    traceparent: str | None = None,
    tracestate: str | None = None,
    privacy_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Export a deterministic bundle without mutating the runtime database."""

    source_revision = _bounded_text(source_revision, "source_revision") or ""
    policy_revision = _bounded_text(policy_revision, "policy_revision") or ""
    key_id = _bounded_text(key_id, "key_id", limit=128) or ""
    if not KEY_ID_RE.fullmatch(key_id):
        raise ProvenanceError("key_id has an invalid format")
    policy = _privacy_policy(privacy_policy)
    trust_policy = _load_trust_policy(Path(trust_policy_path))
    raw_key = _key_for_export(trust_policy, key_id, Path(signing_key_path))
    lineage = _lineage_module()
    manifest = lineage.export_manifest(Path(database), Path(receipts_path) if receipts_path is not None else None)
    lineage.verify_manifest(manifest)
    _assert_policy_revision_matches_lineage(manifest, policy_revision)
    incoming = parse_trace_context(traceparent, tracestate)
    trace_context = {
        "schema_version": 1,
        "source": incoming["source"],
        "traceparent": incoming["traceparent"],
        "tracestate": incoming["tracestate"],
        "unknown_fields": list(incoming["unknown_fields"]),
    }
    mapping = _mapping()
    traces = [
        _trace_projection(
            run,
            manifest["effects"],
            manifest["receipts"],
            manifest["manifest_digest"],
            incoming,
            policy,
        )
        for run in sorted(manifest["runs"], key=lambda item: item["run_id"])
    ]
    provenance = _statement(manifest, traces, trace_context, mapping, source_revision, policy_revision)
    body = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "mapping": mapping,
        "trace_context": trace_context,
        "traces": traces,
        "evidence": {"lineage": manifest},
        "provenance": provenance,
        "signature": _signature(provenance, key_id, raw_key),
        "privacy": _privacy_metadata(policy),
    }
    bundle = {**body, "bundle_digest": digest_ref(body)}
    verify_bundle(bundle, trust_policy_path, expected_source_revision=source_revision, expected_policy_revision=policy_revision)
    return bundle


def _verify_trace_context(value: Mapping[str, Any], field: str) -> None:
    _assert_known_fields(value, TRACE_CONTEXT_FIELDS, field)
    if value.get("schema_version") != 1:
        raise ProvenanceError(f"{field}.schema_version must be 1")
    if value.get("source") not in {"derived", "incoming"}:
        raise ProvenanceError(f"{field}.source is invalid")
    unknown = value.get("unknown_fields")
    if not isinstance(unknown, list) or not all(isinstance(item, str) for item in unknown):
        raise ProvenanceError(f"{field}.unknown_fields must be a string array")
    parsed = parse_trace_context(value.get("traceparent"), value.get("tracestate"))
    if parsed["source"] != value["source"] or parsed["unknown_fields"] != unknown:
        raise ProvenanceError(f"{field} does not preserve parsed W3C context")


def _verify_traces(traces: Any, trace_context: Mapping[str, Any]) -> None:
    if not isinstance(traces, list):
        raise ProvenanceError("traces must be an array")
    seen_spans: set[str] = set()
    for trace in traces:
        if not isinstance(trace, Mapping):
            raise ProvenanceError("trace must be an object")
        _assert_known_fields(trace, TRACE_FIELDS, "trace")
        run_id = _bounded_text(trace.get("run_id"), "trace.run_id")
        trace_id = trace.get("trace_id")
        root_span_id = trace.get("root_span_id")
        if not isinstance(trace_id, str) or not TRACE_ID_RE.fullmatch(trace_id) or trace_id == "0" * 32:
            raise ProvenanceError(f"trace has invalid trace_id: {run_id}")
        if not isinstance(root_span_id, str) or not SPAN_ID_RE.fullmatch(root_span_id) or root_span_id == "0" * 16:
            raise ProvenanceError(f"trace has invalid root_span_id: {run_id}")
        parsed = parse_trace_context(trace.get("traceparent"), trace.get("tracestate"))
        if parsed["trace_id"] != trace_id or parsed["parent_span_id"] != root_span_id:
            raise ProvenanceError(f"traceparent does not describe trace root: {run_id}")
        spans = trace.get("spans")
        if not isinstance(spans, list) or not spans:
            raise ProvenanceError(f"trace spans must be a non-empty array: {run_id}")
        root_seen = False
        for span in spans:
            if not isinstance(span, Mapping):
                raise ProvenanceError(f"span must be an object: {run_id}")
            _assert_known_fields(span, SPAN_FIELDS, "span")
            span_id = span.get("span_id")
            if not isinstance(span_id, str) or not SPAN_ID_RE.fullmatch(span_id) or span_id in seen_spans:
                raise ProvenanceError(f"span has an invalid or duplicate span_id: {run_id}")
            seen_spans.add(span_id)
            if span.get("trace_id") != trace_id:
                raise ProvenanceError(f"span trace_id mismatch: {span_id}")
            if not isinstance(span.get("attributes"), Mapping):
                raise ProvenanceError(f"span attributes must be an object: {span_id}")
            _bounded_text(span.get("name"), "span.name")
            _bounded_text(span.get("kind"), "span.kind")
            _bounded_text(span.get("start_time"), "span.start_time", limit=64)
            _bounded_text(span.get("end_time"), "span.end_time", limit=64)
            if span.get("status") not in {"ok", "error"}:
                raise ProvenanceError(f"span status is invalid: {span_id}")
            parent = span.get("parent_span_id")
            if parent is not None and (not isinstance(parent, str) or not SPAN_ID_RE.fullmatch(parent)):
                raise ProvenanceError(f"span parent is invalid: {span_id}")
            if span_id == root_span_id:
                root_seen = True
                if parent is not None and trace_context["source"] == "derived":
                    raise ProvenanceError(f"derived root span has a parent: {run_id}")
        if not root_seen:
            raise ProvenanceError(f"trace is missing root span: {run_id}")


def _verify_provenance(
    provenance: Mapping[str, Any],
    manifest: Mapping[str, Any],
    traces: list[Mapping[str, Any]],
    trace_context: Mapping[str, Any],
    mapping: Mapping[str, Any],
    expected_source_revision: str | None,
    expected_policy_revision: str | None,
) -> tuple[str, str]:
    _assert_known_fields(provenance, PROVENANCE_FIELDS, "provenance")
    if provenance.get("_type") != STATEMENT_TYPE or provenance.get("predicateType") != PROVENANCE_TYPE:
        raise ProvenanceError("provenance statement type is unsupported")
    subject = provenance.get("subject")
    if not isinstance(subject, list) or len(subject) != 1 or not isinstance(subject[0], Mapping):
        raise ProvenanceError("provenance must contain exactly one subject")
    subject_item = subject[0]
    if subject_item.get("name") != "forge-runtime-lineage":
        raise ProvenanceError("provenance subject name is invalid")
    subject_digest = subject_item.get("digest")
    if not isinstance(subject_digest, Mapping) or set(subject_digest) != {"sha256"}:
        raise ProvenanceError("provenance subject digest is malformed")
    subject_hex = subject_digest.get("sha256")
    if not isinstance(subject_hex, str) or not re.fullmatch(r"[0-9a-f]{64}", subject_hex):
        raise ProvenanceError("provenance subject digest is invalid")
    expected_subject = manifest.get("manifest_digest")
    if expected_subject != "sha256:" + subject_hex:
        raise ProvenanceError("provenance subject digest does not match lineage evidence")
    predicate = provenance.get("predicate")
    if not isinstance(predicate, Mapping):
        raise ProvenanceError("provenance predicate must be an object")
    _assert_known_fields(predicate, PREDICATE_FIELDS, "provenance.predicate")
    build = predicate.get("buildDefinition")
    if not isinstance(build, Mapping):
        raise ProvenanceError("provenance buildDefinition must be an object")
    _assert_known_fields(build, BUILD_DEFINITION_FIELDS, "provenance.buildDefinition")
    if build.get("buildType") != BUILD_TYPE:
        raise ProvenanceError("provenance build type is unsupported")
    external = build.get("externalParameters")
    if not isinstance(external, Mapping):
        raise ProvenanceError("provenance externalParameters must be an object")
    _assert_known_fields(external, EXTERNAL_PARAMETER_FIELDS, "provenance.externalParameters")
    source_revision = _bounded_text(external.get("source_revision"), "provenance.source_revision") or ""
    policy_revision = _bounded_text(external.get("policy_revision"), "provenance.policy_revision") or ""
    _assert_policy_revision_matches_lineage(manifest, policy_revision)
    if expected_source_revision is not None and source_revision != expected_source_revision:
        raise ProvenanceError("source revision does not match expected value")
    if expected_policy_revision is not None and policy_revision != expected_policy_revision:
        raise ProvenanceError("policy revision does not match expected value")
    internal = build.get("internalParameters")
    if not isinstance(internal, Mapping):
        raise ProvenanceError("provenance internalParameters must be an object")
    _assert_known_fields(internal, INTERNAL_PARAMETER_FIELDS, "provenance.internalParameters")
    if internal.get("mapping_revision") != mapping["version"]:
        raise ProvenanceError("provenance mapping revision does not match bundle mapping")
    inputs = internal.get("evidence_inputs")
    expected_inputs = [
        {"name": "runtime-lineage", "digest": manifest["manifest_digest"]},
        {"name": "trace-projection", "digest": digest_ref(traces)},
        {"name": "trace-context", "digest": digest_ref(trace_context)},
        {"name": "mapping", "digest": digest_ref(mapping)},
    ]
    if inputs != expected_inputs:
        names = {item.get("name") for item in inputs} if isinstance(inputs, list) else set()
        if "trace-projection" in names:
            raise ProvenanceError("trace projection digest does not match bundle")
        raise ProvenanceError("provenance evidence inputs do not match bundle")
    run_details = predicate.get("runDetails")
    if not isinstance(run_details, Mapping):
        raise ProvenanceError("provenance runDetails must be an object")
    _assert_known_fields(run_details, RUN_DETAILS_FIELDS, "provenance.runDetails")
    builder = run_details.get("builder")
    metadata = run_details.get("metadata")
    if not isinstance(builder, Mapping) or builder.get("id") != BUILDER_ID:
        raise ProvenanceError("provenance builder identity is invalid")
    if not isinstance(metadata, Mapping) or metadata.get("invocation_id") != digest_ref(
        {"subject_digest": manifest["manifest_digest"], "source_revision": source_revision, "policy_revision": policy_revision}
    ):
        raise ProvenanceError("provenance invocation identity is invalid")
    return source_revision, policy_revision


def _verify_signature(bundle: Mapping[str, Any], trust_policy_path: Path) -> str:
    signature = bundle.get("signature")
    if not isinstance(signature, Mapping):
        raise ProvenanceError("signature must be an object")
    _assert_known_fields(signature, SIGNATURE_FIELDS, "signature")
    if signature.get("schema_version") != 1 or signature.get("algorithm") != SIGNATURE_ALGORITHM:
        raise ProvenanceError("signature schema or algorithm is unsupported")
    if signature.get("payload_type") != PAYLOAD_TYPE:
        raise ProvenanceError("signature payload type is unsupported")
    key_id = _bounded_text(signature.get("key_id"), "signature.key_id", limit=128) or ""
    trust_policy = _load_trust_policy(Path(trust_policy_path))
    key = trust_policy["keys"].get(key_id)
    if key is None:
        raise ProvenanceError(f"signature key is not trusted: {key_id}")
    if key["status"] == "revoked":
        raise ProvenanceError(f"signature key is revoked: {key_id}")
    provenance = bundle["provenance"]
    payload = canonical_json(provenance).encode("utf-8")
    if signature.get("payload_digest") != digest_ref(provenance):
        raise ProvenanceError("signature payload digest mismatch")
    encoded = signature.get("signature")
    if not isinstance(encoded, str) or not encoded:
        raise ProvenanceError("signature value is missing")
    try:
        actual = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ProvenanceError("signature value is not valid base64") from exc
    expected = hmac.new(key["key"], _pae(PAYLOAD_TYPE, payload), sha256).digest()
    if not hmac.compare_digest(actual, expected):
        raise ProvenanceError("signature verification failed")
    return key_id


def verify_bundle(
    bundle: Mapping[str, Any],
    trust_policy_path: Path,
    *,
    expected_subject_digest: str | None = None,
    expected_source_revision: str | None = None,
    expected_policy_revision: str | None = None,
) -> dict[str, Any]:
    """Verify a bundle, its lineage subject, context, evidence inputs, and signature offline."""

    if not isinstance(bundle, Mapping):
        raise ProvenanceError("bundle must be an object")
    _assert_known_fields(bundle, BUNDLE_FIELDS, "bundle")
    required = BUNDLE_FIELDS
    missing = sorted(required - set(bundle))
    if missing:
        raise ProvenanceError("bundle is missing: " + ", ".join(missing))
    if bundle.get("schema_version") != SCHEMA_VERSION or bundle.get("contract_revision") != CONTRACT_REVISION:
        raise ProvenanceError("unsupported provenance bundle revision")
    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    if bundle.get("bundle_digest") != digest_ref(body):
        raise ProvenanceError("bundle digest mismatch")
    mapping = bundle.get("mapping")
    if mapping != _mapping():
        raise ProvenanceError("bundle mapping is not the pinned Forge mapping")
    trace_context = bundle.get("trace_context")
    if not isinstance(trace_context, Mapping):
        raise ProvenanceError("trace_context must be an object")
    _verify_trace_context(trace_context, "trace_context")
    privacy = bundle.get("privacy")
    if not isinstance(privacy, Mapping):
        raise ProvenanceError("privacy must be an object")
    _assert_known_fields(privacy, PRIVACY_FIELDS, "privacy")
    if privacy.get("schema_version") != 1 or privacy.get("mode") not in {"digest-only", "opt-in-content"}:
        raise ProvenanceError("privacy metadata is invalid")
    if not isinstance(privacy.get("policy_digest"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", privacy["policy_digest"]):
        raise ProvenanceError("privacy policy digest is invalid")
    _assert_private(bundle)
    evidence = bundle.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ProvenanceError("evidence must be an object")
    _assert_known_fields(evidence, EVIDENCE_FIELDS, "evidence")
    manifest = evidence.get("lineage")
    if not isinstance(manifest, Mapping):
        raise ProvenanceError("evidence.lineage must be an object")
    lineage = _lineage_module()
    lineage_result = lineage.verify_manifest(manifest)
    subject_digest = manifest["manifest_digest"]
    if expected_subject_digest is not None and subject_digest != expected_subject_digest:
        raise ProvenanceError("lineage subject digest does not match expected value")
    traces = bundle.get("traces")
    _verify_traces(traces, trace_context)
    source_revision, policy_revision = _verify_provenance(
        bundle["provenance"],
        manifest,
        traces,
        trace_context,
        mapping,
        expected_source_revision,
        expected_policy_revision,
    )
    key_id = _verify_signature(bundle, Path(trust_policy_path))
    return {
        "verified": True,
        "bundle_digest": bundle["bundle_digest"],
        "subject_digest": subject_digest,
        "source_revision": source_revision,
        "policy_revision": policy_revision,
        "key_id": key_id,
        "traces": len(traces),
        "spans": sum(len(trace["spans"]) for trace in traces),
        "lineage": lineage_result,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export and verify signed Forge provenance offline")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="export a signed provenance bundle from runtime evidence")
    export.add_argument("--db", type=Path, required=True)
    export.add_argument("--receipts", type=Path)
    export.add_argument("--source-revision", required=True)
    export.add_argument("--policy-revision", required=True)
    export.add_argument("--key-id", required=True)
    export.add_argument("--key-file", type=Path, required=True)
    export.add_argument("--trust-policy", type=Path, required=True)
    export.add_argument("--traceparent")
    export.add_argument("--tracestate")
    export.add_argument("--privacy-policy", type=Path)
    export.add_argument("--output", type=Path)
    verify = sub.add_parser("verify", help="verify a signed provenance bundle without network access")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--trust-policy", type=Path, required=True)
    verify.add_argument("--subject-digest")
    verify.add_argument("--source-revision")
    verify.add_argument("--policy-revision")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "export":
            privacy_policy = _load_json(args.privacy_policy, "privacy policy") if args.privacy_policy else None
            bundle = export_bundle(
                args.db,
                source_revision=args.source_revision,
                policy_revision=args.policy_revision,
                signing_key_path=args.key_file,
                trust_policy_path=args.trust_policy,
                key_id=args.key_id,
                receipts_path=args.receipts,
                traceparent=args.traceparent,
                tracestate=args.tracestate,
                privacy_policy=privacy_policy,
            )
        else:
            bundle = _load_json(args.bundle, "provenance bundle")
            result = verify_bundle(
                bundle,
                args.trust_policy,
                expected_subject_digest=args.subject_digest,
                expected_source_revision=args.source_revision,
                expected_policy_revision=args.policy_revision,
            )
            print(json.dumps(result, ensure_ascii=True, sort_keys=True))
            return 0
        rendered = json.dumps(bundle, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    except (ProvenanceError, OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        print(f"forge-provenance: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
