#!/usr/bin/env python3
"""Inspect, import, and safely reconcile GitHub native Stacked PRs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

API_VERSION = "2022-11-28"
MAX_PAGES = 100
SCHEMA_VERSION = 1
MARKER_RE = re.compile(r"/pull/(\d+)(?:/|$)")


class StackSyncError(RuntimeError):
    """Raised for safe-to-report stack synchronization failures."""


class FeatureUnavailable(StackSyncError):
    """Raised when native Stacked PRs are not enabled for a repository."""


class ApiError(StackSyncError):
    def __init__(self, status: int, message: str, path: str) -> None:
        super().__init__(f"GitHub API {status} for {path}: {message}")
        self.status = status
        self.path = path


class ConflictError(StackSyncError):
    """Raised when an expected remote SHA or graph changed before apply."""


@dataclass(frozen=True)
class RemotePullRequest:
    number: int
    branch: str
    head_sha: str
    base_ref: str
    base_sha: str = ""
    state: str = "open"
    draft: bool = False
    merged_at: str | None = None

    def canonical(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "branch": self.branch,
            "head_sha": self.head_sha,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "state": self.state,
            "draft": self.draft,
            "merged_at": self.merged_at,
        }


@dataclass(frozen=True)
class RemoteStack:
    stack_id: int | str
    number: int
    node_id: str
    base_ref: str
    base_sha: str
    pull_requests: tuple[RemotePullRequest, ...]
    open: bool = True

    def canonical(self) -> dict[str, Any]:
        return {
            "id": self.stack_id,
            "number": self.number,
            "node_id": self.node_id,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "open": self.open,
            "pull_requests": [item.canonical() for item in self.pull_requests],
        }


@dataclass(frozen=True)
class Divergence:
    kind: str
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class Operation:
    action: str
    reason: str
    payload: dict[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        material = {"action": self.action, "reason": self.reason, "payload": self.payload}
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.key(), "action": self.action, "reason": self.reason, "payload": self.payload}


def parse_pull_request(data: Mapping[str, Any]) -> RemotePullRequest:
    head = data.get("head") or {}
    base = data.get("base") or {}
    return RemotePullRequest(
        number=int(data["number"]),
        branch=str(head.get("ref") or data.get("headRefName") or ""),
        head_sha=str(head.get("sha") or data.get("headRefOid") or ""),
        base_ref=str(base.get("ref") or data.get("baseRefName") or ""),
        base_sha=str(base.get("sha") or data.get("baseRefOid") or ""),
        state=str(data.get("state") or "open"),
        draft=bool(data.get("draft", data.get("isDraft", False))),
        merged_at=data.get("merged_at", data.get("mergedAt")),
    )


def remote_stack_from_rest(data: Mapping[str, Any], pull_requests: Mapping[int, RemotePullRequest]) -> RemoteStack:
    entries: list[RemotePullRequest] = []
    for item in data.get("pull_requests", []):
        number = int(item["number"])
        entry = pull_requests.get(number)
        if entry is None:
            entry = RemotePullRequest(
                number=number,
                branch=str((item.get("head") or {}).get("ref", "")),
                head_sha=str((item.get("head") or {}).get("sha", "")),
                base_ref="",
                state=str(item.get("state") or "open"),
                draft=bool(item.get("draft", False)),
                merged_at=item.get("merged_at"),
            )
        entries.append(entry)
    base = data.get("base") or {}
    return RemoteStack(
        stack_id=data.get("id", data.get("node_id", "")),
        number=int(data["number"]),
        node_id=str(data.get("node_id", "")),
        base_ref=str(base.get("ref", "")),
        base_sha=str(base.get("sha", "")),
        pull_requests=tuple(entries),
        open=bool(data.get("open", True)),
    )


def remote_stack_from_graphql(data: Mapping[str, Any]) -> RemoteStack | None:
    repository = data.get("data", {}).get("repository", {})
    pull_request = repository.get("pullRequest") or {}
    stack = pull_request.get("stack")
    if not stack:
        return None
    entries = []
    for node in stack.get("entries", {}).get("nodes", []):
        pr = node.get("pullRequest") or {}
        entries.append(
            RemotePullRequest(
                number=int(pr["number"]),
                branch=str(pr.get("headRefName", "")),
                head_sha=str(pr.get("headRefOid", "")),
                base_ref=str(pr.get("baseRefName", "")),
                base_sha=str(pr.get("baseRefOid", "")),
                state=str(pr.get("state", "OPEN")).lower(),
                draft=bool(pr.get("isDraft", False)),
                merged_at=pr.get("mergedAt"),
            )
        )
    entries.sort(key=lambda item: next((node.get("position", 0) for node in stack["entries"]["nodes"] if (node.get("pullRequest") or {}).get("number") == item.number), 0))
    return RemoteStack(
        stack_id=str(stack.get("id", "")),
        number=int(stack["number"]),
        node_id=str(stack.get("id", "")),
        base_ref=str(stack.get("baseRefName", "")),
        base_sha="",
        pull_requests=tuple(entries),
        open=True,
    )


class GitHubStackClient:
    """Small gh-backed client with bounded REST and GraphQL pagination."""

    def __init__(self, repository: str, executable: str = "gh") -> None:
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
            raise StackSyncError("repository must be OWNER/REPO")
        self.repository = repository
        self.executable = executable

    def request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        command = [
            self.executable,
            "api",
            path,
            "--method",
            method,
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            f"X-GitHub-Api-Version: {API_VERSION}",
        ]
        input_data = None
        if payload is not None:
            command.extend(["--input", "-"])
            input_data = json.dumps(payload)
        try:
            result = subprocess.run(command, input=input_data, capture_output=True, text=True, check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StackSyncError(f"GitHub CLI unavailable or timed out: {exc}") from exc
        if result.returncode:
            status = _error_status(result.stderr)
            message = result.stderr.strip() or result.stdout.strip() or "request failed"
            if status == 404 and "/stacks" in path:
                raise FeatureUnavailable("GitHub native Stacked PRs are unavailable for this repository")
            raise ApiError(status, message, path)
        if not result.stdout.strip():
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise StackSyncError(f"GitHub returned invalid JSON for {path}") from exc

    def graphql(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        command = [self.executable, "api", "graphql", "--raw-field", f"query={query}"]
        for key, value in variables.items():
            if value is None:
                continue
            flag = "--field" if isinstance(value, (int, float, bool)) else "--raw-field"
            command.extend([flag, f"{key}={str(value).lower() if isinstance(value, bool) else value}"])
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StackSyncError(f"GitHub CLI unavailable or timed out: {exc}") from exc
        if result.returncode:
            raise ApiError(_error_status(result.stderr), result.stderr.strip() or "GraphQL request failed", "graphql")
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise StackSyncError("GitHub GraphQL returned invalid JSON") from exc
        if data.get("errors"):
            raise ApiError(0, json.dumps(data["errors"], sort_keys=True), "graphql")
        return data

    def get_pull_request(self, number: int) -> RemotePullRequest:
        data = self.request("GET", f"repos/{self.repository}/pulls/{number}")
        if not isinstance(data, dict):
            raise StackSyncError("GitHub pull request response was not an object")
        return parse_pull_request(data)

    def find_pull_request(self, branch: str) -> RemotePullRequest | None:
        owner, _ = self.repository.split("/", 1)
        encoded = f"?state=all&head={owner}:{branch}&per_page=100&page=1"
        data = self.request("GET", f"repos/{self.repository}/pulls{encoded}")
        if not isinstance(data, list):
            raise StackSyncError("GitHub pull request response was not a list")
        return parse_pull_request(data[0]) if data else None

    def list_stacks(self, pull_request: int | None = None) -> list[dict[str, Any]]:
        stacks: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            query = f"?per_page=100&page={page}"
            if pull_request is not None:
                query += f"&pull_request={pull_request}"
            data = self.request("GET", f"repos/{self.repository}/stacks{query}")
            if not isinstance(data, list):
                raise StackSyncError("GitHub stacks response was not a list")
            stacks.extend(item for item in data if isinstance(item, dict))
            if len(data) < 100:
                return stacks
        raise StackSyncError("GitHub stack pagination exceeded 100 pages")

    def get_stack(self, number: int) -> dict[str, Any]:
        data = self.request("GET", f"repos/{self.repository}/stacks/{number}")
        if not isinstance(data, dict):
            raise StackSyncError("GitHub stack response was not an object")
        return data

    def stack_for_pull_request(self, number: int) -> RemoteStack | None:
        stacks = self.list_stacks(number)
        if not stacks:
            return None
        raw = stacks[0]
        pull_requests = {item.number: item for item in (self.get_pull_request(int(entry["number"])) for entry in raw.get("pull_requests", []))}
        return remote_stack_from_rest(raw, pull_requests)

    def stack_from_graphql(self, number: int) -> RemoteStack | None:
        owner, name = self.repository.split("/", 1)
        query = """
        query($owner:String!, $name:String!, $number:Int!, $after:String) {
          repository(owner:$owner, name:$name) {
            pullRequest(number:$number) {
              stack {
                id number size baseRefName
                entries(first:100, after:$after) {
                  nodes { position pullRequest { number state isDraft mergedAt headRefName headRefOid baseRefName baseRefOid } }
                  pageInfo { hasNextPage endCursor }
                }
              }
            }
          }
        }
        """
        first = self.graphql(query, {"owner": owner, "name": name, "number": number, "after": None})
        repository = first.get("data", {}).get("repository", {})
        stack = (repository.get("pullRequest") or {}).get("stack")
        if not stack:
            return None
        pages = list(stack.get("entries", {}).get("nodes", []))
        page_info = stack.get("entries", {}).get("pageInfo", {})
        while page_info.get("hasNextPage"):
            page = self.graphql(query, {"owner": owner, "name": name, "number": number, "after": page_info.get("endCursor")})
            next_stack = page.get("data", {}).get("repository", {}).get("pullRequest", {}).get("stack") or {}
            entries = next_stack.get("entries", {})
            pages.extend(entries.get("nodes", []))
            page_info = entries.get("pageInfo", {})
        normalized = {"data": {"repository": {"pullRequest": {"stack": {**stack, "entries": {"nodes": pages}}}}}}
        return remote_stack_from_graphql(normalized)

    def create_stack(self, pull_requests: list[int]) -> dict[str, Any]:
        data = self.request("POST", f"repos/{self.repository}/stacks", {"pull_requests": pull_requests})
        return data if isinstance(data, dict) else {}

    def append_stack(self, stack_number: int, pull_requests: list[int]) -> dict[str, Any]:
        data = self.request("POST", f"repos/{self.repository}/stacks/{stack_number}/add", {"pull_requests": pull_requests})
        return data if isinstance(data, dict) else {}

    def unstack(self, stack_number: int) -> dict[str, Any] | None:
        data = self.request("POST", f"repos/{self.repository}/stacks/{stack_number}/unstack")
        return data if isinstance(data, dict) else None

    def relink_pull_request(self, number: int, base: str) -> dict[str, Any]:
        data = self.request("PATCH", f"repos/{self.repository}/pulls/{number}", {"base": base})
        return data if isinstance(data, dict) else {}


def _error_status(message: str) -> int:
    match = re.search(r"(?:HTTP|status)\s*(\d{3})", message, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def load_stack_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StackSyncError(f"no stack manifest at {path}") from exc
    except json.JSONDecodeError as exc:
        raise StackSyncError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise StackSyncError(f"stack manifest at {path} must contain an object")
    return data


def local_pull_requests(manifest: Mapping[str, Any]) -> list[tuple[dict[str, Any], int]]:
    return [(branch, int(branch["pr"])) for branch in manifest.get("branches", []) if branch.get("pr")]


def classify_divergence(manifest: Mapping[str, Any], remote: RemoteStack | None) -> Divergence:
    local = local_pull_requests(manifest)
    local_numbers = [number for _, number in local]
    remote_numbers = [item.number for item in remote.pull_requests] if remote else []
    if not local_numbers and not remote_numbers:
        return Divergence("compatible")
    if not remote_numbers:
        return Divergence("local-only", ("local manifest has pull requests but GitHub has no native stack",))
    if not local_numbers:
        return Divergence("remote-only", ("GitHub has a native stack but the local manifest has no PR mappings",))
    shared = min(len(local_numbers), len(remote_numbers))
    if local_numbers[:shared] != remote_numbers[:shared]:
        return Divergence("conflicting", ("pull request order differs",))
    if len(local_numbers) < len(remote_numbers):
        return Divergence("remote-only", ("GitHub contains stack entries missing from the local manifest",))
    if len(local_numbers) > len(remote_numbers):
        return Divergence("local-only", ("local manifest contains pull requests missing from GitHub",))
    reasons: list[str] = []
    for branch, number in local:
        remote_pr = next(item for item in remote.pull_requests if item.number == number)
        metadata = branch.get("github", {})
        if branch["name"] != remote_pr.branch:
            reasons.append(f"PR #{number} branch changed from {branch['name']} to {remote_pr.branch}")
        expected_sha = metadata.get("head_sha")
        if expected_sha and expected_sha != remote_pr.head_sha:
            reasons.append(f"PR #{number} head SHA changed")
    return Divergence("conflicting" if reasons else "compatible", tuple(reasons))


def import_manifest(manifest: Mapping[str, Any], remote: RemoteStack) -> dict[str, Any]:
    imported = {
        "version": SCHEMA_VERSION,
        "provider": "github",
        "trunk": remote.base_ref,
        "remote": manifest.get("remote", "origin"),
        "github_stack": {
            "id": remote.stack_id,
            "number": remote.number,
            "node_id": remote.node_id,
            "base_ref": remote.base_ref,
            "base_sha": remote.base_sha,
        },
        "branches": [],
    }
    parent = remote.base_ref
    for position, pull_request in enumerate(remote.pull_requests, start=1):
        base = pull_request.base_ref or parent
        branch = {
            "name": pull_request.branch,
            "parent": base,
            "pr": pull_request.number,
            "github": {
                "stack_number": remote.number,
                "position": position,
                "head_sha": pull_request.head_sha,
                "base_ref": base,
                "base_sha": pull_request.base_sha,
            },
        }
        imported["branches"].append(branch)
        parent = pull_request.branch
    return imported


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def plan_reconciliation(
    manifest: Mapping[str, Any], remote: RemoteStack | None, *, unstack: bool = False
) -> list[Operation]:
    local = local_pull_requests(manifest)
    local_numbers = [number for _, number in local]
    if remote is None:
        if len(local_numbers) >= 2:
            return [Operation("create_stack", "local manifest has no native stack", {"pull_requests": local_numbers})]
        return []
    remote_numbers = [item.number for item in remote.pull_requests]
    if local_numbers == remote_numbers:
        operations: list[Operation] = []
        for branch, number in local:
            remote_pr = next(item for item in remote.pull_requests if item.number == number)
            expected = branch.get("github", {}).get("head_sha")
            if expected and expected != remote_pr.head_sha:
                operations.append(Operation("conflict", f"PR #{number} head SHA changed since import", {"pr": number, "expected_head_sha": expected, "actual_head_sha": remote_pr.head_sha}))
            if branch["parent"] != remote_pr.base_ref and remote_pr.base_ref:
                operations.append(Operation("relink_pr", f"PR #{number} base differs from local manifest", {"pr": number, "base": branch["parent"], "expected_base": remote_pr.base_ref, "expected_head_sha": remote_pr.head_sha}))
        return operations
    if remote_numbers == local_numbers[: len(remote_numbers)] and len(local_numbers) > len(remote_numbers):
        additions = local_numbers[len(remote_numbers) :]
        top = remote.pull_requests[-1]
        return [Operation("append_stack", "local manifest extends the native stack", {"stack_number": remote.number, "pull_requests": additions, "expected_top_pr": top.number, "expected_top_sha": top.head_sha})]
    if local_numbers == remote_numbers[: len(local_numbers)] and len(remote_numbers) > len(local_numbers):
        if unstack:
            return [Operation("unstack", "explicitly dissolve the remote stack", {"stack_number": remote.number, "expected_pull_requests": remote_numbers, "expected_head_shas": [item.head_sha for item in remote.pull_requests]})]
        return [Operation("conflict", "remote stack contains entries absent from local manifest; pass --unstack to dissolve", {"remote_pull_requests": remote_numbers})]
    return [Operation("conflict", "local and remote stack order diverged", {"local_pull_requests": local_numbers, "remote_pull_requests": remote_numbers})]


def resolve_pr_number(client: GitHubStackClient, repo: Path, pr: int | None, url: str | None, branch: str | None) -> int:
    if pr is not None:
        return pr
    if url:
        match = MARKER_RE.search(url)
        if not match:
            raise StackSyncError("PR URL must contain /pull/<number>")
        return int(match.group(1))
    selected_branch = branch
    if not selected_branch:
        result = subprocess.run(["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True, check=False)
        selected_branch = result.stdout.strip()
    if not selected_branch:
        raise StackSyncError("pass --pr, --url, or --branch from a named checkout")
    pull_request = client.find_pull_request(selected_branch)
    if pull_request is None:
        raise StackSyncError(f"no GitHub pull request found for branch {selected_branch}")
    return pull_request.number


def record_receipt(path: Path, repository: str, operation: Operation, result: Mapping[str, Any]) -> None:
    module_path = Path(__file__).resolve().parents[2] / "observability" / "scripts" / "forge-receipts.py"
    spec = importlib.util.spec_from_file_location("forge_receipts", module_path)
    if spec is None or spec.loader is None:
        raise StackSyncError("could not load Forge receipt store")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.ReceiptStore(path).append(
        module.make_event(
            "tool.called",
            f"github-stack-sync:{repository}",
            idempotency_key=f"forge-stack-sync:{operation.key()}",
            attributes={"stack_action": operation.action, "stack_status": "applied", "result": dict(result)},
        )
    )


def apply_operations(
    client: GitHubStackClient,
    repository: str,
    operations: list[Operation],
    state_path: Path,
    receipts_path: Path,
    *,
    yes: bool,
    authority: str,
) -> list[dict[str, Any]]:
    if authority != "local":
        raise StackSyncError("only local authority may apply native stack mutations")
    if not yes:
        raise StackSyncError("apply requires explicit --yes")
    if any(operation.action == "conflict" for operation in operations):
        raise ConflictError("conflicts must be resolved before apply")
    state = {"schema_version": 1, "repository": repository, "completed_operations": []}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    completed = set(state.get("completed_operations", []))
    results = []
    for operation in operations:
        if operation.key() in completed:
            results.append({"operation": operation.as_dict(), "status": "already-complete"})
            continue
        result = apply_one(client, operation)
        completed.add(operation.key())
        state["completed_operations"] = sorted(completed)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        record_receipt(receipts_path, repository, operation, result)
        results.append({"operation": operation.as_dict(), "status": "applied", "result": result})
    return results


def apply_one(client: GitHubStackClient, operation: Operation) -> dict[str, Any]:
    payload = operation.payload
    if operation.action == "create_stack":
        current = client.stack_for_pull_request(int(payload["pull_requests"][0]))
        if current:
            if [item.number for item in current.pull_requests] == payload["pull_requests"]:
                return {"stack_number": current.number, "recovered": True}
            raise ConflictError("the first pull request already belongs to a different stack")
        response = client.create_stack(payload["pull_requests"])
        return {"stack_number": response.get("number"), "created": True}
    if operation.action == "append_stack":
        # Re-fetch remote state before each mutation so a stale plan cannot overwrite drift.
        current = client.get_stack(int(payload["stack_number"]))
        current_numbers = [int(item["number"]) for item in current.get("pull_requests", [])]
        additions = [int(item) for item in payload["pull_requests"]]
        if current_numbers[-len(additions) :] == additions:
            return {"stack_number": payload["stack_number"], "appended": additions, "recovered": True}
        top = next((item for item in current.get("pull_requests", []) if int(item["number"]) == int(payload["expected_top_pr"])), None)
        actual_sha = ((top or {}).get("head") or {}).get("sha")
        if actual_sha and actual_sha != payload["expected_top_sha"]:
            raise ConflictError("stack top SHA changed before append")
        response = client.append_stack(int(payload["stack_number"]), list(payload["pull_requests"]))
        return {"stack_number": response.get("number", payload["stack_number"]), "appended": payload["pull_requests"]}
    if operation.action == "relink_pr":
        current = client.get_pull_request(int(payload["pr"]))
        if current.head_sha != payload["expected_head_sha"]:
            raise ConflictError(f"PR #{payload['pr']} head SHA changed before relink")
        if current.base_ref != payload["expected_base"]:
            raise ConflictError(f"PR #{payload['pr']} base changed before relink")
        response = client.relink_pull_request(int(payload["pr"]), str(payload["base"]))
        return {"pr": payload["pr"], "base": response.get("base", {}).get("ref", payload["base"])}
    if operation.action == "unstack":
        current = client.get_stack(int(payload["stack_number"]))
        current_numbers = [int(item["number"]) for item in current.get("pull_requests", [])]
        if current_numbers != payload["expected_pull_requests"]:
            raise ConflictError("stack membership changed before unstack")
        current_shas = [str((item.get("head") or {}).get("sha", "")) for item in current.get("pull_requests", [])]
        if payload.get("expected_head_shas") and current_shas != payload["expected_head_shas"]:
            raise ConflictError("stack head SHAs changed before unstack")
        client.unstack(int(payload["stack_number"]))
        return {"stack_number": payload["stack_number"], "unstacked": True}
    raise StackSyncError(f"unsupported operation: {operation.action}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconcile Forge manifests with GitHub native Stacked PRs.")
    parser.add_argument("--repo", default="", help="GitHub repository OWNER/REPO")
    parser.add_argument("--repo-path", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=Path(".forge/stack.json"))
    parser.add_argument("--state", type=Path, default=Path(".forge/stack-sync.json"))
    parser.add_argument("--receipts", type=Path, default=Path(".forge/receipts.jsonl"))
    parser.add_argument("--api", choices=("rest", "graphql"), default="rest")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--authority", choices=("local", "github"), default="local")
    target = argparse.ArgumentParser(add_help=False)
    target.add_argument("--repo", default=argparse.SUPPRESS)
    target.add_argument("--repo-path", type=Path, default=argparse.SUPPRESS)
    target.add_argument("--manifest", type=Path, default=argparse.SUPPRESS)
    target.add_argument("--state", type=Path, default=argparse.SUPPRESS)
    target.add_argument("--receipts", type=Path, default=argparse.SUPPRESS)
    target.add_argument("--api", choices=("rest", "graphql"), default=argparse.SUPPRESS)
    target.add_argument("--authority", choices=("local", "github"), default=argparse.SUPPRESS)
    target.add_argument("--pr", type=int)
    target.add_argument("--url")
    target.add_argument("--branch")
    target.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", parents=[target], help="inspect a stack from a PR, URL, branch, or checkout")
    inspect.add_argument("--include-local", action="store_true")
    sub.add_parser("import", parents=[target], help="import the remote stack into a local manifest").add_argument("--write", action="store_true")
    plan = sub.add_parser("plan", parents=[target], help="show reconciliation operations")
    plan.add_argument("--unstack", action="store_true")
    apply = sub.add_parser("apply", parents=[target], help="apply a local-authority reconciliation plan")
    apply.add_argument("--yes", action="store_true")
    apply.add_argument("--unstack", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.repo:
            raise StackSyncError("pass --repo OWNER/REPO")
        manifest_path = args.manifest if args.manifest.is_absolute() else args.repo_path / args.manifest
        if manifest_path.exists():
            manifest = load_stack_manifest(manifest_path)
        elif args.command in {"inspect", "import"}:
            manifest = {"version": SCHEMA_VERSION, "provider": "github", "trunk": "main", "remote": "origin", "branches": []}
        else:
            manifest = load_stack_manifest(manifest_path)
        client = GitHubStackClient(args.repo)
        number = resolve_pr_number(client, args.repo_path, args.pr, args.url, args.branch)
        try:
            remote = client.stack_from_graphql(number) if args.api == "graphql" else client.stack_for_pull_request(number)
        except FeatureUnavailable as exc:
            if args.command == "apply":
                raise
            result = {"status": "fallback", "fallback": True, "target_pr": number, "reason": str(exc)}
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "inspect":
            result: dict[str, Any] = {"status": "native-stack" if remote else "standalone", "fallback": remote is None, "target_pr": number, "remote": remote.canonical() if remote else None}
            if args.include_local:
                result["local"] = manifest
                result["divergence"] = classify_divergence(manifest, remote).as_dict()
        elif args.command == "import":
            if remote is None:
                result = {"status": "fallback", "written": False, "reason": "PR is not in a native stack"}
            else:
                imported = import_manifest(manifest, remote)
                if args.write:
                    write_manifest(manifest_path, imported)
                result = {"status": "imported", "written": bool(args.write), "manifest": imported}
        else:
            operations = plan_reconciliation(manifest, remote, unstack=args.unstack)
            result = {"authority": args.authority, "operations": [operation.as_dict() for operation in operations]}
            if args.command == "apply":
                result["results"] = apply_operations(client, args.repo, operations, args.state, args.receipts, yes=args.yes, authority=args.authority)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, StackSyncError, ValueError, json.JSONDecodeError) as exc:
        error = {"error": {"code": type(exc).__name__, "message": str(exc)}}
        print(json.dumps(error, indent=2) if args.json else f"forge-stack-sync: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
