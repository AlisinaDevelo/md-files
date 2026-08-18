"""Tests for the digest-only host-authenticated admission contract."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/policy/scripts/forge-host-admission.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_host_admission_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ref(module, label: str) -> str:
    return module.digest_ref({"label": label})


def material(module, **overrides):
    value = {
        "host_ref": "host:codex",
        "audience_ref": "audience:github",
        "workspace_ref": "workspace:md-files",
        "resource_ref": "resource:repo/md-files",
        "request_ref": ref(module, "request"),
        "authority_ref": ref(module, "authority"),
        "action_ref": ref(module, "action"),
        "policy_decision_ref": ref(module, "policy-decision"),
        "approval_ref": ref(module, "approval"),
        "lease_ref": ref(module, "lease"),
        "runtime_episode_ref": ref(module, "episode"),
        "provider_operation_ref": ref(module, "provider-operation"),
        "provenance_ref": ref(module, "provenance"),
        "policy_revision_ref": ref(module, "policy"),
        "scope_refs": ["scope:repo.write", "scope:issue.create"],
        "auth": {
            "scheme": "dpop",
            "key_ref": "key:codex-host",
            "proof_ref": ref(module, "dpop-proof"),
            "verification_ref": ref(module, "host-verification"),
            "replay_protection": "sender-constrained",
        },
        "issued_at": "2026-08-18T12:00:00Z",
        "expires_at": "2026-08-18T12:05:00Z",
        "nonce": "nonce:host-admission-1",
        "generation": 3,
    }
    value.update(overrides)
    return value


def admission(module, **overrides):
    return module.make_admission(material(module, **overrides))


def verify_kwargs(module, value, **overrides):
    kwargs = {
        "expected_audience_ref": value["audience_ref"],
        "expected_workspace_ref": value["workspace_ref"],
        "expected_resource_ref": value["resource_ref"],
        "expected_request_ref": value["request_ref"],
        "expected_host_ref": value["host_ref"],
        "expected_scope_refs": value["scope_refs"],
        "expected_bindings": {
            field: value[field] for field in module.BINDING_FIELDS
        },
        "at": "2026-08-18T12:01:00Z",
    }
    kwargs.update(overrides)
    return kwargs


def test_valid_admission_is_external_digest_only_evidence():
    module = load_module()
    value = admission(module)

    result = module.verify_admission(value, **verify_kwargs(module, value))

    assert result["status"] == "passed"
    assert result["authentication_boundary"] == "external"
    assert result["admission_id"] == value["admission_id"]
    assert result["auth"]["scheme"] == "dpop"
    assert result["checks"]["host_proof_reference"] is True
    assert "signature" not in json.dumps(result, sort_keys=True)


def test_admission_digest_is_deterministic_and_binds_every_field():
    module = load_module()
    first = admission(module)
    second = admission(module)

    assert first == second
    assert module.admission_ref(first) == first["admission_id"]

    changed = copy.deepcopy(first)
    changed["provider_operation_ref"] = ref(module, "different-provider-operation")
    with pytest.raises(module.HostAdmissionError, match="admission-digest-mismatch"):
        module.verify_admission(changed, **verify_kwargs(module, first))


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("audience_ref", "audience_ref-mismatch"),
        ("workspace_ref", "workspace_ref-mismatch"),
        ("resource_ref", "resource_ref-mismatch"),
        ("request_ref", "request_ref-mismatch"),
    ],
)
def test_request_context_drift_fails_closed(field, message):
    module = load_module()
    value = admission(module)
    kwargs = verify_kwargs(module, value)
    parameter = {
        "audience_ref": "expected_audience_ref",
        "workspace_ref": "expected_workspace_ref",
        "resource_ref": "expected_resource_ref",
        "request_ref": "expected_request_ref",
    }[field]
    kwargs[parameter] = (
        "audience:other"
        if field == "audience_ref"
        else "workspace:other"
        if field == "workspace_ref"
        else "resource:other"
        if field == "resource_ref"
        else ref(module, "other-request")
    )
    with pytest.raises(module.HostAdmissionError, match=message):
        module.verify_admission(value, **kwargs)


def test_binding_drift_and_scope_escalation_fail_closed():
    module = load_module()
    value = admission(module)
    kwargs = verify_kwargs(module, value)
    kwargs["expected_bindings"] = {
        **kwargs["expected_bindings"],
        "lease_ref": ref(module, "different-lease"),
    }
    with pytest.raises(module.HostAdmissionError, match="lease_ref-mismatch"):
        module.verify_admission(value, **kwargs)

    with pytest.raises(module.HostAdmissionError, match="scope-escalation"):
        module.verify_admission(
            value,
            **verify_kwargs(module, value, expected_scope_refs=["scope:repo.read"]),
        )


def test_expiry_lifetime_replay_and_generation_are_enforced():
    module = load_module()
    value = admission(module)
    with pytest.raises(module.HostAdmissionError, match="expired-or-not-yet-valid"):
        module.verify_admission(
            value,
            **verify_kwargs(module, value, at="2026-08-18T12:05:00Z"),
        )
    with pytest.raises(module.HostAdmissionError, match="admission-lifetime-too-long"):
        module.verify_admission(
            admission(module, expires_at="2026-08-18T12:20:00Z"),
            **verify_kwargs(module, value),
        )
    with pytest.raises(module.HostAdmissionError, match="nonce-replay"):
        module.verify_admission(
            value,
            **verify_kwargs(module, value, seen_nonces=[value["nonce"]]),
        )
    with pytest.raises(module.HostAdmissionError, match="stale-generation"):
        module.verify_admission(
            value,
            **verify_kwargs(module, value, generation_state={value["host_ref"]: 4}),
        )


def test_authentication_scheme_requires_matching_replay_protection():
    module = load_module()
    with pytest.raises(module.HostAdmissionError, match="sender-constrained-auth"):
        admission(
            module,
            auth={
                "scheme": "mtls",
                "key_ref": "key:codex-host",
                "proof_ref": ref(module, "mtls-proof"),
                "verification_ref": ref(module, "host-verification"),
                "replay_protection": "nonce-cache",
            },
        )
    with pytest.raises(module.HostAdmissionError, match="bearer-auth"):
        admission(
            module,
            auth={
                "scheme": "oauth2-bearer",
                "key_ref": "key:codex-host",
                "proof_ref": ref(module, "oauth-proof"),
                "verification_ref": ref(module, "host-verification"),
                "replay_protection": "sender-constrained",
            },
        )


def test_raw_credentials_and_unknown_proof_material_are_rejected():
    module = load_module()
    value = material(module)
    value["auth"]["access_token"] = "Bearer should-never-enter-forge"
    with pytest.raises(module.HostAdmissionError, match="credential material"):
        module.make_admission(value)

    value = material(module)
    value["auth"]["signature"] = "opaque-signature"
    with pytest.raises(module.HostAdmissionError, match="credential material"):
        module.make_admission(value)


def test_schema_is_strict_and_corpus_report_is_deterministic(tmp_path):
    module = load_module()
    schema = json.loads(
        (REPO / "data/runtime-host-admission.schema.json").read_text(encoding="utf-8")
    )
    assert schema["properties"]["contract_revision"]["const"] == module.CONTRACT_REVISION
    assert schema["additionalProperties"] is False

    corpus = tmp_path / "corpus.jsonl"
    value = admission(module)
    cases = [
        {
            "case_id": "valid",
            "expected": "passed",
            "admission": value,
            "context": verify_kwargs(module, value),
        },
        {
            "case_id": "replay",
            "expected": "failed",
            "admission": value,
            "context": verify_kwargs(module, value, seen_nonces=[value["nonce"]]),
        },
    ]
    corpus.write_text(
        "\n".join(json.dumps(case, sort_keys=True) for case in cases) + "\n",
        encoding="utf-8",
    )
    first = module.evaluate_corpus(corpus)
    second = module.evaluate_corpus(corpus)
    assert first == second
    assert first["status"] == "passed"
    assert first["case_count"] == 2
    assert first["threat_cases"] == 1
