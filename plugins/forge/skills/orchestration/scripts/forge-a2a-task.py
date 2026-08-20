#!/usr/bin/env python3
"""Verify bounded A2A task handoff evidence and emit a digest-only report."""

from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
CONTRACT_REVISION = "forge-a2a-task-v1"
SCHEMA_URI = "https://github.com/AlisinaDevelo/md-files/schema/runtime/a2a-task/v1"
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
INTERRUPTED_STATES = {
    "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_AUTH_REQUIRED",
}
OPERATIONS = {"send", "status", "artifact", "cancel", "subscribe", "push"}
ENVELOPE_FIELDS = {
    "$schema",
    "schema_version",
    "contract_revision",
    "card_ref",
    "protocol_version",
    "context",
    "task",
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
TASK_FIELDS = {"task_id", "context_id", "events"}
EVENT_FIELDS = {
    "event_id",
    "operation",
    "state",
    "sequence",
    "occurred_at",
    "message_id",
    "message_ref",
    "artifact_refs",
    "idempotency_key",
    "stream_id",
    "stream_position",
    "stream_first",
    "stream_terminal",
}
PUSH_FIELDS = {"url", "task_id", "context_id", "authentication_ref"}
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


class A2ATaskError(ValueError):
    """Raised when A2A task handoff evidence cannot be admitted."""


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
        raise A2ATaskError(f"canonical-json: {exc}") from exc


def digest_ref(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise A2ATaskError(f"invalid-{label}: expected object with string keys")
    return {str(key): copy.deepcopy(child) for key, child in value.items()}


def _unknown(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise A2ATaskError(f"unknown-{label}-field:" + ",".join(unknown))


def _text(value: Any, label: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise A2ATaskError(f"invalid-{label}: expected bounded string")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        raise A2ATaskError(f"invalid-{label}: control character")
    if FORBIDDEN_VALUE_RE.search(value):
        raise A2ATaskError(f"{label} contains credential-shaped material")
    return value


def _opaque(value: Any, label: str) -> str:
    result = _text(value, label, maximum=256)
    if not OPAQUE_RE.fullmatch(result):
        raise A2ATaskError(f"invalid-{label}: malformed reference")
    return result


def _ref(value: Any, label: str) -> str:
    result = _text(value, label, maximum=71)
    if not REF_RE.fullmatch(result):
        raise A2ATaskError(f"invalid-{label}: expected sha256 reference")
    return result


def _positive_int(value: Any, label: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > 1_000_000:
        raise A2ATaskError(f"invalid-{label}: expected bounded integer")
    return value


def _time(value: Any, label: str) -> datetime:
    text = _text(value, label, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise A2ATaskError(f"invalid-{label}: expected RFC3339") from exc
    if parsed.tzinfo is None:
        raise A2ATaskError(f"invalid-{label}: timezone required")
    return parsed.astimezone(timezone.utc)


def _ref_list(value: Any, label: str, *, maximum: int = 64) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise A2ATaskError(f"invalid-{label}: expected bounded array")
    refs = [_ref(item, f"{label}-item") for item in value]
    if len(refs) != len(set(refs)):
        raise A2ATaskError(f"invalid-{label}: duplicate references")
    return refs


def _reject_forbidden_keys(value: Any, path: str = "envelope") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower().replace("-", "_")
            if key_text in FORBIDDEN_KEYS:
                raise A2ATaskError(f"{path}.{key} cannot contain raw provider material")
            _reject_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{path}[{index}]")


def _push_url(value: Any, label: str) -> str:
    text = _text(value, label, maximum=2048)
    parsed = urlsplit(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise A2ATaskError(f"insecure-{label}: HTTPS is required")
    if parsed.username is not None or parsed.password is not None:
        raise A2ATaskError(f"invalid-{label}: credentials in URL")
    if parsed.fragment or parsed.query:
        raise A2ATaskError(f"invalid-{label}: query and fragment are not allowed")
    try:
        hostname = parsed.hostname
    except ValueError as exc:
        raise A2ATaskError(f"invalid-{label}: malformed host") from exc
    if not hostname:
        raise A2ATaskError(f"invalid-{label}: hostname is required")
    lowered = hostname.rstrip(".").lower()
    if lowered == "localhost" or lowered.endswith((".localhost", ".local")):
        raise A2ATaskError(f"unsafe-{label}: local hostname")
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
    ):
        raise A2ATaskError(f"unsafe-{label}: private or local address")
    return text


def _parse_context(value: Any) -> dict[str, str]:
    data = _mapping(value, "context")
    _unknown(data, CONTEXT_FIELDS, "context")
    missing = sorted(CONTEXT_FIELDS - set(data))
    if missing:
        raise A2ATaskError("missing-context-fields:" + ",".join(missing))
    context: dict[str, str] = {}
    for field in ("host_ref", "audience_ref", "workspace_ref", "resource_ref"):
        context[field] = _opaque(data[field], f"context.{field}")
    for field in sorted(CONTEXT_FIELDS - {"host_ref", "audience_ref", "workspace_ref", "resource_ref"}):
        context[field] = _ref(data[field], f"context.{field}")
    return context


def _parse_event(value: Any, index: int) -> dict[str, Any]:
    data = _mapping(value, f"event-{index}")
    _unknown(data, EVENT_FIELDS, f"event-{index}")
    required = {"event_id", "operation", "state", "sequence", "occurred_at", "idempotency_key"}
    missing = sorted(required - set(data))
    if missing:
        raise A2ATaskError(f"missing-event-fields:{','.join(missing)}")
    event = {
        "event_id": _opaque(data["event_id"], f"event-{index}.event_id"),
        "operation": _text(data["operation"], f"event-{index}.operation", maximum=32),
        "state": _text(data["state"], f"event-{index}.state", maximum=64),
        "sequence": _positive_int(data["sequence"], f"event-{index}.sequence"),
        "occurred_at": _time(data["occurred_at"], f"event-{index}.occurred_at").isoformat().replace(
            "+00:00", "Z"
        ),
        "idempotency_key": _opaque(data["idempotency_key"], f"event-{index}.idempotency_key"),
    }
    if event["operation"] not in OPERATIONS:
        raise A2ATaskError(f"unsupported-event-operation:{event['operation']}")
    if event["state"] not in STATES:
        raise A2ATaskError(f"unsupported-task-state:{event['state']}")
    if "message_id" in data:
        event["message_id"] = _opaque(data["message_id"], f"event-{index}.message_id")
    if "message_ref" in data:
        event["message_ref"] = _ref(data["message_ref"], f"event-{index}.message_ref")
    if "message_id" in event and "message_ref" not in event:
        raise A2ATaskError(f"message-ref-required:{event['event_id']}")
    if "message_ref" in event and "message_id" not in event:
        raise A2ATaskError(f"message-id-required:{event['event_id']}")
    if "artifact_refs" in data:
        event["artifact_refs"] = _ref_list(data["artifact_refs"], f"event-{index}.artifact_refs")
    else:
        event["artifact_refs"] = []
    if "stream_id" in data:
        event["stream_id"] = _opaque(data["stream_id"], f"event-{index}.stream_id")
    if "stream_position" in data:
        event["stream_position"] = _positive_int(
            data["stream_position"], f"event-{index}.stream_position", allow_zero=True
        )
    if "stream_first" in data:
        if not isinstance(data["stream_first"], bool):
            raise A2ATaskError(f"invalid-event-{index}.stream_first")
        event["stream_first"] = data["stream_first"]
    if "stream_terminal" in data:
        if not isinstance(data["stream_terminal"], bool):
            raise A2ATaskError(f"invalid-event-{index}.stream_terminal")
        event["stream_terminal"] = data["stream_terminal"]
    stream_fields = {"stream_id", "stream_position", "stream_first", "stream_terminal"}
    if any(field in event for field in stream_fields) and not stream_fields <= set(event):
        raise A2ATaskError(f"incomplete-stream-binding:{event['event_id']}")
    operation = event["operation"]
    if operation == "send" and "message_id" not in event:
        raise A2ATaskError(f"send-message-required:{event['event_id']}")
    if operation == "artifact" and not event["artifact_refs"]:
        raise A2ATaskError(f"artifact-reference-required:{event['event_id']}")
    if operation == "cancel" and event["state"] != "TASK_STATE_CANCELED":
        raise A2ATaskError(f"cancel-must-be-terminal:{event['event_id']}")
    if operation in {"cancel", "subscribe", "push"} and (
        "message_id" in event or event["artifact_refs"]
    ):
        raise A2ATaskError(f"unexpected-event-payload:{event['event_id']}")
    return event


def _parse_push(value: Any, task_id: str, context_id: str) -> dict[str, str]:
    data = _mapping(value, "push")
    _unknown(data, PUSH_FIELDS, "push")
    missing = sorted(PUSH_FIELDS - set(data))
    if missing:
        raise A2ATaskError("missing-push-fields:" + ",".join(missing))
    push = {
        "url": _push_url(data["url"], "push.url"),
        "task_id": _opaque(data["task_id"], "push.task_id"),
        "context_id": _opaque(data["context_id"], "push.context_id"),
        "authentication_ref": _ref(data["authentication_ref"], "push.authentication_ref"),
    }
    if push["task_id"] != task_id or push["context_id"] != context_id:
        raise A2ATaskError("push-task-context-mismatch")
    return push


def verify_task(value: Mapping[str, Any]) -> dict[str, Any]:
    data = _mapping(value, "envelope")
    _reject_forbidden_keys(data)
    _unknown(data, ENVELOPE_FIELDS, "envelope")
    required = ENVELOPE_FIELDS - {"push"}
    missing = sorted(required - set(data))
    if missing:
        raise A2ATaskError("missing-envelope-fields:" + ",".join(missing))
    if data["$schema"] != SCHEMA_URI:
        raise A2ATaskError("schema-uri-mismatch")
    if data["schema_version"] != SCHEMA_VERSION:
        raise A2ATaskError("schema-version-mismatch")
    if data["contract_revision"] != CONTRACT_REVISION:
        raise A2ATaskError("contract-revision-mismatch")
    card_ref = _ref(data["card_ref"], "card_ref")
    protocol_version = _text(data["protocol_version"], "protocol_version", maximum=32)
    if protocol_version != PROTOCOL_VERSION:
        raise A2ATaskError("unsupported-protocol-version:" + protocol_version)
    context = _parse_context(data["context"])
    task_data = _mapping(data["task"], "task")
    _unknown(task_data, TASK_FIELDS, "task")
    missing = sorted(TASK_FIELDS - set(task_data))
    if missing:
        raise A2ATaskError("missing-task-fields:" + ",".join(missing))
    task_id = _opaque(task_data["task_id"], "task.task_id")
    context_id = _opaque(task_data["context_id"], "task.context_id")
    raw_events = task_data["events"]
    if not isinstance(raw_events, list) or not raw_events or len(raw_events) > 512:
        raise A2ATaskError("invalid-task.events: expected bounded non-empty array")
    events = [_parse_event(raw, index + 1) for index, raw in enumerate(raw_events)]
    event_ids = [event["event_id"] for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise A2ATaskError("duplicate-event-id")
    previous_state: str | None = None
    previous_time: datetime | None = None
    message_refs: dict[str, str] = {}
    idempotency_effects: dict[str, dict[str, Any]] = {}
    state_path: list[str] = []
    for index, event in enumerate(events, start=1):
        if event["sequence"] != index:
            raise A2ATaskError("event-sequence-gap")
        occurred_at = _time(event["occurred_at"], f"event-{index}.occurred_at")
        if previous_time is not None and occurred_at < previous_time:
            raise A2ATaskError("event-time-regression")
        previous_time = occurred_at
        state = event["state"]
        if previous_state is None:
            if event["operation"] != "send" or state != "TASK_STATE_SUBMITTED":
                raise A2ATaskError("lifecycle-must-start-with-send")
        elif previous_state in TERMINAL_STATES:
            duplicate_cancel = (
                previous_state == "TASK_STATE_CANCELED"
                and event["operation"] == "cancel"
                and state == "TASK_STATE_CANCELED"
            )
            if not duplicate_cancel:
                raise A2ATaskError("event-after-terminal-state")
        else:
            allowed = {
                "TASK_STATE_SUBMITTED": {
                    "TASK_STATE_SUBMITTED",
                    "TASK_STATE_WORKING",
                    "TASK_STATE_INPUT_REQUIRED",
                    "TASK_STATE_AUTH_REQUIRED",
                    "TASK_STATE_COMPLETED",
                    "TASK_STATE_FAILED",
                    "TASK_STATE_CANCELED",
                    "TASK_STATE_REJECTED",
                },
                "TASK_STATE_WORKING": {
                    "TASK_STATE_WORKING",
                    "TASK_STATE_INPUT_REQUIRED",
                    "TASK_STATE_AUTH_REQUIRED",
                    "TASK_STATE_COMPLETED",
                    "TASK_STATE_FAILED",
                    "TASK_STATE_CANCELED",
                    "TASK_STATE_REJECTED",
                },
                "TASK_STATE_INPUT_REQUIRED": {
                    "TASK_STATE_INPUT_REQUIRED",
                    "TASK_STATE_WORKING",
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
            }[previous_state]
            if state not in allowed:
                raise A2ATaskError("invalid-state-transition")
        effect = {
            "operation": event["operation"],
            "state": state,
            "message_id": event.get("message_id"),
            "message_ref": event.get("message_ref"),
            "artifact_refs": event["artifact_refs"],
            "stream_id": event.get("stream_id"),
            "stream_position": event.get("stream_position"),
        }
        existing_effect = idempotency_effects.get(event["idempotency_key"])
        if existing_effect is not None and existing_effect != effect:
            raise A2ATaskError("idempotency-key-effect-drift")
        idempotency_effects[event["idempotency_key"]] = effect
        message_id = event.get("message_id")
        if message_id is not None:
            if event["operation"] != "send":
                raise A2ATaskError("message-id-outside-send")
            message_ref = event["message_ref"]
            previous_ref = message_refs.get(message_id)
            if previous_ref is not None and previous_ref != message_ref:
                raise A2ATaskError("message-id-content-drift")
            message_refs[message_id] = message_ref
        state_path.append(state)
        previous_state = state
    if previous_state not in TERMINAL_STATES:
        raise A2ATaskError("lifecycle-must-end-terminal")
    stream_present = any("stream_id" in event for event in events)
    stream_refs: list[str] = []
    if stream_present:
        if not all("stream_id" in event for event in events):
            raise A2ATaskError("stream-must-bind-every-event")
        positions = [event["stream_position"] for event in events]
        if positions != list(range(len(events))):
            raise A2ATaskError("stream-position-gap")
        if not events[0]["stream_first"] or any(event["stream_first"] for event in events[1:]):
            raise A2ATaskError("stream-first-marker-invalid")
        if any(event["stream_terminal"] for event in events[:-1]) or not events[-1]["stream_terminal"]:
            raise A2ATaskError("stream-terminal-marker-invalid")
        stream_ids = {event["stream_id"] for event in events}
        if len(stream_ids) != 1:
            raise A2ATaskError("multiple-streams-not-supported")
        stream_refs = [
            digest_ref(
                {
                    "stream_id": events[0]["stream_id"],
                    "event_count": len(events),
                    "terminal_state": previous_state,
                }
            )
        ]
    push = _parse_push(data["push"], task_id, context_id) if "push" in data else None
    normalized_task = {"task_id": task_id, "context_id": context_id, "events": events}
    event_refs = [digest_ref(event) for event in events]
    task_ref = digest_ref(normalized_task)
    push_ref = None if push is None else digest_ref(push)
    interrupted_states = [state for state in state_path if state in INTERRUPTED_STATES]
    report_material = {
        "contract_revision": CONTRACT_REVISION,
        "card_ref": card_ref,
        "protocol_version": protocol_version,
        "context": context,
        "task_ref": task_ref,
        "event_refs": event_refs,
        "push_ref": push_ref,
    }
    return {
        "$schema": SCHEMA_URI,
        "status": "passed",
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "report_id": digest_ref(report_material),
        "card_ref": card_ref,
        "protocol_version": protocol_version,
        "context": context,
        "task_ref": task_ref,
        "task_id": task_id,
        "context_id": context_id,
        "event_refs": event_refs,
        "event_count": len(events),
        "message_count": len(message_refs),
        "artifact_ref_count": sum(len(event["artifact_refs"]) for event in events),
        "state_path": state_path,
        "terminal_state": previous_state,
        "interrupted_states": list(dict.fromkeys(interrupted_states)),
        "stream_refs": stream_refs,
        "push_ref": push_ref,
        "idempotency_key_count": len(idempotency_effects),
        "authentication_boundary": "external-reference",
        "authority_grant": False,
        "checks": {
            "required_fields": True,
            "context_binding": True,
            "protocol_version": True,
            "bounded_transitions": True,
            "message_idempotency": True,
            "cancel_idempotency": True,
            "terminal_closure": True,
            "stream_ordering": True,
            "push_url_safety": True,
            "credential_exclusion": True,
            "authority_non_grant": True,
        },
    }


def load_envelope(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise A2ATaskError(f"cannot-load-envelope:{path}") from exc
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
                raise A2ATaskError("invalid-corpus-expected")
            observed = "passed"
            result: dict[str, Any] | None = None
            error = None
            try:
                result = verify_task(_mapping(case.get("envelope"), "corpus-envelope"))
            except (A2ATaskError, TypeError, AttributeError) as exc:
                observed = "failed"
                error = str(exc).split(":", 1)[0]
            status = "pass" if observed == expected else "fail"
            record: dict[str, Any] = {
                "case_id": case_id,
                "expected": expected,
                "observed": observed,
                "status": status,
            }
            if error is not None:
                record["error"] = error
            if result is not None:
                record["report_id"] = result["report_id"]
                record["task_ref"] = result["task_ref"]
            cases.append(record)
        except (A2ATaskError, json.JSONDecodeError, TypeError) as exc:
            cases.append(
                {
                    "case_id": f"line-{line_number}",
                    "expected": "failed",
                    "observed": "failed",
                    "status": "fail",
                    "error": str(exc).split(":", 1)[0],
                }
            )
    passed = sum(item["status"] == "pass" for item in cases)
    threat_cases = sum(item["expected"] == "failed" for item in cases)
    return {
        "status": "passed" if passed == len(cases) else "failed",
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "case_count": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "threat_cases": threat_cases,
        "deterministic": True,
        "cases": cases,
        "corpus_digest": digest_ref(cases),
    }


def _json_output(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify", help="verify one A2A task envelope")
    verify_parser.add_argument("--input", type=Path, required=True)
    evaluate_parser = subparsers.add_parser(
        "evaluate", help="evaluate the deterministic A2A task handoff corpus"
    )
    evaluate_parser.add_argument("--corpus", type=Path, required=True)
    evaluate_parser.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
        result = (
            verify_task(load_envelope(args.input))
            if args.command == "verify"
            else evaluate_corpus(args.corpus)
        )
        _json_output(result)
        return 0 if result.get("status") == "passed" else 1
    except (A2ATaskError, OSError, TypeError, ValueError) as exc:
        print(f"forge-a2a-task: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
