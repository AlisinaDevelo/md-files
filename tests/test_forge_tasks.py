"""Behavioral tests for Forge's GitHub task-ledger backend."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/task-ledger/scripts/forge-tasks.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_tasks", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def task(module, task_id="0001", **overrides):
    values = {
        "task_id": task_id,
        "title": f"Task {task_id}",
        "status": "ready",
        "agent": "test-engineer",
        "model": "sonnet",
        "depends_on": [],
        "parent": None,
        "release": "v3.1.0",
        "goal": "Deliver a verifiable task.",
        "acceptance": ["The behavior is tested."],
        "context": "Use the Forge task ledger.",
        "notes": "",
    }
    values.update(overrides)
    return module.Task(**values)


class FakeGitHub:
    def __init__(self, module, records=None):
        self.module = module
        self.records = records or []
        self.sub_issues = {}
        self.blocked_by = {}
        self.created = []
        self.updated = []
        self.relationships = []

    def repository_metadata(self):
        return {"full_name": "owner/repo"}

    def list_issues(self):
        return self.records

    def list_sub_issues(self, issue_number):
        return self.sub_issues.get(issue_number, [])

    def list_blocked_by(self, issue_number):
        return self.blocked_by.get(issue_number, [])

    def create_issue(self, payload):
        issue = {"number": 100 + len(self.created), "id": 900 + len(self.created)}
        self.created.append((issue, payload))
        return issue

    def update_issue(self, issue_number, payload):
        self.updated.append((issue_number, payload))
        return {"number": issue_number}

    def request(self, method, path, payload=None):
        issue_number = int(path.rsplit("/", 1)[-1])
        return {"id": issue_number + 800}

    def add_sub_issue(self, parent_number, child_issue_id):
        self.relationships.append(("sub_issue", parent_number, child_issue_id))

    def add_blocked_by(self, issue_number, blocking_issue_id):
        self.relationships.append(("blocked_by", issue_number, blocking_issue_id))


def remote(module, task_value, number=10, sync_hash=None):
    sync_hash = sync_hash or task_value.content_hash()
    return module.RemoteIssue(
        number=number,
        issue_id=number + 800,
        title=task_value.title,
        body=module.render_remote(task_value, sync_hash),
        state=module.issue_state(task_value),
    )


def engine(module, tmp_path, tasks, client):
    instance = module.SyncEngine(tasks, client, tmp_path / "github-sync.json", "owner/repo")
    instance.discover()
    return instance


def test_remote_round_trip_preserves_identity_and_graph_fields():
    module = load_module()
    original = task(module, parent="0000", depends_on=["0002"])
    parsed = module.parse_remote_task(remote(module, original))

    assert parsed is not None
    recovered, sync_hash = parsed
    assert recovered.task_id == "0001"
    assert recovered.parent == "0000"
    assert recovered.depends_on == ["0002"]
    assert sync_hash == original.content_hash()
    assert recovered.content_hash() == original.content_hash()


def test_unchanged_state_produces_zero_operations(tmp_path):
    module = load_module()
    value = task(module)
    client = FakeGitHub(module, [remote(module, value)])
    instance = engine(module, tmp_path, [value], client)

    assert instance.plan() == []


def test_local_edit_plans_one_body_update_without_churn(tmp_path):
    module = load_module()
    baseline = task(module)
    changed = task(module, notes="A verified implementation note.", sync_hash=baseline.content_hash())
    client = FakeGitHub(module, [remote(module, baseline)])
    instance = engine(module, tmp_path, [changed], client)
    operations = instance.plan()

    assert [operation.action for operation in operations] == ["update_issue"]
    assert operations[0].payload["title"] == changed.title
    assert operations[0].payload["body"].count("forge-task:v1") == 1


def test_status_transition_is_explicit_close_operation(tmp_path):
    module = load_module()
    value = task(module, status="done")
    issue = module.RemoteIssue(
        number=10,
        issue_id=810,
        title=value.title,
        body=module.render_remote(value, value.content_hash()),
        state="open",
    )
    instance = engine(module, tmp_path, [value], FakeGitHub(module, [issue]))

    operations = instance.plan()

    assert [operation.action for operation in operations] == ["close_issue"]
    assert operations[0].payload == {"state": "closed"}


def test_divergent_local_and_remote_edits_become_structured_conflict(tmp_path):
    module = load_module()
    baseline = task(module)
    local = task(module, notes="Local edit.", sync_hash=baseline.content_hash())
    remote_task = task(module, notes="Remote edit.")
    client = FakeGitHub(module, [remote(module, remote_task, sync_hash=baseline.content_hash())])
    instance = engine(module, tmp_path, [local], client)
    operations = instance.plan()

    assert len(operations) == 1
    assert operations[0].action == "conflict"
    assert "diverged" in operations[0].reason


def test_native_sub_issue_and_blocked_by_relationships_are_planned(tmp_path):
    module = load_module()
    parent = task(module, "0001")
    child = task(module, "0002", parent="0001", depends_on=["0001"])
    client = FakeGitHub(module, [remote(module, parent, 10), remote(module, child, 11)])
    instance = engine(module, tmp_path, [parent, child], client)
    operations = instance.plan()

    assert {operation.action for operation in operations} == {"add_sub_issue", "add_blocked_by"}
    assert {operation.target_task_id for operation in operations} == {"0001"}


def test_apply_is_resumable_and_requires_confirmation(tmp_path):
    module = load_module()
    value = task(module)
    client = FakeGitHub(module)
    instance = engine(module, tmp_path, [value], client)
    operations = instance.plan()

    with pytest.raises(module.SyncError, match="--yes"):
        instance.apply(operations)
    first = instance.apply(operations, confirm=True)
    second = instance.apply(operations, confirm=True)

    assert first[0]["status"] == "applied"
    assert second[0]["status"] == "already-complete"
    assert len(client.created) == 1
    state = json.loads((tmp_path / "github-sync.json").read_text())
    assert state["tasks"]["0001"]["issue"] == 100
    receipts = json.loads((tmp_path / "receipts.jsonl").read_text().splitlines()[0])
    assert receipts["event_type"] == "tool.called"
    assert receipts["idempotency_key"].startswith("forge-tasks:")


def test_import_is_byte_stable_for_same_task(tmp_path):
    module = load_module()
    value = task(module, sync_hash=None)
    tasks_dir = tmp_path / "tasks"
    paths = module.write_import(tasks_dir, [value])
    first = Path(paths[0]).read_bytes()
    parsed = module.load_tasks(tasks_dir)[0]
    module.write_import(tasks_dir, [parsed])

    assert Path(paths[0]).read_bytes() == first


def test_github_issue_pagination_filters_pull_requests(monkeypatch):
    module = load_module()
    client = module.GitHubClient("owner/repo")
    calls = []

    def fake_request(method, path, payload=None):
        calls.append(path)
        if path.endswith("page=1"):
            return [{"id": 1, "number": 1, "title": "issue", "body": "", "state": "open"}] * 100
        return [{"id": 2, "number": 2, "title": "pr", "body": "", "state": "open", "pull_request": {}}]

    monkeypatch.setattr(client, "request", fake_request)
    issues = client.list_issues()

    assert len(issues) == 100
    assert calls[-1].endswith("page=2")


def test_github_api_errors_keep_status_and_path():
    module = load_module()
    error = module.ApiError(403, "forbidden", "repos/owner/repo/issues")
    assert error.status == 403
    assert error.path.endswith("issues")


def test_missing_saved_issue_plans_explicit_recovery(tmp_path):
    module = load_module()
    state_path = tmp_path / "github-sync.json"
    state_path.write_text(json.dumps({"schema_version": 1, "repository": "owner/repo", "tasks": {"0001": {"issue": 44}}, "completed_operations": []}))
    value = task(module)
    instance = engine(module, tmp_path, [value], FakeGitHub(module))

    operations = instance.plan()

    assert operations[0].action == "create_issue"
    assert "recreate" in operations[0].reason
    assert "#44" in operations[0].reason


def test_renamed_repository_stops_before_issue_scan(tmp_path):
    module = load_module()
    client = FakeGitHub(module)
    client.repository_metadata = lambda: {"full_name": "owner/new-repo"}

    with pytest.raises(module.SyncError, match="renamed"):
        engine(module, tmp_path, [task(module)], client)


def test_issue_pagination_has_a_hard_limit(monkeypatch):
    module = load_module()
    client = module.GitHubClient("owner/repo")
    monkeypatch.setattr(client, "request", lambda method, path, payload=None: [{"id": 1, "number": 1, "title": "issue", "body": "", "state": "open"}] * 100)

    with pytest.raises(module.SyncError, match="100 pages"):
        client.list_issues()


def test_relationship_retry_checks_native_graph_before_writing(tmp_path):
    module = load_module()
    parent = task(module, "0001")
    child = task(module, "0002", parent="0001")
    client = FakeGitHub(module, [remote(module, parent, 10), remote(module, child, 11)])
    client.sub_issues[10] = []
    client.blocked_by[11] = []
    instance = engine(module, tmp_path, [parent, child], client)
    operation = next(item for item in instance.plan() if item.action == "add_sub_issue")
    client.sub_issues[10] = [{"id": 811}]
    instance.state["tasks"] = {"0001": {"issue": 10}, "0002": {"issue": 11}}

    result = instance.apply_one(operation, {"0001": 10, "0002": 11})

    assert result["already_present"] is True
    assert client.relationships == []
