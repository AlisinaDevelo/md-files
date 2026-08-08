"""Tests for the fenced Forge gh-aw GitHub provider worker."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-gh-aw-provider.py"
SPEC_PATH = REPO / "data/gh-aw-workflows.json"
REF_A = "sha256:" + "a" * 64
REF_B = "sha256:" + "b" * 64


def load_module():
    spec = importlib.util.spec_from_file_location("forge_gh_aw_provider_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, responses: list[dict[str, Any]], *, login: str = "AlisinaDevelo") -> None:
        self.login = login
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def authenticated_login(self) -> str:
        return self.login

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        body: dict[str, Any] | None = None,
        paginate: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": method,
                "endpoint": endpoint,
                "body": copy.deepcopy(body),
                "paginate": paginate,
            }
        )
        if not self.responses:
            raise AssertionError(f"unexpected provider call: {method} {endpoint}")
        return copy.deepcopy(self.responses.pop(0))


def prepare(module, tmp_path: Path) -> tuple[Any, Path, Path]:
    bridge = module._bridge()
    output = tmp_path / "gh-aw"
    bridge._compiler().compile_artifacts(REPO, SPEC_PATH, output)
    return bridge, output, tmp_path / "runtime.sqlite3"


def envelope(
    module,
    episode_id: str,
    workflow_id: str,
    output_type: str,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    material = {
        "repository": "AlisinaDevelo/md-files",
        "workflow_id": workflow_id,
        "safe_output_type": output_type,
        "operations": operations,
    }
    return {
        "$schema": module.REQUEST_SCHEMA,
        "schema_version": 1,
        "adapter_contract_revision": module.PROVIDER_REVISION,
        "episode_id": episode_id,
        "request_ref": module.digest(material),
        **material,
    }


def receipt(bridge, effect: dict[str, Any]) -> dict[str, str]:
    payload = effect["payload"]
    return {
        "status": "succeeded",
        "episode_id": payload["episode_id"],
        "workflow_id": payload["workflow_id"],
        "safe_output_type": payload["safe_output_type"],
        "approval_id": REF_A,
        "adapter_contract_revision": bridge.BRIDGE_REVISION,
        "provider_request_id": f"fixture:{effect['effect_id']}",
        "result_ref": REF_B,
    }


def dispatch_episode(module, bridge, output: Path, database: Path) -> tuple[str, dict[str, Any], dict[str, Any]]:
    operations = [
        {
            "type": "dispatch-workflow",
            "workflow_id": workflow_id,
            "ref": "main",
            "inputs": {"activate": True},
        }
        for workflow_id in (
            "forge-issue-triage",
            "forge-ci-diagnosis",
            "forge-docs-maintenance",
            "forge-feature-planning",
        )
    ]
    material = {
        "repository": "AlisinaDevelo/md-files",
        "workflow_id": "forge-dispatcher",
        "safe_output_type": "dispatch-workflow",
        "operations": operations,
    }
    request_ref = module.digest(material)
    started = bridge.start_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        request_ref,
        occurred_at="2026-08-08T10:00:00Z",
    )
    episode_id = started["episode_id"]
    request = envelope(module, episode_id, "forge-dispatcher", "dispatch-workflow", operations)
    bridge.dispatch_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        request_ref,
        occurred_at="2026-08-08T10:01:00Z",
    )
    claimed = bridge.claim_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        "provider-a",
        limit=4,
        now="2026-08-08T10:02:00Z",
    )["claimed"]
    return episode_id, request, claimed[0]


def worker_effect(
    module,
    bridge,
    output: Path,
    database: Path,
    *,
    worker_id: str,
    output_type: str,
    operations: list[dict[str, Any]],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    episode_id, dispatch_request, _ = dispatch_episode(module, bridge, output, database)
    runtime = bridge._runtime()
    with runtime.RuntimeStore(database) as store:
        dispatches = store.list_outbox(episode_id)
    for effect in dispatches:
        bridge.acknowledge_episode(
            SPEC_PATH,
            output,
            database,
            "forge-dispatcher",
            episode_id,
            effect["effect_id"],
            "provider-a",
            effect["lease_generation"],
            receipt(bridge, effect),
            received_at="2026-08-08T10:02:30Z",
        )
    bridge.start_worker(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        worker_id,
        occurred_at="2026-08-08T10:04:00Z",
    )
    request = envelope(module, episode_id, worker_id, output_type, operations)
    bridge.complete_worker(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        worker_id,
        request["request_ref"],
        safe_output_type=output_type,
        occurred_at="2026-08-08T10:05:00Z",
    )
    effect = bridge.claim_episode(
        SPEC_PATH,
        output,
        database,
        "forge-dispatcher",
        episode_id,
        "provider-b",
        now="2026-08-08T10:06:00Z",
    )["claimed"][0]
    assert dispatch_request["request_ref"] != request["request_ref"]
    return episode_id, request, effect


def approve(
    module,
    output: Path,
    database: Path,
    request: dict[str, Any],
    effect: dict[str, Any],
    tmp_path: Path,
    *,
    worker_id: str,
) -> str:
    approval_time = (
        "2026-08-08T10:02:20Z" if worker_id == "provider-a" else "2026-08-08T10:06:20Z"
    )
    result = module.issue_approval(
        SPEC_PATH,
        output,
        database,
        request,
        effect["effect_id"],
        worker_id,
        effect["lease_generation"],
        approvals_path=tmp_path / "approvals.jsonl",
        ttl_seconds=600,
        now=approval_time,
    )
    assert result["status"] == "approval-issued"
    assert result["action_digest"].startswith("sha256:")
    return result["approval_id"]


def test_plan_is_digest_only_and_does_not_consume_approval(tmp_path):
    module = load_module()
    bridge, output, database = prepare(module, tmp_path)
    _, request, effect = dispatch_episode(module, bridge, output, database)
    approvals = tmp_path / "approvals.jsonl"

    plan = module.plan_effect(
        SPEC_PATH,
        output,
        database,
        request,
        effect["effect_id"],
        "provider-a",
        effect["lease_generation"],
        approvals_path=approvals,
        now="2026-08-08T10:02:30Z",
    )

    assert plan["status"] == "staged"
    assert plan["effect_id"] == effect["effect_id"]
    assert plan["request_ref"] == request["request_ref"]
    assert plan["safe_output_type"] == "dispatch-workflow"
    assert plan["operation_count"] == 1
    assert plan["policy"]["compiled_action_digest"] == effect["payload"]["policy_action_digest"]
    assert plan["policy"]["authorization_action_digest"].startswith("sha256:")
    assert "operations" not in plan
    assert "inputs" not in json.dumps(plan, sort_keys=True)
    assert not approvals.exists()


def test_dispatch_execute_requires_login_approval_and_acks_run_details(tmp_path):
    module = load_module()
    bridge, output, database = prepare(module, tmp_path)
    episode_id, request, effect = dispatch_episode(module, bridge, output, database)
    approval_id = approve(module, output, database, request, effect, tmp_path, worker_id="provider-a")
    wrong_account = FakeTransport([], login="AliSinaKarimi")
    with pytest.raises(module.GhAwProviderError, match="login mismatch"):
        module.execute_effect(
            SPEC_PATH,
            output,
            database,
            request,
            effect["effect_id"],
            "provider-a",
            effect["lease_generation"],
            approval_id,
            expected_login="AlisinaDevelo",
            approvals_path=tmp_path / "approvals.jsonl",
            journal_path=tmp_path / "provider.jsonl",
            transport=wrong_account,
            now="2026-08-08T10:02:25Z",
        )
    assert wrong_account.calls == []
    transport = FakeTransport(
        [
            {
                "workflow_run_id": 31234567890,
                "run_url": "https://api.github.com/repos/AlisinaDevelo/md-files/actions/runs/31234567890",
                "html_url": "https://github.com/AlisinaDevelo/md-files/actions/runs/31234567890",
            },
        ]
    )

    result = module.execute_effect(
        SPEC_PATH,
        output,
        database,
        request,
        effect["effect_id"],
        "provider-a",
        effect["lease_generation"],
        approval_id,
        expected_login="AlisinaDevelo",
        approvals_path=tmp_path / "approvals.jsonl",
        journal_path=tmp_path / "provider.jsonl",
        transport=transport,
        now="2026-08-08T10:02:30Z",
    )

    assert result["status"] == "succeeded"
    assert result["receipt"]["resource_ref"].endswith("/31234567890")
    assert result["receipt"]["approval_id"].startswith("sha256:")
    assert result["receipt"]["result_ref"].startswith("sha256:")
    assert transport.calls[-1]["method"] == "POST"
    target_workflow = effect["payload"]["worker_workflow_id"]
    assert transport.calls[-1]["endpoint"].endswith(
        f"/actions/workflows/{target_workflow}.lock.yml/dispatches"
    )
    assert transport.calls[-1]["body"]["return_run_details"] is True
    assert transport.calls[-1]["body"]["ref"] == "main"
    with bridge._runtime().RuntimeStore(database) as store:
        stored = next(item for item in store.list_outbox(episode_id) if item["effect_id"] == effect["effect_id"])
    assert stored["status"] == "succeeded"


def test_add_comment_sanitizes_content_and_acks_comment_reference(tmp_path):
    module = load_module()
    bridge, output, database = prepare(module, tmp_path)
    episode_id, request, effect = worker_effect(
        module,
        bridge,
        output,
        database,
        worker_id="forge-issue-triage",
        output_type="add-comment",
        operations=[
            {
                "type": "add-comment",
                "item_number": 21,
                "body": "Triage @team: javascript:alert(1)",
            }
        ],
    )
    approval_id = approve(module, output, database, request, effect, tmp_path, worker_id="provider-b")
    transport = FakeTransport(
        [
            {"items": []},
            {
                "id": 7001,
                "html_url": "https://github.com/AlisinaDevelo/md-files/issues/21#issuecomment-7001",
            },
        ]
    )

    result = module.execute_effect(
        SPEC_PATH,
        output,
        database,
        request,
        effect["effect_id"],
        "provider-b",
        effect["lease_generation"],
        approval_id,
        expected_login="AlisinaDevelo",
        approvals_path=tmp_path / "approvals.jsonl",
        journal_path=tmp_path / "provider.jsonl",
        transport=transport,
        now="2026-08-08T10:06:30Z",
    )

    assert result["status"] == "succeeded"
    post = next(item for item in transport.calls if item["method"] == "POST")
    assert post["endpoint"] == "/repos/AlisinaDevelo/md-files/issues/21/comments"
    assert "@team" not in post["body"]["body"]
    assert "javascript:" not in post["body"]["body"]
    assert "forge-gh-aw:" in post["body"]["body"]
    assert result["receipt"]["resource_ref"].endswith("issuecomment-7001")
    with bridge._runtime().RuntimeStore(database) as store:
        stored = next(item for item in store.list_outbox(episode_id) if item["effect_id"] == effect["effect_id"])
    assert stored["status"] == "succeeded"


def test_journal_recovers_a_post_write_pre_acknowledgement_crash(tmp_path, monkeypatch):
    module = load_module()
    bridge, output, database = prepare(module, tmp_path)
    episode_id, request, effect = worker_effect(
        module,
        bridge,
        output,
        database,
        worker_id="forge-feature-planning",
        output_type="create-issue",
        operations=[
            {
                "type": "create-issue",
                "title": "Plan bounded retries",
                "body": "Track the remaining retry work.",
                "labels": ["planning"],
            }
        ],
    )
    approval_id = approve(
        module,
        output,
        database,
        request,
        effect,
        tmp_path,
        worker_id="provider-b",
    )
    transport = FakeTransport(
        [
            {"items": []},
            {
                "number": 93,
                "id": 9003,
                "html_url": "https://github.com/AlisinaDevelo/md-files/issues/93",
            },
        ]
    )
    original_acknowledge = module._acknowledge

    def crash_before_ack(*args, **kwargs):
        raise module.GhAwProviderError("simulated acknowledgement crash")

    monkeypatch.setattr(module, "_acknowledge", crash_before_ack)
    with pytest.raises(module.GhAwProviderError, match="simulated acknowledgement crash"):
        module.execute_effect(
            SPEC_PATH,
            output,
            database,
            request,
            effect["effect_id"],
            "provider-b",
            effect["lease_generation"],
            approval_id,
            expected_login="AlisinaDevelo",
            approvals_path=tmp_path / "approvals.jsonl",
            journal_path=tmp_path / "provider.jsonl",
            transport=transport,
            now="2026-08-08T10:06:30Z",
        )
    monkeypatch.setattr(module, "_acknowledge", original_acknowledge)

    recovered = module.execute_effect(
        SPEC_PATH,
        output,
        database,
        request,
        effect["effect_id"],
        "provider-b",
        effect["lease_generation"],
        approval_id,
        expected_login="AlisinaDevelo",
        approvals_path=tmp_path / "approvals.jsonl",
        journal_path=tmp_path / "provider.jsonl",
        transport=transport,
        now="2026-08-08T10:06:40Z",
    )

    assert recovered["replayed"] is True
    assert recovered["receipt"]["resource_ref"].endswith("/issues/93")
    assert len([item for item in transport.calls if item["method"] == "POST"]) == 1
    with bridge._runtime().RuntimeStore(database) as store:
        stored = next(
            item
            for item in store.list_outbox(episode_id)
            if item["effect_id"] == effect["effect_id"]
        )
    assert stored["status"] == "succeeded"


def test_create_issue_enforces_prefix_labels_and_replays_from_journal(tmp_path):
    module = load_module()
    bridge, output, database = prepare(module, tmp_path)
    episode_id, request, effect = worker_effect(
        module,
        bridge,
        output,
        database,
        worker_id="forge-ci-diagnosis",
        output_type="create-issue",
        operations=[
            {
                "type": "create-issue",
                "title": "CI failed on the release job",
                "body": "The release check fails after dependency resolution.",
                "labels": ["triage"],
            }
        ],
    )
    approval_id = approve(module, output, database, request, effect, tmp_path, worker_id="provider-b")
    transport = FakeTransport(
        [
            {"items": []},
            {
                "number": 91,
                "id": 9001,
                "html_url": "https://github.com/AlisinaDevelo/md-files/issues/91",
            },
        ]
    )
    kwargs = {
        "approvals_path": tmp_path / "approvals.jsonl",
        "journal_path": tmp_path / "provider.jsonl",
        "transport": transport,
        "now": "2026-08-08T10:06:30Z",
    }

    first = module.execute_effect(
        SPEC_PATH,
        output,
        database,
        request,
        effect["effect_id"],
        "provider-b",
        effect["lease_generation"],
        approval_id,
        expected_login="AlisinaDevelo",
        **kwargs,
    )
    replayed = module.execute_effect(
        SPEC_PATH,
        output,
        database,
        request,
        effect["effect_id"],
        "provider-b",
        effect["lease_generation"],
        approval_id,
        expected_login="AlisinaDevelo",
        **kwargs,
    )

    create_call = next(item for item in transport.calls if item["method"] == "POST")
    recovery_call = next(item for item in transport.calls if item["method"] == "GET")
    assert recovery_call["paginate"] is True
    assert create_call["endpoint"] == "/repos/AlisinaDevelo/md-files/issues"
    assert create_call["body"]["title"].startswith("[ci-diagnosis] ")
    assert create_call["body"]["labels"] == ["ci", "triage"]
    assert "forge-gh-aw:" in create_call["body"]["body"]
    assert replayed["receipt"] == first["receipt"]
    assert len([item for item in transport.calls if item["method"] == "POST"]) == 1
    drifted = copy.deepcopy(request)
    drifted["operations"][0]["title"] = "A different issue"
    material = {
        key: drifted[key]
        for key in ("repository", "workflow_id", "safe_output_type", "operations")
    }
    drifted["request_ref"] = module.digest(material)
    with pytest.raises(module.GhAwProviderError, match="request_ref"):
        module.execute_effect(
            SPEC_PATH,
            output,
            database,
            drifted,
            effect["effect_id"],
            "provider-b",
            effect["lease_generation"],
            approval_id,
            expected_login="AlisinaDevelo",
            **kwargs,
        )
    with bridge._runtime().RuntimeStore(database) as store:
        assert next(item for item in store.list_outbox(episode_id) if item["effect_id"] == effect["effect_id"])["status"] == "succeeded"


def test_provider_journal_rejects_success_without_authorization(tmp_path):
    module = load_module()
    journal = module.ProviderJournal(tmp_path / "provider.jsonl")
    receipt_value = {
        "status": "succeeded",
        "episode_id": "gh-aw:episode",
        "workflow_id": "forge-feature-planning",
        "safe_output_type": "create-issue",
        "approval_id": REF_A,
        "adapter_contract_revision": "forge-gh-aw-runtime-v1",
        "provider_request_id": "forge-gh-aw:request",
        "resource_ref": "https://github.com/AlisinaDevelo/md-files/issues/1",
        "result_ref": REF_B,
    }

    with pytest.raises(module.GhAwProviderError, match="prior authorization"):
        journal.append(
            "succeeded",
            "effect-1",
            REF_A,
            {"receipt": receipt_value, "recovered": False},
            occurred_at="2026-08-08T10:00:00Z",
        )
    assert journal.read() == []


def test_comment_constraints_and_stale_lease_fail_before_provider_call(tmp_path):
    module = load_module()
    bridge, output, database = prepare(module, tmp_path)
    _, request, effect = worker_effect(
        module,
        bridge,
        output,
        database,
        worker_id="forge-issue-triage",
        output_type="add-comment",
        operations=[{"type": "add-comment", "item_number": 21, "body": "Triage complete."}],
    )
    approval_id = approve(module, output, database, request, effect, tmp_path, worker_id="provider-b")
    with bridge._runtime().RuntimeStore(database) as store:
        reclaimed = store.claim_outbox(
            "provider-c",
            run_id=request["episode_id"],
            now="2026-08-08T11:07:00Z",
        )[0]
    transport = FakeTransport([])

    with pytest.raises(module.GhAwProviderError, match="lease"):
        module.execute_effect(
            SPEC_PATH,
            output,
            database,
            request,
            effect["effect_id"],
            "provider-b",
            effect["lease_generation"],
            approval_id,
            expected_login="AlisinaDevelo",
            approvals_path=tmp_path / "approvals.jsonl",
            journal_path=tmp_path / "provider.jsonl",
            transport=transport,
            now="2026-08-08T11:07:01Z",
        )
    assert reclaimed["lease_generation"] > effect["lease_generation"]
    assert transport.calls == []

    oversized = copy.deepcopy(request)
    oversized["operations"][0]["body"] = "x" * 65_537
    material = {key: oversized[key] for key in ("repository", "workflow_id", "safe_output_type", "operations")}
    oversized["request_ref"] = module.digest(material)
    with pytest.raises(module.GhAwProviderError, match="65536"):
        module.validate_request(oversized)


def test_pull_request_preflight_verifies_head_sha_and_allowed_files(tmp_path):
    module = load_module()
    bridge, output, database = prepare(module, tmp_path)
    _, request, effect = worker_effect(
        module,
        bridge,
        output,
        database,
        worker_id="forge-docs-maintenance",
        output_type="create-pull-request",
        operations=[
            {
                "type": "create-pull-request",
                "title": "Clarify provider recovery",
                "body": "Documents the fenced provider recovery path.",
                "head": "feature/provider-docs",
                "base": "main",
                "head_sha": "1" * 40,
                "changed_files": ["docs/gh-aw.md"],
                "draft": True,
            }
        ],
    )
    approval_id = approve(module, output, database, request, effect, tmp_path, worker_id="provider-b")
    transport = FakeTransport(
        [
            {
                "status": "ahead",
                "ahead_by": 1,
                "head_commit": {"sha": "1" * 40},
                "files": [{"filename": "docs/gh-aw.md"}],
            },
            {"items": []},
            {
                "number": 92,
                "id": 9002,
                "html_url": "https://github.com/AlisinaDevelo/md-files/pull/92",
            },
        ]
    )

    result = module.execute_effect(
        SPEC_PATH,
        output,
        database,
        request,
        effect["effect_id"],
        "provider-b",
        effect["lease_generation"],
        approval_id,
        expected_login="AlisinaDevelo",
        approvals_path=tmp_path / "approvals.jsonl",
        journal_path=tmp_path / "provider.jsonl",
        transport=transport,
        now="2026-08-08T10:06:30Z",
    )

    assert result["receipt"]["resource_ref"].endswith("/pull/92")
    compare_call = transport.calls[0]
    assert compare_call["method"] == "GET"
    assert "/compare/main...feature%2Fprovider-docs" in compare_call["endpoint"]
    create_call = transport.calls[-1]
    assert create_call["body"]["draft"] is True
    assert create_call["body"]["title"].startswith("[docs] ")

    invalid_bridge, invalid_output, invalid_database = prepare(module, tmp_path / "invalid")
    _, invalid_request, invalid_effect = worker_effect(
        module,
        invalid_bridge,
        invalid_output,
        invalid_database,
        worker_id="forge-docs-maintenance",
        output_type="create-pull-request",
        operations=[
            {
                "type": "create-pull-request",
                "title": "Touch a protected file",
                "body": "This request must be rejected.",
                "head": "feature/unsafe-docs",
                "base": "main",
                "head_sha": "2" * 40,
                "changed_files": ["plugins/forge/secret.py"],
                "draft": True,
            }
        ],
    )
    with pytest.raises(module.GhAwProviderError, match="allowed-files"):
        module.plan_effect(
            SPEC_PATH,
            invalid_output,
            invalid_database,
            invalid_request,
            invalid_effect["effect_id"],
            "provider-b",
            invalid_effect["lease_generation"],
            now="2026-08-08T10:06:10Z",
        )


def test_request_rejects_unknown_fields_credentials_and_identity_drift(tmp_path):
    module = load_module()
    bridge, output, database = prepare(module, tmp_path)
    _, request, effect = dispatch_episode(module, bridge, output, database)

    credential = copy.deepcopy(request)
    credential["operations"][0]["inputs"]["token"] = "github_pat_not-allowed"
    material = {key: credential[key] for key in ("repository", "workflow_id", "safe_output_type", "operations")}
    credential["request_ref"] = module.digest(material)
    with pytest.raises(module.GhAwProviderError, match="credential"):
        module.validate_request(credential)

    drifted = copy.deepcopy(request)
    drifted["repository"] = "someone/else"
    material = {key: drifted[key] for key in ("repository", "workflow_id", "safe_output_type", "operations")}
    drifted["request_ref"] = module.digest(material)
    with pytest.raises(module.GhAwProviderError, match="repository"):
        module.plan_effect(
            SPEC_PATH,
            output,
            database,
            drifted,
            effect["effect_id"],
            "provider-a",
            effect["lease_generation"],
            now="2026-08-08T10:02:30Z",
        )

    unknown = copy.deepcopy(request)
    unknown["surprise"] = True
    with pytest.raises(module.GhAwProviderError, match="unsupported fields"):
        module.validate_request(unknown)
