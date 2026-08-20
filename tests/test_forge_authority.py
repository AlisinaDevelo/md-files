"""Offline identity and delegated-authority contract tests."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/policy/scripts/forge-authority.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_authority", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ref(module, value: str) -> str:
    return module.digest_ref(value)


def identity(module, *, subject: str, scopes: list[str], tools: list[str], intents: list[str], profile: str = "authority-v1"):
    value = {
        "schema_version": 1,
        "contract_revision": module.CONTRACT_REVISION,
        "kind": "identity",
        "profile": profile,
        "issuer_ref": "human:owner",
        "subject_ref": subject,
        "agent_ref": subject,
        "build_ref": ref(module, "build:forge"),
        "audience_ref": "host:forge",
        "workspace_ref": "workspace:md-files",
        "scopes": scopes,
        "resource_refs": ["resource:repo/md-files"],
        "tool_refs": tools,
        "intent_refs": intents,
        "issued_at": "2026-08-18T12:00:00Z",
        "expires_at": "2026-08-18T13:00:00Z",
        "nonce": f"nonce:{subject.replace(':', '-')}",
        "revocation_ref": ref(module, "revocation:forge"),
        "policy_revision_ref": ref(module, "policy:review"),
        "generation": 1,
        "legacy_principal": "principal:alice" if profile == "legacy-principal-v1" else None,
    }
    value["proof"] = module.external_proof(value)
    return value


def delegation(module, *, issuer: str, subject: str, parent: str | None, scopes: list[str], tools: list[str], intents: list[str]):
    value = {
        "schema_version": 1,
        "contract_revision": module.CONTRACT_REVISION,
        "kind": "delegation",
        "delegation_id": "delegation:worker",
        "issuer_identity_ref": issuer,
        "subject_identity_ref": subject,
        "parent_delegation_ref": parent,
        "audience_ref": "host:forge",
        "workspace_ref": "workspace:md-files",
        "scopes": scopes,
        "resource_refs": ["resource:repo/md-files"],
        "tool_refs": tools,
        "intent_refs": intents,
        "issued_at": "2026-08-18T12:10:00Z",
        "expires_at": "2026-08-18T12:50:00Z",
        "nonce": "nonce:delegation-worker",
        "revocation_ref": ref(module, "revocation:forge"),
        "policy_revision_ref": ref(module, "policy:review"),
        "generation": 1,
    }
    value["proof"] = module.external_proof(value)
    return value


def bundle(module, *, scope_escalation: bool = False, tool: str = "tool:github.issue.create", intent: str | None = None, parent_override: str | None = None, legacy: bool = False):
    intent_ref = intent or ref(module, "intent:build")
    root = identity(
        module,
        subject="agent:planner",
        scopes=["scope:repo.read", "scope:repo.write"],
        tools=["tool:git.read", "tool:github.issue.create"],
        intents=[ref(module, "intent:build")],
        profile="legacy-principal-v1" if legacy else "authority-v1",
    )
    root_ref = module.identity_ref(root)
    child = identity(
        module,
        subject="agent:worker",
        scopes=["scope:repo.write"],
        tools=["tool:github.issue.create"],
        intents=[ref(module, "intent:build")],
    )
    child_ref = module.identity_ref(child)
    delegated_scopes = ["scope:repo.admin"] if scope_escalation else ["scope:repo.write"]
    delegated = delegation(
        module,
        issuer=root_ref,
        subject=child_ref,
        parent=parent_override,
        scopes=delegated_scopes,
        tools=["tool:github.issue.create"],
        intents=[ref(module, "intent:build")],
    )
    authority_ref = module.delegation_ref(delegated)
    action = {
        "schema_version": 1,
        "contract_revision": module.CONTRACT_REVISION,
        "kind": "action",
        "actor_identity_ref": child_ref,
        "authority_ref": authority_ref,
        "audience_ref": "host:forge",
        "workspace_ref": "workspace:md-files",
        "capability": "scope:repo.write",
        "resource_ref": "resource:repo/md-files",
        "tool_ref": tool,
        "effect_ref": "effect:issue-create",
        "intent_ref": intent_ref,
        "policy_decision_ref": ref(module, "placeholder:policy"),
        "approval_ref": ref(module, "placeholder:approval"),
        "runtime_episode_ref": ref(module, "run:episode"),
        "provider_operation_ref": ref(module, "provider:operation"),
        "provenance_ref": ref(module, "provenance:receipt"),
        "lease_ref": ref(module, "lease:worker"),
        "delegation_generation": 1,
        "issued_at": "2026-08-18T12:20:00Z",
        "expires_at": "2026-08-18T12:40:00Z",
        "nonce": "nonce:action-issue-create",
    }
    action["proof"] = module.external_proof(action)
    action_operation_ref = module.action_ref(action)
    approval = {
        "schema_version": 1,
        "contract_revision": module.CONTRACT_REVISION,
        "kind": "approval",
        "status": "not-required",
        "action_ref": action_operation_ref,
        "actor_identity_ref": child_ref,
        "authority_ref": authority_ref,
        "approver_ref": "policy:review",
        "audience_ref": "host:forge",
        "workspace_ref": "workspace:md-files",
        "capability": "scope:repo.write",
        "resource_ref": "resource:repo/md-files",
        "policy_revision_ref": ref(module, "policy:review"),
        "lease_ref": ref(module, "lease:worker"),
        "delegation_generation": 1,
        "expires_at": "2026-08-18T12:40:00Z",
    }
    approval_digest = module.approval_ref(approval)
    authorization = {
        "schema_version": 1,
        "contract_revision": module.CONTRACT_REVISION,
        "kind": "authorization",
        "decision": "allow",
        "action_ref": action_operation_ref,
        "actor_identity_ref": child_ref,
        "authority_ref": authority_ref,
        "audience_ref": "host:forge",
        "workspace_ref": "workspace:md-files",
        "capability": "scope:repo.write",
        "resource_ref": "resource:repo/md-files",
        "policy_revision_ref": ref(module, "policy:review"),
        "approval_ref": approval_digest,
        "lease_ref": ref(module, "lease:worker"),
        "delegation_generation": 1,
        "expires_at": "2026-08-18T12:40:00Z",
    }
    action["policy_decision_ref"] = module.authorization_ref(authorization)
    action["approval_ref"] = approval_digest
    action["proof"] = module.external_proof(action)
    return {
        "schema_version": 1,
        "contract_revision": module.CONTRACT_REVISION,
        "identities": [root, child],
        "delegations": [delegated],
        "action": action,
        "authorization": authorization,
        "approval": approval,
    }


def trust(module, *, revoked_refs: list[str] | None = None, minimum_generations: dict[str, int] | None = None):
    return {
        "schema_version": 1,
        "contract_revision": module.CONTRACT_REVISION,
        "keys": [{"key_id": "key:external", "algorithm": "ed25519", "status": "external"}],
        "revoked_refs": revoked_refs or [],
        "minimum_generations": minimum_generations or {},
    }


def verify(module, value, *, at="2026-08-18T12:30:00Z", audience="host:forge", seen=None, generations=None, trust_policy=None):
    return module.verify_bundle(
        value,
        trust_policy=trust_policy or trust(module),
        expected_audience_ref=audience,
        expected_workspace_ref="workspace:md-files",
        at=at,
        seen_nonces=seen or [],
        generation_state=generations or {},
    )


def test_valid_chain_binds_policy_approval_lease_runtime_and_provenance():
    module = load_module()
    result = verify(module, bundle(module))
    assert result["status"] == "passed"
    assert result["authentication_boundary"] == "external"
    assert result["checks"]["policy_revision_binding"] is True
    assert result["checks"]["lease_binding"] is True
    assert result["checks"]["policy_approval_binding"] is True
    assert set(result["binding_refs"]) == {"lease_ref", "runtime_episode_ref", "provider_operation_ref", "provenance_ref"}


def test_child_delegation_must_narrow_every_authority_dimension():
    module = load_module()
    value = bundle(module, scope_escalation=True)
    with pytest.raises(module.AuthorityError, match="scope-escalation"):
        verify(module, value)


def test_goal_hijack_and_tool_poisoning_are_rejected():
    module = load_module()
    goal_hijack = bundle(module, intent=ref(module, "intent:unapproved"))
    with pytest.raises(module.AuthorityError, match="intent-scope-mismatch"):
        verify(module, goal_hijack)
    poisoned_tool = bundle(module, tool="tool:poisoned")
    with pytest.raises(module.AuthorityError, match="tool-scope-mismatch"):
        verify(module, poisoned_tool)


def test_rogue_delegation_and_audience_drift_fail_closed():
    module = load_module()
    value = bundle(module, parent_override=ref(module, "delegation:unrelated"))
    with pytest.raises(module.AuthorityError, match="rogue-delegation"):
        verify(module, value)
    with pytest.raises(module.AuthorityError, match="audience-or-workspace-drift"):
        verify(module, bundle(module), audience="host:other")


def test_expiry_revocation_generation_and_nonce_replay_fail_closed():
    module = load_module()
    value = bundle(module)
    with pytest.raises(module.AuthorityError, match="expired-or-not-yet-valid"):
        verify(module, value, at="2026-08-18T13:00:00Z")
    root_ref = module.identity_ref(value["identities"][0])
    with pytest.raises(module.AuthorityError, match="revoked"):
        verify(module, value, trust_policy=trust(module, revoked_refs=[root_ref]))
    final_ref = module.delegation_ref(value["delegations"][0])
    with pytest.raises(module.AuthorityError, match="delegation-generation-changed"):
        verify(module, value, generations={final_ref: 2})
    with pytest.raises(module.AuthorityError, match="nonce-replay"):
        verify(module, value, seen=["nonce:action-issue-create"])


def test_legacy_principal_is_explicit_and_still_scope_bound():
    module = load_module()
    value = bundle(module, legacy=True)
    result = verify(module, value)
    assert result["legacy_profile"] is True
    poisoned = copy.deepcopy(value)
    poisoned["action"]["resource_ref"] = "resource:other-repo"
    poisoned["action"]["proof"] = module.external_proof(poisoned["action"])
    with pytest.raises(module.AuthorityError, match="resource-scope-mismatch"):
        verify(module, poisoned)


def test_lease_binding_cannot_be_reassigned_after_authorization():
    module = load_module()
    value = bundle(module)
    value["authorization"]["lease_ref"] = ref(module, "lease:other")
    value["action"]["policy_decision_ref"] = module.authorization_ref(value["authorization"])
    value["action"]["proof"] = module.external_proof(value["action"])
    with pytest.raises(module.AuthorityError, match="authorization-binding-mismatch:lease_ref"):
        verify(module, value)


def test_policy_revision_drift_cannot_rebind_an_effect():
    module = load_module()
    value = bundle(module)
    value["authorization"]["policy_revision_ref"] = ref(module, "policy:other")
    value["action"]["policy_decision_ref"] = module.authorization_ref(value["authorization"])
    value["action"]["proof"] = module.external_proof(value["action"])
    with pytest.raises(module.AuthorityError, match="policy-revision-binding-mismatch"):
        verify(module, value)


def test_local_hmac_proof_is_supported_without_exporting_key_material():
    module = load_module()
    statement = {"schema_version": 1, "kind": "test", "value_ref": ref(module, "value:test")}
    statement["proof"] = module.local_proof(statement, key_id="key:local", key=b"forge-authority-test-key")
    policy = {
        "schema_version": 1,
        "contract_revision": module.CONTRACT_REVISION,
        "keys": [
            {
                "key_id": "key:local",
                "algorithm": "hmac-sha256",
                "status": "active",
                "key_b64": "Zm9yZ2UtYXV0aG9yaXR5LXRlc3Qta2V5",
            }
        ],
        "revoked_refs": [],
        "minimum_generations": {},
    }
    assert module._verify_proof(statement, "test", module._trust_policy(policy)) == "local"
    assert "forge-authority-test-key" not in json.dumps(statement)


def test_authority_schema_is_versioned_and_strict():
    schema = json.loads((REPO / "data/runtime-authority.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"].endswith("/authority/v1")
    assert schema["properties"]["contract_revision"]["const"] == "forge-authority-v1"
    assert schema["$defs"]["action"]["additionalProperties"] is False
