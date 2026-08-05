"""Definition identity and replay-compatibility contract tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge_definitions.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_definitions", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def definition(module, version="v1", *, compatible_with=()):
    return module.make_definition(
        workflow_id="feature-flow",
        definition_version=version,
        worker_build_id=f"worker-{version}",
        policy_revision="policy-v1",
        compatible_definition_digests=compatible_with,
    )


def test_definition_digest_is_canonical_and_tamper_evident():
    module = load_module()
    first = definition(module)
    second = definition(module)

    assert first == second
    assert first["definition_digest"].startswith("sha256:")
    assert module.normalize_definition(first) == first

    tampered = {**first, "worker_build_id": "worker-attacker"}
    with pytest.raises(module.DefinitionError, match="definition_digest does not match"):
        module.normalize_definition(tampered)


def test_declared_compatibility_accepts_only_the_pinned_digest():
    module = load_module()
    pinned = definition(module, "v1")
    candidate = definition(module, "v2", compatible_with=(pinned["definition_digest"],))

    accepted = module.compare_definitions(pinned, candidate, operation="replay")
    assert accepted["decision"] == "accepted"
    assert accepted["reason_code"] == "declared_compatible"
    assert accepted["differences"] == ["definition_digest"]
    migrated = module.compare_definitions(pinned, candidate, operation="migration")
    assert migrated["decision"] == "accepted"
    assert migrated["reason_code"] == "declared_compatible"

    unrelated = definition(module, "v3")
    rejected = module.compare_definitions(pinned, unrelated, operation="replay")
    assert rejected["decision"] == "rejected"
    assert rejected["reason_code"] == "definition_mismatch"
    assert "worker_build_id" in rejected["differences"]
    assert rejected["decision_digest"].startswith("sha256:")


def test_continue_as_new_is_an_explicit_boundary_and_workflow_mismatch_rejects():
    module = load_module()
    pinned = definition(module, "v1")
    candidate = definition(module, "v2")

    transition = module.compare_definitions(pinned, candidate, operation="continue_as_new")
    assert transition["decision"] == "accepted"
    assert transition["reason_code"] == "explicit_boundary"
    assert transition["requires_new_run"] is True

    other = module.make_definition(
        workflow_id="other-flow",
        definition_version="v1",
        worker_build_id="worker-v1",
        policy_revision="policy-v1",
    )
    rejected = module.compare_definitions(pinned, other, operation="replay")
    assert rejected["decision"] == "rejected"
    assert rejected["reason_code"] == "workflow_mismatch"


def test_registry_aliases_select_new_runs_and_retirement_preserves_resolution():
    module = load_module()
    current = definition(module, "v1")
    next_definition = definition(module, "v2", compatible_with=(current["definition_digest"],))
    registry = module.DefinitionRegistry()
    registry.register(current, aliases=("stable",))
    registry.register(next_definition, rollout="canary", aliases=("canary",))

    selected = registry.select("stable")
    assert selected["definition"] == current
    assert selected["selection"]["new_run_only"] is True

    registry.redirect("stable", next_definition["definition_digest"])
    redirected = registry.select("stable")
    assert redirected["definition"] == next_definition
    assert redirected["selection"]["redirected_from"] == current["definition_digest"]

    registry.rollback("stable")
    assert registry.select("stable")["definition"] == current
    registry.redirect("stable", next_definition["definition_digest"])

    registry.retire(next_definition["definition_digest"])
    with pytest.raises(module.DefinitionError, match="retired"):
        registry.select("stable")
    assert registry.resolve(next_definition["definition_digest"]) == next_definition


def test_definition_validation_rejects_unknown_fields_and_bad_digest_references():
    module = load_module()
    current = definition(module)
    with pytest.raises(module.DefinitionError, match="unsupported fields"):
        module.normalize_definition({**current, "prompt": "never"})
    with pytest.raises(module.DefinitionError, match="sha256 reference"):
        module.make_definition(
            workflow_id="feature-flow",
            definition_version="v1",
            worker_build_id="worker-v1",
            policy_revision="policy-v1",
            policy_digest="raw-policy",
        )


def test_workflow_digests_and_step_identities_are_deterministic():
    module = load_module()
    code_digest = "sha256:" + "1" * 64
    schema_digest = "sha256:" + "2" * 64
    first = module.make_definition(
        workflow_id="feature-flow",
        definition_version="v1",
        worker_build_id="worker-v1",
        policy_revision="policy-v1",
        workflow_code_digest=code_digest,
        workflow_schema_digest=schema_digest,
    )
    assert first["workflow_code_digest"] == code_digest
    assert first["workflow_schema_digest"] == schema_digest
    assert module.stable_step_identity("feature-flow", "build/package") == module.stable_step_identity(
        "feature-flow", "build/package"
    )
    assert module.stable_step_identity("feature-flow", "build/package") != module.stable_step_identity(
        "feature-flow", "test/package"
    )
    key = module.stable_idempotency_key("run-1", "forge-step:" + "a" * 64, "execute", attempt=2)
    assert key == module.stable_idempotency_key("run-1", "forge-step:" + "a" * 64, "execute", attempt=2)
    assert key != module.stable_idempotency_key("run-1", "forge-step:" + "a" * 64, "execute", attempt=3)
