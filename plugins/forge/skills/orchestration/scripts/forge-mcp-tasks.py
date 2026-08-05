#!/usr/bin/env python3
"""Expose Forge human waits through an MCP Tasks-shaped, reference-only view."""

from __future__ import annotations

import argparse
import importlib.util
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


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _task_status(run_status: str, wait_status: str, expiration_outcome: str) -> str:
    if run_status == "cancelled" or wait_status == "cancelled":
        return "cancelled"
    if run_status == "failed" or (wait_status == "expired" and expiration_outcome == "fail_run"):
        return "failed"
    if wait_status == "submitted":
        return "completed"
    if wait_status == "input_required":
        return "input_required"
    return "working"


class McpTasksAdapter:
    """Project canonical Forge wait state into MCP Tasks-shaped responses."""

    def __init__(self, store: Any) -> None:
        self.store = store

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

    def get_task(self, run_id: str, wait_id: str, *, now: str | None = None) -> dict[str, Any]:
        state, wait, history = self._wait(run_id, wait_id)
        now_value = _timestamp(now or runtime.utc_now())
        expires_at = _timestamp(wait["expires_at"])
        ttl = max(0, int((expires_at - now_value).total_seconds() * 1000))
        status = _task_status(state["status"], wait["status"], wait["expiration_outcome"])
        return {
            "taskId": self.task_id(run_id, wait_id),
            "status": status,
            "createdAt": wait["created_at"],
            "lastUpdatedAt": history[-1]["occurred_at"],
            "ttl": ttl,
            "pollInterval": wait["poll_interval_ms"],
            "_meta": {
                "forge": {
                    "run_id": run_id,
                    "wait_id": wait_id,
                    "checkpoint_id": wait["checkpoint_id"],
                    "checkpoint_sequence": wait["checkpoint_sequence"],
                    "policy_revision": wait["policy_revision"],
                    "input_schema_digest": wait["input_schema_digest"],
                    "resume_contract": wait["resume_contract"],
                }
            },
        }

    def get_result(self, run_id: str, wait_id: str) -> dict[str, Any]:
        state, wait, _history = self._wait(run_id, wait_id)
        status = _task_status(state["status"], wait["status"], wait["expiration_outcome"])
        if status != "completed":
            raise McpTaskError(f"MCP task result is unavailable while task is {status}")
        return {
            "taskId": self.task_id(run_id, wait_id),
            "status": "completed",
            "result": {
                "_meta": {
                    "forge": {
                        "submission_id": wait["submission_id"],
                        "input_digest": wait["input_digest"],
                    }
                }
            },
        }

    def cancel(
        self,
        run_id: str,
        wait_id: str,
        authorization_context_digest: str,
        *,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        self.store.cancel_confirmed(
            run_id,
            wait_id,
            authorization_context_digest,
            occurred_at=occurred_at,
        )
        return self.get_task(run_id, wait_id, now=occurred_at)

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
    for name in ("get", "result", "notifications"):
        command = sub.add_parser(name)
        command.add_argument("--run-id", required=True)
        command.add_argument("--wait-id", required=True)
    sub.choices["get"].add_argument("--now")
    sub.choices["notifications"].add_argument("--after-sequence", type=int, default=0)
    cancel = sub.add_parser("cancel")
    cancel.add_argument("--run-id", required=True)
    cancel.add_argument("--wait-id", required=True)
    cancel.add_argument("--authorization-context-digest", required=True)
    cancel.add_argument("--occurred-at")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = None
    try:
        store = runtime.RuntimeStore(args.db)
        adapter = McpTasksAdapter(store)
        if args.command == "get":
            result = adapter.get_task(args.run_id, args.wait_id, now=args.now)
        elif args.command == "result":
            result = adapter.get_result(args.run_id, args.wait_id)
        elif args.command == "notifications":
            result = adapter.notifications(args.run_id, args.wait_id, after_sequence=args.after_sequence)
        else:
            result = adapter.cancel(
                args.run_id,
                args.wait_id,
                args.authorization_context_digest,
                occurred_at=args.occurred_at,
            )
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
