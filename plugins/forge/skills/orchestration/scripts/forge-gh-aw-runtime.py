#!/usr/bin/env python3
"""Bind GitHub Agentic Workflows effects to the durable Forge runtime.

This adapter stages GitHub dispatches and safe outputs in the existing SQLite/WAL runtime.
It never calls GitHub itself: a provider worker must claim an outbox lease, obtain the
recorded approval, perform one idempotent operation, and acknowledge it with references.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[5]
DEFAULT_SPEC = REPO / "data" / "gh-aw-workflows.json"
DEFAULT_OUTPUT = REPO / "build" / "gh-aw"
DEFAULT_DB = REPO / ".forge" / "runtime.sqlite3"
BRIDGE_REVISION = "forge-gh-aw-runtime-v1"
SCHEMA_VERSION = 1
REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PROVIDER_REFERENCE_KEYS = ("provider_request_id", "resource_ref", "result_ref")
RECEIPT_KEYS = {
    "status",
    "episode_id",
    "workflow_id",
    "safe_output_type",
    "approval_id",
    "adapter_contract_revision",
    "provider_request_id",
    "resource_ref",
    "result_ref",
}
SAFE_OUTPUT_EFFECT_TYPES = {
    "add-comment": "github.issue.comment",
    "create-issue": "github.issue.create",
    "create-pull-request": "github.pull-request.create",
    "dispatch-workflow": "github.workflow.dispatch",
}


class GhAwRuntimeError(ValueError):
    """Raised when a gh-aw runtime transition is unsafe or inconsistent."""


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GhAwRuntimeError(f"cannot load Forge module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _compiler() -> Any:
    return _load_module(
        "forge_gh_aw_runtime_compiler",
        Path(__file__).with_name("forge-gh-aw.py"),
    )


def _runtime() -> Any:
    return _load_module(
        "forge_gh_aw_runtime_store",
        Path(__file__).with_name("forge-runtime.py"),
    )


def _ref(value: Any, field: str) -> str:
    if not isinstance(value, str) or not REF_RE.fullmatch(value):
        raise GhAwRuntimeError(f"{field} must be a sha256 reference")
    return value


def _text(value: Any, field: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise GhAwRuntimeError(f"{field} must be non-empty text of at most {maximum} characters")
    return value


def _paths(spec_path: Path, output: Path) -> tuple[Path, Path]:
    spec_path = spec_path if spec_path.is_absolute() else REPO / spec_path
    output = output if output.is_absolute() else REPO / output
    return spec_path, output


def _contract(spec_path: Path, output: Path) -> dict[str, Any]:
    compiler = _compiler()
    spec_path, output = _paths(spec_path, output)
    raw_spec = compiler._load_json(spec_path, "gh-aw workflow spec")
    graph = compiler._load_graph(REPO)
    spec = compiler.validate_spec(REPO, raw_spec, graph)
    compiler.check_artifacts(REPO, spec_path, output)
    manifest = compiler._load_json(output / "manifest.json", "gh-aw manifest")
    if manifest.get("adapter_revision") != compiler.ADAPTER_REVISION:
        raise GhAwRuntimeError("manifest adapter revision does not match the compiler")
    if manifest.get("spec_digest") != compiler.digest(spec):
        raise GhAwRuntimeError("gh-aw manifest spec digest is stale")
    if manifest.get("mode") not in {"contract-preview", "upstream-gh-aw"}:
        raise GhAwRuntimeError("unsupported gh-aw manifest mode")
    return {"compiler": compiler, "spec": spec, "manifest": manifest, "output": output}


def _workflow(context: Mapping[str, Any], workflow_id: str) -> dict[str, Any]:
    workflow_id = _text(workflow_id, "workflow_id", maximum=128)
    for workflow in context["spec"]["workflows"]:
        if workflow["id"] == workflow_id:
            return workflow
    raise GhAwRuntimeError(f"unknown gh-aw workflow: {workflow_id}")


def _manifest_workflow(context: Mapping[str, Any], workflow_id: str) -> dict[str, Any]:
    for workflow in context["manifest"]["workflows"]:
        if workflow["id"] == workflow_id:
            return workflow
    raise GhAwRuntimeError(f"manifest is missing workflow: {workflow_id}")


def _policy_plan(context: Mapping[str, Any], workflow_id: str, output_type: str) -> dict[str, Any]:
    plans = context["compiler"]._policy_plans(REPO, context["spec"])
    for plan in plans[workflow_id]:
        if plan["type"] == output_type:
            if plan["policy"]["decision"] != "require_approval":
                raise GhAwRuntimeError(
                    f"gh-aw effect is not approval-gated: {workflow_id}/{output_type}"
                )
            return plan
    raise GhAwRuntimeError(f"workflow {workflow_id} has no safe output: {output_type}")


def _safe_output(context: Mapping[str, Any], workflow_id: str, output_type: str | None) -> dict[str, Any] | None:
    workflow = _workflow(context, workflow_id)
    outputs = workflow["safe_outputs"]
    if output_type is None:
        if not outputs:
            return None
        if len(outputs) != 1:
            raise GhAwRuntimeError(f"workflow {workflow_id} requires an explicit safe output type")
        output_type = outputs[0]["type"]
    for output in outputs:
        if output["type"] == output_type:
            _policy_plan(context, workflow_id, output_type)
            return output
    raise GhAwRuntimeError(f"workflow {workflow_id} has no safe output: {output_type}")


def _source_digest(context: Mapping[str, Any], workflow_id: str) -> str:
    for artifact in context["manifest"]["artifacts"]:
        if artifact["kind"] == "source" and artifact["path"] == f"workflows/{workflow_id}.md":
            return _ref(artifact["sha256"], f"source digest for {workflow_id}")
    raise GhAwRuntimeError(f"manifest is missing source digest: {workflow_id}")


def _policy_digest(context: Mapping[str, Any]) -> str:
    profile = context["spec"]["defaults"]["policy_profile"]
    return context["compiler"].file_digest(REPO / "policies" / f"{profile}.json")


def _runtime_definition(context: Mapping[str, Any], workflow_id: str) -> dict[str, Any]:
    compiler = context["compiler"]
    workflow = _workflow(context, workflow_id)
    policy_digest = _policy_digest(context)
    schema_digest = compiler.digest(
        {
            "adapter_revision": compiler.ADAPTER_REVISION,
            "upstream": context["spec"]["upstream"],
            "workflow_schema": context["spec"]["upstream"]["workflow_schema"],
        }
    )
    policy_revision = f"gh-aw:{policy_digest[7:23]}"
    return _runtime().DEFINITION_CONTRACT.make_definition(
        workflow_id=f"gh-aw:{workflow_id}",
        definition_version=f"{context['spec']['upstream']['version']}:{workflow_id}",
        worker_build_id=f"gh-aw:{compiler.ADAPTER_REVISION}:{context['manifest']['mode']}",
        policy_revision=policy_revision,
        workflow_code_digest=_source_digest(context, workflow_id),
        workflow_schema_digest=schema_digest,
        policy_digest=policy_digest,
        feature_flags_digest=compiler.digest(
            {"mode": context["manifest"]["mode"], "staged": workflow["staged"]}
        ),
        compatibility_revision=BRIDGE_REVISION,
        step_identity_revision="gh-aw-step-v1",
    )


def _episode_id(context: Mapping[str, Any], dispatcher_id: str, request_digest: str, supplied: str | None) -> str:
    runtime = _runtime()
    if supplied is not None:
        episode_id = runtime._identifier(supplied, "episode_id")
        if not episode_id.startswith("gh-aw:"):
            raise GhAwRuntimeError("episode_id must use the gh-aw: prefix")
        return episode_id
    material = {
        "adapter_revision": BRIDGE_REVISION,
        "dispatcher_workflow_id": dispatcher_id,
        "request_digest": request_digest,
        "spec_digest": context["manifest"]["spec_digest"],
        "upstream": context["manifest"]["upstream"],
    }
    return f"gh-aw:{dispatcher_id}:{context['compiler'].digest(material)[7:39]}"


def _episode_effect(
    context: Mapping[str, Any],
    episode_id: str,
    workflow_id: str,
    output_type: str,
    *,
    task_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    plan = _policy_plan(context, workflow_id, output_type)
    manifest_workflow = _manifest_workflow(context, workflow_id)
    return {
        "effect_type": SAFE_OUTPUT_EFFECT_TYPES[output_type],
        "task_id": task_id or workflow_id,
        "activity_id": "gh-aw-safe-output",
        "attempt": extra.pop("attempt", 1),
        "effect_definition_revision": f"{BRIDGE_REVISION}:{context['manifest']['upstream']['commit']}",
        "payload": {
            "repository": context["spec"]["defaults"]["repository"],
            "workflow_id": workflow_id,
            "episode_id": episode_id,
            "safe_output_type": output_type,
            "effect_set_digest": _ref(manifest_workflow["effect_set_digest"], "effect_set_digest"),
            "policy_action_digest": _ref(
                plan["action_digest"]
                if str(plan["action_digest"]).startswith("sha256:")
                else f"sha256:{plan['action_digest']}",
                "policy_action_digest",
            ),
            "policy_decision": plan["policy"]["decision"],
            "approval_required": True,
            "adapter_revision": BRIDGE_REVISION,
            **extra,
        },
    }


def _dispatch_effect(context: Mapping[str, Any], episode_id: str, dispatcher_id: str, worker_id: str, request_digest: str) -> dict[str, Any]:
    worker = _workflow(context, worker_id)
    effect = _episode_effect(
        context,
        episode_id,
        dispatcher_id,
        "dispatch-workflow",
        task_id=worker_id,
        dispatcher_workflow_id=dispatcher_id,
        worker_workflow_id=worker_id,
        source_workflow=worker["source_workflow"],
        request_digest=request_digest,
    )
    return effect


def _outbox_for_task(store: Any, task_id: str, effect_type: str | None = None) -> list[dict[str, Any]]:
    effects = [item for item in store.list_outbox() if item["task_id"] == task_id]
    if effect_type is not None:
        effects = [item for item in effects if item["effect_type"] == effect_type]
    return sorted(effects, key=lambda item: (item["created_at"], item["effect_id"]))


def _require_running(store: Any, episode_id: str) -> dict[str, Any]:
    state = store.state(episode_id)
    if state["status"] != "running":
        raise GhAwRuntimeError(f"episode is not running: {state['status']}")
    return state


def _history_event(store: Any, episode_id: str, idempotency_key: str) -> dict[str, Any] | None:
    for event in store.history(episode_id):
        if event["idempotency_key"] == idempotency_key:
            return event
    return None


def start_episode(
    spec_path: Path,
    output: Path,
    database: Path,
    dispatcher_id: str,
    request_digest: str,
    *,
    episode_id: str | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    context = _contract(spec_path, output)
    dispatcher = _workflow(context, dispatcher_id)
    if not dispatcher["dispatches"]:
        raise GhAwRuntimeError("episode dispatcher must declare workers")
    if not any(item["type"] == "dispatch-workflow" for item in dispatcher["safe_outputs"]):
        raise GhAwRuntimeError("episode dispatcher must declare dispatch-workflow")
    request_digest = _ref(request_digest, "request_digest")
    episode_id = _episode_id(context, dispatcher_id, request_digest, episode_id)
    definition = _runtime_definition(context, dispatcher_id)
    runtime = _runtime()
    with runtime.RuntimeStore(database) as store:
        store.start_run(
            episode_id,
            definition["workflow_id"],
            definition["definition_version"],
            definition["policy_revision"],
            definition_descriptor=definition,
            occurred_at=occurred_at,
        )
        return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)


def dispatch_episode(
    spec_path: Path,
    output: Path,
    database: Path,
    dispatcher_id: str,
    episode_id: str,
    request_digest: str,
    *,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    context = _contract(spec_path, output)
    dispatcher = _workflow(context, dispatcher_id)
    episode_id = _episode_id(context, dispatcher_id, _ref(request_digest, "request_digest"), episode_id)
    runtime = _runtime()
    with runtime.RuntimeStore(database) as store:
        state = _require_running(store, episode_id)
        if state["workflow_id"] != f"gh-aw:{dispatcher_id}":
            raise GhAwRuntimeError("episode dispatcher does not match the pinned runtime definition")
        for worker_id in dispatcher["dispatches"]:
            existing = state["tasks"].get(worker_id)
            effect = _dispatch_effect(context, episode_id, dispatcher_id, worker_id, request_digest)
            if existing is not None:
                effects = _outbox_for_task(store, worker_id, "github.workflow.dispatch")
                if not effects or effects[0]["payload"].get("request_digest") != request_digest:
                    raise GhAwRuntimeError(f"worker dispatch identity conflicts: {worker_id}")
                continue
            store.append_event(
                episode_id,
                "task.scheduled",
                {"task_id": worker_id, "title": _workflow(context, worker_id)["name"], "depends_on": []},
                idempotency_key=f"gh-aw:dispatch:{dispatcher_id}:{worker_id}",
                occurred_at=occurred_at,
                effect=effect,
            )
        return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)


def start_worker(
    spec_path: Path,
    output: Path,
    database: Path,
    dispatcher_id: str,
    episode_id: str,
    worker_id: str,
    *,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    context = _contract(spec_path, output)
    dispatcher = _workflow(context, dispatcher_id)
    if worker_id not in dispatcher["dispatches"]:
        raise GhAwRuntimeError(f"worker is not declared by dispatcher: {worker_id}")
    runtime = _runtime()
    with runtime.RuntimeStore(database) as store:
        state = _require_running(store, episode_id)
        task = state["tasks"].get(worker_id)
        if task is None:
            raise GhAwRuntimeError(f"worker has not been dispatched: {worker_id}")
        dispatch_effects = _outbox_for_task(store, worker_id, "github.workflow.dispatch")
        if not dispatch_effects or dispatch_effects[-1]["status"] != "succeeded":
            raise GhAwRuntimeError(f"worker dispatch has no succeeded receipt: {worker_id}")
        if task["status"] == "started":
            idempotency_key = f"gh-aw:worker-start:{worker_id}:{task['attempt']}"
            event = _history_event(store, episode_id, idempotency_key)
            if event is not None and event["payload"] == {"task_id": worker_id, "attempt": task["attempt"]}:
                return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)
            raise GhAwRuntimeError(f"worker is already started: {worker_id}")
        attempt = task["attempt"] + 1
        store.append_event(
            episode_id,
            "task.started",
            {"task_id": worker_id, "attempt": attempt},
            idempotency_key=f"gh-aw:worker-start:{worker_id}:{attempt}",
            occurred_at=occurred_at,
        )
        return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)


def complete_worker(
    spec_path: Path,
    output: Path,
    database: Path,
    dispatcher_id: str,
    episode_id: str,
    worker_id: str,
    output_ref: str,
    *,
    safe_output_type: str | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    context = _contract(spec_path, output)
    dispatcher = _workflow(context, dispatcher_id)
    if worker_id not in dispatcher["dispatches"]:
        raise GhAwRuntimeError(f"worker is not declared by dispatcher: {worker_id}")
    output_ref = _ref(output_ref, "output_ref")
    runtime = _runtime()
    with runtime.RuntimeStore(database) as store:
        state = _require_running(store, episode_id)
        task = state["tasks"].get(worker_id)
        if task is None:
            raise GhAwRuntimeError(f"worker is not started: {worker_id}")
        worker = _workflow(context, worker_id)
        safe_output = _safe_output(context, worker_id, safe_output_type)
        payload = {"task_id": worker_id, "output_ref": output_ref}
        idempotency_key = f"gh-aw:worker-complete:{worker_id}:{task['attempt']}"
        if task["status"] == "completed":
            event = _history_event(store, episode_id, idempotency_key)
            if event is None or event["payload"] != payload:
                raise GhAwRuntimeError(f"worker completion identity conflicts: {worker_id}")
            output_effects = [
                item
                for item in _outbox_for_task(store, worker_id)
                if item["effect_type"] != "github.workflow.dispatch"
            ]
            if (safe_output is None) != (not output_effects):
                raise GhAwRuntimeError(f"worker completion effect identity conflicts: {worker_id}")
            if safe_output is not None and any(
                item["payload"].get("safe_output_type") != safe_output["type"]
                for item in output_effects
            ):
                raise GhAwRuntimeError(f"worker completion effect identity conflicts: {worker_id}")
            return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)
        if task["status"] != "started":
            raise GhAwRuntimeError(f"worker is not started: {worker_id}")
        effect = None
        if safe_output is not None:
            effect = _episode_effect(
                context,
                episode_id,
                worker_id,
                safe_output["type"],
                attempt=task["attempt"],
                output_ref=output_ref,
                source_workflow=worker["source_workflow"],
            )
        store.append_event(
            episode_id,
            "task.completed",
            payload,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            effect=effect,
        )
        return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)


def fail_worker(
    spec_path: Path,
    output: Path,
    database: Path,
    dispatcher_id: str,
    episode_id: str,
    worker_id: str,
    error_ref: str,
    *,
    retryable: bool = False,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    context = _contract(spec_path, output)
    dispatcher = _workflow(context, dispatcher_id)
    if worker_id not in dispatcher["dispatches"]:
        raise GhAwRuntimeError(f"worker is not declared by dispatcher: {worker_id}")
    error_ref = _ref(error_ref, "error_ref")
    runtime = _runtime()
    with runtime.RuntimeStore(database) as store:
        state = _require_running(store, episode_id)
        task = state["tasks"].get(worker_id)
        if task is None:
            raise GhAwRuntimeError(f"worker is not started: {worker_id}")
        payload = {"task_id": worker_id, "error_ref": error_ref, "retryable": retryable}
        idempotency_key = f"gh-aw:worker-failed:{worker_id}:{task['attempt']}"
        if task["status"] == "failed":
            event = _history_event(store, episode_id, idempotency_key)
            if event is not None and event["payload"] == payload:
                return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)
            raise GhAwRuntimeError(f"worker failure identity conflicts: {worker_id}")
        if task["status"] != "started":
            raise GhAwRuntimeError(f"worker is not started: {worker_id}")
        store.append_event(
            episode_id,
            "task.failed",
            payload,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
        )
        return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)


def claim_episode(
    spec_path: Path,
    output: Path,
    database: Path,
    dispatcher_id: str,
    episode_id: str,
    worker_id: str,
    *,
    limit: int = 1,
    now: str | None = None,
) -> dict[str, Any]:
    context = _contract(spec_path, output)
    _workflow(context, dispatcher_id)
    runtime = _runtime()
    with runtime.RuntimeStore(database) as store:
        _require_running(store, episode_id)
        definition = store.definition(episode_id)
        claimed = store.claim_outbox(
            worker_id,
            limit=limit,
            run_id=episode_id,
            definition_descriptor=definition,
            now=now,
        )
        return {"episode": inspect_episode(spec_path, output, database, dispatcher_id, episode_id), "claimed": claimed}


def _normalize_receipt(receipt: Mapping[str, Any], episode_id: str, effect: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(str(key) for key in receipt if key not in RECEIPT_KEYS)
    if unknown:
        raise GhAwRuntimeError("receipt contains unsupported fields: " + ", ".join(unknown))
    normalized = dict(receipt)
    if normalized.get("status") != "succeeded":
        raise GhAwRuntimeError("gh-aw effect receipts must have status=succeeded")
    if normalized.get("episode_id") != episode_id:
        raise GhAwRuntimeError("receipt episode_id does not match the runtime episode")
    if normalized.get("adapter_contract_revision") != BRIDGE_REVISION:
        raise GhAwRuntimeError("receipt adapter contract revision does not match")
    _ref(normalized.get("approval_id"), "receipt.approval_id")
    for key in ("provider_request_id", "resource_ref"):
        if key in normalized:
            _text(normalized[key], f"receipt.{key}")
    if not any(normalized.get(key) for key in PROVIDER_REFERENCE_KEYS):
        raise GhAwRuntimeError("receipt must include a provider reference")
    if normalized.get("result_ref") is not None:
        _ref(normalized["result_ref"], "receipt.result_ref")
    if normalized.get("workflow_id") != effect["payload"].get("workflow_id"):
        raise GhAwRuntimeError("receipt workflow_id does not match the effect")
    if normalized.get("safe_output_type") != effect["payload"].get("safe_output_type"):
        raise GhAwRuntimeError("receipt safe_output_type does not match the effect")
    return normalized


def acknowledge_episode(
    spec_path: Path,
    output: Path,
    database: Path,
    dispatcher_id: str,
    episode_id: str,
    effect_id: str,
    worker_id: str,
    lease_generation: int,
    receipt: Mapping[str, Any],
    *,
    received_at: str | None = None,
) -> dict[str, Any]:
    context = _contract(spec_path, output)
    _workflow(context, dispatcher_id)
    runtime = _runtime()
    with runtime.RuntimeStore(database) as store:
        effects = [item for item in store.list_outbox(episode_id) if item["effect_id"] == effect_id]
        if not effects:
            raise GhAwRuntimeError(f"unknown episode effect: {effect_id}")
        effect = effects[0]
        if effect["status"] != "succeeded" and store.state(episode_id)["status"] != "running":
            raise GhAwRuntimeError("cannot acknowledge a new effect after episode termination")
        normalized = _normalize_receipt(receipt, episode_id, effect)
        store.acknowledge_outbox(
            effect_id,
            worker_id,
            normalized,
            lease_generation=lease_generation,
            received_at=received_at,
        )
        return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)


def finish_episode(
    spec_path: Path,
    output: Path,
    database: Path,
    dispatcher_id: str,
    episode_id: str,
    *,
    outcome: str = "completed",
    error_ref: str | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    context = _contract(spec_path, output)
    _workflow(context, dispatcher_id)
    runtime = _runtime()
    with runtime.RuntimeStore(database) as store:
        if outcome not in {"completed", "failed"}:
            raise GhAwRuntimeError("outcome must be completed or failed")
        state = store.state(episode_id)
        idempotency_key = f"gh-aw:episode:{outcome}"
        if state["status"] in runtime.RUN_TERMINAL:
            event = _history_event(store, episode_id, idempotency_key)
            if event is None:
                raise GhAwRuntimeError(f"episode is not running: {state['status']}")
            if outcome == "failed" and event["payload"] != {"error_ref": _ref(error_ref, "error_ref")}:
                raise GhAwRuntimeError("episode failure identity conflicts")
            if outcome == "completed" and event["payload"]:
                raise GhAwRuntimeError("episode completion identity conflicts")
            return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)
        _require_running(store, episode_id)
        if outcome == "completed":
            if any(task["status"] != "completed" for task in state["tasks"].values()):
                raise GhAwRuntimeError("episode cannot complete until every worker succeeds")
            if any(effect["status"] != "succeeded" for effect in store.list_outbox(episode_id)):
                raise GhAwRuntimeError("episode cannot complete until every safe output succeeds")
            store.append_event(episode_id, "run.completed", idempotency_key=idempotency_key, occurred_at=occurred_at)
        elif outcome == "failed":
            store.append_event(
                episode_id,
                "run.failed",
                {"error_ref": _ref(error_ref, "error_ref")},
                idempotency_key=idempotency_key,
                occurred_at=occurred_at,
            )
        return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)


def cancel_episode(
    spec_path: Path,
    output: Path,
    database: Path,
    dispatcher_id: str,
    episode_id: str,
    authorization_context_digest: str,
    reason_ref: str,
    *,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    context = _contract(spec_path, output)
    _workflow(context, dispatcher_id)
    authorization_context_digest = _ref(authorization_context_digest, "authorization_context_digest")
    reason_ref = _ref(reason_ref, "reason_ref")
    runtime = _runtime()
    with runtime.RuntimeStore(database) as store:
        state = store.state(episode_id)
        if state["status"] in runtime.RUN_TERMINAL:
            return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)
        prefix = f"gh-aw:cancel:{episode_id}"
        store.request_cancel(
            episode_id,
            reason_ref=reason_ref,
            authorization_context_digest=authorization_context_digest,
            idempotency_key=f"{prefix}:requested",
            occurred_at=occurred_at,
        )
        ack_ref = context["compiler"].digest({"episode_id": episode_id, "reason_ref": reason_ref, "prefix": prefix})
        store.acknowledge_cancel(
            episode_id,
            ack_ref=ack_ref,
            authorization_context_digest=authorization_context_digest,
            idempotency_key=f"{prefix}:acknowledged",
            occurred_at=occurred_at,
        )
        store.cancel_run(episode_id, idempotency_key=f"{prefix}:cancelled", occurred_at=occurred_at)
        return inspect_episode(spec_path, output, database, dispatcher_id, episode_id)


def inspect_episode(
    spec_path: Path,
    output: Path,
    database: Path,
    dispatcher_id: str,
    episode_id: str,
) -> dict[str, Any]:
    context = _contract(spec_path, output)
    dispatcher = _workflow(context, dispatcher_id)
    manifest_workflow = _manifest_workflow(context, dispatcher_id)
    runtime = _runtime()
    with runtime.RuntimeStore(database) as store:
        state = store.state(episode_id)
        effects = store.list_outbox(episode_id)
        inbox = store.list_inbox(episode_id)
        history = store.history(episode_id)
        receipt_summaries: list[dict[str, Any]] = []
        receipt_digests: list[str] = []
        for item in inbox:
            receipt = item["receipt"]
            normalized = _normalize_receipt(receipt, episode_id, next(effect for effect in effects if effect["effect_id"] == item["effect_id"]))
            receipt_digest = context["compiler"].digest(normalized)
            receipt_digests.append(receipt_digest)
            summary = {
                "effect_id": item["effect_id"],
                "status": normalized["status"],
                "receipt_digest": receipt_digest,
            }
            for key in ("approval_id", "provider_request_id", "resource_ref", "result_ref"):
                if key in normalized:
                    summary[key] = normalized[key]
            receipt_summaries.append(summary)
        task_summaries: list[dict[str, Any]] = []
        effect_ids_by_task: dict[str, list[str]] = {}
        for effect in effects:
            effect_ids_by_task.setdefault(effect["task_id"], []).append(effect["effect_id"])
        for task_id, task in sorted(state["tasks"].items()):
            summary = {
                "task_id": task_id,
                "workflow_id": task_id,
                "status": task["status"],
                "attempt": task["attempt"],
                "depends_on": task["depends_on"],
                "effect_ids": sorted(effect_ids_by_task.get(task_id, [])),
            }
            for key in ("output_ref", "error_ref"):
                if key in task:
                    summary[key] = task[key]
            task_summaries.append(summary)
        effect_summaries = [
            {
                "effect_id": effect["effect_id"],
                "task_id": effect["task_id"],
                "effect_type": effect["effect_type"],
                "status": effect["status"],
                "idempotency_key": effect["idempotency_key"],
                "source_event_id": effect["source_event_id"],
                "activity_attempt": effect["activity_attempt"],
            }
            for effect in effects
        ]
        correlation = {
            "dispatcher_workflow_id": dispatcher_id,
            "episode_id": episode_id,
            "effect_ids": [item["effect_id"] for item in effect_summaries],
            "receipt_digests": sorted(receipt_digests),
            "worker_task_ids": [item["task_id"] for item in task_summaries],
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "contract_revision": BRIDGE_REVISION,
            "episode_id": episode_id,
            "repository": context["spec"]["defaults"]["repository"],
            "dispatcher_workflow_id": dispatcher_id,
            "dispatcher_source_workflow": dispatcher["source_workflow"],
            "runtime_definition_digest": state["definition_digest"],
            "gh_aw_definition_digest": _ref(manifest_workflow["definition_digest"], "definition_digest"),
            "graph_digest": _ref(context["manifest"]["graph_digest"], "graph_digest"),
            "spec_digest": _ref(context["manifest"]["spec_digest"], "spec_digest"),
            "effect_set_digest": _ref(manifest_workflow["effect_set_digest"], "effect_set_digest"),
            "upstream": copy.deepcopy(context["manifest"]["upstream"]),
            "status": state["status"],
            "sequence": state["sequence"],
            "history_head": history[-1]["event_hash"],
            "tasks": task_summaries,
            "effects": effect_summaries,
            "receipts": receipt_summaries,
            "correlation": correlation,
            "correlation_digest": context["compiler"].digest(correlation),
        }


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dispatcher", required=True)
    parser.add_argument("--episode-id", required=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start", help="start a durable gh-aw episode")
    start_parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    start_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    start_parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    start_parser.add_argument("--dispatcher", required=True)
    start_parser.add_argument("--request-digest", required=True)
    start_parser.add_argument("--episode-id")
    start_parser.add_argument("--occurred-at")
    dispatch_parser = subparsers.add_parser("dispatch", help="stage declared worker dispatch effects")
    _common(dispatch_parser)
    dispatch_parser.add_argument("--request-digest", required=True)
    dispatch_parser.add_argument("--occurred-at")
    worker_start_parser = subparsers.add_parser("worker-start", help="record a dispatched worker start")
    _common(worker_start_parser)
    worker_start_parser.add_argument("--worker", required=True)
    worker_start_parser.add_argument("--occurred-at")
    complete_parser = subparsers.add_parser("worker-complete", help="record completion and stage a safe output")
    _common(complete_parser)
    complete_parser.add_argument("--worker", required=True)
    complete_parser.add_argument("--output-ref", required=True)
    complete_parser.add_argument("--safe-output-type")
    complete_parser.add_argument("--occurred-at")
    fail_parser = subparsers.add_parser("worker-fail", help="record a worker failure")
    _common(fail_parser)
    fail_parser.add_argument("--worker", required=True)
    fail_parser.add_argument("--error-ref", required=True)
    fail_parser.add_argument("--retryable", action="store_true")
    fail_parser.add_argument("--occurred-at")
    claim_parser = subparsers.add_parser("claim", help="claim staged effects through the runtime lease")
    _common(claim_parser)
    claim_parser.add_argument("--worker-id", required=True)
    claim_parser.add_argument("--limit", type=int, default=1)
    claim_parser.add_argument("--now")
    ack_parser = subparsers.add_parser("ack", help="acknowledge a safe output with a bounded receipt")
    _common(ack_parser)
    ack_parser.add_argument("--effect-id", required=True)
    ack_parser.add_argument("--worker-id", required=True)
    ack_parser.add_argument("--lease-generation", type=int, required=True)
    ack_parser.add_argument("--receipt-json", required=True)
    ack_parser.add_argument("--received-at")
    finish_parser = subparsers.add_parser("finish", help="finish an episode after effect/task gates pass")
    _common(finish_parser)
    finish_parser.add_argument("--outcome", choices=("completed", "failed"), default="completed")
    finish_parser.add_argument("--error-ref")
    finish_parser.add_argument("--occurred-at")
    cancel_parser = subparsers.add_parser("cancel", help="cancel an episode with durable acknowledgement")
    _common(cancel_parser)
    cancel_parser.add_argument("--authorization-context-digest", required=True)
    cancel_parser.add_argument("--reason-ref", required=True)
    cancel_parser.add_argument("--occurred-at")
    inspect_parser = subparsers.add_parser("inspect", help="inspect a privacy-safe episode projection")
    _common(inspect_parser)
    try:
        args = parser.parse_args(argv)
        if args.command == "start":
            result = start_episode(
                args.spec,
                args.output,
                args.db,
                args.dispatcher,
                args.request_digest,
                episode_id=args.episode_id,
                occurred_at=args.occurred_at,
            )
        elif args.command == "dispatch":
            result = dispatch_episode(
                args.spec,
                args.output,
                args.db,
                args.dispatcher,
                args.episode_id,
                args.request_digest,
                occurred_at=args.occurred_at,
            )
        elif args.command == "worker-start":
            result = start_worker(
                args.spec,
                args.output,
                args.db,
                args.dispatcher,
                args.episode_id,
                args.worker,
                occurred_at=args.occurred_at,
            )
        elif args.command == "worker-complete":
            result = complete_worker(
                args.spec,
                args.output,
                args.db,
                args.dispatcher,
                args.episode_id,
                args.worker,
                args.output_ref,
                safe_output_type=args.safe_output_type,
                occurred_at=args.occurred_at,
            )
        elif args.command == "worker-fail":
            result = fail_worker(
                args.spec,
                args.output,
                args.db,
                args.dispatcher,
                args.episode_id,
                args.worker,
                args.error_ref,
                retryable=args.retryable,
                occurred_at=args.occurred_at,
            )
        elif args.command == "claim":
            result = claim_episode(
                args.spec,
                args.output,
                args.db,
                args.dispatcher,
                args.episode_id,
                args.worker_id,
                limit=args.limit,
                now=args.now,
            )
        elif args.command == "ack":
            receipt = json.loads(args.receipt_json)
            if not isinstance(receipt, dict):
                raise GhAwRuntimeError("receipt-json must contain an object")
            result = acknowledge_episode(
                args.spec,
                args.output,
                args.db,
                args.dispatcher,
                args.episode_id,
                args.effect_id,
                args.worker_id,
                args.lease_generation,
                receipt,
                received_at=args.received_at,
            )
        elif args.command == "finish":
            result = finish_episode(
                args.spec,
                args.output,
                args.db,
                args.dispatcher,
                args.episode_id,
                outcome=args.outcome,
                error_ref=args.error_ref,
                occurred_at=args.occurred_at,
            )
        elif args.command == "cancel":
            result = cancel_episode(
                args.spec,
                args.output,
                args.db,
                args.dispatcher,
                args.episode_id,
                args.authorization_context_digest,
                args.reason_ref,
                occurred_at=args.occurred_at,
            )
        else:
            result = inspect_episode(args.spec, args.output, args.db, args.dispatcher, args.episode_id)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0
    except (GhAwRuntimeError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"forge-gh-aw-runtime: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
