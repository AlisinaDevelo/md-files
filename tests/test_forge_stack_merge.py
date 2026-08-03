"""Behavioral tests for native GitHub Stack Merge and Merge Queue tracking."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/stacked-changes/scripts/forge-stack-merge.py"
FIXTURES = REPO / "tests/fixtures/stack-merge"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_stack_merge", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_remote(module):
    return module.RemoteStack(
        stack_id=42,
        number=7,
        node_id="stack-node",
        base_ref="main",
        base_sha="base-sha",
        pull_requests=(
            module.RemotePullRequest(101, "feature/auth", "sha-auth", "main", "base-sha"),
            module.RemotePullRequest(102, "feature/api", "sha-api", "feature/auth", "sha-auth"),
            module.RemotePullRequest(103, "feature/ui", "sha-ui", "feature/api", "sha-api"),
        ),
    )


def make_manifest():
    return {
        "version": 1,
        "provider": "github",
        "trunk": "main",
        "remote": "origin",
        "branches": [
            {"name": "feature/auth", "parent": "main", "pr": 101, "github": {"head_sha": "sha-auth"}},
            {"name": "feature/api", "parent": "feature/auth", "pr": 102, "github": {"head_sha": "sha-api"}},
            {"name": "feature/ui", "parent": "feature/api", "pr": 103, "github": {"head_sha": "sha-ui"}},
        ],
    }


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeClient:
    def __init__(self, module, remote, responses, observed=None):
        self.module = module
        self.remote = remote
        self.responses = list(responses)
        self.observed = observed or {"status": "pending", "merged_prs": [], "open_prs": [101, 102]}
        self.submit_count = 0
        self.poll_count = 0
        self.queue_count = 0

    def verify_plan(self, plan):
        return {"status": "verified", "stack_number": plan.stack_number}

    def preflight_plan(self, plan):
        return {"status": "pass", "checks": [{"name": "fixture", "status": "pass"}]}

    def submit_merge(self, plan):
        self.submit_count += 1
        return self.responses.pop(0)

    def poll_merge(self, plan, request_uuid):
        self.poll_count += 1
        return self.responses.pop(0)

    def poll_queue(self, plan):
        self.queue_count += 1
        return self.responses.pop(0) if self.responses else self.observed

    def observe_plan(self, plan):
        return self.observed


def test_plan_previews_exact_contiguous_range_and_expected_sha():
    module = load_module()

    plan = module.plan_merge(make_manifest(), make_remote(module), target_pr=102, merge_method="squash", merge_action="direct_merge")

    assert plan.selected_pull_requests == (101, 102)
    assert plan.expected_head_shas == ("sha-auth", "sha-api")
    assert plan.request_payload() == {"merge_action": "direct_merge", "merge_method": "squash", "sha": "sha-api"}
    assert plan.expected_result == "merged"
    assert plan.as_dict()["preview"]["contiguous_range"] == [101, 102]


def test_plan_refuses_manifest_head_drift_before_approval():
    module = load_module()
    manifest = make_manifest()
    manifest["branches"][1]["github"]["head_sha"] = "stale-sha"

    with pytest.raises(module.ConflictError, match="PR #102 head SHA changed"):
        module.plan_merge(manifest, make_remote(module), target_pr=102)


def test_plan_refuses_a_non_contiguous_or_closed_range():
    module = load_module()
    remote = make_remote(module)
    remote = module.RemoteStack(
        remote.stack_id,
        remote.number,
        remote.node_id,
        remote.base_ref,
        remote.base_sha,
        (remote.pull_requests[0], module.RemotePullRequest(102, "feature/api", "sha-api", "feature/auth", "sha-auth", state="closed"), remote.pull_requests[2]),
    )

    with pytest.raises(module.MergeError, match="closed"):
        module.plan_merge(make_manifest(), remote, target_pr=103)


def test_timeout_persists_uuid_and_retry_resumes_without_duplicate_submission(tmp_path):
    module = load_module()
    plan = module.plan_merge(make_manifest(), make_remote(module), target_pr=102)
    client = FakeClient(
        module,
        make_remote(module),
        responses=[
            {"status": "pending", "details": {"uuid": "request-1", "message": "accepted"}},
            {"status": "pending", "details": {"uuid": "request-1", "message": "still running"}},
            {"status": "pending", "details": {"uuid": "request-1", "message": "still running"}},
        ],
    )
    state = tmp_path / "merge.json"
    receipts = tmp_path / "receipts.jsonl"

    first = module.execute_merge(client, "owner/repo", plan, state, receipts, yes=True, poll_attempts=1)
    second = module.execute_merge(client, "owner/repo", plan, state, receipts, yes=True, poll_attempts=1)

    assert first["status"] == "pending"
    assert first["timed_out"] is True
    assert second["status"] == "pending"
    assert client.submit_count == 1
    saved = json.loads(state.read_text())
    assert saved["requests"][plan.operation_id]["request_uuid"] == "request-1"


@pytest.mark.parametrize("status", ["merged", "enqueued", "failed"])
def test_terminal_submit_states_are_persisted(status, tmp_path):
    module = load_module()
    plan = module.plan_merge(make_manifest(), make_remote(module), target_pr=102)
    observed = {"status": "merged", "merged_prs": [101, 102], "open_prs": []} if status == "merged" else None
    client = FakeClient(module, make_remote(module), [fixture(f"{status}.json")], observed=observed)

    result = module.execute_merge(client, "owner/repo", plan, tmp_path / "merge.json", tmp_path / "receipts.jsonl", yes=True, poll_attempts=1)

    assert result["status"] == status
    stored = json.loads((tmp_path / "merge.json").read_text())["requests"][plan.operation_id]
    assert stored["status"] == status


def test_failed_request_with_remote_merge_evidence_is_indeterminate(tmp_path):
    module = load_module()
    plan = module.plan_merge(make_manifest(), make_remote(module), target_pr=102, merge_action="direct_merge")
    client = FakeClient(
        module,
        make_remote(module),
        [{"status": "failed", "details": {"message": "rule failure"}}],
        observed={"status": "partial", "merged_prs": [101], "open_prs": [102]},
    )

    result = module.execute_merge(client, "owner/repo", plan, tmp_path / "merge.json", tmp_path / "receipts.jsonl", yes=True)

    assert result["status"] == "indeterminate"
    assert result["action"] == "stop-and-reconcile"
    assert result["partial_merge_detected"] is True


def test_unsupported_native_merge_returns_provider_fallback(tmp_path):
    module = load_module()
    plan = module.plan_merge(make_manifest(), make_remote(module), target_pr=102)

    class Unsupported(FakeClient):
        def submit_merge(self, plan):
            raise module.FeatureUnavailable("async stack merge is unavailable")

    result = module.execute_merge(Unsupported(module, make_remote(module), []), "owner/repo", plan, tmp_path / "merge.json", tmp_path / "receipts.jsonl", yes=True)

    assert result["status"] == "fallback"
    assert result["fallback"] is True
    assert result["provider_plan"]["strategy"] == "provider-native-bottom-up"
    assert not (tmp_path / "merge.json").exists()


def test_policy_staged_merge_never_submits_or_writes_merge_state(tmp_path):
    module = load_module()
    plan = module.plan_merge(make_manifest(), make_remote(module), target_pr=102)
    client = FakeClient(module, make_remote(module), [{"status": "merged", "details": {}}])

    result = module.execute_merge(
        client,
        "owner/repo",
        plan,
        tmp_path / "merge.json",
        tmp_path / "receipts.jsonl",
        yes=False,
        policy_profile=REPO / "policies/github-mutation.json",
        policy_staged=True,
        policy_approvals_path=tmp_path / "approvals.jsonl",
        workspace=tmp_path,
    )

    assert result["status"] == "staged"
    assert client.submit_count == 0
    assert not (tmp_path / "merge.json").exists()


def test_failed_readiness_gate_stops_before_submit(tmp_path):
    module = load_module()
    plan = module.plan_merge(make_manifest(), make_remote(module), target_pr=102)

    class NotReady(FakeClient):
        def preflight_plan(self, plan):
            return {"status": "fail", "checks": [{"name": "required-checks", "status": "fail", "message": "CI failed"}]}

    client = NotReady(module, make_remote(module), [{"status": "merged", "details": {}}])
    with pytest.raises(module.MergeError, match="preflight"):
        module.execute_merge(client, "owner/repo", plan, tmp_path / "merge.json", tmp_path / "receipts.jsonl", yes=True)
    assert client.submit_count == 0
    assert not (tmp_path / "merge.json").exists()


def test_policy_merge_requires_scoped_approval_before_submit(tmp_path):
    module = load_module()
    plan = module.plan_merge(make_manifest(), make_remote(module), target_pr=102)
    client = FakeClient(module, make_remote(module), [{"status": "merged", "details": {}}])

    with pytest.raises(module.MergeError, match="approval"):
        module.execute_merge(
            client,
            "owner/repo",
            plan,
            tmp_path / "merge.json",
            tmp_path / "receipts.jsonl",
            yes=True,
            policy_profile=REPO / "policies/github-mutation.json",
            policy_approvals_path=tmp_path / "approvals.jsonl",
            workspace=tmp_path,
        )
    assert client.submit_count == 0


def test_duplicate_submit_409_reuses_structured_request_uuid():
    module = load_module()
    plan = module.plan_merge(make_manifest(), make_remote(module), target_pr=102)
    client = module.GitHubStackMergeClient("owner/repo")

    def request(method, path, payload=None):
        raise module.sync.ApiError(
            409,
            "an existing merge request is active",
            path,
            {"status": "pending", "details": {"uuid": "630b9d5e-3f2a-4f7e-8b0c-2d5f9a8c1e42"}},
        )

    client.request = request

    result = client.submit_merge(plan)

    assert result["status"] == "pending"
    assert result["recovered"] is True
    assert result["details"]["uuid"].startswith("630b9d5e")


def test_merge_group_event_is_correlated_to_enqueued_receipt(tmp_path):
    module = load_module()
    plan = module.plan_merge(make_manifest(), make_remote(module), target_pr=102, merge_action="merge_queue")
    client = FakeClient(module, make_remote(module), [{"status": "enqueued", "details": {"message": "queued"}}])
    state = tmp_path / "merge.json"
    receipts = tmp_path / "receipts.jsonl"
    module.execute_merge(client, "owner/repo", plan, state, receipts, yes=True)
    event = fixture("merge-group-checks-requested.json")

    result = module.ingest_merge_group_event(state, receipts, event, operation_id=plan.operation_id)

    assert result["status"] == "enqueued"
    assert result["merge_group"]["head_sha"] == "queue-head-sha"
    saved = json.loads(state.read_text())["requests"][plan.operation_id]
    assert saved["queue"]["checks_requested"] is True


def test_merge_group_event_rejects_wrong_repository_or_action(tmp_path):
    module = load_module()
    state = tmp_path / "merge.json"
    state.write_text(json.dumps({"schema_version": 1, "repository": "owner/repo", "requests": {}}))

    with pytest.raises(module.MergeError, match="checks_requested"):
        module.ingest_merge_group_event(state, tmp_path / "receipts.jsonl", {"action": "completed", "merge_group": {}}, operation_id="missing")
