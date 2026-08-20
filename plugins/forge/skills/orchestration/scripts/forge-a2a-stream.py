#!/usr/bin/env python3
"""Verify A2A 1.0 StreamResponse evidence without contacting a provider."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
CONTRACT_REVISION = "forge-a2a-stream-v2"
SCHEMA_URI = "https://github.com/AlisinaDevelo/md-files/schema/runtime/a2a-stream/v2"
PROTOCOL_VERSION = "1.0"
REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OPAQUE_RE = re.compile(
    r"^[a-z][a-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._:/@-]{0,191}$"
)
FORBIDDEN_VALUE_RE = re.compile(
    r"(?:github_pat_|gh[opusr]_|Bearer\s+|sk-[A-Za-z0-9]{16,}|eyJ[A-Za-z0-9._-]{16,})",
    re.IGNORECASE,
)

STATES = {
    "TASK_STATE_SUBMITTED",
    "TASK_STATE_WORKING",
    "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_AUTH_REQUIRED",
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
}
TERMINAL_STATES = {
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
}
INTERRUPTED_STATES = {"TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED"}
CLOSING_STATES = TERMINAL_STATES | INTERRUPTED_STATES
RESPONSE_MEMBERS = {"task", "message", "statusUpdate", "artifactUpdate"}
PUSH_MEMBERS = RESPONSE_MEMBERS
ENVELOPE_FIELDS = {
    "$schema",
    "schema_version",
    "contract_revision",
    "card_ref",
    "protocol_version",
    "context",
    "context_id",
    "task_id",
    "streams",
    "push",
}
CONTEXT_FIELDS = {
    "host_ref",
    "audience_ref",
    "workspace_ref",
    "resource_ref",
    "authority_ref",
    "admission_ref",
    "lease_ref",
    "runtime_episode_ref",
    "provider_operation_ref",
    "provenance_ref",
}
STREAM_FIELDS = {"stream_id", "closed", "events"}
EVENT_FIELDS = {
    "event_id",
    "response_member",
    "sequence",
    "observed_at",
    "task_ref",
    "message_id",
    "message_ref",
    "task_state",
    "artifact_refs",
}
PUSH_FIELDS = {
    "delivery_id",
    "stream_id",
    "event_id",
    "task_id",
    "context_id",
    "response_member",
    "endpoint_ref",
    "payload_ref",
}
CORPUS_FIELDS = {"case_id", "expected", "envelope"}
FORBIDDEN_KEYS = {
    "authorization",
    "body",
    "content",
    "credentials",
    "headers",
    "parts",
    "payload",
    "prompt",
    "provider_response",
    "raw",
    "secret",
    "token",
}


class A2AStreamError(ValueError):
    """Raised when A2A StreamResponse evidence cannot be admitted."""


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise A2AStreamError(f"canonical-json: {exc}") from exc


def digest_ref(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise A2AStreamError(f"invalid-{label}: expected object with string keys")
    return {str(key): copy.deepcopy(child) for key, child in value.items()}


def _unknown(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise A2AStreamError(f"unknown-{label}-field:" + ",".join(unknown))


def _text(value: Any, label: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise A2AStreamError(f"invalid-{label}: expected bounded string")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        raise A2AStreamError(f"invalid-{label}: control character")
    if FORBIDDEN_VALUE_RE.search(value):
        raise A2AStreamError(f"{label} contains credential-shaped material")
    return value


def _opaque(value: Any, label: str) -> str:
    result = _text(value, label, maximum=256)
    if "://" in result:
        raise A2AStreamError(f"invalid-{label}: URL-shaped reference")
    if not OPAQUE_RE.fullmatch(result):
        raise A2AStreamError(f"invalid-{label}: malformed reference")
    return result


def _ref(value: Any, label: str) -> str:
    result = _text(value, label, maximum=71)
    if not REF_RE.fullmatch(result):
        raise A2AStreamError(f"invalid-{label}: expected sha256 reference")
    return result


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 1_000_000:
        raise A2AStreamError(f"invalid-{label}: expected bounded positive integer")
    return value


def _time(value: Any, label: str) -> datetime:
    text = _text(value, label, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise A2AStreamError(f"invalid-{label}: expected RFC3339") from exc
    if parsed.tzinfo is None:
        raise A2AStreamError(f"invalid-{label}: timezone required")
    return parsed.astimezone(timezone.utc)


def _ref_list(value: Any, label: str, *, maximum: int = 64) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise A2AStreamError(f"invalid-{label}: expected bounded array")
    refs = [_ref(item, f"{label}-item") for item in value]
    if len(refs) != len(set(refs)):
        raise A2AStreamError(f"invalid-{label}: duplicate references")
    return refs


def _reject_forbidden_keys(value: Any, path: str = "envelope") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower().replace("-", "_")
            if key_text in FORBIDDEN_KEYS:
                raise A2AStreamError(f"{path}.{key} cannot contain raw provider material")
            _reject_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{path}[{index}]")


def _parse_context(value: Any) -> dict[str, str]:
    data = _mapping(value, "context")
    _unknown(data, CONTEXT_FIELDS, "context")
    missing = sorted(CONTEXT_FIELDS - set(data))
    if missing:
        raise A2AStreamError("missing-context-fields:" + ",".join(missing))
    context: dict[str, str] = {}
    opaque_fields = {"host_ref", "audience_ref", "workspace_ref", "resource_ref"}
    for field in sorted(opaque_fields):
        context[field] = _opaque(data[field], f"context.{field}")
    for field in sorted(CONTEXT_FIELDS - opaque_fields):
        context[field] = _ref(data[field], f"context.{field}")
    return context


def _response_material(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "response_member": event["response_member"],
        "sequence": event["sequence"],
        "task_ref": event.get("task_ref"),
        "message_id": event.get("message_id"),
        "message_ref": event.get("message_ref"),
        "task_state": event.get("task_state"),
        "artifact_refs": list(event.get("artifact_refs", [])),
    }


def _event_material(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event["event_id"],
        "observed_at": event["observed_at"],
        "response_ref": event["response_ref"],
    }


def _parse_event(value: Any, stream_index: int, event_index: int) -> dict[str, Any]:
    label = f"stream-{stream_index}.event-{event_index}"
    data = _mapping(value, label)
    _unknown(data, EVENT_FIELDS, label)
    required = {"event_id", "response_member", "sequence", "observed_at"}
    missing = sorted(required - set(data))
    if missing:
        raise A2AStreamError(f"missing-{label}-fields:" + ",".join(missing))
    response_member = _text(
        data["response_member"], f"{label}.response_member", maximum=32
    )
    if response_member not in RESPONSE_MEMBERS:
        raise A2AStreamError(f"unsupported-response-member:{response_member}")
    event: dict[str, Any] = {
        "event_id": _opaque(data["event_id"], f"{label}.event_id"),
        "response_member": response_member,
        "sequence": _positive_int(data["sequence"], f"{label}.sequence"),
        "observed_at": _time(data["observed_at"], f"{label}.observed_at")
        .isoformat()
        .replace("+00:00", "Z"),
    }
    if "task_ref" in data:
        event["task_ref"] = _ref(data["task_ref"], f"{label}.task_ref")
    if "message_id" in data:
        event["message_id"] = _opaque(data["message_id"], f"{label}.message_id")
    if "message_ref" in data:
        event["message_ref"] = _ref(data["message_ref"], f"{label}.message_ref")
    if "task_state" in data:
        event["task_state"] = _text(data["task_state"], f"{label}.task_state", maximum=64)
        if event["task_state"] not in STATES:
            raise A2AStreamError(f"unsupported-task-state:{event['task_state']}")
    event["artifact_refs"] = (
        _ref_list(data["artifact_refs"], f"{label}.artifact_refs")
        if "artifact_refs" in data
        else []
    )
    if ("message_id" in event) != ("message_ref" in event):
        raise A2AStreamError(f"message-reference-pair-required:{label}")
    if response_member == "message":
        if "message_id" not in event or event["sequence"] != 1:
            raise A2AStreamError("message-only-stream-shape-invalid")
        if any(key in event for key in ("task_ref", "task_state")) or event["artifact_refs"]:
            raise A2AStreamError("message-event-has-task-payload")
    elif response_member == "task":
        if "task_ref" not in event or "task_state" not in event or event["sequence"] != 1:
            raise A2AStreamError("task-first-response-shape-invalid")
        if any(key in event for key in ("message_id", "message_ref")) or event["artifact_refs"]:
            raise A2AStreamError("task-event-has-message-or-artifact-payload")
    elif response_member == "statusUpdate":
        if "task_state" not in event or event["artifact_refs"] or "task_ref" in event:
            raise A2AStreamError("status-update-shape-invalid")
        if any(key in event for key in ("message_id", "message_ref")):
            raise A2AStreamError("status-update-has-message-payload")
    elif response_member == "artifactUpdate":
        if not event["artifact_refs"] or "task_state" in event or "task_ref" in event:
            raise A2AStreamError("artifact-update-shape-invalid")
        if any(key in event for key in ("message_id", "message_ref")):
            raise A2AStreamError("artifact-update-has-message-payload")
    event["response_ref"] = digest_ref(_response_material(event))
    return event


def _allowed_states(previous: str) -> set[str]:
    return {
        "TASK_STATE_SUBMITTED": {
            "TASK_STATE_SUBMITTED",
            "TASK_STATE_WORKING",
            "TASK_STATE_INPUT_REQUIRED",
            "TASK_STATE_AUTH_REQUIRED",
            *TERMINAL_STATES,
        },
        "TASK_STATE_WORKING": {
            "TASK_STATE_WORKING",
            "TASK_STATE_INPUT_REQUIRED",
            "TASK_STATE_AUTH_REQUIRED",
            *TERMINAL_STATES,
        },
        "TASK_STATE_INPUT_REQUIRED": {
            "TASK_STATE_INPUT_REQUIRED",
            "TASK_STATE_WORKING",
            "TASK_STATE_AUTH_REQUIRED",
            "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED",
            "TASK_STATE_REJECTED",
        },
        "TASK_STATE_AUTH_REQUIRED": {
            "TASK_STATE_AUTH_REQUIRED",
            "TASK_STATE_WORKING",
            "TASK_STATE_INPUT_REQUIRED",
            "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED",
            "TASK_STATE_REJECTED",
        },
    }.get(previous, set())


def _parse_stream(value: Any, stream_index: int) -> dict[str, Any]:
    data = _mapping(value, f"stream-{stream_index}")
    _unknown(data, STREAM_FIELDS, f"stream-{stream_index}")
    missing = sorted(STREAM_FIELDS - set(data))
    if missing:
        raise A2AStreamError("missing-stream-fields:" + ",".join(missing))
    stream_id = _opaque(data["stream_id"], f"stream-{stream_index}.stream_id")
    if not isinstance(data["closed"], bool):
        raise A2AStreamError(f"invalid-stream-{stream_index}.closed")
    if not data["closed"]:
        raise A2AStreamError("stream-transport-closure-required")
    raw_events = data["events"]
    if not isinstance(raw_events, list) or not raw_events or len(raw_events) > 512:
        raise A2AStreamError(f"invalid-stream-{stream_index}.events: expected bounded non-empty array")
    events = [_parse_event(raw, stream_index, index) for index, raw in enumerate(raw_events, start=1)]
    if [event["sequence"] for event in events] != list(range(1, len(events) + 1)):
        raise A2AStreamError("stream-sequence-gap")
    event_ids = [event["event_id"] for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise A2AStreamError("duplicate-stream-event-id")
    previous_time: datetime | None = None
    for event_index, event in enumerate(events, start=1):
        observed_at = _time(
            event["observed_at"], f"stream-{stream_index}.events[{event_index}].observed_at"
        )
        if previous_time is not None and observed_at < previous_time:
            raise A2AStreamError("stream-time-regression")
        previous_time = observed_at
    first = events[0]
    if first["response_member"] == "message":
        if len(events) != 1:
            raise A2AStreamError("message-only-stream-must-close-after-one-message")
        mode = "message"
        closing_state = None
    elif first["response_member"] == "task":
        mode = "task"
        previous_state = first["task_state"]
        if previous_state in TERMINAL_STATES:
            if len(events) != 1:
                raise A2AStreamError("event-after-terminal-task")
        elif len(events) == 1:
            if previous_state not in INTERRUPTED_STATES:
                raise A2AStreamError(
                    "task-stream-must-close-with-terminal-or-interrupted-status"
                )
        else:
            for event in events[1:]:
                if event["response_member"] == "statusUpdate":
                    if previous_state in TERMINAL_STATES or event[
                        "task_state"
                    ] not in _allowed_states(previous_state):
                        raise A2AStreamError("stream-invalid-state-transition")
                    previous_state = event["task_state"]
                elif event["response_member"] == "artifactUpdate":
                    if previous_state in TERMINAL_STATES:
                        raise A2AStreamError("artifact-after-terminal-task")
                else:
                    raise A2AStreamError("task-stream-response-member-invalid")
            if (
                events[-1]["response_member"] != "statusUpdate"
                or events[-1]["task_state"] not in CLOSING_STATES
            ):
                raise A2AStreamError("task-stream-must-close-with-terminal-or-interrupted-status")
        closing_state = events[-1].get("task_state")
    else:
        raise A2AStreamError("stream-must-start-with-task-or-message")
    event_refs = [digest_ref(_event_material(event)) for event in events]
    response_refs = [event["response_ref"] for event in events]
    return {
        "stream_id": stream_id,
        "closed": data["closed"],
        "mode": mode,
        "events": events,
        "event_refs": event_refs,
        "response_refs": response_refs,
        "closing_state": closing_state,
        "stream_ref": digest_ref(
            {
                "stream_id": stream_id,
                "mode": mode,
                "event_refs": event_refs,
                "response_refs": response_refs,
                "closing_state": closing_state,
                "closed": data["closed"],
            }
        ),
    }


def _parse_push(
    value: Any,
    *,
    task_id: str,
    context_id: str,
    streams: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    data = _mapping(value, "push")
    _unknown(data, PUSH_FIELDS, "push")
    missing = sorted(PUSH_FIELDS - set(data))
    if missing:
        raise A2AStreamError("missing-push-fields:" + ",".join(missing))
    delivery = {
        "delivery_id": _opaque(data["delivery_id"], "push.delivery_id"),
        "stream_id": _opaque(data["stream_id"], "push.stream_id"),
        "event_id": _opaque(data["event_id"], "push.event_id"),
        "task_id": _opaque(data["task_id"], "push.task_id"),
        "context_id": _opaque(data["context_id"], "push.context_id"),
        "response_member": _text(
            data["response_member"], "push.response_member", maximum=32
        ),
        "endpoint_ref": _ref(data["endpoint_ref"], "push.endpoint_ref"),
        "payload_ref": _ref(data["payload_ref"], "push.payload_ref"),
    }
    if delivery["task_id"] != task_id or delivery["context_id"] != context_id:
        raise A2AStreamError("push-task-context-mismatch")
    stream = streams.get(delivery["stream_id"])
    if stream is None:
        raise A2AStreamError("push-stream-unknown")
    if stream["mode"] != "task":
        raise A2AStreamError("push-requires-task-stream")
    event = next((item for item in stream["events"] if item["event_id"] == delivery["event_id"]), None)
    if event is None:
        raise A2AStreamError("push-event-unknown")
    if (
        delivery["response_member"] not in PUSH_MEMBERS
        or delivery["response_member"] != event["response_member"]
    ):
        raise A2AStreamError("push-payload-must-match-stream-response")
    return delivery


def verify_streams(value: Mapping[str, Any]) -> dict[str, Any]:
    data = _mapping(value, "envelope")
    _reject_forbidden_keys(data)
    _unknown(data, ENVELOPE_FIELDS, "envelope")
    required = ENVELOPE_FIELDS - {"task_id", "push"}
    missing = sorted(required - set(data))
    if missing:
        raise A2AStreamError("missing-envelope-fields:" + ",".join(missing))
    if data["$schema"] != SCHEMA_URI:
        raise A2AStreamError("schema-uri-mismatch")
    if data["schema_version"] != SCHEMA_VERSION:
        raise A2AStreamError("schema-version-mismatch")
    if data["contract_revision"] != CONTRACT_REVISION:
        raise A2AStreamError("contract-revision-mismatch")
    card_ref = _ref(data["card_ref"], "card_ref")
    protocol_version = _text(data["protocol_version"], "protocol_version", maximum=32)
    if protocol_version != PROTOCOL_VERSION:
        raise A2AStreamError("unsupported-protocol-version:" + protocol_version)
    context = _parse_context(data["context"])
    context_id = _opaque(data["context_id"], "context_id")
    task_id = _opaque(data["task_id"], "task_id") if "task_id" in data else None
    raw_streams = data["streams"]
    if not isinstance(raw_streams, list) or not raw_streams or len(raw_streams) > 8:
        raise A2AStreamError("invalid-streams: expected one to eight streams")
    streams = [_parse_stream(raw, index) for index, raw in enumerate(raw_streams, start=1)]
    stream_ids = [stream["stream_id"] for stream in streams]
    if len(stream_ids) != len(set(stream_ids)):
        raise A2AStreamError("duplicate-stream-id")
    modes = {stream["mode"] for stream in streams}
    if len(modes) != 1:
        raise A2AStreamError("mixed-stream-modes")
    mode = streams[0]["mode"]
    if mode == "message":
        if task_id is not None or len(streams) != 1:
            raise A2AStreamError("message-only-bundle-must-have-one-stream-and-no-task")
    else:
        if task_id is None:
            raise A2AStreamError("task-stream-requires-task-id")
        task_refs = {stream["events"][0]["task_ref"] for stream in streams}
        if len(task_refs) != 1:
            raise A2AStreamError("task-reference-drift-across-streams")
        event_sequences = [stream["response_refs"] for stream in streams]
        if any(sequence != event_sequences[0] for sequence in event_sequences[1:]):
            raise A2AStreamError("concurrent-stream-response-drift")
    stream_map = {stream["stream_id"]: stream for stream in streams}
    raw_push = data.get("push", [])
    if not isinstance(raw_push, list) or len(raw_push) > 64:
        raise A2AStreamError("invalid-push: expected bounded array")
    push = [
        _parse_push(item, task_id=task_id or "", context_id=context_id, streams=stream_map)
        for item in raw_push
    ]
    delivery_ids = [item["delivery_id"] for item in push]
    if len(delivery_ids) != len(set(delivery_ids)):
        raise A2AStreamError("duplicate-push-delivery-id")
    stream_refs = [stream["stream_ref"] for stream in streams]
    canonical_events = streams[0]["event_refs"]
    canonical_responses = streams[0]["response_refs"]
    report_material = {
        "contract_revision": CONTRACT_REVISION,
        "card_ref": card_ref,
        "protocol_version": protocol_version,
        "context": context,
        "context_id": context_id,
        "task_id": task_id,
        "stream_refs": stream_refs,
        "response_refs": canonical_responses,
        "push_refs": [digest_ref(item) for item in push],
    }
    task_stream_count = len(streams) if mode == "task" else 0
    message_stream_count = len(streams) if mode == "message" else 0
    concurrent_stream_count = task_stream_count if task_stream_count > 1 else 0
    return {
        "$schema": SCHEMA_URI,
        "status": "passed",
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "report_id": digest_ref(report_material),
        "card_ref": card_ref,
        "protocol_version": protocol_version,
        "context": context,
        "context_id": context_id,
        "task_id": task_id,
        "mode": mode,
        "stream_count": len(streams),
        "task_stream_count": task_stream_count,
        "message_stream_count": message_stream_count,
        "concurrent_stream_count": concurrent_stream_count,
        "event_count": len(canonical_events),
        "event_refs": canonical_events,
        "response_refs": canonical_responses,
        "stream_refs": stream_refs,
        "push_refs": [digest_ref(item) for item in push],
        "terminal_states": list(
            dict.fromkeys(
                stream["closing_state"]
                for stream in streams
                if stream["closing_state"] in TERMINAL_STATES
            )
        ),
        "interrupted_states": list(
            dict.fromkeys(
                stream["closing_state"]
                for stream in streams
                if stream["closing_state"] in INTERRUPTED_STATES
            )
        ),
        "authentication_boundary": "external-reference",
        "authority_grant": False,
        "checks": {
            "first_response": True,
            "message_only_closure": mode == "message",
            "task_lifecycle": mode == "task",
            "transport_closure": all(stream["closed"] for stream in streams),
            "stream_ordering": True,
            "concurrent_stream_equivalence": mode == "task" and len(streams) > 1,
            "push_stream_response": all(
                item["response_member"] in PUSH_MEMBERS for item in push
            ),
            "interrupted_closure": all(
                stream["closing_state"] not in INTERRUPTED_STATES
                or stream["closed"]
                for stream in streams
            ),
            "credential_exclusion": True,
            "authority_non_grant": True,
        },
    }


def load_envelope(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise A2AStreamError(f"cannot-load-envelope:{path}") from exc
    return _mapping(value, "envelope")


def evaluate_corpus(path: Path) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = _mapping(json.loads(line), f"corpus-case-{line_number}")
            _unknown(case, CORPUS_FIELDS, f"corpus-case-{line_number}")
            case_id = _text(case.get("case_id"), "corpus-case-id", maximum=96)
            expected = case.get("expected")
            if expected not in {"passed", "failed"}:
                raise A2AStreamError("invalid-corpus-expected")
            observed = "passed"
            result: dict[str, Any] | None = None
            error = None
            try:
                result = verify_streams(_mapping(case.get("envelope"), "corpus-envelope"))
            except A2AStreamError as exc:
                observed = "failed"
                error = str(exc)
            if observed != expected:
                raise A2AStreamError(
                    f"corpus-expectation-mismatch:{case_id}:expected={expected}:observed={observed}"
                )
            cases.append({"case_id": case_id, "expected": expected, "observed": observed, "error": error})
            if result is not None and result["status"] != "passed":
                raise A2AStreamError(f"corpus-result-not-passed:{case_id}")
        except (A2AStreamError, json.JSONDecodeError) as exc:
            return {"status": "failed", "case_count": len(cases), "error": str(exc)}
    threat_cases = sum(case["expected"] == "failed" for case in cases)
    return {
        "status": "passed",
        "contract_revision": CONTRACT_REVISION,
        "case_count": len(cases),
        "threat_cases": threat_cases,
        "deterministic": True,
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify digest-only A2A StreamResponse evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify", help="verify one stream bundle")
    verify.add_argument("--input", type=Path, required=True)
    verify.add_argument("--json", action="store_true")
    evaluate = subparsers.add_parser("evaluate", help="run the deterministic corpus")
    evaluate.add_argument("--corpus", type=Path, required=True)
    evaluate.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            output = verify_streams(load_envelope(args.input))
        else:
            output = evaluate_corpus(args.corpus)
        print(json.dumps(output, indent=2 if args.json else None, sort_keys=True))
        return 0 if output.get("status") == "passed" else 1
    except A2AStreamError as exc:
        print(f"a2a-stream: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
