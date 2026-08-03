#!/usr/bin/env python3
"""Preview, submit, resume, and audit native GitHub Stack Merge requests."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SYNC_PATH = Path(__file__).with_name("forge-stack-sync.py")
SYNC_SPEC = importlib.util.spec_from_file_location("forge_stack_sync_for_merge", SYNC_PATH)
if SYNC_SPEC is None or SYNC_SPEC.loader is None:  # pragma: no cover - import failure is host-specific.
    raise RuntimeError("could not load the native stack sync adapter")
sync = importlib.util.module_from_spec(SYNC_SPEC)
sys.modules[SYNC_SPEC.name] = sync
SYNC_SPEC.loader.exec_module(sync)

RemotePullRequest = sync.RemotePullRequest
RemoteStack = sync.RemoteStack
ConflictError = sync.ConflictError
FeatureUnavailable = sync.FeatureUnavailable
StackSyncError = sync.StackSyncError

SCHEMA_VERSION = 1
MERGE_STATUSES = ("pending", "enqueued", "merged", "failed", "indeterminate")
TERMINAL_STATUSES = {"merged", "failed", "indeterminate"}
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.IGNORECASE)


class MergeError(StackSyncError):
    """Raised for safe-to-report native merge failures."""


@dataclass(frozen=True)
class MergePlan:
    """The exact stack range and remote preconditions bound by one approval."""

    stack_number: int
    target_pr: int
    base_ref: str
    base_sha: str
    selected_pull_requests: tuple[int, ...]
    expected_head_shas: tuple[str, ...]
    merge_method: str
    merge_action: str
    readiness: dict[str, Any]

    @property
    def expected_target_sha(self) -> str:
        return self.expected_head_shas[-1]

    @property
    def expected_result(self) -> str:
        if self.merge_action == "direct_merge":
            return "merged"
        if self.merge_action == "merge_queue":
            return "enqueued-then-merged"
        return "merged-or-enqueued"

    @property
    def operation_id(self) -> str:
        material = {
            "schema_version": SCHEMA_VERSION,
            "stack_number": self.stack_number,
            "target_pr": self.target_pr,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "selected_pull_requests": self.selected_pull_requests,
            "expected_head_shas": self.expected_head_shas,
            "merge_method": self.merge_method,
            "merge_action": self.merge_action,
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def request_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "merge_action": self.merge_action,
            "sha": self.expected_target_sha,
        }
        if self.merge_action != "merge_queue":
            payload["merge_method"] = self.merge_method
        return payload

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "operation_id": self.operation_id,
            "stack_number": self.stack_number,
            "target_pr": self.target_pr,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "selected_pull_requests": list(self.selected_pull_requests),
            "expected_head_shas": list(self.expected_head_shas),
            "merge_method": self.merge_method,
            "merge_action": self.merge_action,
            "expected_result": self.expected_result,
            "request_payload": self.request_payload(),
            "preview": {
                "contiguous_range": list(self.selected_pull_requests),
                "policy_gate": {
                    "tool": "forge-stack-merge.submit",
                    "effect": "github_stack_merge",
                    "approval": "required",
                },
                "readiness": self.readiness,
            },
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> MergePlan:
        if value.get("schema_version") != SCHEMA_VERSION:
            raise MergeError("unsupported native merge state schema version")
        try:
            return cls(
                stack_number=int(value["stack_number"]),
                target_pr=int(value["target_pr"]),
                base_ref=str(value["base_ref"]),
                base_sha=str(value.get("base_sha", "")),
                selected_pull_requests=tuple(int(item) for item in value["selected_pull_requests"]),
                expected_head_shas=tuple(str(item) for item in value["expected_head_shas"]),
                merge_method=str(value["merge_method"]),
                merge_action=str(value["merge_action"]),
                readiness=dict(value.get("preview", {}).get("readiness", {"status": "unknown"})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MergeError(f"invalid persisted native merge plan: {exc}") from exc


def _normalize_result(value: Mapping[str, Any]) -> dict[str, Any]:
    status = str(value.get("status", "")).lower()
    if status not in {"pending", "enqueued", "merged", "failed"}:
        raise MergeError(f"GitHub returned unsupported merge status: {status or 'missing'}")
    details = value.get("details", {})
    if not isinstance(details, Mapping):
        details = {"message": str(details)}
    result = {"status": status, "details": dict(details)}
    if value.get("recovered"):
        result["recovered"] = True
    return result


def _uuid_from(value: Any) -> str | None:
    if isinstance(value, Mapping):
        details = value.get("details")
        if isinstance(details, Mapping) and details.get("uuid"):
            return str(details["uuid"])
        if value.get("uuid"):
            return str(value["uuid"])
    match = UUID_RE.search(str(value))
    return match.group(0) if match else None


def _local_pull_requests(manifest: Mapping[str, Any]) -> list[tuple[dict[str, Any], int]]:
    return [(branch, int(branch["pr"])) for branch in manifest.get("branches", []) if branch.get("pr")]


def plan_merge(
    manifest: Mapping[str, Any],
    remote: RemoteStack | None,
    *,
    target_pr: int,
    merge_method: str = "merge",
    merge_action: str = "default",
    readiness: Mapping[str, Any] | None = None,
) -> MergePlan:
    """Build a byte-stable, exact-range merge preview without making remote changes."""

    if remote is None:
        raise FeatureUnavailable("the target pull request is not in a native GitHub stack")
    if merge_method not in {"merge", "squash", "rebase"}:
        raise MergeError("merge method must be merge, squash, or rebase")
    if merge_action not in {"default", "direct_merge", "merge_queue"}:
        raise MergeError("merge action must be default, direct_merge, or merge_queue")
    remote_numbers = [item.number for item in remote.pull_requests]
    if target_pr not in remote_numbers:
        raise MergeError(f"PR #{target_pr} is not in native stack #{remote.number}")
    local = _local_pull_requests(manifest)
    local_numbers = [number for _, number in local]
    if local_numbers and local_numbers != remote_numbers:
        raise ConflictError("local and remote stack ranges differ; reconcile before landing")
    for branch, number in local:
        expected_sha = (branch.get("github") or {}).get("head_sha")
        if expected_sha:
            actual = next(item for item in remote.pull_requests if item.number == number).head_sha
            if expected_sha != actual:
                raise ConflictError(f"PR #{number} head SHA changed since the stack was recorded")
    expected_base = str((manifest.get("github_stack") or {}).get("base_sha") or "")
    if expected_base and remote.base_sha and expected_base != remote.base_sha:
        raise ConflictError("stack base SHA changed since the stack was recorded")
    target_index = remote_numbers.index(target_pr)
    prefix = remote.pull_requests[: target_index + 1]
    for pull_request in prefix:
        state = pull_request.state.lower()
        if state == "closed" and not pull_request.merged_at:
            raise MergeError(f"PR #{pull_request.number} is closed inside the requested contiguous range")
    selected = tuple(item for item in prefix if item.state.lower() != "merged" and not item.merged_at)
    if not selected:
        raise MergeError(f"PR #{target_pr} is already merged")
    if selected[-1].number != target_pr:
        raise MergeError(f"PR #{target_pr} is already merged; choose the highest unmerged PR")
    if any(item.draft for item in selected):
        draft = next(item.number for item in selected if item.draft)
        raise MergeError(f"PR #{draft} is a draft and cannot enter a native stack merge")
    if any(not item.head_sha for item in selected):
        raise ConflictError("one or more selected PRs has no remote head SHA")
    return MergePlan(
        stack_number=remote.number,
        target_pr=target_pr,
        base_ref=remote.base_ref or str(manifest.get("trunk") or "main"),
        base_sha=remote.base_sha,
        selected_pull_requests=tuple(item.number for item in selected),
        expected_head_shas=tuple(item.head_sha for item in selected),
        merge_method=merge_method,
        merge_action=merge_action,
        readiness=dict(readiness or {"status": "unknown", "checks": []}),
    )


def fallback_plan(plan: MergePlan, reason: str) -> dict[str, Any]:
    return {
        "status": "fallback",
        "fallback": True,
        "reason": reason,
        "provider_plan": {
            "strategy": "provider-native-bottom-up",
            "target_pr": plan.target_pr,
            "contiguous_range": list(plan.selected_pull_requests),
            "merge_method": plan.merge_method,
            "steps": [
                "run the configured provider's read-only landing plan",
                "verify reviews, required checks, unresolved threads, rulesets, and queue policy",
                "land from the lowest unmerged PR upward using the provider's protected merge path",
                "reconcile remote heads and report every landed or failed PR",
            ],
        },
    }


def _readiness_failures(readiness: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    checks = readiness.get("checks", [])
    if not isinstance(checks, list):
        return ["preflight checks are not a list"]
    for check in checks:
        if not isinstance(check, Mapping):
            failures.append("preflight returned a malformed check")
            continue
        status = str(check.get("status", "unknown")).lower()
        if status != "pass":
            failures.append(f"{check.get('name', 'preflight')}: {check.get('message', status)}")
    if str(readiness.get("status", "unknown")).lower() != "pass":
        failures.append(str(readiness.get("message", "preflight is incomplete")))
    return failures


def _load_receipts(path: Path):
    module_path = SYNC_PATH.parents[2] / "observability" / "scripts" / "forge-receipts.py"
    spec = importlib.util.spec_from_file_location("forge_receipts_for_stack_merge", module_path)
    if spec is None or spec.loader is None:
        raise MergeError("could not load Forge receipt store")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.ReceiptStore(path), module


def _record_receipt(path: Path, repository: str, operation_id: str, event: str, result: Mapping[str, Any]) -> None:
    store, module = _load_receipts(path)
    store.append(
        module.make_event(
            "tool.called" if event == "submit" else "outcome.recorded",
            f"github-stack-merge:{repository}",
            idempotency_key=f"forge-stack-merge:{operation_id}:{event}:{hashlib.sha256(json.dumps(dict(result), sort_keys=True).encode()).hexdigest()}",
            attributes={"merge_event": event, "merge_status": result.get("status", "unknown"), "result": dict(result)},
        )
    )


def _load_state(path: Path, repository: str | None = None) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "repository": repository or "", "requests": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MergeError(f"cannot load native merge state {path}: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION or not isinstance(state.get("requests"), dict):
        raise MergeError("native merge state is invalid or unsupported")
    if repository and state.get("repository") and state["repository"] != repository:
        raise MergeError("native merge state belongs to a different repository")
    if repository:
        state["repository"] = repository
    return state


def _save_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path
    handle: Any
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _policy_session(profile: Path, approvals: Path, receipts: Path, principal: str | None, workspace: Path | None):
    module_path = SYNC_PATH.parents[2] / "policy" / "scripts" / "forge-policy.py"
    spec = importlib.util.spec_from_file_location("forge_policy_for_stack_merge", module_path)
    if spec is None or spec.loader is None:
        raise MergeError("could not load Forge policy engine")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    try:
        return module.PolicySession(
            profile,
            approvals_path=approvals,
            receipts_path=receipts,
            principal=principal,
            workspace=workspace or Path.cwd(),
        ), module.PolicyError
    except module.PolicyError as exc:
        raise MergeError(str(exc)) from exc


def _authorization(
    plan: MergePlan,
    repository: str,
    *,
    profile: Path,
    approvals: Path,
    receipts: Path,
    approval_id: str | None,
    staged: bool,
    principal: str | None,
    workspace: Path | None,
):
    policy, error_type = _policy_session(profile, approvals, receipts, principal, workspace)
    action = policy.action(
        action_id=f"forge-stack-merge:{plan.operation_id}",
        tool="forge-stack-merge.submit",
        arguments=plan.as_dict(),
        repository=repository,
        branch=plan.base_ref,
        paths=[],
        domains=["github.com"],
        effect="github_stack_merge",
        risk="critical",
        fan_out=len(plan.selected_pull_requests),
    )
    try:
        return policy, error_type, policy.authorize(action, approval_id=approval_id, staged=staged)
    except Exception as exc:
        if isinstance(exc, error_type):
            raise MergeError(str(exc)) from exc
        raise


def _verify_observed(plan: MergePlan, observed: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    merged = {int(item) for item in observed.get("merged_prs", [])}
    selected = set(plan.selected_pull_requests)
    if selected and selected.issubset(merged):
        return "merged", {"status": "merged", "observed": dict(observed)}
    if selected.intersection(merged):
        return "partial", {"status": "partial", "observed": dict(observed)}
    return "none", {"status": "not-merged", "observed": dict(observed)}


def _terminal_result(client: Any, plan: MergePlan, result: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_result(result)
    observed = client.observe_plan(plan)
    if not isinstance(observed, Mapping):
        raise MergeError("post-merge observation was not an object")
    observation_status, evidence = _verify_observed(plan, observed)
    if normalized["status"] == "merged" and observation_status != "merged":
        return {
            "status": "indeterminate",
            "action": "stop-and-reconcile",
            "message": "GitHub reported merged, but post-state verification did not show every selected PR merged",
            "native_result": normalized,
            "evidence": evidence,
            "partial_merge_detected": observation_status == "partial",
        }
    if normalized["status"] == "failed" and observation_status == "partial":
        return {
            "status": "indeterminate",
            "action": "stop-and-reconcile",
            "message": "GitHub reported failure after remote merge evidence appeared; partial landing must be reconciled",
            "native_result": normalized,
            "evidence": evidence,
            "partial_merge_detected": True,
        }
    return {**normalized, "evidence": evidence}


def _persist_request(state: dict[str, Any], plan: MergePlan, result: Mapping[str, Any], *, request_uuid: str | None = None, timed_out: bool = False) -> dict[str, Any]:
    existing = state["requests"].get(plan.operation_id, {})
    record = {
        **existing,
        "schema_version": SCHEMA_VERSION,
        "operation_id": plan.operation_id,
        "plan": plan.as_dict(),
        "request_uuid": request_uuid or existing.get("request_uuid"),
        "status": result.get("status"),
        "last_result": dict(result),
        "timed_out": timed_out,
    }
    state["requests"][plan.operation_id] = record
    return record


def execute_merge(
    client: Any,
    repository: str,
    plan: MergePlan,
    state_path: Path,
    receipts_path: Path,
    *,
    yes: bool,
    authority: str = "local",
    policy_profile: Path | None = None,
    policy_approval: str | None = None,
    policy_staged: bool = False,
    policy_approvals_path: Path | None = None,
    policy_principal: str | None = None,
    workspace: Path | None = None,
    poll_attempts: int = 10,
    allow_unknown_readiness: bool = False,
    allow_submit: bool = True,
) -> dict[str, Any]:
    """Submit once, persist the UUID, and resume polling without duplicate writes."""

    if authority != "local":
        raise MergeError("only local authority may submit native stack merges")
    if not yes and not policy_staged:
        raise MergeError("submit requires explicit --yes")
    if policy_staged and policy_profile is None:
        raise MergeError("--policy-staged requires --policy-profile")
    if poll_attempts < 0:
        raise MergeError("poll attempts cannot be negative")
    state = _load_state(state_path, repository)
    existing = state["requests"].get(plan.operation_id)
    if existing and existing.get("status") in TERMINAL_STATUSES:
        return dict(existing.get("last_result") or {"status": existing["status"]})
    if not existing and not allow_submit:
        raise MergeError("no persisted native merge request for this operation")
    policy = None
    authorization = None
    policy_error_type = None
    native_result: dict[str, Any]
    if not existing:
        try:
            client.verify_plan(plan)
            readiness = client.preflight_plan(plan)
        except FeatureUnavailable:
            return fallback_plan(plan, "native GitHub Stack Merge is unavailable for this repository")
        except StackSyncError as exc:
            raise MergeError(f"native merge preflight failed: {exc}") from exc
        if not isinstance(readiness, Mapping):
            raise MergeError("native merge preflight returned an invalid result")
        plan = MergePlan(**{**plan.__dict__, "readiness": dict(readiness)})
        failures = _readiness_failures(readiness)
        if failures and not allow_unknown_readiness:
            raise MergeError("native merge preflight did not pass: " + "; ".join(failures))
        if policy_profile is not None:
            policy, policy_error_type, authorization = _authorization(
                plan,
                repository,
                profile=policy_profile,
                approvals=policy_approvals_path or state_path.with_name("approvals.jsonl"),
                receipts=receipts_path,
                approval_id=policy_approval,
                staged=policy_staged,
                principal=policy_principal,
                workspace=workspace,
            )
            if authorization.status == "staged":
                return {"status": "staged", "operation_id": plan.operation_id, "plan": plan.as_dict(), "policy": authorization.as_dict()}
            if authorization.effective_action != authorization.action:
                raise MergeError("policy transform is not supported by the native merge adapter")
        try:
            if policy is not None:
                policy.recheck(authorization)
            native_result = _normalize_result(client.submit_merge(plan))
        except FeatureUnavailable:
            return fallback_plan(plan, "native GitHub Stack Merge is unavailable for this repository")
        except StackSyncError as exc:
            # A transport timeout after the PUT may have created a request. Never issue a blind retry.
            result = {
                "status": "indeterminate",
                "action": "stop-and-reconcile",
                "message": f"submission outcome is unknown; refusing to submit a duplicate: {exc}",
            }
            _persist_request(state, plan, result)
            _save_state(state_path, state)
            _record_receipt(receipts_path, repository, plan.operation_id, "submit-unknown", result)
            return result
        if policy is not None:
            try:
                policy.commit(authorization, native_result)
            except Exception as exc:
                if policy_error_type is not None and isinstance(exc, policy_error_type):
                    raise MergeError(str(exc)) from exc
                raise
        request_uuid = _uuid_from(native_result)
        if native_result["status"] == "pending" and not request_uuid:
            raise MergeError("GitHub returned pending without a merge request UUID")
        _persist_request(state, plan, native_result, request_uuid=request_uuid)
        _save_state(state_path, state)
        _record_receipt(receipts_path, repository, plan.operation_id, "submit", native_result)
        existing = state["requests"][plan.operation_id]
    else:
        native_result = dict(existing.get("last_result") or {"status": existing.get("status")})

    status = str(existing.get("status", native_result.get("status")))
    request_uuid = existing.get("request_uuid") or _uuid_from(native_result)
    if status == "pending":
        if not request_uuid:
            result = {"status": "indeterminate", "action": "stop-and-reconcile", "message": "pending request has no persisted UUID"}
            _persist_request(state, plan, result)
            _save_state(state_path, state)
            return result
        latest = native_result
        for _ in range(poll_attempts):
            try:
                latest = _normalize_result(client.poll_merge(plan, request_uuid))
            except StackSyncError as exc:
                result = {"status": "indeterminate", "action": "stop-and-reconcile", "message": f"merge polling failed: {exc}"}
                _persist_request(state, plan, result, request_uuid=request_uuid)
                _save_state(state_path, state)
                _record_receipt(receipts_path, repository, plan.operation_id, "poll-unknown", result)
                return result
            if latest["status"] != "pending":
                break
        if latest["status"] == "pending":
            _persist_request(state, plan, latest, request_uuid=request_uuid, timed_out=True)
            _save_state(state_path, state)
            _record_receipt(receipts_path, repository, plan.operation_id, "poll-timeout", latest)
            return {**latest, "operation_id": plan.operation_id, "timed_out": True, "request_uuid": request_uuid}
        native_result = latest
        status = latest["status"]
    if status == "enqueued":
        latest = native_result
        for _ in range(poll_attempts):
            try:
                latest = _normalize_result(client.poll_queue(plan))
            except StackSyncError as exc:
                result = {"status": "indeterminate", "action": "stop-and-reconcile", "message": f"merge queue observation failed: {exc}"}
                _persist_request(state, plan, result, request_uuid=request_uuid)
                _save_state(state_path, state)
                _record_receipt(receipts_path, repository, plan.operation_id, "queue-unknown", result)
                return result
            if latest["status"] not in {"enqueued", "pending"}:
                break
        if latest["status"] in {"enqueued", "pending"}:
            if latest["status"] == "pending":
                latest = {"status": "enqueued", "details": {"message": "merge queue is still processing"}}
            _persist_request(state, plan, latest, request_uuid=request_uuid, timed_out=True)
            _save_state(state_path, state)
            _record_receipt(receipts_path, repository, plan.operation_id, "queue-pending", latest)
            return {**latest, "operation_id": plan.operation_id, "timed_out": True}
        native_result = latest
    if native_result["status"] in {"merged", "failed"}:
        result = _terminal_result(client, plan, native_result)
    else:
        result = native_result
    _persist_request(state, plan, result, request_uuid=request_uuid)
    _save_state(state_path, state)
    _record_receipt(receipts_path, repository, plan.operation_id, "terminal", result)
    return {**result, "operation_id": plan.operation_id}


def ingest_merge_group_event(state_path: Path, receipts_path: Path, event: Mapping[str, Any], *, operation_id: str | None = None) -> dict[str, Any]:
    """Attach a checks_requested merge_group delivery to its durable enqueued request."""

    if event.get("action") != "checks_requested":
        raise MergeError("only merge_group checks_requested events can be correlated")
    merge_group = event.get("merge_group")
    if not isinstance(merge_group, Mapping) or not merge_group.get("head_sha"):
        raise MergeError("merge_group event must contain merge_group.head_sha")
    repository = ((event.get("repository") or {}).get("full_name") if isinstance(event.get("repository"), Mapping) else None) or ""
    state = _load_state(state_path)
    if repository and state.get("repository") and repository != state["repository"]:
        raise MergeError("merge_group event belongs to a different repository")
    candidates = [
        (key, value)
        for key, value in state["requests"].items()
        if value.get("status") == "enqueued"
    ]
    if operation_id:
        request = state["requests"].get(operation_id)
        if not request or request.get("status") != "enqueued":
            raise MergeError("operation is not an enqueued native merge request")
        selected = [(operation_id, request)]
    elif len(candidates) == 1:
        selected = candidates
    else:
        raise MergeError("merge_group event is ambiguous; pass --operation-id")
    selected_id, request = selected[0]
    plan = MergePlan.from_mapping(request["plan"])
    if merge_group.get("base_ref") and merge_group["base_ref"] != plan.base_ref:
        raise ConflictError("merge_group base ref does not match the originating stack plan")
    summary = {
        "head_sha": str(merge_group["head_sha"]),
        "base_ref": str(merge_group.get("base_ref") or plan.base_ref),
        "head_ref": str(merge_group.get("head_ref") or ""),
        "delivery_id": str(event.get("delivery_id") or event.get("id") or ""),
        "checks_requested": True,
    }
    request["queue"] = {**request.get("queue", {}), "checks_requested": True, "last_merge_group": summary}
    state["requests"][selected_id] = request
    _save_state(state_path, state)
    _record_receipt(receipts_path, state.get("repository", ""), selected_id, "merge-group", {"status": "enqueued", "merge_group": summary})
    return {"status": "enqueued", "operation_id": selected_id, "merge_group": summary}


class GitHubStackMergeClient(sync.GitHubStackClient):
    """gh-backed native merge client with explicit async and queue observation."""

    def submit_merge(self, plan: MergePlan) -> dict[str, Any]:
        path = f"repos/{self.repository}/pulls/{plan.target_pr}/merge-async"
        try:
            response = self.request("PUT", path, plan.request_payload())
        except FeatureUnavailable:
            raise
        except sync.ApiError as exc:
            if exc.status == 404:
                raise FeatureUnavailable("GitHub Stack Merge is unavailable for this repository") from exc
            if exc.status == 409:
                request_uuid = _uuid_from(getattr(exc, "data", None) or str(exc))
                if request_uuid:
                    return {"status": "pending", "recovered": True, "details": {"uuid": request_uuid, "message": "reused existing merge request"}}
                raise MergeError("GitHub reported an existing merge request without its UUID; inspect before retrying") from exc
            if exc.status == 400:
                return {"status": "failed", "details": {"message": str(exc)}}
            raise
        if not isinstance(response, Mapping):
            raise MergeError("GitHub async merge response was not an object")
        return dict(response)

    def poll_merge(self, plan: MergePlan, request_uuid: str) -> dict[str, Any]:
        path = f"repos/{self.repository}/pulls/{plan.target_pr}/merge-async/{request_uuid}"
        try:
            response = self.request("GET", path)
        except sync.ApiError as exc:
            if exc.status == 404:
                raise MergeError("native merge request expired or is no longer readable; refusing a duplicate submit") from exc
            raise
        if not isinstance(response, Mapping):
            raise MergeError("GitHub async merge result was not an object")
        return dict(response)

    def verify_plan(self, plan: MergePlan) -> dict[str, Any]:
        remote = self.stack_for_pull_request(plan.target_pr)
        if remote is None or remote.number != plan.stack_number:
            raise ConflictError("native stack identity changed before submit")
        actual = {item.number: item.head_sha for item in remote.pull_requests}
        for number, expected in zip(plan.selected_pull_requests, plan.expected_head_shas):
            if actual.get(number) != expected:
                raise ConflictError(f"PR #{number} head SHA changed before submit")
        if plan.base_sha and remote.base_sha and plan.base_sha != remote.base_sha:
            raise ConflictError("native stack base SHA changed before submit")
        return {"status": "verified", "stack_number": remote.number}

    def preflight_plan(self, plan: MergePlan) -> dict[str, Any]:
        """Collect available GitHub evidence; unknown gates fail closed by default."""

        checks: list[dict[str, Any]] = []
        for number, expected_sha in zip(plan.selected_pull_requests, plan.expected_head_shas):
            data = self.request("GET", f"repos/{self.repository}/pulls/{number}")
            if not isinstance(data, Mapping):
                raise MergeError(f"PR #{number} readiness response was not an object")
            checks.extend(
                [
                    {
                        "name": f"pr-{number}-open",
                        "status": "pass" if data.get("state") == "open" else "fail",
                        "message": "open" if data.get("state") == "open" else f"state={data.get('state')}",
                    },
                    {
                        "name": f"pr-{number}-head-sha",
                        "status": "pass" if (data.get("head") or {}).get("sha") == expected_sha else "fail",
                        "message": "matches preview" if (data.get("head") or {}).get("sha") == expected_sha else "head SHA changed",
                    },
                    self._field_gate(data, number, "mergeability", ("mergeable_state", "mergeStateStatus"), {"clean"}),
                    self._field_gate(data, number, "reviews", ("review_decision", "reviewDecision"), {"approved", "APPROVED"}),
                    self._field_gate(data, number, "required-checks", ("required_checks", "requiredChecks"), {"pass", "passed", "success"}),
                    self._field_gate(data, number, "unresolved-threads", ("unresolved_threads", "unresolvedThreads"), {0}),
                    self._field_gate(data, number, "rulesets", ("rulesets", "ruleset_status"), {"pass", "passed", "active"}),
                ]
            )
        if plan.merge_action == "merge_queue":
            checks.append(self._field_gate({}, plan.target_pr, "queue-policy", ("queue_policy",), {"pass", "enabled", "required"}))
        else:
            checks.append({"name": "queue-policy", "status": "pass", "message": "not required for direct merge"})
        failures = [check for check in checks if check["status"] == "fail"]
        unknown = [check for check in checks if check["status"] == "unknown"]
        return {
            "status": "fail" if failures else ("unknown" if unknown else "pass"),
            "checks": checks,
            "message": "; ".join(check["message"] for check in failures + unknown),
        }

    @staticmethod
    def _field_gate(data: Mapping[str, Any], number: int, name: str, fields: tuple[str, ...], passing: set[Any]) -> dict[str, Any]:
        value = next((data[field] for field in fields if field in data), None)
        if value is None:
            return {"name": f"pr-{number}-{name}", "status": "unknown", "message": "GitHub did not expose this gate"}
        if isinstance(value, Mapping):
            value = value.get("status")
        if isinstance(value, list):
            value = "pass" if all(str(item.get("conclusion", item.get("status", ""))).lower() in {"success", "passed", "skipped", "neutral"} for item in value if isinstance(item, Mapping)) else "fail"
        normalized = str(value).lower() if not isinstance(value, (int, float)) else value
        accepted = {str(item).lower() if not isinstance(item, (int, float)) else item for item in passing}
        return {"name": f"pr-{number}-{name}", "status": "pass" if normalized in accepted else "fail", "message": str(value)}

    def observe_plan(self, plan: MergePlan) -> dict[str, Any]:
        merged: list[int] = []
        closed: list[int] = []
        open_prs: list[int] = []
        for number in plan.selected_pull_requests:
            data = self.request("GET", f"repos/{self.repository}/pulls/{number}")
            if not isinstance(data, Mapping):
                continue
            if data.get("merged_at") or data.get("mergedAt") or data.get("state") == "merged":
                merged.append(number)
            elif data.get("state") == "closed":
                closed.append(number)
            else:
                open_prs.append(number)
        status = "merged" if len(merged) == len(plan.selected_pull_requests) else ("failed" if closed else "pending")
        return {"status": status, "merged_prs": merged, "closed_prs": closed, "open_prs": open_prs}

    def poll_queue(self, plan: MergePlan) -> dict[str, Any]:
        observed = self.observe_plan(plan)
        if observed["status"] == "merged":
            return {"status": "merged", "details": {"message": "all selected PRs merged from the queue"}, "observed": observed}
        if observed["closed_prs"]:
            return {
                "status": "failed",
                "details": {"message": f"merge queue ejected or closed PRs: {observed['closed_prs']}"},
                "observed": observed,
            }
        return {"status": "enqueued", "details": {"message": "merge queue is still processing"}, "observed": observed}


def _resolve_pr(client: GitHubStackMergeClient, repo_path: Path, pr: int | None, url: str | None, branch: str | None) -> int:
    return sync.resolve_pr_number(client, repo_path, pr, url, branch)


def _path(value: Path, repo_path: Path) -> Path:
    return value if value.is_absolute() else repo_path / value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely land native GitHub Stacked PRs through async Stack Merge.")
    parser.add_argument("--repo", required=True, help="GitHub repository OWNER/REPO")
    parser.add_argument("--repo-path", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=Path(".forge/stack.json"))
    parser.add_argument("--state", type=Path, default=Path(".forge/stack-merge.json"))
    parser.add_argument("--receipts", type=Path, default=Path(".forge/receipts.jsonl"))
    parser.add_argument("--api", choices=("rest", "graphql"), default="rest")
    parser.add_argument("--authority", choices=("local", "github"), default="local")
    parser.add_argument("--policy-profile", type=Path)
    parser.add_argument("--policy-approval")
    parser.add_argument("--policy-approvals", type=Path, default=Path(".forge/approvals.jsonl"))
    parser.add_argument("--policy-staged", action="store_true")
    parser.add_argument("--policy-principal")
    parser.add_argument("--merge-method", choices=("merge", "squash", "rebase"), default="merge")
    parser.add_argument("--merge-action", choices=("default", "direct_merge", "merge_queue"), default="default")
    parser.add_argument("--poll-attempts", type=int, default=10)
    parser.add_argument("--allow-unknown-readiness", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--url")
    parser.add_argument("--branch")
    parser.add_argument("--operation-id")
    parser.add_argument("--event", type=Path)
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="show the exact native merge preview")
    sub.add_parser("submit", help="submit or resume an approved native merge")
    sub.add_parser("poll", help="resume polling a persisted native merge request")
    sub.add_parser("queue-event", help="correlate a merge_group checks_requested payload")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_path = args.repo_path.resolve()
    state_path = _path(args.state, repo_path)
    receipts_path = _path(args.receipts, repo_path)
    try:
        if args.command == "queue-event":
            if not args.event:
                raise MergeError("queue-event requires --event JSON")
            event = json.loads(args.event.read_text(encoding="utf-8"))
            result = ingest_merge_group_event(state_path, receipts_path, event, operation_id=args.operation_id)
        else:
            manifest_path = _path(args.manifest, repo_path)
            manifest = sync.load_stack_manifest(manifest_path)
            client = GitHubStackMergeClient(args.repo)
            if args.command == "poll" and args.operation_id:
                state = _load_state(state_path, args.repo)
                record = state["requests"].get(args.operation_id)
                if not record:
                    raise MergeError(f"no native merge request {args.operation_id}")
                plan = MergePlan.from_mapping(record["plan"])
            else:
                target_pr = _resolve_pr(client, repo_path, args.pr, args.url, args.branch)
                try:
                    remote = client.stack_from_graphql(target_pr) if args.api == "graphql" else client.stack_for_pull_request(target_pr)
                except FeatureUnavailable as exc:
                    plan = MergePlan(0, target_pr, str(manifest.get("trunk") or "main"), "", (target_pr,), ("unknown",), args.merge_method, args.merge_action, {"status": "unknown"})
                    result = fallback_plan(plan, str(exc))
                    print(json.dumps(result, indent=2, sort_keys=True))
                    return 0
                plan = plan_merge(
                    manifest,
                    remote,
                    target_pr=target_pr,
                    merge_method=args.merge_method,
                    merge_action=args.merge_action,
                )
            if args.command == "plan":
                try:
                    readiness = client.preflight_plan(plan)
                except StackSyncError as exc:
                    readiness = {"status": "unknown", "checks": [], "message": str(exc)}
                result = {"status": "planned", "plan": MergePlan(**{**plan.__dict__, "readiness": dict(readiness)}).as_dict()}
            else:
                result = execute_merge(
                    client,
                    args.repo,
                    plan,
                    state_path,
                    receipts_path,
                    yes=args.yes or args.command == "poll",
                    authority=args.authority,
                    policy_profile=args.policy_profile,
                    policy_approval=args.policy_approval,
                    policy_staged=args.policy_staged,
                    policy_approvals_path=_path(args.policy_approvals, repo_path),
                    policy_principal=args.policy_principal,
                    workspace=repo_path,
                    poll_attempts=args.poll_attempts,
                    allow_unknown_readiness=args.allow_unknown_readiness,
                    allow_submit=args.command == "submit",
                )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, StackSyncError, MergeError, ValueError, json.JSONDecodeError) as exc:
        error = {"error": {"code": type(exc).__name__, "message": str(exc)}}
        print(json.dumps(error, indent=2) if args.json else f"forge-stack-merge: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
