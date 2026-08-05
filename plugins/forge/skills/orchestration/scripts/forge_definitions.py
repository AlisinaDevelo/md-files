#!/usr/bin/env python3
"""Digest-addressed workflow definitions and replay compatibility decisions."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any

DEFINITION_SCHEMA_VERSION = 1
COMPATIBILITY_SCHEMA_VERSION = 1
DEFAULT_COMPATIBILITY_REVISION = "forge-replay-v1"
DEFAULT_STEP_IDENTITY_REVISION = "forge-step-id-v1"
MAX_COMPATIBLE_DEFINITIONS = 32
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/_-]{0,127}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ROLLOUT_STATES = {"active", "canary", "redirected", "retired"}
COMPATIBILITY_OPERATIONS = {
    "replay",
    "checkpoint_restore",
    "effect_retry",
    "migration",
    "continue_as_new",
}
IDENTITY_FIELDS = (
    "workflow_id",
    "definition_version",
    "workflow_code_digest",
    "workflow_schema_digest",
    "worker_build_id",
    "policy_revision",
    "policy_digest",
    "feature_flags_digest",
    "compatibility_revision",
    "step_identity_revision",
    "compatible_definition_digests",
)
DESCRIPTOR_FIELDS = {
    "schema_version",
    *IDENTITY_FIELDS,
    "definition_digest",
}


class DefinitionError(ValueError):
    """Raised when a definition or compatibility decision is invalid."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return "sha256:" + sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise DefinitionError(f"{field} must be a non-empty string of at most 128 characters")
    return value


def _identifier(value: Any, field: str) -> str:
    value = _text(value, field)
    if not IDENTIFIER_RE.fullmatch(value):
        raise DefinitionError(f"{field} contains unsupported characters")
    return value


def _digest_reference(value: Any, field: str) -> str:
    value = _text(value, field)
    if not DIGEST_RE.fullmatch(value):
        raise DefinitionError(f"{field} must be a sha256 reference")
    return value


def _compatible_digests(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DefinitionError("compatible_definition_digests must be a string array")
    if len(value) > MAX_COMPATIBLE_DEFINITIONS:
        raise DefinitionError(
            f"compatible_definition_digests must contain at most {MAX_COMPATIBLE_DEFINITIONS} entries"
        )
    result = sorted({_digest_reference(item, "compatible_definition_digests") for item in value})
    return result


def _definition_material(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": descriptor["schema_version"],
        **{field: descriptor[field] for field in IDENTITY_FIELDS},
    }


def _definition_digest(descriptor: Mapping[str, Any]) -> str:
    return _digest(_definition_material(descriptor))


def normalize_definition(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a definition and verify its digest when one is supplied."""

    if not isinstance(value, Mapping):
        raise DefinitionError("definition must be a JSON object")
    unknown = sorted(str(key) for key in value if key not in DESCRIPTOR_FIELDS)
    if unknown:
        raise DefinitionError("definition contains unsupported fields: " + ", ".join(unknown))
    schema_version = value.get("schema_version", DEFINITION_SCHEMA_VERSION)
    if schema_version != DEFINITION_SCHEMA_VERSION:
        raise DefinitionError(f"unsupported definition schema_version: {schema_version}")
    workflow_id = _identifier(value.get("workflow_id"), "workflow_id")
    definition_version = _text(value.get("definition_version"), "definition_version")
    workflow_code_digest = value.get("workflow_code_digest") or _digest(
        {"kind": "workflow-code", "workflow_id": workflow_id, "definition_version": definition_version}
    )
    workflow_schema_digest = value.get("workflow_schema_digest") or _digest(
        {"kind": "workflow-schema", "workflow_id": workflow_id, "definition_version": definition_version}
    )
    worker_build_id = _text(value.get("worker_build_id"), "worker_build_id")
    policy_revision = _text(value.get("policy_revision"), "policy_revision")
    policy_digest = value.get("policy_digest") or _digest({"policy_revision": policy_revision})
    feature_flags_digest = value.get("feature_flags_digest") or _digest({})
    normalized = {
        "schema_version": DEFINITION_SCHEMA_VERSION,
        "workflow_id": workflow_id,
        "definition_version": definition_version,
        "workflow_code_digest": _digest_reference(workflow_code_digest, "workflow_code_digest"),
        "workflow_schema_digest": _digest_reference(workflow_schema_digest, "workflow_schema_digest"),
        "worker_build_id": worker_build_id,
        "policy_revision": policy_revision,
        "policy_digest": _digest_reference(policy_digest, "policy_digest"),
        "feature_flags_digest": _digest_reference(feature_flags_digest, "feature_flags_digest"),
        "compatibility_revision": _text(
            value.get("compatibility_revision", DEFAULT_COMPATIBILITY_REVISION), "compatibility_revision"
        ),
        "step_identity_revision": _text(
            value.get("step_identity_revision", DEFAULT_STEP_IDENTITY_REVISION), "step_identity_revision"
        ),
        "compatible_definition_digests": _compatible_digests(value.get("compatible_definition_digests")),
    }
    expected_digest = _definition_digest(normalized)
    supplied_digest = value.get("definition_digest")
    if supplied_digest is not None:
        supplied_digest = _digest_reference(supplied_digest, "definition_digest")
        if supplied_digest != expected_digest:
            raise DefinitionError("definition_digest does not match definition identity")
    normalized["definition_digest"] = expected_digest
    return normalized


def make_definition(
    *,
    workflow_id: str,
    definition_version: str,
    worker_build_id: str,
    policy_revision: str,
    workflow_code_digest: str | None = None,
    workflow_schema_digest: str | None = None,
    policy_digest: str | None = None,
    feature_flags_digest: str | None = None,
    compatibility_revision: str = DEFAULT_COMPATIBILITY_REVISION,
    step_identity_revision: str = DEFAULT_STEP_IDENTITY_REVISION,
    compatible_definition_digests: Sequence[str] = (),
) -> dict[str, Any]:
    """Create a canonical immutable definition descriptor."""

    return normalize_definition(
        {
            "workflow_id": workflow_id,
            "definition_version": definition_version,
            "worker_build_id": worker_build_id,
            "policy_revision": policy_revision,
            "workflow_code_digest": workflow_code_digest,
            "workflow_schema_digest": workflow_schema_digest,
            "policy_digest": policy_digest,
            "feature_flags_digest": feature_flags_digest,
            "compatibility_revision": compatibility_revision,
            "step_identity_revision": step_identity_revision,
            "compatible_definition_digests": list(compatible_definition_digests),
        }
    )


def legacy_definition(workflow_id: str, definition_version: str, policy_revision: str) -> dict[str, Any]:
    """Derive a deterministic descriptor for histories created before v4 pinning."""

    return make_definition(
        workflow_id=workflow_id,
        definition_version=definition_version,
        worker_build_id="legacy",
        policy_revision=policy_revision,
    )


def stable_step_identity(
    workflow_id: str,
    step_path: str,
    *,
    step_identity_revision: str = DEFAULT_STEP_IDENTITY_REVISION,
) -> str:
    """Return a privacy-safe, deterministic identity for one workflow step."""

    material = {
        "workflow_id": _identifier(workflow_id, "workflow_id"),
        "step_path": _identifier(step_path, "step_path"),
        "step_identity_revision": _text(step_identity_revision, "step_identity_revision"),
    }
    return "forge-step:" + sha256(canonical_json(material).encode("utf-8")).hexdigest()


def stable_idempotency_key(
    run_id: str,
    step_identity: str,
    operation: str,
    *,
    attempt: int = 1,
) -> str:
    """Return a deterministic idempotency key bound to a run, step, and attempt."""

    run_id = _identifier(run_id, "run_id")
    step_identity = _text(step_identity, "step_identity")
    operation = _identifier(operation, "operation")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise DefinitionError("attempt must be a positive integer")
    material = {
        "run_id": run_id,
        "step_identity": step_identity,
        "operation": operation,
        "attempt": attempt,
    }
    return "forge-idem:" + sha256(canonical_json(material).encode("utf-8")).hexdigest()


def compare_definitions(
    pinned: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    operation: str = "replay",
) -> dict[str, Any]:
    """Return a deterministic, digest-bound compatibility decision."""

    if operation not in COMPATIBILITY_OPERATIONS:
        expected = ", ".join(sorted(COMPATIBILITY_OPERATIONS))
        raise DefinitionError(f"operation must be one of: {expected}")
    pinned = normalize_definition(pinned)
    candidate = normalize_definition(candidate)
    differences = [field for field in IDENTITY_FIELDS if pinned[field] != candidate[field]]
    same_digest = pinned["definition_digest"] == candidate["definition_digest"]
    same_workflow = pinned["workflow_id"] == candidate["workflow_id"]
    same_compatibility = pinned["compatibility_revision"] == candidate["compatibility_revision"]
    requires_new_run = operation == "continue_as_new"

    if same_digest:
        decision = "accepted"
        reason_code = "exact_definition"
        reported_differences: list[str] = []
    elif requires_new_run and same_workflow and same_compatibility:
        decision = "accepted"
        reason_code = "explicit_boundary"
        reported_differences = ["definition_digest", *differences]
    elif (
        operation in {"replay", "checkpoint_restore", "effect_retry", "migration"}
        and same_workflow
        and same_compatibility
        and pinned["definition_digest"] in candidate["compatible_definition_digests"]
    ):
        decision = "accepted"
        reason_code = "declared_compatible"
        reported_differences = ["definition_digest"]
    else:
        decision = "rejected"
        if not same_workflow:
            reason_code = "workflow_mismatch"
        elif not same_compatibility:
            reason_code = "compatibility_revision_mismatch"
        else:
            reason_code = "definition_mismatch"
        reported_differences = ["definition_digest", *differences]

    result = {
        "schema_version": COMPATIBILITY_SCHEMA_VERSION,
        "operation": operation,
        "decision": decision,
        "reason_code": reason_code,
        "requires_new_run": requires_new_run,
        "pinned_definition_digest": pinned["definition_digest"],
        "candidate_definition_digest": candidate["definition_digest"],
        "differences": sorted(set(reported_differences)),
    }
    result["decision_digest"] = _digest(result)
    return result


class DefinitionRegistry:
    """Small offline rollout registry; runtime runs retain their selected digest."""

    def __init__(self) -> None:
        self._definitions: dict[str, dict[str, Any]] = {}
        self._rollouts: dict[str, str] = {}
        self._aliases: dict[str, str] = {}
        self._alias_history: dict[str, list[str]] = {}

    def register(
        self,
        value: Mapping[str, Any],
        *,
        aliases: Sequence[str] = (),
        rollout: str = "active",
    ) -> dict[str, Any]:
        if rollout not in ROLLOUT_STATES:
            expected = ", ".join(sorted(ROLLOUT_STATES))
            raise DefinitionError(f"rollout must be one of: {expected}")
        descriptor = normalize_definition(value)
        digest = descriptor["definition_digest"]
        existing = self._definitions.get(digest)
        if existing is not None and existing != descriptor:
            raise DefinitionError(f"definition digest is already registered with different content: {digest}")
        self._definitions[digest] = copy.deepcopy(descriptor)
        self._rollouts[digest] = rollout
        for alias in aliases:
            alias = _identifier(alias, "alias")
            if alias in self._aliases and self._aliases[alias] != digest:
                raise DefinitionError(f"alias already points to another definition: {alias}")
            self._aliases[alias] = digest
            self._alias_history.setdefault(alias, [])
        return copy.deepcopy(descriptor)

    def resolve(self, reference: str) -> dict[str, Any]:
        reference = _text(reference, "definition_reference")
        digest = self._aliases.get(reference, reference)
        descriptor = self._definitions.get(digest)
        if descriptor is None:
            raise DefinitionError(f"unknown definition reference: {reference}")
        return copy.deepcopy(descriptor)

    def select(self, reference: str) -> dict[str, Any]:
        reference = _text(reference, "definition_reference")
        digest = self._aliases.get(reference, reference)
        descriptor = self.resolve(reference)
        rollout = self._rollouts[digest]
        if rollout == "retired":
            raise DefinitionError(f"definition is retired and cannot start a new run: {digest}")
        selection: dict[str, Any] = {
            "schema_version": COMPATIBILITY_SCHEMA_VERSION,
            "reference": reference,
            "reference_type": "alias" if reference in self._aliases else "digest",
            "new_run_only": True,
            "rollout": rollout,
        }
        history = self._alias_history.get(reference, [])
        if history:
            selection["redirected_from"] = history[-1]
        return {"definition": descriptor, "selection": selection}

    def redirect(self, alias: str, target: str) -> None:
        alias = _identifier(alias, "alias")
        descriptor = self.resolve(target)
        if self._rollouts[descriptor["definition_digest"]] == "retired":
            raise DefinitionError("cannot redirect an alias to a retired definition")
        if alias not in self._aliases:
            raise DefinitionError(f"unknown alias: {alias}")
        previous = self._aliases[alias]
        if previous == descriptor["definition_digest"]:
            return
        self._aliases[alias] = descriptor["definition_digest"]
        self._alias_history.setdefault(alias, []).append(previous)

    def rollback(self, alias: str) -> None:
        """Restore an alias to its previous non-retired target for new runs."""

        alias = _identifier(alias, "alias")
        history = self._alias_history.get(alias)
        if not history:
            raise DefinitionError(f"alias has no redirect history: {alias}")
        target = history[-1]
        if self._rollouts[target] == "retired":
            raise DefinitionError(f"cannot roll back to a retired definition: {target}")
        self._aliases[alias] = target
        history.pop()

    def retire(self, reference: str) -> None:
        descriptor = self.resolve(reference)
        self._rollouts[descriptor["definition_digest"]] = "retired"
