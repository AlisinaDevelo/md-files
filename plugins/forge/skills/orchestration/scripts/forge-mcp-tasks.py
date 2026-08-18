#!/usr/bin/env python3
"""Expose Forge human waits through an MCP Tasks-shaped, reference-only view."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import importlib.util
import json
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).with_name("forge-runtime.py")
spec = importlib.util.spec_from_file_location("forge_runtime", SCRIPT)
if spec is None or spec.loader is None:  # pragma: no cover - packaging failure
    raise RuntimeError(f"cannot load runtime module: {SCRIPT}")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class McpTaskError(ValueError):
    """Raised when an MCP task view or operation cannot be served safely."""


MCP_PROTOCOL_VERSION = "2026-07-28"
MCP_TASKS_EXTENSION = "io.modelcontextprotocol/tasks"
MCP_TASK_METHODS = ("tasks/get", "tasks/update", "tasks/cancel")
TASK_HANDLE_PREFIX = "forge-task-v1."
TASK_HANDLE_FIELDS = {"version", "run_id", "task_id", "request_identity_digest", "nonce"}


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _optional_digest(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return runtime._digest_reference(value, field)


def _handle_bytes(payload: dict[str, Any]) -> bytes:
    return runtime.canonical_json(payload).encode("utf-8")


def _encode_task_handle(
    run_id: str,
    task_id: str,
    authorization_context_digest: str,
    request_identity_digest: str | None,
) -> tuple[str, str | None]:
    nonce = None if request_identity_digest is not None else secrets.token_urlsafe(18)
    payload = {
        "version": 1,
        "run_id": runtime._identifier(run_id, "run_id"),
        "task_id": runtime._identifier(task_id, "task_id"),
        "request_identity_digest": request_identity_digest,
        "nonce": nonce,
    }
    payload_bytes = _handle_bytes(payload)
    encoded = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")
    signature = hmac.new(
        authorization_context_digest.encode("ascii"), payload_bytes, hashlib.sha256
    ).hexdigest()
    return f"{TASK_HANDLE_PREFIX}{encoded}.{signature}", nonce


def _decode_task_handle(task_handle: str) -> tuple[dict[str, Any], bytes, str]:
    if not isinstance(task_handle, str) or len(task_handle) > 2048:
        raise McpTaskError("task handle is invalid")
    parts = task_handle.split(".")
    if len(parts) != 3 or parts[0] != TASK_HANDLE_PREFIX[:-1] or not re.fullmatch(r"[0-9a-f]{64}", parts[2]):
        raise McpTaskError("task handle is invalid")
    encoded = parts[1]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", encoded):
        raise McpTaskError("task handle is invalid")
    try:
        payload_bytes = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise McpTaskError("task handle is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != TASK_HANDLE_FIELDS or payload.get("version") != 1:
        raise McpTaskError("task handle is invalid")
    try:
        payload["run_id"] = runtime._identifier(payload["run_id"], "task handle.run_id")
        payload["task_id"] = runtime._identifier(payload["task_id"], "task handle.task_id")
        payload["request_identity_digest"] = _optional_digest(
            payload["request_identity_digest"], "task handle.request_identity_digest"
        )
    except (KeyError, runtime.RuntimeStoreError) as exc:
        raise McpTaskError("task handle is invalid") from exc
    nonce = payload.get("nonce")
    if payload["request_identity_digest"] is None:
        if not isinstance(nonce, str) or not nonce or len(nonce) > 128:
            raise McpTaskError("task handle is invalid")
    elif nonce is not None:
        raise McpTaskError("task handle is invalid")
    return payload, payload_bytes, parts[2]


def _task_status(run_status: str, wait_status: str, expiration_outcome: str) -> str:
    if run_status == "cancelled" or wait_status == "cancelled":
        return "cancelled"
    if run_status == "failed" or (wait_status == "expired" and expiration_outcome == "fail_run"):
        return "failed"
    if wait_status == "expired" and expiration_outcome == "cancel_run":
        return "cancelled"
    if wait_status == "submitted":
        return "completed"
    if wait_status == "input_required":
        return "input_required"
    return "working"


class McpTasksAdapter:
    """Project canonical Forge wait state into a versioned MCP Tasks contract."""

    def __init__(
        self,
        store: Any,
        *,
        protocol_version: str = MCP_PROTOCOL_VERSION,
        extensions: Any = (MCP_TASKS_EXTENSION,),
    ) -> None:
        self.store = store
        self._profile = self.negotiate(protocol_version, extensions)

    @staticmethod
    def profile() -> dict[str, Any]:
        return {
            "profile": "mcp-2026-07-28",
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "extension": MCP_TASKS_EXTENSION,
            "extensions": [MCP_TASKS_EXTENSION],
            "methods": list(MCP_TASK_METHODS),
            "resultType": "task",
            "stateless": True,
            "sessionBound": False,
            "rawPayloads": False,
            "inputResponses": "digest-reference-only",
            "sourceOfTruth": "forge-runtime-history",
        }

    @classmethod
    def negotiate(cls, protocol_version: Any, extensions: Any) -> dict[str, Any]:
        if not isinstance(protocol_version, str) or not protocol_version:
            raise McpTaskError("MCP protocol revision is required")
        if protocol_version != MCP_PROTOCOL_VERSION:
            raise McpTaskError(
                f"unsupported MCP protocol revision: {protocol_version}; expected {MCP_PROTOCOL_VERSION}"
            )
        if isinstance(extensions, (dict, list, tuple, set, frozenset)):
            extension_names = list(extensions)
        else:
            raise McpTaskError("MCP extension capabilities must be a mapping or sequence")
        if not all(isinstance(name, str) and name for name in extension_names):
            raise McpTaskError("MCP extension capabilities must contain non-empty names")
        if len(extension_names) != len(set(extension_names)):
            raise McpTaskError("MCP extension capabilities are ambiguous")
        if MCP_TASKS_EXTENSION not in extension_names:
            raise McpTaskError(f"MCP Tasks extension is not negotiated: {MCP_TASKS_EXTENSION}")
        return cls.profile()

    @staticmethod
    def task_id(run_id: str, wait_id: str) -> str:
        return f"{runtime._identifier(run_id, 'run_id')}:{runtime._identifier(wait_id, 'wait_id')}"

    def _wait(self, run_id: str, wait_id: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        run_id = runtime._identifier(run_id, "run_id")
        wait_id = runtime._identifier(wait_id, "wait_id")
        state = self.store.state(run_id)
        wait = state["waits"].get(wait_id)
        if wait is None:
            raise McpTaskError(f"unknown Forge wait: {wait_id}")
        history = self.store.history(run_id)
        return state, wait, history

    @staticmethod
    def _wait_candidates(state: dict[str, Any], task_id: str) -> list[dict[str, Any]]:
        return sorted(
            (wait for wait in state["waits"].values() if wait["task_id"] == task_id),
            key=lambda wait: wait["created_sequence"],
            reverse=True,
        )

    @staticmethod
    def _operation_key(
        operation: str,
        run_id: str,
        wait_id: str,
        request_identity_digest: str | None,
        handle_nonce: str | None,
    ) -> str:
        return "mcp-" + runtime._digest(
            {
                "protocol_version": MCP_PROTOCOL_VERSION,
                "operation": operation,
                "run_id": run_id,
                "wait_id": wait_id,
                "request_identity_digest": request_identity_digest,
                "handle_nonce": handle_nonce,
            }
        )

    @staticmethod
    def _request_binding_digest(request_identity_digest: str | None, handle_nonce: str | None) -> str:
        return "sha256:" + runtime._digest(
            {
                "request_identity_digest": request_identity_digest,
                "handle_nonce": handle_nonce,
            }
        )

    @staticmethod
    def _input_request_id(wait: dict[str, Any]) -> str:
        return "sha256:" + runtime._digest(
            {
                "wait_id": wait["wait_id"],
                "checkpoint_id": wait["checkpoint_id"],
                "input_schema_digest": wait["input_schema_digest"],
            }
        )

    @staticmethod
    def _authorize_wait(wait: dict[str, Any], authorization_context_digest: str) -> str:
        actual = runtime._digest_reference(authorization_context_digest, "authorization_context_digest")
        if wait["authorization_context_digest"] != actual:
            raise McpTaskError("task authorization context mismatch")
        return actual

    @staticmethod
    def _handle_for_wait(
        run_id: str, wait: dict[str, Any], request_identity_digest: str | None
    ) -> tuple[str, str | None]:
        return _encode_task_handle(
            run_id,
            wait["task_id"],
            wait["authorization_context_digest"],
            request_identity_digest,
        )

    def _resolve_handle(
        self,
        task_handle: str,
        authorization_context_digest: str,
        request_identity_digest: str | None,
    ) -> tuple[str, dict[str, Any], dict[str, Any], str | None]:
        payload, payload_bytes, signature = _decode_task_handle(task_handle)
        actual_identity = _optional_digest(request_identity_digest, "request_identity_digest")
        if actual_identity != payload["request_identity_digest"]:
            raise McpTaskError("task handle request identity mismatch")
        actual_auth = runtime._digest_reference(authorization_context_digest, "authorization_context_digest")
        try:
            state = self.store.state(payload["run_id"])
        except (runtime.RuntimeStoreError, OSError, ValueError) as exc:
            raise McpTaskError("task handle is invalid") from exc
        candidates = self._wait_candidates(state, payload["task_id"])
        expected = hmac.new(actual_auth.encode("ascii"), payload_bytes, hashlib.sha256).hexdigest()
        if not candidates or not hmac.compare_digest(signature, expected):
            raise McpTaskError("task handle authorization mismatch")
        current = candidates[0]
        if current["authorization_context_digest"] != actual_auth:
            raise McpTaskError("task handle authorization context changed")
        return payload["run_id"], state, current, payload["nonce"]

    def _view(
        self,
        run_id: str,
        state: dict[str, Any],
        wait: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        task_handle: str,
        request_identity_digest: str | None,
        handle_nonce: str | None,
        now: str | None,
        operation: str = "tasks/get",
    ) -> dict[str, Any]:
        now_value = _timestamp(now or runtime.utc_now())
        expires_at = _timestamp(wait["expires_at"])
        ttl_ms = max(0, int((expires_at - now_value).total_seconds() * 1000))
        status = _task_status(state["status"], wait["status"], wait["expiration_outcome"])
        forge_meta = {
            "protocol_version": MCP_PROTOCOL_VERSION,
            "extension": MCP_TASKS_EXTENSION,
            "operation": operation,
            "source_of_truth": "forge-runtime-history",
            "request_binding_digest": self._request_binding_digest(request_identity_digest, handle_nonce),
            "run_id": run_id,
            "wait_id": wait["wait_id"],
            "checkpoint_id": wait["checkpoint_id"],
            "checkpoint_sequence": wait["checkpoint_sequence"],
            "policy_revision": wait["policy_revision"],
            "input_schema_digest": wait["input_schema_digest"],
            "resume_contract": wait["resume_contract"],
        }
        view: dict[str, Any] = {
            "taskId": task_handle,
            "status": status,
            "createdAt": wait["created_at"],
            "lastUpdatedAt": history[-1]["occurred_at"],
            "ttlMs": ttl_ms,
            "pollIntervalMs": wait["poll_interval_ms"],
            "_meta": {"forge": forge_meta},
        }
        if status == "input_required":
            input_request_id = self._input_request_id(wait)
            view["inputRequests"] = {
                input_request_id: {
                    "method": "forge/input",
                    "params": {"inputSchemaDigest": wait["input_schema_digest"]},
                    "_meta": {
                        "forge": {
                            "referenceOnly": True,
                            "inputRequestId": input_request_id,
                            "waitId": wait["wait_id"],
                        }
                    },
                }
            }
        elif status == "completed":
            view["result"] = {
                "_meta": {
                    "forge": {
                        "submission_id": wait["submission_id"],
                        "input_digest": wait["input_digest"],
                    }
                }
            }
        return view

    def get_task(
        self,
        run_id: str,
        wait_id: str,
        authorization_context_digest: str,
        *,
        now: str | None = None,
        request_identity_digest: str | None = None,
    ) -> dict[str, Any]:
        state, wait, history = self._wait(run_id, wait_id)
        self._authorize_wait(wait, authorization_context_digest)
        request_identity_digest = _optional_digest(request_identity_digest, "request_identity_digest")
        task_handle, handle_nonce = self._handle_for_wait(run_id, wait, request_identity_digest)
        return self._view(
            run_id,
            state,
            wait,
            history,
            task_handle=task_handle,
            request_identity_digest=request_identity_digest,
            handle_nonce=handle_nonce,
            now=now,
        )

    def get_task_by_id(
        self,
        task_handle: str,
        authorization_context_digest: str,
        *,
        now: str | None = None,
        request_identity_digest: str | None = None,
    ) -> dict[str, Any]:
        run_id, state, wait, handle_nonce = self._resolve_handle(
            task_handle, authorization_context_digest, request_identity_digest
        )
        return self._view(
            run_id,
            state,
            wait,
            self.store.history(run_id),
            task_handle=task_handle,
            request_identity_digest=_optional_digest(request_identity_digest, "request_identity_digest"),
            handle_nonce=handle_nonce,
            now=now,
        )

    def get_result(
        self,
        run_id: str,
        wait_id: str,
        authorization_context_digest: str,
        *,
        request_identity_digest: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        state, wait, _history = self._wait(run_id, wait_id)
        self._authorize_wait(wait, authorization_context_digest)
        status = _task_status(state["status"], wait["status"], wait["expiration_outcome"])
        if status != "completed":
            raise McpTaskError(f"MCP task result is unavailable while task is {status}")
        return self.get_task(
            run_id,
            wait_id,
            authorization_context_digest,
            request_identity_digest=request_identity_digest,
            now=now,
        )

    def update(
        self,
        run_id: str,
        wait_id: str,
        input_digest: str,
        authorization_context_digest: str,
        *,
        input_schema_digest: str,
        input_request_id: str,
        submission_id: str | None = None,
        request_identity_digest: str | None = None,
        handle_nonce: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        _state, wait, history = self._wait(run_id, wait_id)
        authorization_context_digest = self._authorize_wait(wait, authorization_context_digest)
        request_identity_digest = _optional_digest(request_identity_digest, "request_identity_digest")
        input_digest = runtime._digest_reference(input_digest, "input_digest")
        input_schema_digest = runtime._digest_reference(input_schema_digest, "input_schema_digest")
        input_request_id = runtime._digest_reference(input_request_id, "input_request_id")
        if input_request_id != self._input_request_id(wait):
            raise McpTaskError("input request is stale or does not match the current wait")
        operation_key = self._operation_key(
            "tasks/update", run_id, wait_id, request_identity_digest, handle_nonce
        )
        submission_id = runtime._identifier(
            submission_id or "mcp-" + runtime._digest({"operation_key": operation_key}),
            "submission_id",
        )
        expected_payload = {
            "wait_id": wait_id,
            "submission_id": submission_id,
            "input_digest": input_digest,
            "input_schema_digest": input_schema_digest,
            "authorization_context_digest": authorization_context_digest,
        }
        try:
            event = self.store.submit_input(
                run_id,
                wait_id,
                submission_id,
                input_digest,
                authorization_context_digest,
                input_schema_digest=input_schema_digest,
                idempotency_key=operation_key,
                occurred_at=occurred_at,
            )
            if event["payload"] != expected_payload:
                raise McpTaskError("input retry does not match the original request")
        except runtime.RuntimeStoreError:
            existing = next(
                (
                    event
                    for event in history
                    if event["idempotency_key"] == operation_key
                    and event["event_type"] == "wait.input_submitted"
                ),
                None,
            )
            if existing is None or existing["payload"] != expected_payload:
                raise
        return {}

    def update_by_id(
        self,
        task_handle: str,
        authorization_context_digest: str,
        input_digest: str,
        *,
        input_schema_digest: str,
        input_request_id: str,
        submission_id: str | None = None,
        request_identity_digest: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        run_id, _state, wait, handle_nonce = self._resolve_handle(
            task_handle, authorization_context_digest, request_identity_digest
        )
        return self.update(
            run_id,
            wait["wait_id"],
            input_digest,
            authorization_context_digest,
            input_schema_digest=input_schema_digest,
            input_request_id=input_request_id,
            submission_id=submission_id,
            request_identity_digest=request_identity_digest,
            handle_nonce=handle_nonce,
            occurred_at=occurred_at,
        )

    def cancel(
        self,
        run_id: str,
        wait_id: str,
        authorization_context_digest: str,
        *,
        occurred_at: str | None = None,
        request_identity_digest: str | None = None,
        handle_nonce: str | None = None,
        task_handle: str | None = None,
    ) -> dict[str, Any]:
        state, wait, history = self._wait(run_id, wait_id)
        authorization_context_digest = self._authorize_wait(wait, authorization_context_digest)
        request_identity_digest = _optional_digest(request_identity_digest, "request_identity_digest")
        status = _task_status(state["status"], wait["status"], wait["expiration_outcome"])
        if status in {"completed", "failed", "cancelled"}:
            return {}
        prefix = self._operation_key(
            "tasks/cancel", run_id, wait_id, request_identity_digest, handle_nonce
        )
        if not any(event["idempotency_key"] == f"{prefix}:cancelled" for event in history):
            self.store.cancel_confirmed(
                run_id,
                wait_id,
                authorization_context_digest,
                idempotency_prefix=prefix,
                occurred_at=occurred_at,
            )
            state, wait, history = self._wait(run_id, wait_id)
        return {}

    def cancel_by_id(
        self,
        task_handle: str,
        authorization_context_digest: str,
        *,
        request_identity_digest: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        run_id, _state, wait, handle_nonce = self._resolve_handle(
            task_handle, authorization_context_digest, request_identity_digest
        )
        return self.cancel(
            run_id,
            wait["wait_id"],
            authorization_context_digest,
            occurred_at=occurred_at,
            request_identity_digest=request_identity_digest,
            handle_nonce=handle_nonce,
            task_handle=task_handle,
        )

    def notifications(self, run_id: str, wait_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
        _state, _wait, history = self._wait(run_id, wait_id)
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 0:
            raise McpTaskError("after_sequence must be a non-negative integer")
        task_id = self.task_id(run_id, wait_id)
        events = {
            "wait.created",
            "wait.input_submitted",
            "wait.expired",
            "run.cancel_requested",
            "cancel.acknowledged",
            "run.cancelled",
            "run.failed",
        }
        updates = []
        run = self.store._run(run_id)
        for event in history:
            if event["sequence"] <= after_sequence or event["event_type"] not in events:
                continue
            projected = runtime.replay(run, history[: event["sequence"]])
            projected_wait = projected["waits"].get(wait_id)
            if projected_wait is None:
                continue
            updates.append(
                {
                    "taskId": task_id,
                    "status": _task_status(
                        projected["status"], projected_wait["status"], projected_wait["expiration_outcome"]
                    ),
                    "lastUpdatedAt": event["occurred_at"],
                    "sequence": event["sequence"],
                }
            )
        return updates


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Forge MCP Tasks adapter")
    parser.add_argument("--db", type=Path, default=Path(".forge/runtime.sqlite3"))
    sub = parser.add_subparsers(dest="command", required=True)
    profile = sub.add_parser("profile")
    profile.add_argument("--protocol-version", required=True)
    profile.add_argument("--extension", action="append", required=True)
    for name in ("get", "result", "notifications"):
        command = sub.add_parser(name)
        command.add_argument("--run-id", required=True)
        command.add_argument("--wait-id", required=True)
    sub.choices["get"].add_argument("--now")
    sub.choices["get"].add_argument("--authorization-context-digest", required=True)
    sub.choices["get"].add_argument("--request-identity-digest")
    sub.choices["result"].add_argument("--now")
    sub.choices["result"].add_argument("--authorization-context-digest", required=True)
    sub.choices["result"].add_argument("--request-identity-digest")
    sub.choices["notifications"].add_argument("--after-sequence", type=int, default=0)
    get_by_id = sub.add_parser("get-by-id")
    get_by_id.add_argument("--task-id", required=True)
    get_by_id.add_argument("--authorization-context-digest", required=True)
    get_by_id.add_argument("--request-identity-digest")
    get_by_id.add_argument("--now")
    update = sub.add_parser("update")
    update.add_argument("--run-id", required=True)
    update.add_argument("--wait-id", required=True)
    update.add_argument("--input-digest", required=True)
    update.add_argument("--input-schema-digest", required=True)
    update.add_argument("--input-request-id", required=True)
    update.add_argument("--authorization-context-digest", required=True)
    update.add_argument("--request-identity-digest")
    update.add_argument("--submission-id")
    update.add_argument("--occurred-at")
    update_by_id = sub.add_parser("update-by-id")
    update_by_id.add_argument("--task-id", required=True)
    update_by_id.add_argument("--input-digest", required=True)
    update_by_id.add_argument("--input-schema-digest", required=True)
    update_by_id.add_argument("--input-request-id", required=True)
    update_by_id.add_argument("--authorization-context-digest", required=True)
    update_by_id.add_argument("--request-identity-digest")
    update_by_id.add_argument("--submission-id")
    update_by_id.add_argument("--occurred-at")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("--run-id", required=True)
    cancel.add_argument("--wait-id", required=True)
    cancel.add_argument("--authorization-context-digest", required=True)
    cancel.add_argument("--request-identity-digest")
    cancel.add_argument("--occurred-at")
    cancel_by_id = sub.add_parser("cancel-by-id")
    cancel_by_id.add_argument("--task-id", required=True)
    cancel_by_id.add_argument("--authorization-context-digest", required=True)
    cancel_by_id.add_argument("--request-identity-digest")
    cancel_by_id.add_argument("--occurred-at")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "profile":
        print(runtime.canonical_json(McpTasksAdapter.negotiate(args.protocol_version, args.extension)))
        return 0
    store = None
    try:
        store = runtime.RuntimeStore(args.db)
        adapter = McpTasksAdapter(store)
        if args.command == "get":
            result = adapter.get_task(
                args.run_id,
                args.wait_id,
                args.authorization_context_digest,
                now=args.now,
                request_identity_digest=args.request_identity_digest,
            )
        elif args.command == "result":
            result = adapter.get_result(
                args.run_id,
                args.wait_id,
                args.authorization_context_digest,
                now=args.now,
                request_identity_digest=args.request_identity_digest,
            )
        elif args.command == "notifications":
            result = adapter.notifications(args.run_id, args.wait_id, after_sequence=args.after_sequence)
        elif args.command == "get-by-id":
            result = adapter.get_task_by_id(
                args.task_id,
                args.authorization_context_digest,
                now=args.now,
                request_identity_digest=args.request_identity_digest,
            )
        elif args.command == "update":
            result = adapter.update(
                args.run_id,
                args.wait_id,
                args.input_digest,
                args.authorization_context_digest,
                input_schema_digest=args.input_schema_digest,
                input_request_id=args.input_request_id,
                submission_id=args.submission_id,
                request_identity_digest=args.request_identity_digest,
                occurred_at=args.occurred_at,
            )
        elif args.command == "update-by-id":
            result = adapter.update_by_id(
                args.task_id,
                args.authorization_context_digest,
                args.input_digest,
                input_schema_digest=args.input_schema_digest,
                input_request_id=args.input_request_id,
                submission_id=args.submission_id,
                request_identity_digest=args.request_identity_digest,
                occurred_at=args.occurred_at,
            )
        elif args.command == "cancel-by-id":
            result = adapter.cancel_by_id(
                args.task_id,
                args.authorization_context_digest,
                request_identity_digest=args.request_identity_digest,
                occurred_at=args.occurred_at,
            )
        elif args.command == "cancel":
            result = adapter.cancel(
                args.run_id,
                args.wait_id,
                args.authorization_context_digest,
                request_identity_digest=args.request_identity_digest,
                occurred_at=args.occurred_at,
            )
        else:
            raise McpTaskError(f"unsupported adapter command: {args.command}")
        print(runtime.canonical_json(result))
        return 0
    except (McpTaskError, runtime.RuntimeStoreError, OSError, ValueError) as exc:
        print(f"forge-mcp-tasks: {exc}", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
