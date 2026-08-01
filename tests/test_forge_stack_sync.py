"""Behavioral tests for the GitHub native Stacked PR adapter."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/stacked-changes/scripts/forge-stack-sync.py"
FIXTURES = REPO / "tests/fixtures/stack-sync"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_stack_sync", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def manifest(branches):
    return {"version": 1, "provider": "github", "trunk": "main", "remote": "origin", "branches": branches}


def remote(module):
    raw = json.loads((FIXTURES / "rest-stack.json").read_text())
    pulls = {
        101: module.RemotePullRequest(101, "feature/auth", "sha-auth", "main", "base-sha"),
        102: module.RemotePullRequest(102, "feature/api", "sha-api", "feature/auth", "sha-auth", draft=True),
    }
    return module.remote_stack_from_rest(raw, pulls)


def test_rest_fixture_preserves_stack_identity_and_sha_snapshots():
    module = load_module()
    value = remote(module)

    assert value.number == 7
    assert value.stack_id == 42
    assert [item.number for item in value.pull_requests] == [101, 102]
    assert value.pull_requests[1].base_sha == "sha-auth"


def test_graphql_fixture_pagination_is_normalized():
    module = load_module()
    first = json.loads((FIXTURES / "graphql-page-1.json").read_text())
    second = json.loads((FIXTURES / "graphql-page-2.json").read_text())
    first_stack = first["data"]["repository"]["pullRequest"]["stack"]
    first_stack["entries"]["nodes"].extend(second["data"]["repository"]["pullRequest"]["stack"]["entries"]["nodes"])
    first_stack["entries"].pop("pageInfo")
    value = module.remote_stack_from_graphql(first)

    assert value is not None
    assert [item.number for item in value.pull_requests] == [101, 102, 103]
    assert value.pull_requests[-1].head_sha == "sha-ui"


def test_graphql_client_follows_cursor_pages():
    module = load_module()
    first = json.loads((FIXTURES / "graphql-page-1.json").read_text())
    second = json.loads((FIXTURES / "graphql-page-2.json").read_text())

    class Client(module.GitHubStackClient):
        def __init__(self):
            super().__init__("owner/repo")
            self.cursors = []

        def graphql(self, query, variables):
            self.cursors.append(variables.get("after"))
            return first if variables.get("after") is None else second

    value = Client().stack_from_graphql(101)

    assert value is not None
    assert [item.number for item in value.pull_requests] == [101, 102, 103]


def test_rest_client_stack_listing_is_bounded_and_paginated(monkeypatch):
    module = load_module()
    client = module.GitHubStackClient("owner/repo")
    calls = []

    def request(method, path, payload=None):
        calls.append(path)
        if path.endswith("page=1"):
            return [{"number": 7}] * 100
        return [{"number": 8}]

    monkeypatch.setattr(client, "request", request)

    assert [item["number"] for item in client.list_stacks()] == [7] * 100 + [8]
    assert calls[-1].endswith("page=2")


def test_webhook_fixture_contains_stack_identity():
    fixture = json.loads((FIXTURES / "webhook-pull-request-stacked.json").read_text())
    assert fixture["action"] == "stacked"
    assert fixture["pull_request"]["stack"]["number"] == 7


def test_import_is_deterministic_and_carries_remote_identifiers(tmp_path):
    module = load_module()
    imported = module.import_manifest(manifest([]), remote(module))
    path = tmp_path / "stack.json"
    module.write_manifest(path, imported)
    first = path.read_bytes()
    module.write_manifest(path, json.loads(first))

    assert path.read_bytes() == first
    assert imported["github_stack"]["number"] == 7
    assert imported["branches"][1]["github"]["head_sha"] == "sha-api"


def test_divergence_classes_cover_local_remote_compatible_and_conflicting():
    module = load_module()
    value = remote(module)
    local = manifest([
        {"name": "feature/auth", "parent": "main", "pr": 101},
        {"name": "feature/api", "parent": "feature/auth", "pr": 102},
    ])

    assert module.classify_divergence(local, value).kind == "compatible"
    assert module.classify_divergence(manifest([]), value).kind == "remote-only"
    assert module.classify_divergence(manifest([{ "name": "feature/auth", "parent": "main", "pr": 101 }]), value).kind == "remote-only"
    assert module.classify_divergence(manifest([{ "name": "feature/other", "parent": "main", "pr": 102 }, {"name": "feature/api", "parent": "feature/other", "pr": 101}]), value).kind == "conflicting"
    assert module.classify_divergence(manifest([{ "name": "feature/auth", "parent": "main", "pr": 101 }, {"name": "feature/api", "parent": "feature/auth", "pr": 102}, {"name": "feature/ui", "parent": "feature/api", "pr": 103}]), value).kind == "local-only"


def test_plan_creates_native_stack_from_two_mapped_prs():
    module = load_module()
    data = manifest([
        {"name": "feature/auth", "parent": "main", "pr": 101},
        {"name": "feature/api", "parent": "feature/auth", "pr": 102},
    ])

    operations = module.plan_reconciliation(data, None)

    assert [item.action for item in operations] == ["create_stack"]
    assert operations[0].payload == {"pull_requests": [101, 102]}


def test_plan_appends_only_new_top_layers_with_expected_sha():
    module = load_module()
    data = manifest([
        {"name": "feature/auth", "parent": "main", "pr": 101},
        {"name": "feature/api", "parent": "feature/auth", "pr": 102},
        {"name": "feature/ui", "parent": "feature/api", "pr": 103},
    ])

    operations = module.plan_reconciliation(data, remote(module))

    assert [item.action for item in operations] == ["append_stack"]
    assert operations[0].payload["pull_requests"] == [103]
    assert operations[0].payload["expected_top_sha"] == "sha-api"


def test_unstack_requires_explicit_flag():
    module = load_module()
    data = manifest([{ "name": "feature/auth", "parent": "main", "pr": 101 }])

    blocked = module.plan_reconciliation(data, remote(module))
    allowed = module.plan_reconciliation(data, remote(module), unstack=True)

    assert blocked[0].action == "conflict"
    assert allowed[0].action == "unstack"


def test_apply_requires_local_authority_and_confirmation(tmp_path):
    module = load_module()

    class Client:
        pass

    operation = module.Operation("create_stack", "test", {"pull_requests": [101, 102]})
    with pytest.raises(module.StackSyncError, match="--yes"):
        module.apply_operations(Client(), "owner/repo", [operation], tmp_path / "state", tmp_path / "receipts", yes=False, authority="local")
    with pytest.raises(module.StackSyncError, match="local authority"):
        module.apply_operations(Client(), "owner/repo", [operation], tmp_path / "state", tmp_path / "receipts", yes=True, authority="github")


def test_404_stack_api_is_a_feature_fallback(monkeypatch):
    module = load_module()
    client = module.GitHubStackClient("owner/repo")
    monkeypatch.setattr(client, "request", lambda method, path, payload=None: (_ for _ in ()).throw(module.FeatureUnavailable("disabled")))

    with pytest.raises(module.FeatureUnavailable):
        client.stack_for_pull_request(101)


def test_404_response_is_converted_to_feature_fallback(monkeypatch):
    module = load_module()
    client = module.GitHubStackClient("owner/repo")

    class Result:
        returncode = 1
        stdout = ""
        stderr = "gh: Stacked PRs unavailable (HTTP 404)"

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Result())

    with pytest.raises(module.FeatureUnavailable, match="unavailable"):
        client.request("GET", "repos/owner/repo/stacks?pull_request=101")


def test_cli_accepts_json_after_or_before_command():
    module = load_module()

    before = module.build_parser().parse_args(["--json", "inspect", "--pr", "101"])
    after = module.build_parser().parse_args(["inspect", "--pr", "101", "--json"])

    assert before.json is True
    assert after.json is True


def test_relink_plan_carries_expected_head_sha():
    module = load_module()
    value = remote(module)
    data = module.import_manifest(manifest([]), value)
    data["branches"][1]["parent"] = "main"

    operations = module.plan_reconciliation(data, value)

    assert operations[0].action == "relink_pr"
    assert operations[0].payload["expected_head_sha"] == "sha-api"
