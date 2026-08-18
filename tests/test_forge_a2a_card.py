"""Tests for the digest-only A2A Agent Card trust contract."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-a2a-card.py"
CORPUS = REPO / "tests/fixtures/a2a-card/v1.jsonl"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_a2a_card_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def card():
    return {
        "name": "Forge Test Agent",
        "description": "A deterministic A2A test card.",
        "supportedInterfaces": [
            {
                "url": "https://agent.example.test/a2a",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "provider": {
            "organization": "Example Agent Systems",
            "url": "https://provider.example.test",
        },
        "version": "1.0.0",
        "capabilities": {
            "streaming": False,
            "extensions": [
                {
                    "uri": "urn:example:a2a:trace:v1",
                    "description": "Trace correlation extension.",
                    "required": True,
                }
            ],
        },
        "securitySchemes": {
            "oauth": {
                "oauth2SecurityScheme": {
                    "flows": {
                        "clientCredentials": {
                            "tokenUrl": "https://identity.example.test/token",
                            "scopes": {"forge.read": "Read route data"},
                        }
                    }
                }
            }
        },
        "securityRequirements": [{"schemes": {"oauth": {"list": ["forge.read"]}}}],
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "route-plan",
                "name": "Route planning",
                "description": "Plans a route from structured constraints.",
                "tags": ["routing"],
            }
        ],
        "signatures": [
            {
                "protected": "eyJhbGciOiJFUzI1NiIsImtpZCI6ImtleTphMmEtZGVtbyIsInR5cCI6IkpPU0UifQ",
                "signature": "c2lnbmF0dXJlLWJ5dGVz",
            }
        ],
        "x-forward-compatible": {"revision": 1},
    }


def context(**overrides):
    value = {
        "expected_host_ref": "host:codex",
        "expected_audience_ref": "audience:a2a",
        "expected_workspace_ref": "workspace:md-files",
        "expected_resource_ref": "resource:repo/md-files",
        "expected_protocol_versions": ["1.0"],
        "required_skill_ids": ["route-plan"],
        "required_security_scheme_names": ["oauth"],
        "supported_extension_uris": ["urn:example:a2a:trace:v1"],
    }
    value.update(overrides)
    return value


def verify(module, value, **overrides):
    return module.verify_card(value, **context(**overrides))


def test_valid_signed_card_emits_digest_only_external_evidence():
    module = load_module()
    result = verify(module, card())

    assert result["$schema"] == module.SCHEMA_URI
    assert result["status"] == "passed"
    assert result["authentication_boundary"] == "external-reference"
    assert result["signature_verification"] == "external-reference"
    assert result["authority_grant"] is False
    assert result["unknown_field_count"] == 1
    encoded = json.dumps(result, sort_keys=True)
    assert "c2lnbmF0dXJlLWJ5dGVz" not in encoded
    assert "A deterministic A2A test card." not in encoded


def test_card_and_report_digests_are_deterministic_and_bind_unknown_fields():
    module = load_module()
    first = verify(module, card())
    second = verify(module, copy.deepcopy(card()))

    assert first == second
    changed = copy.deepcopy(card())
    changed["x-forward-compatible"]["revision"] = 2
    assert module.digest_ref(changed) != first["card_ref"]


def test_empty_skill_list_is_valid_and_unsigned_cards_are_explicit():
    module = load_module()
    value = card()
    value["skills"] = []
    value["capabilities"]["extensions"] = []
    value.pop("signatures")
    result = verify(module, value, required_skill_ids=[], supported_extension_uris=[])

    assert result["skill_refs"] == []
    assert result["signature_count"] == 0
    assert result["authentication_boundary"] == "declared-only"
    assert result["signature_verification"] == "not-provided"


def test_security_detector_allows_benign_authentication_documentation():
    module = load_module()
    value = card()
    value["description"] = "Explains how clients use a Bearer token."
    result = verify(module, value)

    assert result["status"] == "passed"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value["supportedInterfaces"][0].update({"url": "http://agent.example.test"}), "insecure"),
        (lambda value: value["supportedInterfaces"][0].update({"protocolVersion": "0.3"}), "protocol-version"),
        (lambda value: value["skills"].append(copy.deepcopy(value["skills"][0])), "duplicate-skill-id"),
        (lambda value: value.update({"x-token": "Bearer " + "a" * 24}), "credential-shaped"),
        (
            lambda value: value["securitySchemes"]["oauth"]["oauth2SecurityScheme"]["flows"][
                "clientCredentials"
            ].update({"tokenUrl": "http://identity.example.test/token"}),
            "insecure",
        ),
    ],
)
def test_untrusted_card_mutations_fail_closed(change, message):
    module = load_module()
    value = card()
    change(value)

    with pytest.raises(module.A2ACardError, match=message):
        verify(module, value)


def test_required_extension_and_card_digest_mismatches_fail_closed():
    module = load_module()
    with pytest.raises(module.A2ACardError, match="required-extension-unsupported"):
        verify(module, card(), supported_extension_uris=[])

    expected = module.digest_ref(card())
    changed = card()
    changed["description"] = "changed"
    with pytest.raises(module.A2ACardError, match="card-digest-mismatch"):
        verify(module, changed, expected_card_ref=expected)


def test_duplicate_report_references_fail_closed():
    module = load_module()
    value = card()
    value["supportedInterfaces"].append(copy.deepcopy(value["supportedInterfaces"][0]))

    with pytest.raises(module.A2ACardError, match="duplicate-interface-reference"):
        verify(module, value)


def test_extended_card_requires_declared_authentication():
    module = load_module()
    value = card()
    value["capabilities"]["extendedAgentCard"] = True
    value.pop("securityRequirements")

    with pytest.raises(module.A2ACardError, match="extended-agent-card-requires-authentication"):
        verify(module, value)


def test_schema_is_strict_and_corpus_is_deterministic():
    module = load_module()
    schema = json.loads(
        (REPO / "data/runtime-a2a-card.schema.json").read_text(encoding="utf-8")
    )

    assert schema["properties"]["contract_revision"]["const"] == module.CONTRACT_REVISION
    assert schema["additionalProperties"] is False

    first = module.evaluate_corpus(CORPUS)
    second = module.evaluate_corpus(CORPUS)
    assert first == second
    assert first["status"] == "passed"
    assert first["case_count"] == 4
    assert first["threat_cases"] == 3
