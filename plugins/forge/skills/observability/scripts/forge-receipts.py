#!/usr/bin/env python3
"""Store privacy-safe Forge run receipts locally and export them as OTLP JSON."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows does not expose fcntl.
    fcntl = None


SCHEMA_VERSION = 1
CONVENTIONS_VERSION = "gen-ai-1.42.0"
OTEL_MAPPING_VERSION = "forge-otel-1"
MAX_ATTRIBUTE_LENGTH = 512
EVENT_TYPES = (
    "run.started",
    "run.finished",
    "task.started",
    "task.finished",
    "agent.started",
    "agent.finished",
    "model.called",
    "tool.called",
    "approval.requested",
    "approval.granted",
    "approval.denied",
    "artifact.recorded",
    "outcome.recorded",
)
SENSITIVE_KEYS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "prompt",
    "raw",
    "secret",
    "token",
    "tool_arg",
    "tool_argument",
)
CONTENT_KEYS = ("arguments", "content", "detail", "message", "output", "result")
TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


class ReceiptError(ValueError):
    """Raised when a receipt or receipt log violates the contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(encoded).hexdigest()


def redacted(value: Any) -> dict[str, Any]:
    return {"redacted": True, "sha256": digest(value)}


def sanitize(value: Any, key: str = "", allow_content: bool = False) -> Any:
    lowered = key.lower().replace("-", "_")
    if any(token in lowered for token in SENSITIVE_KEYS):
        return redacted(value)
    if lowered in CONTENT_KEYS and not allow_content:
        return redacted(value)
    if isinstance(value, Mapping):
        return {
            str(child_key): sanitize(child_value, str(child_key), allow_content)
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item, key, allow_content) for item in value]
    if isinstance(value, tuple):
        return [sanitize(item, key, allow_content) for item in value]
    if isinstance(value, str) and len(value) > MAX_ATTRIBUTE_LENGTH:
        return redacted(value)
    return value


def parse_traceparent(traceparent: str) -> dict[str, str]:
    match = TRACEPARENT_RE.fullmatch(traceparent.lower())
    if not match or match.group(1) == "0" * 32 or match.group(2) == "0" * 16:
        raise ReceiptError("traceparent must be a valid W3C traceparent")
    return {"trace_id": match.group(1), "parent_span_id": match.group(2), "trace_flags": match.group(3)}


def make_event(
    event_type: str,
    run_id: str,
    *,
    task_id: str | None = None,
    agent_id: str | None = None,
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    traceparent: str | None = None,
    definition_version: str | None = None,
    policy_revision: str | None = None,
    model_route: Mapping[str, Any] | None = None,
    attributes: Mapping[str, Any] | None = None,
    allow_content: bool = False,
) -> dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise ReceiptError(f"unsupported event type: {event_type}")
    if not run_id:
        raise ReceiptError("run_id is required")
    event_id = str(uuid.uuid4())
    trace = parse_traceparent(traceparent) if traceparent else {}
    if trace:
        trace["span_id"] = sha256(event_id.encode()).hexdigest()[:16]
    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "run_id": run_id,
        "sequence": 0,
        "occurred_at": utc_now(),
        "idempotency_key": idempotency_key or str(uuid.uuid4()),
        "trace": {
            **trace,
            **({"correlation_id": correlation_id} if correlation_id else {}),
            **({"causation_id": causation_id} if causation_id else {}),
        },
        "attributes": sanitize(copy.deepcopy(dict(attributes or {})), allow_content=allow_content),
    }
    optional = {
        "task_id": task_id,
        "agent_id": agent_id,
        "definition_version": definition_version,
        "policy_revision": policy_revision,
        "model_route": sanitize(copy.deepcopy(dict(model_route or {})), allow_content=allow_content)
        if model_route
        else None,
    }
    event.update({key: value for key, value in optional.items() if value is not None})
    return event


def validate_event(event: Mapping[str, Any]) -> None:
    required = (
        "schema_version",
        "event_id",
        "event_type",
        "run_id",
        "sequence",
        "occurred_at",
        "idempotency_key",
        "attributes",
    )
    missing = [key for key in required if key not in event]
    if missing:
        raise ReceiptError("missing required fields: " + ", ".join(missing))
    if event["schema_version"] != SCHEMA_VERSION:
        raise ReceiptError(f"unsupported schema_version: {event['schema_version']}")
    if event["event_type"] not in EVENT_TYPES:
        raise ReceiptError(f"unsupported event type: {event['event_type']}")
    if not isinstance(event["sequence"], int) or event["sequence"] < 1:
        raise ReceiptError("sequence must be a positive integer")
    for key in ("event_id", "run_id", "idempotency_key", "occurred_at"):
        if not isinstance(event[key], str) or not event[key]:
            raise ReceiptError(f"{key} must be a non-empty string")
    try:
        datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiptError("occurred_at must be RFC3339") from exc
    if not isinstance(event["attributes"], Mapping):
        raise ReceiptError("attributes must be an object")
    if "trace" in event and not isinstance(event["trace"], Mapping):
        raise ReceiptError("trace must be an object")


class ReceiptStore:
    """Append-only JSONL receipt storage with explicit final-record recovery."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _parse(self) -> tuple[list[dict[str, Any]], int, bool]:
        if not self.path.exists():
            return [], 0, False
        raw = self.path.read_bytes()
        events: list[dict[str, Any]] = []
        valid_bytes = 0
        truncated = False
        for index, line in enumerate(raw.splitlines(keepends=True), start=1):
            if not line.strip():
                valid_bytes += len(line)
                continue
            try:
                event = json.loads(line.decode("utf-8"))
                validate_event(event)
            except (UnicodeDecodeError, json.JSONDecodeError, ReceiptError) as exc:
                is_final_partial = index == len(raw.splitlines(keepends=True)) and not line.endswith(b"\n")
                if is_final_partial:
                    truncated = True
                    break
                raise ReceiptError(f"invalid receipt record {index}: {exc}") from exc
            events.append(event)
            valid_bytes += len(line)
        expected = 1
        for event in events:
            if event["sequence"] != expected:
                raise ReceiptError(
                    f"receipt sequence is not monotonic at {event['event_id']}: expected {expected}, got {event['sequence']}"
                )
            expected += 1
        return events, valid_bytes, truncated

    def read(self) -> tuple[list[dict[str, Any]], bool]:
        events, _, truncated = self._parse()
        return events, truncated

    def append(self, event: Mapping[str, Any]) -> dict[str, Any]:
        candidate = copy.deepcopy(dict(event))
        existing, _, truncated = self._parse()
        if truncated:
            raise ReceiptError("final receipt record is incomplete; run repair before appending")
        key = candidate.get("idempotency_key")
        if key:
            for stored in existing:
                if stored["idempotency_key"] == key:
                    return stored
        candidate["sequence"] = len(existing) + 1
        validate_event(candidate)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.write(json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return candidate

    def repair_truncated_final(self) -> bool:
        _, valid_bytes, truncated = self._parse()
        if not truncated:
            return False
        with self.path.open("r+b") as handle:
            handle.truncate(valid_bytes)
        return True


def parse_time(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp() * 1_000_000_000)


def otlp_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def event_attributes(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    attributes = [
        ("forge.event_type", event["event_type"]),
        ("forge.event_id", event["event_id"]),
        ("forge.run_id", event["run_id"]),
        ("forge.sequence", event["sequence"]),
        ("forge.schema_version", event["schema_version"]),
        ("forge.conventions_version", CONVENTIONS_VERSION),
        ("forge.otel_mapping_version", OTEL_MAPPING_VERSION),
    ]
    trace = event.get("trace", {})
    if isinstance(trace, Mapping) and trace.get("correlation_id"):
        attributes.append(("forge.correlation_id", trace["correlation_id"]))
    for key, value in event.get("attributes", {}).items():
        if isinstance(value, (str, int, float, bool)):
            prefix = key if key.startswith(("gen_ai.", "mcp.")) else f"forge.attr.{key}"
            attributes.append((prefix, value))
    for key, value in event.get("model_route", {}).items():
        if isinstance(value, (str, int, float, bool)):
            prefix = key if key.startswith(("gen_ai.", "mcp.")) else f"forge.route.{key}"
            attributes.append((prefix, value))
    return [{"key": key, "value": otlp_value(value)} for key, value in attributes]


def event_to_span(event: Mapping[str, Any]) -> dict[str, Any]:
    span_names = {
        "run.started": "invoke_workflow",
        "run.finished": "invoke_workflow",
        "task.started": "invoke_workflow.task",
        "task.finished": "invoke_workflow.task",
        "agent.started": "invoke_agent",
        "agent.finished": "invoke_agent",
        "model.called": "chat",
        "tool.called": "execute_tool",
        "approval.requested": "policy.decision",
        "approval.granted": "policy.decision",
        "approval.denied": "policy.decision",
        "artifact.recorded": "artifact.recorded",
        "outcome.recorded": "workflow.outcome",
    }
    trace = event.get("trace", {})
    trace_id = trace.get("trace_id") if isinstance(trace, Mapping) else None
    span_id = trace.get("span_id") if isinstance(trace, Mapping) else None
    trace_id = trace_id or sha256(event["run_id"].encode()).hexdigest()[:32]
    span_id = span_id or sha256(event["event_id"].encode()).hexdigest()[:16]
    span: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": span_names[event["event_type"]],
        "startTimeUnixNano": str(parse_time(event["occurred_at"])),
        "attributes": event_attributes(event),
    }
    if isinstance(trace, Mapping) and trace.get("parent_span_id"):
        span["parentSpanId"] = trace["parent_span_id"]
    return span


def otlp_payload(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    spans = [event_to_span(event) for event in events]
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "forge"}},
                        {"key": "forge.receipt_schema_version", "value": {"intValue": str(SCHEMA_VERSION)}},
                        {"key": "forge.otel_mapping_version", "value": {"stringValue": OTEL_MAPPING_VERSION}},
                        {"key": "forge.gen_ai_semconv_version", "value": {"stringValue": CONVENTIONS_VERSION}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "forge.receipts", "version": OTEL_MAPPING_VERSION},
                        "spans": spans,
                    }
                ],
            }
        ]
    }


def export_otlp(payload: Mapping[str, Any], endpoint: str, headers: Mapping[str, str]) -> int:
    body = json.dumps(payload, separators=(",", ":")).encode()
    request_headers = {"Content-Type": "application/json", **headers}
    req = request.Request(endpoint, data=body, headers=request_headers, method="POST")
    try:
        with request.urlopen(req, timeout=20) as response:
            return response.status
    except urlerror.URLError as exc:
        raise ReceiptError(f"OTLP export failed: {exc.reason}") from exc


def parse_attributes(values: list[str]) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for item in values:
        if "=" not in item:
            raise ReceiptError(f"attribute must use key=value: {item}")
        key, value = item.split("=", 1)
        try:
            attributes[key] = json.loads(value)
        except json.JSONDecodeError:
            attributes[key] = value
    return attributes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Store privacy-safe Forge run receipts.")
    parser.add_argument("--file", type=Path, default=Path(".forge/receipts.jsonl"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    append = subparsers.add_parser("append", help="append one receipt event")
    append.add_argument("--event-type", required=True, choices=EVENT_TYPES)
    append.add_argument("--run-id", required=True)
    append.add_argument("--task-id")
    append.add_argument("--agent-id")
    append.add_argument("--idempotency-key")
    append.add_argument("--correlation-id")
    append.add_argument("--causation-id")
    append.add_argument("--traceparent")
    append.add_argument("--definition-version")
    append.add_argument("--policy-revision")
    append.add_argument("--model-route", action="append", default=[])
    append.add_argument("--attribute", action="append", default=[])
    append.add_argument("--allow-content", action="store_true")

    read = subparsers.add_parser("read", help="read the receipt log")
    read.add_argument("--json", action="store_true")

    subparsers.add_parser("validate", help="validate the receipt log without changing it")
    subparsers.add_parser("repair", help="truncate an incomplete final record")

    export = subparsers.add_parser("export", help="export receipts as OTLP/HTTP JSON")
    export.add_argument("--endpoint", required=True)
    export.add_argument("--header", action="append", default=[])
    export.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = ReceiptStore(args.file)
    try:
        if args.command == "append":
            event = make_event(
                args.event_type,
                args.run_id,
                task_id=args.task_id,
                agent_id=args.agent_id,
                idempotency_key=args.idempotency_key,
                correlation_id=args.correlation_id,
                causation_id=args.causation_id,
                traceparent=args.traceparent,
                definition_version=args.definition_version,
                policy_revision=args.policy_revision,
                model_route=parse_attributes(args.model_route),
                attributes=parse_attributes(args.attribute),
                allow_content=args.allow_content,
            )
            print(json.dumps(store.append(event), indent=2, sort_keys=True))
        elif args.command == "read":
            events, truncated = store.read()
            if args.json:
                print(json.dumps({"events": events, "truncated_final_record": truncated}, indent=2, sort_keys=True))
            else:
                for event in events:
                    print(f"{event['sequence']}: {event['event_type']} run={event['run_id']} id={event['event_id']}")
                if truncated:
                    print("warning: the final record is incomplete; run repair explicitly to truncate it", file=sys.stderr)
        elif args.command == "validate":
            events, truncated = store.read()
            print(f"valid: {len(events)} event(s); truncated_final_record={str(truncated).lower()}")
        elif args.command == "repair":
            repaired = store.repair_truncated_final()
            print("repaired truncated final record" if repaired else "no repair needed")
        elif args.command == "export":
            events, truncated = store.read()
            payload = otlp_payload(events)
            if truncated:
                raise ReceiptError("refusing to export while the final record is incomplete")
            if args.dry_run:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                headers = parse_headers(args.header)
                print(f"exported {len(events)} event(s), HTTP {export_otlp(payload, args.endpoint, headers)}")
    except (OSError, ReceiptError) as exc:
        print(f"forge-receipts: {exc}", file=sys.stderr)
        return 1
    return 0


def parse_headers(values: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ReceiptError(f"header must use Name=Value: {item}")
        key, value = item.split("=", 1)
        headers[key] = value
    return headers


if __name__ == "__main__":
    raise SystemExit(main())
