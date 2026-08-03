#!/usr/bin/env python3
"""Synchronize Forge Markdown tasks with native GitHub Issues relationships."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MARKER_RE = re.compile(r"<!-- forge-task:v1 id=(\S+?)(?: sync=([0-9a-f]{64}))? -->")
STATUS_RE = re.compile(r"^Status:\s*`?([A-Za-z-]+)`?\s*$", re.MULTILINE | re.IGNORECASE)
ASSIGNED_RE = re.compile(r"^Assigned:\s*([^@\n]+?)(?:\s*@\s*(\S+))?\s*$", re.MULTILINE)
MODEL_RE = re.compile(r"^Model:\s*`?(\S+?)`?\s*$", re.MULTILINE | re.IGNORECASE)
DEPENDS_RE = re.compile(r"^Depends on:\s*(.*?)\s*$", re.MULTILINE | re.IGNORECASE)
PARENT_RE = re.compile(r"^Parent:\s*(\S+)\s*$", re.MULTILINE | re.IGNORECASE)
RELEASE_RE = re.compile(r"^Release:\s*(\S+)\s*$", re.MULTILINE | re.IGNORECASE)
STATUSES = {"backlog", "ready", "in-progress", "review", "done", "blocked"}
SCHEMA_VERSION = 1


class SyncError(RuntimeError):
    """Raised for a safe-to-report synchronization failure."""


class ApiError(SyncError):
    def __init__(self, status: int, message: str, path: str) -> None:
        super().__init__(f"GitHub API {status} for {path}: {message}")
        self.status = status
        self.path = path


@dataclass
class Task:
    task_id: str
    title: str
    status: str
    agent: str
    model: str
    depends_on: list[str]
    parent: str | None
    release: str | None
    goal: str
    acceptance: list[str]
    context: str
    notes: str
    source_path: Path | None = None
    sync_hash: str | None = None

    def canonical(self) -> dict[str, Any]:
        return {
            "id": self.task_id,
            "title": self.title.strip(),
            "status": self.status,
            "agent": self.agent.strip(),
            "model": self.model.strip(),
            "depends_on": sorted(self.depends_on),
            "parent": self.parent,
            "release": self.release,
            "goal": self.goal.strip(),
            "acceptance": [item.strip() for item in self.acceptance],
            "context": self.context.strip(),
            "notes": self.notes.strip(),
        }

    def content_hash(self) -> str:
        payload = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class RemoteIssue:
    number: int
    issue_id: int
    title: str
    body: str
    state: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RemoteTask:
    issue: RemoteIssue
    task: Task
    sync_hash: str | None
    sub_issue_ids: set[int] = field(default_factory=set)
    blocked_by_ids: set[int] = field(default_factory=set)


@dataclass
class Operation:
    action: str
    task_id: str | None
    reason: str
    issue_number: int | None = None
    target_task_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        material = {
            "action": self.action,
            "task_id": self.task_id,
            "issue_number": self.issue_number,
            "target_task_id": self.target_task_id,
            "payload": self.payload,
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.key(),
            "action": self.action,
            "task_id": self.task_id,
            "target_task_id": self.target_task_id,
            "issue_number": self.issue_number,
            "reason": self.reason,
            "payload": self.payload,
        }


def parse_frontmatter(text: str) -> tuple[dict[str, str], str, str | None]:
    marker = MARKER_RE.search(text)
    sync_hash = marker.group(2) if marker else None
    if not text.startswith("---\n"):
        return {}, text, sync_hash
    end = text.find("\n---", 4)
    if end == -1:
        raise SyncError("task frontmatter is not closed")
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip('"')
    return fields, text[end + 4 :], sync_hash


def section(body: str, heading: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)",
        body,
        re.MULTILINE | re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def acceptance_items(text: str) -> list[str]:
    return [
        re.sub(r"^[-*]\s+\[[ xX]\]\s*", "", line).strip()
        for line in text.splitlines()
        if re.match(r"^[-*]\s+\[[ xX]\]", line)
    ]


def parse_task_file(path: Path) -> Task:
    fields, body, sync_hash = parse_frontmatter(path.read_text(encoding="utf-8"))
    task_id = fields.get("id", path.stem.split("-", 1)[0])
    status = fields.get("status", "backlog")
    if status not in STATUSES:
        raise SyncError(f"{path}: unsupported task status {status}")
    deps = fields.get("depends_on", "[]").strip("[] ")
    depends_on = [item.strip() for item in deps.split(",") if item.strip()]
    goal = section(body, "Goal")
    acceptance = acceptance_items(section(body, "Acceptance criteria"))
    return Task(
        task_id=task_id,
        title=fields.get("title", path.stem),
        status=status,
        agent=fields.get("agent", ""),
        model=fields.get("model", ""),
        depends_on=depends_on,
        parent=fields.get("parent") or None,
        release=fields.get("release") or None,
        goal=goal,
        acceptance=acceptance,
        context=section(body, "Context"),
        notes=section(body, "Notes"),
        source_path=path,
        sync_hash=sync_hash,
    )


def parse_remote_task(issue: RemoteIssue) -> tuple[Task, str | None] | None:
    marker = MARKER_RE.search(issue.body)
    if not marker:
        return None
    task_id, sync_hash = marker.group(1), marker.group(2)
    status_match = STATUS_RE.search(issue.body)
    status = status_match.group(1).lower() if status_match else ("done" if issue.state == "closed" else "ready")
    assigned = ASSIGNED_RE.search(issue.body)
    model_match = MODEL_RE.search(issue.body)
    deps_match = DEPENDS_RE.search(issue.body)
    depends_on = []
    if deps_match and deps_match.group(1).strip() not in {"", "-", "none"}:
        depends_on = [item.strip().strip("`") for item in deps_match.group(1).split(",")]
    parent_match = PARENT_RE.search(issue.body)
    release_match = RELEASE_RE.search(issue.body)
    parent = parent_match.group(1) if parent_match and parent_match.group(1) != "-" else None
    release = release_match.group(1) if release_match and release_match.group(1) != "-" else None
    task = Task(
        task_id=task_id,
        title=issue.title,
        status=status if status in STATUSES else "backlog",
        agent=assigned.group(1).strip() if assigned else "",
        model=(assigned.group(2) if assigned and assigned.group(2) else model_match.group(1) if model_match else ""),
        depends_on=depends_on,
        parent=parent,
        release=release,
        goal=section(issue.body, "Goal"),
        acceptance=acceptance_items(section(issue.body, "Acceptance criteria")),
        context=section(issue.body, "Context"),
        notes=section(issue.body, "Notes"),
        sync_hash=sync_hash,
    )
    return task, sync_hash


def render_local(task: Task, sync_hash: str | None = None) -> str:
    deps = "[" + ", ".join(task.depends_on) + "]"
    parent = f"parent: {task.parent}\n" if task.parent else ""
    release = f"release: {task.release}\n" if task.release else ""
    marker = f"<!-- forge-task:v1 id={task.task_id}"
    if sync_hash:
        marker += f" sync={sync_hash}"
    marker += " -->"
    acceptance = "\n".join(f"- [ ] {item}" for item in task.acceptance) or "- [ ] Define acceptance criteria"
    return f"""---
id: {task.task_id}
title: {task.title}
status: {task.status}
agent: {task.agent}
model: {task.model}
depends_on: {deps}
{parent}{release}---
{marker}

## Goal
{task.goal}

## Acceptance criteria
{acceptance}

## Context
{task.context}

## Notes
{task.notes}
"""


def render_remote(task: Task, sync_hash: str) -> str:
    deps = ", ".join(f"`{item}`" for item in task.depends_on) or "-"
    assigned = task.agent or "unassigned"
    model = task.model or "unspecified"
    parent = task.parent or "-"
    release = task.release or "-"
    acceptance = "\n".join(f"- [ ] {item}" for item in task.acceptance) or "- [ ] Define acceptance criteria"
    return f"""<!-- forge-task:v1 id={task.task_id} sync={sync_hash} -->

Status: `{task.status}`
Assigned: {assigned} @ {model}
Depends on: {deps}
Parent: {parent}
Release: {release}

## Goal
{task.goal}

## Acceptance criteria
{acceptance}

## Context
{task.context}

## Notes
{task.notes}
"""


def load_tasks(tasks_dir: Path) -> list[Task]:
    if not tasks_dir.exists():
        return []
    tasks = [parse_task_file(path) for path in sorted(tasks_dir.glob("*.md")) if path.name != "README.md"]
    ids = [task.task_id for task in tasks]
    if len(ids) != len(set(ids)):
        raise SyncError("duplicate Forge task IDs in local ledger")
    known = set(ids)
    for task in tasks:
        unknown = sorted(set(task.depends_on) - known)
        if task.parent and task.parent not in known:
            unknown.append(task.parent)
        if unknown:
            raise SyncError(f"task {task.task_id} references unknown task(s): {', '.join(unknown)}")
    return tasks


class GitHubClient:
    """Small gh-backed client with bounded pagination and structured failures."""

    def __init__(self, repository: str, executable: str = "gh") -> None:
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
            raise SyncError("repository must be OWNER/REPO")
        self.repository = repository
        self.executable = executable

    def request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        command = [self.executable, "api", path, "--method", method, "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2022-11-28"]
        input_data = None
        if payload is not None:
            command.extend(["--input", "-"])
            input_data = json.dumps(payload)
        try:
            result = subprocess.run(command, input=input_data, capture_output=True, text=True, check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SyncError(f"GitHub CLI unavailable or timed out: {exc}") from exc
        if result.returncode:
            status = 0
            match = re.search(r"HTTP (\d+)", result.stderr)
            if match:
                status = int(match.group(1))
            message = result.stderr.strip() or result.stdout.strip() or "request failed"
            raise ApiError(status, message, path)
        try:
            return json.loads(result.stdout) if result.stdout.strip() else None
        except json.JSONDecodeError as exc:
            raise SyncError(f"GitHub returned invalid JSON for {path}") from exc

    def repository_metadata(self) -> dict[str, Any]:
        data = self.request("GET", f"repos/{self.repository}")
        if not isinstance(data, dict):
            raise SyncError("GitHub repository metadata was not an object")
        return data

    def list_issues(self) -> list[RemoteIssue]:
        issues: list[RemoteIssue] = []
        for page in range(1, 101):
            data = self.request("GET", f"repos/{self.repository}/issues?state=all&per_page=100&page={page}")
            if not isinstance(data, list):
                raise SyncError("GitHub issues response was not a list")
            for item in data:
                if "pull_request" in item:
                    continue
                issues.append(
                    RemoteIssue(
                        number=int(item["number"]),
                        issue_id=int(item["id"]),
                        title=item.get("title", ""),
                        body=item.get("body") or "",
                        state=item.get("state", "open"),
                        raw=item,
                    )
                )
            if len(data) < 100:
                return issues
        raise SyncError("GitHub issue pagination exceeded 100 pages; refusing an unbounded scan")

    def _list_paginated(self, path: str) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for page in range(1, 101):
            data = self.request("GET", f"{path}?per_page=100&page={page}")
            if not isinstance(data, list):
                raise SyncError(f"GitHub response was not a list for {path}")
            values.extend(item for item in data if isinstance(item, dict))
            if len(data) < 100:
                return values
        raise SyncError(f"GitHub pagination exceeded 100 pages for {path}; refusing an unbounded scan")

    def list_sub_issues(self, issue_number: int) -> list[dict[str, Any]]:
        return self._list_paginated(f"repos/{self.repository}/issues/{issue_number}/sub_issues")

    def list_blocked_by(self, issue_number: int) -> list[dict[str, Any]]:
        return self._list_paginated(f"repos/{self.repository}/issues/{issue_number}/dependencies/blocked_by")

    def create_issue(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = self.request("POST", f"repos/{self.repository}/issues", payload)
        if not isinstance(data, dict) or "number" not in data:
            raise SyncError("GitHub create issue response was invalid")
        return data

    def update_issue(self, issue_number: int, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = self.request("PATCH", f"repos/{self.repository}/issues/{issue_number}", payload)
        if not isinstance(data, dict):
            raise SyncError("GitHub update issue response was invalid")
        return data

    def add_sub_issue(self, parent_number: int, child_issue_id: int) -> None:
        self.request("POST", f"repos/{self.repository}/issues/{parent_number}/sub_issues", {"sub_issue_id": child_issue_id})

    def add_blocked_by(self, issue_number: int, blocking_issue_id: int) -> None:
        self.request("POST", f"repos/{self.repository}/issues/{issue_number}/dependencies/blocked_by", {"issue_id": blocking_issue_id})


class SyncEngine:
    def __init__(
        self,
        tasks: list[Task],
        client: Any,
        state_path: Path,
        repository: str,
        receipts_path: Path | None = None,
        *,
        policy_profile: Path | None = None,
        policy_approval: str | None = None,
        policy_staged: bool = False,
        policy_approvals_path: Path | None = None,
        policy_principal: str | None = None,
        workspace: Path | None = None,
    ) -> None:
        self.tasks = tasks
        self.client = client
        self.state_path = state_path
        self.repository = repository
        self.receipts_path = receipts_path or state_path.with_name("receipts.jsonl")
        self.policy_profile = policy_profile
        self.policy_approval = policy_approval
        self.policy_staged = policy_staged
        self.policy_error_type: Any = None
        self.policy = self._load_policy_session(
            policy_profile,
            policy_approvals_path=policy_approvals_path,
            policy_principal=policy_principal,
            workspace=workspace,
        )
        self.state = load_state(state_path)
        self.remote: dict[str, RemoteTask] = {}
        self.remote_by_issue: dict[int, RemoteTask] = {}
        self.missing_saved_issues: dict[str, int] = {}

    def _load_policy_session(
        self,
        profile_path: Path | None,
        *,
        policy_approvals_path: Path | None,
        policy_principal: str | None,
        workspace: Path | None,
    ) -> Any:
        if profile_path is None:
            return None
        module_path = Path(__file__).resolve().parents[2] / "policy" / "scripts" / "forge-policy.py"
        spec = importlib.util.spec_from_file_location("forge_policy", module_path)
        if spec is None or spec.loader is None:
            raise SyncError("could not load Forge policy engine")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.policy_error_type = module.PolicyError
        try:
            return module.PolicySession(
                profile_path,
                approvals_path=policy_approvals_path or self.state_path.with_name("approvals.jsonl"),
                receipts_path=self.receipts_path,
                principal=policy_principal,
                workspace=workspace or Path.cwd(),
            )
        except module.PolicyError as exc:
            raise SyncError(str(exc)) from exc

    def _authorize_policy(self, operation: Operation) -> Any:
        if self.policy is None:
            if self.policy_staged:
                raise SyncError("--policy-staged requires --policy-profile")
            return None
        paths = operation.payload.get("paths", [])
        if isinstance(paths, str):
            paths = [paths]
        if not isinstance(paths, list):
            paths = []
        branch = operation.payload.get("branch")
        branch = branch if isinstance(branch, str) else "main"
        action = self.policy.action(
            action_id=f"forge-tasks:{operation.key()}",
            tool="forge-tasks.apply",
            arguments=operation.as_dict(),
            repository=self.repository,
            branch=branch,
            paths=[str(path) for path in paths],
            domains=["github.com"],
            effect="github_issue_write",
            risk="high",
            fan_out=1,
        )
        try:
            return self.policy.authorize(action, approval_id=self.policy_approval, staged=self.policy_staged)
        except Exception as exc:
            if self.policy_error_type is not None and isinstance(exc, self.policy_error_type):
                raise SyncError(str(exc)) from exc
            raise

    def discover(self) -> None:
        metadata = self.client.repository_metadata()
        full_name = metadata.get("full_name")
        if full_name and full_name.lower() != self.repository.lower():
            raise SyncError(f"repository was renamed to {full_name}; update --repo and retry")
        issues = self.client.list_issues()
        by_id: dict[str, RemoteIssue] = {}
        for issue in issues:
            parsed = parse_remote_task(issue)
            if parsed:
                task, sync_hash = parsed
                if task.task_id in by_id:
                    raise SyncError(f"duplicate remote Forge task marker: {task.task_id}")
                by_id[task.task_id] = issue
        for task in self.tasks:
            issue = by_id.get(task.task_id)
            if not issue:
                saved = self.state.get("tasks", {}).get(task.task_id, {})
                issue_number = saved.get("issue")
                if issue_number:
                    self.missing_saved_issues[task.task_id] = int(issue_number)
                if issue_number:
                    issue = next((item for item in issues if item.number == issue_number), None)
            if not issue:
                continue
            parsed = parse_remote_task(issue)
            if not parsed:
                continue
            remote_task, sync_hash = parsed
            sub_ids = {int(item["id"]) for item in self.client.list_sub_issues(issue.number)}
            blocked_ids = {int(item["id"]) for item in self.client.list_blocked_by(issue.number)}
            record = RemoteTask(issue, remote_task, sync_hash, sub_ids, blocked_ids)
            self.remote[task.task_id] = record
            self.remote_by_issue[issue.number] = record

    def plan(self) -> list[Operation]:
        operations: list[Operation] = []
        for task in self.tasks:
            remote = self.remote.get(task.task_id)
            current_hash = task.content_hash()
            if remote is None:
                previous_issue = self.missing_saved_issues.get(task.task_id)
                operations.append(
                    Operation(
                        "create_issue",
                        task.task_id,
                        (
                            f"previous mapped issue #{previous_issue} is missing; recreate managed issue"
                            if previous_issue
                            else "no managed GitHub issue exists"
                        ),
                        payload={"title": task.title, "body": render_remote(task, current_hash), "state": issue_state(task)},
                    )
                )
                continue
            baseline = task.sync_hash or remote.sync_hash
            local_changed = bool(baseline and current_hash != baseline)
            remote_changed = bool(baseline and remote.task.content_hash() != baseline)
            if not baseline and current_hash != remote.task.content_hash():
                operations.append(Operation("conflict", task.task_id, "both local and remote state lack a shared sync baseline", issue_number=remote.issue.number))
            elif local_changed and remote_changed and current_hash != remote.task.content_hash():
                operations.append(Operation("conflict", task.task_id, "local and remote edits diverged from the last shared baseline", issue_number=remote.issue.number))
            elif current_hash != remote.task.content_hash():
                action = "update_issue"
                if issue_state(task) == "closed" and remote.issue.state != "closed":
                    action = "close_issue"
                elif issue_state(task) == "open" and remote.issue.state == "closed":
                    action = "reopen_issue"
                operations.append(
                    Operation(
                        action,
                        task.task_id,
                        "local task content changed",
                        issue_number=remote.issue.number,
                        payload={"title": task.title, "body": render_remote(task, current_hash), "state": issue_state(task)},
                    )
                )
            elif remote.issue.state != issue_state(task):
                operations.append(
                    Operation(
                        "close_issue" if issue_state(task) == "closed" else "reopen_issue",
                        task.task_id,
                        "local task status changed",
                        issue_number=remote.issue.number,
                        payload={"state": issue_state(task)},
                    )
                )

        issue_ids = {task_id: record.issue.issue_id for task_id, record in self.remote.items()}
        for task in self.tasks:
            child = self.remote.get(task.task_id)
            child_issue_id = issue_ids.get(task.task_id)
            if task.parent and child and child_issue_id:
                parent = self.remote.get(task.parent)
                if parent and child_issue_id not in parent.sub_issue_ids:
                    operations.append(Operation("add_sub_issue", task.task_id, "parent relationship missing", parent.issue.number, task.parent))
            for dependency in task.depends_on:
                dependent = self.remote.get(task.task_id)
                blocker = self.remote.get(dependency)
                if dependent and blocker and blocker.issue.issue_id not in dependent.blocked_by_ids:
                    operations.append(Operation("add_blocked_by", task.task_id, "blocked-by relationship missing", dependent.issue.number, dependency))
        return operations

    def apply(self, operations: list[Operation], confirm: bool = False) -> list[dict[str, Any]]:
        if not confirm and not self.policy_staged:
            raise SyncError("apply requires explicit --yes")
        if self.policy_staged and self.policy is None:
            raise SyncError("--policy-staged requires --policy-profile")
        if any(operation.action == "conflict" for operation in operations):
            raise SyncError("conflicts must be resolved before apply")
        completed = set(self.state.get("completed_operations", []))
        task_issues = {task_id: data.get("issue") for task_id, data in self.state.get("tasks", {}).items()}
        results: list[dict[str, Any]] = []
        for operation in operations:
            if operation.key() in completed:
                results.append({"operation": operation.as_dict(), "status": "already-complete"})
                continue
            authorization = self._authorize_policy(operation)
            if authorization is not None and authorization.status == "staged":
                results.append({"operation": operation.as_dict(), "status": "staged", "policy": authorization.as_dict()})
                continue
            if authorization is not None and authorization.effective_action != authorization.action:
                raise SyncError("policy transform is not supported by the task-ledger adapter")
            result = self.apply_one(operation, task_issues, before_effect=self._policy_guard(authorization))
            if authorization is not None:
                try:
                    self.policy.commit(authorization, result)
                except Exception as exc:
                    if self.policy_error_type is not None and isinstance(exc, self.policy_error_type):
                        raise SyncError(str(exc)) from exc
                    raise
            completed.add(operation.key())
            self.state.setdefault("completed_operations", []).append(operation.key())
            self.state.setdefault("tasks", {}).setdefault(operation.task_id or "", {})["issue"] = task_issues.get(operation.task_id or "")
            self.state["repository"] = self.repository
            save_state(self.state_path, self.state)
            self.record_receipt(operation, result)
            results.append({"operation": operation.as_dict(), "status": "applied", "result": result})
        return results

    def record_receipt(self, operation: Operation, result: Mapping[str, Any]) -> None:
        """Record a redacted, idempotent evidence event for each external mutation."""
        module_path = Path(__file__).resolve().parents[2] / "observability" / "scripts" / "forge-receipts.py"
        spec = importlib.util.spec_from_file_location("forge_receipts", module_path)
        if spec is None or spec.loader is None:
            raise SyncError("could not load Forge receipt store")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        store = module.ReceiptStore(self.receipts_path)
        store.append(
            module.make_event(
                "tool.called",
                f"github-sync:{self.repository}",
                task_id=operation.task_id,
                idempotency_key=f"forge-tasks:{operation.key()}",
                attributes={
                    "sync_action": operation.action,
                    "sync_status": "applied",
                    "issue_number": operation.issue_number,
                    "target_task_id": operation.target_task_id,
                    "result": dict(result),
                },
            )
        )

    def _policy_guard(self, authorization: Any) -> Callable[[], None] | None:
        if authorization is None:
            return None

        def guard() -> None:
            try:
                self.policy.recheck(authorization)
            except Exception as exc:
                if self.policy_error_type is not None and isinstance(exc, self.policy_error_type):
                    raise SyncError(str(exc)) from exc
                raise

        return guard

    def apply_one(
        self,
        operation: Operation,
        task_issues: dict[str, int | None],
        *,
        before_effect: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        if operation.action == "create_issue":
            marker = MARKER_RE.search(str(operation.payload.get("body", "")))
            if marker:
                for issue in self.client.list_issues():
                    parsed = parse_remote_task(issue)
                    if parsed and parsed[0].task_id == marker.group(1):
                        task_issues[operation.task_id or ""] = issue.number
                        self.state.setdefault("tasks", {}).setdefault(operation.task_id or "", {})["issue"] = issue.number
                        return {"issue": issue.number, "recovered": True}
            if before_effect:
                before_effect()
            data = self.client.create_issue(operation.payload)
            task_issues[operation.task_id or ""] = int(data["number"])
            self.state.setdefault("tasks", {}).setdefault(operation.task_id or "", {})["issue"] = int(data["number"])
            return {"issue": int(data["number"])}
        if operation.action in {"update_issue", "update_state", "close_issue", "reopen_issue"}:
            if before_effect:
                before_effect()
            data = self.client.update_issue(operation.issue_number, operation.payload)
            return {"issue": int(data.get("number", operation.issue_number))}
        if operation.action == "add_sub_issue":
            parent = task_issues.get(operation.target_task_id or "")
            child = task_issues.get(operation.task_id or "")
            if not parent or not child:
                raise SyncError("sub-issue relationship cannot resolve parent and child issue IDs")
            child_data = self.client.request("GET", f"repos/{self.repository}/issues/{child}")
            if any(int(item.get("id", -1)) == int(child_data["id"]) for item in self.client.list_sub_issues(parent)):
                return {"parent": parent, "child": child, "already_present": True}
            if before_effect:
                before_effect()
            self.client.add_sub_issue(parent, int(child_data["id"]))
            return {"parent": parent, "child": child}
        if operation.action == "add_blocked_by":
            dependent = task_issues.get(operation.task_id or "")
            blocker = task_issues.get(operation.target_task_id or "")
            if not dependent or not blocker:
                raise SyncError("blocked-by relationship cannot resolve both issue IDs")
            blocker_data = self.client.request("GET", f"repos/{self.repository}/issues/{blocker}")
            if any(int(item.get("id", -1)) == int(blocker_data["id"]) for item in self.client.list_blocked_by(dependent)):
                return {"dependent": dependent, "blocked_by": blocker, "already_present": True}
            if before_effect:
                before_effect()
            self.client.add_blocked_by(dependent, int(blocker_data["id"]))
            return {"dependent": dependent, "blocked_by": blocker}
        raise SyncError(f"unsupported operation: {operation.action}")


def issue_state(task: Task) -> str:
    return "closed" if task.status == "done" else "open"


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "tasks": {}, "completed_operations": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncError(f"cannot read sync state: {exc}") from exc
    if data.get("schema_version") != SCHEMA_VERSION:
        raise SyncError("unsupported sync state schema version")
    return data


def save_state(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_import(tasks_dir: Path, tasks: Iterable[Task]) -> list[str]:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    existing = {task.task_id: task.source_path for task in load_tasks(tasks_dir)}
    written: list[str] = []
    for task in tasks:
        path = existing.get(task.task_id)
        if path is None:
            slug = re.sub(r"[^a-z0-9]+", "-", task.title.lower()).strip("-") or "task"
            path = tasks_dir / f"{task.task_id}-{slug}.md"
        path.write_text(render_local(task, task.content_hash()), encoding="utf-8")
        written.append(str(path))
    return written


def parse_repo(path: Path) -> str:
    remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=path, capture_output=True, text=True, check=False)
    if remote.returncode:
        raise SyncError("could not infer GitHub repository; pass --repo OWNER/REPO")
    value = remote.stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", value)
    if not match:
        raise SyncError("origin is not a GitHub remote; pass --repo OWNER/REPO")
    return f"{match.group(1)}/{match.group(2)}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronize Forge task ledgers with GitHub Issues.")
    parser.add_argument("--repo", help="GitHub repository OWNER/REPO (default: origin)")
    parser.add_argument("--tasks-dir", type=Path, default=Path(".forge/tasks"))
    parser.add_argument("--state", type=Path, default=Path(".forge/github-sync.json"))
    parser.add_argument("--receipts", type=Path, default=Path(".forge/receipts.jsonl"))
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--authority", choices=("local", "github"), default="local")
    parser.add_argument("--policy-profile", type=Path, default=None, help="opt into a declarative policy profile")
    parser.add_argument("--policy-approval", help="one-use approval ID for the exact operation")
    parser.add_argument("--policy-approvals", type=Path, default=Path(".forge/approvals.jsonl"))
    parser.add_argument("--policy-staged", action="store_true", help="preview policy-authorized operations without effects")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan", help="show proposed operations without writing")
    apply = subparsers.add_parser("apply", help="apply the local-authority plan")
    apply.add_argument("--yes", action="store_true", help="confirm external writes")
    apply.add_argument("--policy-profile", type=Path, default=argparse.SUPPRESS)
    apply.add_argument("--policy-approval", default=argparse.SUPPRESS)
    apply.add_argument("--policy-approvals", type=Path, default=argparse.SUPPRESS)
    apply.add_argument("--policy-staged", action="store_true", default=argparse.SUPPRESS)
    import_parser = subparsers.add_parser("import", help="import managed GitHub tasks into local Markdown")
    import_parser.add_argument("--write", action="store_true", help="write local task files")
    subparsers.add_parser("status", help="show local/remote mapping and drift")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repository = args.repo or parse_repo(Path.cwd())
        tasks = load_tasks(args.tasks_dir)
        client = GitHubClient(repository)
        engine = SyncEngine(
            tasks,
            client,
            args.state,
            repository,
            args.receipts,
            policy_profile=args.policy_profile,
            policy_approval=args.policy_approval,
            policy_staged=args.policy_staged,
            policy_approvals_path=args.policy_approvals,
        )
        engine.discover()
        if args.authority == "github" and args.command not in {"import", "status"}:
            raise SyncError("github authority supports import and status; local authority is required for apply")
        if args.command == "import":
            remote_tasks = [record.task for record in engine.remote.values()]
            if args.write:
                result = {"authority": "github", "written": write_import(args.tasks_dir, remote_tasks)}
            else:
                result = {"authority": "github", "would_write": [str(task.task_id) for task in remote_tasks]}
        elif args.command == "status":
            operations = engine.plan()
            result = {
                "authority": args.authority,
                "local_tasks": len(tasks),
                "managed_remote_tasks": len(engine.remote),
                "operations": [operation.as_dict() for operation in operations],
            }
        else:
            operations = engine.plan()
            result = {"authority": "local", "operations": [operation.as_dict() for operation in operations]}
            if args.command == "apply":
                result["results"] = engine.apply(operations, confirm=args.yes)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, SyncError, ApiError) as exc:
        error = {"error": {"code": type(exc).__name__, "message": str(exc)}}
        print(json.dumps(error, indent=2) if args.json else f"forge-tasks: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
