#!/usr/bin/env python3
"""Verify Forge agent identity, delegated authority, and effect bindings offline."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import hmac
import json
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CONTRACT_REVISION = "forge-authority-v1"
LEGACY_PROFILE = "legacy-principal-v1"
STRICT_PROFILE = "authority-v1"
REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OPAQUE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._:/@-]{0,191}$")
NONCE_RE = re.compile(r"^nonce:[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
KEY_ID_RE = re.compile(r"^key:[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
ALGORITHMS = {"ed25519", "jws", "dpop", "spiffe-svid", "hmac-sha256"}
PROOF_MODES = {"external-reference", "local"}
AUTHORIZATION_DECISIONS = {"allow", "require_approval"}
APPROVAL_STATUSES = {"approved", "not-required"}

IDENTITY_FIELDS = {
    "schema_version",
    "contract_revision",
    "kind",
    "profile",
    "issuer_ref",
    "subject_ref",
    "agent_ref",
    "build_ref",
    "audience_ref",
    "workspace_ref",
    "scopes",
    "resource_refs",
    "tool_refs",
    "intent_refs",
    "issued_at",
    "expires_at",
    "nonce",
    "revocation_ref",
    "policy_revision_ref",
    "generation",
    "legacy_principal",
    "proof",
}
DELEGATION_FIELDS = {
    "schema_version",
    "contract_revision",
    "kind",
    "delegation_id",
    "issuer_identity_ref",
    "subject_identity_ref",
    "parent_delegation_ref",
    "audience_ref",
    "workspace_ref",
    "scopes",
    "resource_refs",
    "tool_refs",
    "intent_refs",
    "issued_at",
    "expires_at",
    "nonce",
    "revocation_ref",
    "policy_revision_ref",
    "generation",
    "proof",
}
ACTION_FIELDS = {
    "schema_version",
    "contract_revision",
    "kind",
    "actor_identity_ref",
    "authority_ref",
    "audience_ref",
    "workspace_ref",
    "capability",
    "resource_ref",
    "tool_ref",
    "effect_ref",
    "intent_ref",
    "policy_decision_ref",
    "approval_ref",
    "runtime_episode_ref",
    "provider_operation_ref",
    "provenance_ref",
    "lease_ref",
    "delegation_generation",
    "issued_at",
    "expires_at",
    "nonce",
    "proof",
}
AUTHORIZATION_FIELDS = {
    "schema_version",
    "contract_revision",
    "kind",
    "decision",
    "action_ref",
    "actor_identity_ref",
    "authority_ref",
    "audience_ref",
    "workspace_ref",
    "capability",
    "resource_ref",
    "policy_revision_ref",
    "approval_ref",
    "lease_ref",
    "delegation_generation",
    "expires_at",
}
APPROVAL_FIELDS = {
    "schema_version",
    "contract_revision",
    "kind",
    "status",
    "action_ref",
    "actor_identity_ref",
    "authority_ref",
    "approver_ref",
    "audience_ref",
    "workspace_ref",
    "capability",
    "resource_ref",
    "policy_revision_ref",
    "lease_ref",
    "delegation_generation",
    "expires_at",
}
BUNDLE_FIELDS = {"schema_version", "contract_revision", "identities", "delegations", "action", "authorization", "approval"}
TRUST_FIELDS = {"schema_version", "contract_revision", "keys", "revoked_refs", "minimum_generations"}
TRUST_KEY_FIELDS = {"key_id", "algorithm", "status", "key_b64"}


class AuthorityError(ValueError):
    """Raised when an authority bundle cannot be verified."""


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AuthorityError(f"canonical-json: {exc}") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest_ref(value: Any) -> str:
    return f"sha256:{digest(value)}"


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthorityError(f"invalid-{label}: expected object")
    if any(not isinstance(key, str) for key in value):
        raise AuthorityError(f"invalid-{label}: keys must be strings")
    return {str(key): copy.deepcopy(child) for key, child in value.items()}


def _unknown(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise AuthorityError(f"unknown-{label}-field: {','.join(unknown)}")


def _text(value: Any, label: str, *, pattern: re.Pattern[str] | None = None, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise AuthorityError(f"invalid-{label}: expected bounded string")
    if pattern is not None and not pattern.fullmatch(value):
        raise AuthorityError(f"invalid-{label}: malformed reference")
    return value


def _opaque(value: Any, label: str) -> str:
    return _text(value, label, pattern=OPAQUE_RE)


def _ref(value: Any, label: str) -> str:
    return _text(value, label, pattern=REF_RE)


def _nonce(value: Any, label: str) -> str:
    return _text(value, label, pattern=NONCE_RE, max_length=160)


def _key_id(value: Any, label: str) -> str:
    return _text(value, label, pattern=KEY_ID_RE, max_length=144)


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AuthorityError(f"invalid-{label}: expected positive integer")
    return value


def _string_list(value: Any, label: str, *, pattern: re.Pattern[str] = OPAQUE_RE, maximum: int = 64) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise AuthorityError(f"invalid-{label}: expected bounded string array")
    values = [_text(item, f"{label}-item", pattern=pattern) for item in value]
    if len(set(values)) != len(values):
        raise AuthorityError(f"invalid-{label}: duplicate values")
    return sorted(values)


def _time(value: Any, label: str) -> datetime:
    text = _text(value, label, max_length=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthorityError(f"invalid-{label}: expected RFC3339") from exc
    if parsed.tzinfo is None:
        raise AuthorityError(f"invalid-{label}: timezone required")
    return parsed.astimezone(timezone.utc)


def _interval(issued_at: str, expires_at: str, label: str) -> None:
    if _time(expires_at, f"{label}-expires") <= _time(issued_at, f"{label}-issued"):
        raise AuthorityError(f"invalid-{label}-interval: expiry must be after issuance")


def _without_proof(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(child) for key, child in value.items() if key != "proof"}


def _proof(value: Any, payload: Mapping[str, Any], label: str) -> dict[str, Any]:
    proof = _mapping(value, f"{label}-proof")
    _unknown(proof, {"mode", "algorithm", "key_id", "payload_digest", "signature", "proof_ref"}, f"{label}-proof")
    mode = proof.get("mode")
    if mode not in PROOF_MODES:
        raise AuthorityError(f"invalid-{label}-proof-mode")
    algorithm = _text(proof.get("algorithm"), f"{label}-proof-algorithm", max_length=32)
    if algorithm not in ALGORITHMS:
        raise AuthorityError(f"invalid-{label}-proof-algorithm")
    key_id = _key_id(proof.get("key_id"), f"{label}-proof-key-id")
    payload_digest = _ref(proof.get("payload_digest"), f"{label}-proof-payload-digest")
    expected = digest_ref(payload)
    if payload_digest != expected:
        raise AuthorityError(f"proof-payload-mismatch:{label}")
    if mode == "local":
        if algorithm != "hmac-sha256":
            raise AuthorityError(f"invalid-{label}-local-proof-algorithm")
        signature = proof.get("signature")
        if not isinstance(signature, str) or not signature:
            raise AuthorityError(f"invalid-{label}-proof-signature")
        try:
            base64.b64decode(signature.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError) as exc:
            raise AuthorityError(f"invalid-{label}-proof-signature") from exc
        normalized = {"mode": mode, "algorithm": algorithm, "key_id": key_id, "payload_digest": payload_digest, "signature": signature}
    else:
        if algorithm == "hmac-sha256":
            raise AuthorityError(f"invalid-{label}-external-proof-algorithm")
        proof_ref = _ref(proof.get("proof_ref"), f"{label}-proof-ref")
        normalized = {"mode": mode, "algorithm": algorithm, "key_id": key_id, "payload_digest": payload_digest, "proof_ref": proof_ref}
    return normalized


def _identity(value: Any) -> dict[str, Any]:
    data = _mapping(value, "identity")
    _unknown(data, IDENTITY_FIELDS, "identity")
    if data.get("schema_version") != SCHEMA_VERSION or data.get("contract_revision") != CONTRACT_REVISION:
        raise AuthorityError("unsupported-identity-contract")
    if data.get("kind") != "identity":
        raise AuthorityError("invalid-identity-kind")
    profile = data.get("profile")
    if profile not in {STRICT_PROFILE, LEGACY_PROFILE}:
        raise AuthorityError("invalid-identity-profile")
    issuer_ref = _opaque(data.get("issuer_ref"), "identity-issuer-ref")
    subject_ref = _opaque(data.get("subject_ref"), "identity-subject-ref")
    agent_ref = _opaque(data.get("agent_ref"), "identity-agent-ref")
    if subject_ref != agent_ref:
        raise AuthorityError("identity-subject-agent-mismatch")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "kind": "identity",
        "profile": profile,
        "issuer_ref": issuer_ref,
        "subject_ref": subject_ref,
        "agent_ref": agent_ref,
        "build_ref": _ref(data.get("build_ref"), "identity-build-ref"),
        "audience_ref": _opaque(data.get("audience_ref"), "identity-audience-ref"),
        "workspace_ref": _opaque(data.get("workspace_ref"), "identity-workspace-ref"),
        "scopes": _string_list(data.get("scopes"), "identity-scopes"),
        "resource_refs": _string_list(data.get("resource_refs"), "identity-resource-refs"),
        "tool_refs": _string_list(data.get("tool_refs"), "identity-tool-refs"),
        "intent_refs": _string_list(data.get("intent_refs"), "identity-intent-refs", pattern=REF_RE),
        "issued_at": _text(data.get("issued_at"), "identity-issued-at", max_length=64),
        "expires_at": _text(data.get("expires_at"), "identity-expires-at", max_length=64),
        "nonce": _nonce(data.get("nonce"), "identity-nonce"),
        "revocation_ref": _ref(data.get("revocation_ref"), "identity-revocation-ref"),
        "policy_revision_ref": _ref(data.get("policy_revision_ref"), "identity-policy-revision-ref"),
        "generation": _positive_int(data.get("generation"), "identity-generation"),
        "legacy_principal": None,
    }
    _time(normalized["issued_at"], "identity-issued-at")
    _time(normalized["expires_at"], "identity-expires-at")
    _interval(normalized["issued_at"], normalized["expires_at"], "identity")
    legacy = data.get("legacy_principal")
    if legacy is not None:
        normalized["legacy_principal"] = _opaque(legacy, "identity-legacy-principal")
    elif profile == LEGACY_PROFILE:
        raise AuthorityError("legacy-profile-requires-principal")
    normalized["proof"] = _proof(data.get("proof"), _without_proof(normalized), "identity")
    return normalized


def _delegation(value: Any) -> dict[str, Any]:
    data = _mapping(value, "delegation")
    _unknown(data, DELEGATION_FIELDS, "delegation")
    if data.get("schema_version") != SCHEMA_VERSION or data.get("contract_revision") != CONTRACT_REVISION:
        raise AuthorityError("unsupported-delegation-contract")
    if data.get("kind") != "delegation":
        raise AuthorityError("invalid-delegation-kind")
    parent = data.get("parent_delegation_ref")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "kind": "delegation",
        "delegation_id": _opaque(data.get("delegation_id"), "delegation-id"),
        "issuer_identity_ref": _ref(data.get("issuer_identity_ref"), "delegation-issuer-identity-ref"),
        "subject_identity_ref": _ref(data.get("subject_identity_ref"), "delegation-subject-identity-ref"),
        "parent_delegation_ref": None if parent is None else _ref(parent, "delegation-parent-ref"),
        "audience_ref": _opaque(data.get("audience_ref"), "delegation-audience-ref"),
        "workspace_ref": _opaque(data.get("workspace_ref"), "delegation-workspace-ref"),
        "scopes": _string_list(data.get("scopes"), "delegation-scopes"),
        "resource_refs": _string_list(data.get("resource_refs"), "delegation-resource-refs"),
        "tool_refs": _string_list(data.get("tool_refs"), "delegation-tool-refs"),
        "intent_refs": _string_list(data.get("intent_refs"), "delegation-intent-refs", pattern=REF_RE),
        "issued_at": _text(data.get("issued_at"), "delegation-issued-at", max_length=64),
        "expires_at": _text(data.get("expires_at"), "delegation-expires-at", max_length=64),
        "nonce": _nonce(data.get("nonce"), "delegation-nonce"),
        "revocation_ref": _ref(data.get("revocation_ref"), "delegation-revocation-ref"),
        "policy_revision_ref": _ref(data.get("policy_revision_ref"), "delegation-policy-revision-ref"),
        "generation": _positive_int(data.get("generation"), "delegation-generation"),
    }
    _time(normalized["issued_at"], "delegation-issued-at")
    _time(normalized["expires_at"], "delegation-expires-at")
    _interval(normalized["issued_at"], normalized["expires_at"], "delegation")
    normalized["proof"] = _proof(data.get("proof"), _without_proof(normalized), "delegation")
    return normalized


def _action(value: Any) -> dict[str, Any]:
    data = _mapping(value, "action")
    _unknown(data, ACTION_FIELDS, "action")
    if data.get("schema_version") != SCHEMA_VERSION or data.get("contract_revision") != CONTRACT_REVISION:
        raise AuthorityError("unsupported-action-contract")
    if data.get("kind") != "action":
        raise AuthorityError("invalid-action-kind")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "kind": "action",
        "actor_identity_ref": _ref(data.get("actor_identity_ref"), "action-actor-identity-ref"),
        "authority_ref": _ref(data.get("authority_ref"), "action-authority-ref"),
        "audience_ref": _opaque(data.get("audience_ref"), "action-audience-ref"),
        "workspace_ref": _opaque(data.get("workspace_ref"), "action-workspace-ref"),
        "capability": _opaque(data.get("capability"), "action-capability"),
        "resource_ref": _opaque(data.get("resource_ref"), "action-resource-ref"),
        "tool_ref": _opaque(data.get("tool_ref"), "action-tool-ref"),
        "effect_ref": _opaque(data.get("effect_ref"), "action-effect-ref"),
        "intent_ref": _ref(data.get("intent_ref"), "action-intent-ref"),
        "policy_decision_ref": _ref(data.get("policy_decision_ref"), "action-policy-decision-ref"),
        "approval_ref": _ref(data.get("approval_ref"), "action-approval-ref"),
        "runtime_episode_ref": _ref(data.get("runtime_episode_ref"), "action-runtime-episode-ref"),
        "provider_operation_ref": _ref(data.get("provider_operation_ref"), "action-provider-operation-ref"),
        "provenance_ref": _ref(data.get("provenance_ref"), "action-provenance-ref"),
        "lease_ref": _ref(data.get("lease_ref"), "action-lease-ref"),
        "delegation_generation": _positive_int(data.get("delegation_generation"), "action-delegation-generation"),
        "issued_at": _text(data.get("issued_at"), "action-issued-at", max_length=64),
        "expires_at": _text(data.get("expires_at"), "action-expires-at", max_length=64),
        "nonce": _nonce(data.get("nonce"), "action-nonce"),
    }
    _time(normalized["issued_at"], "action-issued-at")
    _time(normalized["expires_at"], "action-expires-at")
    _interval(normalized["issued_at"], normalized["expires_at"], "action")
    normalized["proof"] = _proof(data.get("proof"), _without_proof(normalized), "action")
    return normalized


def _authorization(value: Any) -> dict[str, Any]:
    data = _mapping(value, "authorization")
    _unknown(data, AUTHORIZATION_FIELDS, "authorization")
    if data.get("schema_version") != SCHEMA_VERSION or data.get("contract_revision") != CONTRACT_REVISION:
        raise AuthorityError("unsupported-authorization-contract")
    if data.get("kind") != "authorization":
        raise AuthorityError("invalid-authorization-kind")
    decision = data.get("decision")
    if decision not in AUTHORIZATION_DECISIONS:
        raise AuthorityError("invalid-authorization-decision")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "kind": "authorization",
        "decision": decision,
        "action_ref": _ref(data.get("action_ref"), "authorization-action-ref"),
        "actor_identity_ref": _ref(data.get("actor_identity_ref"), "authorization-actor-identity-ref"),
        "authority_ref": _ref(data.get("authority_ref"), "authorization-authority-ref"),
        "audience_ref": _opaque(data.get("audience_ref"), "authorization-audience-ref"),
        "workspace_ref": _opaque(data.get("workspace_ref"), "authorization-workspace-ref"),
        "capability": _opaque(data.get("capability"), "authorization-capability"),
        "resource_ref": _opaque(data.get("resource_ref"), "authorization-resource-ref"),
        "policy_revision_ref": _ref(data.get("policy_revision_ref"), "authorization-policy-revision-ref"),
        "approval_ref": _ref(data.get("approval_ref"), "authorization-approval-ref"),
        "lease_ref": _ref(data.get("lease_ref"), "authorization-lease-ref"),
        "delegation_generation": _positive_int(data.get("delegation_generation"), "authorization-delegation-generation"),
        "expires_at": _text(data.get("expires_at"), "authorization-expires-at", max_length=64),
    }
    _time(normalized["expires_at"], "authorization-expires-at")
    return normalized


def _approval(value: Any) -> dict[str, Any]:
    data = _mapping(value, "approval")
    _unknown(data, APPROVAL_FIELDS, "approval")
    if data.get("schema_version") != SCHEMA_VERSION or data.get("contract_revision") != CONTRACT_REVISION:
        raise AuthorityError("unsupported-approval-contract")
    if data.get("kind") != "approval":
        raise AuthorityError("invalid-approval-kind")
    status = data.get("status")
    if status not in APPROVAL_STATUSES:
        raise AuthorityError("invalid-approval-status")
    approver = _opaque(data.get("approver_ref"), "approval-approver-ref")
    if status == "approved" and not approver.startswith(("human:", "host:")):
        raise AuthorityError("approval-requires-human-or-host-approver")
    if status == "not-required" and not approver.startswith("policy:"):
        raise AuthorityError("not-required-approval-needs-policy-approver")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "kind": "approval",
        "status": status,
        "action_ref": _ref(data.get("action_ref"), "approval-action-ref"),
        "actor_identity_ref": _ref(data.get("actor_identity_ref"), "approval-actor-identity-ref"),
        "authority_ref": _ref(data.get("authority_ref"), "approval-authority-ref"),
        "approver_ref": approver,
        "audience_ref": _opaque(data.get("audience_ref"), "approval-audience-ref"),
        "workspace_ref": _opaque(data.get("workspace_ref"), "approval-workspace-ref"),
        "capability": _opaque(data.get("capability"), "approval-capability"),
        "resource_ref": _opaque(data.get("resource_ref"), "approval-resource-ref"),
        "policy_revision_ref": _ref(data.get("policy_revision_ref"), "approval-policy-revision-ref"),
        "lease_ref": _ref(data.get("lease_ref"), "approval-lease-ref"),
        "delegation_generation": _positive_int(data.get("delegation_generation"), "approval-delegation-generation"),
        "expires_at": _text(data.get("expires_at"), "approval-expires-at", max_length=64),
    }
    _time(normalized["expires_at"], "approval-expires-at")
    return normalized


def identity_ref(identity: Mapping[str, Any]) -> str:
    return digest_ref(_identity(identity))


def delegation_ref(delegation: Mapping[str, Any]) -> str:
    return digest_ref(_delegation(delegation))


def action_ref(action: Mapping[str, Any]) -> str:
    normalized = _action(action)
    # Authorization and approval point back to the operation. Exclude those
    # back-references so the evidence graph has a deterministic acyclic root.
    core = {
        key: copy.deepcopy(value)
        for key, value in normalized.items()
        if key not in {"proof", "policy_decision_ref", "approval_ref"}
    }
    return digest_ref(core)


def authorization_ref(authorization: Mapping[str, Any]) -> str:
    return digest_ref(_authorization(authorization))


def approval_ref(approval: Mapping[str, Any]) -> str:
    return digest_ref(_approval(approval))


def external_proof(statement: Mapping[str, Any], *, key_id: str = "key:external", algorithm: str = "ed25519") -> dict[str, Any]:
    """Create an opaque proof reference for a host-authenticated statement."""

    body = _without_proof(statement)
    payload_digest = digest_ref(body)
    return {
        "mode": "external-reference",
        "algorithm": algorithm,
        "key_id": key_id,
        "payload_digest": payload_digest,
        "proof_ref": digest_ref({"algorithm": algorithm, "key_id": key_id, "payload_digest": payload_digest}),
    }


def local_proof(statement: Mapping[str, Any], *, key_id: str, key: bytes) -> dict[str, Any]:
    """Create a local HMAC proof for tests and air-gapped deployments."""

    body = _without_proof(statement)
    payload_digest = digest_ref(body)
    signature = hmac.new(key, payload_digest.encode("ascii"), hashlib.sha256).digest()
    return {
        "mode": "local",
        "algorithm": "hmac-sha256",
        "key_id": key_id,
        "payload_digest": payload_digest,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def _trust_policy(value: Any) -> dict[str, Any]:
    data = _mapping(value, "trust-policy")
    _unknown(data, TRUST_FIELDS, "trust-policy")
    if data.get("schema_version") != SCHEMA_VERSION or data.get("contract_revision") != CONTRACT_REVISION:
        raise AuthorityError("unsupported-trust-policy-contract")
    raw_keys = data.get("keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise AuthorityError("trust-policy-needs-keys")
    keys: dict[str, dict[str, Any]] = {}
    for raw in raw_keys:
        item = _mapping(raw, "trust-key")
        _unknown(item, TRUST_KEY_FIELDS, "trust-key")
        key_id = _key_id(item.get("key_id"), "trust-key-id")
        algorithm = _text(item.get("algorithm"), "trust-key-algorithm", max_length=32)
        if algorithm not in ALGORITHMS:
            raise AuthorityError("invalid-trust-key-algorithm")
        status = item.get("status")
        if status not in {"active", "retired", "external", "revoked"}:
            raise AuthorityError("invalid-trust-key-status")
        if key_id in keys:
            raise AuthorityError("duplicate-trust-key")
        normalized = {"key_id": key_id, "algorithm": algorithm, "status": status}
        if "key_b64" in item:
            encoded = item["key_b64"]
            if not isinstance(encoded, str) or not encoded:
                raise AuthorityError("invalid-trust-key-material")
            try:
                decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
            except (ValueError, UnicodeEncodeError) as exc:
                raise AuthorityError("invalid-trust-key-material") from exc
            if not decoded:
                raise AuthorityError("invalid-trust-key-material")
            normalized["key_b64"] = encoded
        keys[key_id] = normalized
    revoked = data.get("revoked_refs", [])
    if not isinstance(revoked, list) or any(not isinstance(ref, str) or not REF_RE.fullmatch(ref) for ref in revoked):
        raise AuthorityError("invalid-trust-policy-revoked-refs")
    if len(set(revoked)) != len(revoked):
        raise AuthorityError("duplicate-trust-policy-revoked-ref")
    minimum = data.get("minimum_generations", {})
    minimum_map = _mapping(minimum, "trust-policy-minimum-generations")
    normalized_minimum: dict[str, int] = {}
    for ref, generation in minimum_map.items():
        _ref(ref, "trust-policy-generation-ref")
        normalized_minimum[ref] = _positive_int(generation, "trust-policy-minimum-generation")
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "keys": keys,
        "revoked_refs": set(revoked),
        "minimum_generations": normalized_minimum,
    }


def _verify_proof(statement: Mapping[str, Any], label: str, trust: Mapping[str, Any]) -> str:
    normalized = _proof(statement.get("proof"), _without_proof(statement), label)
    if normalized["key_id"] not in trust["keys"]:
        raise AuthorityError(f"untrusted-proof-key:{label}")
    key = trust["keys"][normalized["key_id"]]
    if key["status"] == "revoked":
        raise AuthorityError(f"revoked-proof-key:{label}")
    if key["algorithm"] != normalized["algorithm"]:
        raise AuthorityError(f"proof-algorithm-mismatch:{label}")
    if normalized["mode"] == "external-reference":
        if key["status"] not in {"active", "retired", "external"}:
            raise AuthorityError(f"inactive-proof-key:{label}")
        return "external"
    encoded = key.get("key_b64")
    if not encoded:
        raise AuthorityError(f"missing-local-proof-key:{label}")
    try:
        key_bytes = base64.b64decode(encoded.encode("ascii"), validate=True)
        expected = hmac.new(key_bytes, normalized["payload_digest"].encode("ascii"), hashlib.sha256).digest()
        actual = base64.b64decode(normalized["signature"].encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise AuthorityError(f"invalid-local-proof:{label}") from exc
    if not hmac.compare_digest(expected, actual):
        raise AuthorityError(f"proof-signature-mismatch:{label}")
    return "local"


def _check_time_window(issued_at: str, expires_at: str, now: datetime, label: str) -> None:
    if now < _time(issued_at, f"{label}-issued") or now >= _time(expires_at, f"{label}-expires"):
        raise AuthorityError(f"expired-or-not-yet-valid:{label}")


def _subset(child: list[str], parent: list[str], label: str) -> None:
    missing = sorted(set(child) - set(parent))
    if missing:
        raise AuthorityError(f"scope-escalation:{label}:{','.join(missing)}")


def _revocation_check(ref: str, generation: int, trust: Mapping[str, Any], label: str) -> None:
    if ref in trust["revoked_refs"]:
        raise AuthorityError(f"revoked:{label}")
    minimum = trust["minimum_generations"].get(ref)
    if minimum is not None and generation < minimum:
        raise AuthorityError(f"stale-generation:{label}")


def _bundle(value: Any) -> dict[str, Any]:
    data = _mapping(value, "bundle")
    _unknown(data, BUNDLE_FIELDS, "bundle")
    if data.get("schema_version") != SCHEMA_VERSION or data.get("contract_revision") != CONTRACT_REVISION:
        raise AuthorityError("unsupported-bundle-contract")
    identities = data.get("identities")
    delegations = data.get("delegations")
    if not isinstance(identities, list) or not identities or len(identities) > 32:
        raise AuthorityError("invalid-bundle-identities")
    if not isinstance(delegations, list) or len(delegations) > 32:
        raise AuthorityError("invalid-bundle-delegations")
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "identities": [_identity(item) for item in identities],
        "delegations": [_delegation(item) for item in delegations],
        "action": _action(data.get("action")),
        "authorization": _authorization(data.get("authorization")),
        "approval": _approval(data.get("approval")),
    }


def verify_bundle(
    value: Mapping[str, Any],
    *,
    trust_policy: Mapping[str, Any],
    expected_audience_ref: str,
    expected_workspace_ref: str,
    at: str,
    seen_nonces: list[str] | None = None,
    generation_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify one authority bundle and return only digest/reference evidence."""

    bundle = _bundle(value)
    trust = _trust_policy(trust_policy)
    expected_audience = _opaque(expected_audience_ref, "expected-audience-ref")
    expected_workspace = _opaque(expected_workspace_ref, "expected-workspace-ref")
    now = _time(at, "verification-at")
    generations = dict(generation_state or {})
    for ref, generation in generations.items():
        _ref(ref, "generation-state-ref")
        generations[ref] = _positive_int(generation, "generation-state")

    identities = bundle["identities"]
    identity_refs = [identity_ref(item) for item in identities]
    if len(set(identity_refs)) != len(identity_refs):
        raise AuthorityError("duplicate-identity-ref")
    identity_map = dict(zip(identity_refs, identities))
    proof_modes = [_verify_proof(item, "identity", trust) for item in identities]
    for ref, identity in zip(identity_refs, identities):
        _check_time_window(identity["issued_at"], identity["expires_at"], now, "identity")
        _revocation_check(ref, identity["generation"], trust, "identity")
        if identity["audience_ref"] != expected_audience or identity["workspace_ref"] != expected_workspace:
            raise AuthorityError("audience-or-workspace-drift:identity")
        current_generation = generations.get(ref)
        if current_generation is not None and current_generation != identity["generation"]:
            raise AuthorityError("delegation-generation-changed:identity")

    delegations = bundle["delegations"]
    delegation_refs = [delegation_ref(item) for item in delegations]
    if len(set(delegation_refs)) != len(delegation_refs):
        raise AuthorityError("duplicate-delegation-ref")
    proof_modes.extend(_verify_proof(item, "delegation", trust) for item in delegations)

    if delegations:
        first = delegations[0]
        root_identity_ref = first["issuer_identity_ref"]
        if root_identity_ref not in identity_map:
            raise AuthorityError("missing-root-identity")
        root = identity_map[root_identity_ref]
        root_policy_revision = root["policy_revision_ref"]
        if any(identity["policy_revision_ref"] != root_policy_revision for identity in identities):
            raise AuthorityError("policy-revision-drift:identity")
        parent_scopes = root["scopes"]
        parent_resources = root["resource_refs"]
        parent_tools = root["tool_refs"]
        parent_intents = root["intent_refs"]
        parent_audience = root["audience_ref"]
        parent_workspace = root["workspace_ref"]
        parent_issued = _time(root["issued_at"], "root-identity-issued")
        parent_expires = _time(root["expires_at"], "root-identity-expires")
        previous_subject = root_identity_ref
        previous_delegation_ref: str | None = None
        for index, (ref, delegation) in enumerate(zip(delegation_refs, delegations)):
            if delegation["issuer_identity_ref"] != previous_subject:
                raise AuthorityError(f"rogue-delegation:issuer:{index}")
            if delegation["parent_delegation_ref"] != previous_delegation_ref:
                raise AuthorityError(f"rogue-delegation:parent:{index}")
            if delegation["audience_ref"] != parent_audience or delegation["workspace_ref"] != parent_workspace:
                raise AuthorityError(f"audience-or-workspace-drift:delegation:{index}")
            if delegation["policy_revision_ref"] != root_policy_revision:
                raise AuthorityError(f"policy-revision-drift:delegation:{index}")
            _subset(delegation["scopes"], parent_scopes, f"delegation-{index}-scopes")
            _subset(delegation["resource_refs"], parent_resources, f"delegation-{index}-resources")
            _subset(delegation["tool_refs"], parent_tools, f"delegation-{index}-tools")
            _subset(delegation["intent_refs"], parent_intents, f"delegation-{index}-intents")
            issued = _time(delegation["issued_at"], f"delegation-{index}-issued")
            expires = _time(delegation["expires_at"], f"delegation-{index}-expires")
            if issued < parent_issued or expires > parent_expires:
                raise AuthorityError(f"delegation-lifetime-expansion:{index}")
            subject = identity_map.get(delegation["subject_identity_ref"])
            if subject is None:
                raise AuthorityError(f"missing-delegated-identity:{index}")
            _subset(delegation["scopes"], subject["scopes"], f"delegation-{index}-subject-scopes")
            _subset(delegation["resource_refs"], subject["resource_refs"], f"delegation-{index}-subject-resources")
            _subset(delegation["tool_refs"], subject["tool_refs"], f"delegation-{index}-subject-tools")
            _subset(delegation["intent_refs"], subject["intent_refs"], f"delegation-{index}-subject-intents")
            _check_time_window(delegation["issued_at"], delegation["expires_at"], now, f"delegation-{index}")
            _revocation_check(ref, delegation["generation"], trust, f"delegation-{index}")
            current_generation = generations.get(ref)
            if current_generation is not None and current_generation != delegation["generation"]:
                raise AuthorityError(f"delegation-generation-changed:{index}")
            parent_scopes = delegation["scopes"]
            parent_resources = delegation["resource_refs"]
            parent_tools = delegation["tool_refs"]
            parent_intents = delegation["intent_refs"]
            parent_issued = issued
            parent_expires = expires
            previous_subject = delegation["subject_identity_ref"]
            previous_delegation_ref = ref
        final_identity_ref = previous_subject
        final_authority_ref = delegation_refs[-1]
        final_authority = delegations[-1]
    else:
        final_identity_ref = next(iter(identity_map))
        final_authority_ref = final_identity_ref
        final_authority = identity_map[final_identity_ref]

    action = bundle["action"]
    computed_action_ref = action_ref(action)
    if action["actor_identity_ref"] != final_identity_ref:
        raise AuthorityError("actor-identity-mismatch")
    if action["authority_ref"] != final_authority_ref:
        raise AuthorityError("authority-chain-mismatch")
    if action["audience_ref"] != expected_audience or action["workspace_ref"] != expected_workspace:
        raise AuthorityError("audience-or-workspace-drift:action")
    action_issued = _time(action["issued_at"], "action-issued")
    action_expires = _time(action["expires_at"], "action-expires")
    _check_time_window(action["issued_at"], action["expires_at"], now, "action")
    authority_issued = _time(final_authority["issued_at"], "authority-issued")
    authority_expires = _time(final_authority["expires_at"], "authority-expires")
    if action_issued < authority_issued or action_expires > authority_expires:
        raise AuthorityError("action-lifetime-expansion")
    if action["capability"] not in final_authority["scopes"]:
        raise AuthorityError("least-agency-capability-mismatch")
    if action["resource_ref"] not in final_authority["resource_refs"]:
        raise AuthorityError("resource-scope-mismatch")
    if action["tool_ref"] not in final_authority["tool_refs"]:
        raise AuthorityError("tool-scope-mismatch")
    if action["intent_ref"] not in final_authority["intent_refs"]:
        raise AuthorityError("intent-scope-mismatch:goal-hijack")
    if action["delegation_generation"] != final_authority["generation"]:
        raise AuthorityError("delegation-generation-mismatch:action")
    _revocation_check(computed_action_ref, action["delegation_generation"], trust, "action")
    current_generation = generations.get(final_authority_ref)
    if current_generation is not None and current_generation != action["delegation_generation"]:
        raise AuthorityError("delegation-generation-changed:action")
    proof_modes.append(_verify_proof(action, "action", trust))

    authorization = bundle["authorization"]
    computed_authorization_ref = authorization_ref(authorization)
    approval = bundle["approval"]
    computed_approval_ref = approval_ref(approval)
    binding_fields = {
        "action_ref": computed_action_ref,
        "actor_identity_ref": final_identity_ref,
        "authority_ref": final_authority_ref,
        "audience_ref": expected_audience,
        "workspace_ref": expected_workspace,
        "capability": action["capability"],
        "resource_ref": action["resource_ref"],
        "lease_ref": action["lease_ref"],
        "delegation_generation": action["delegation_generation"],
    }
    for label, evidence in (("authorization", authorization), ("approval", approval)):
        for field, expected in binding_fields.items():
            if evidence[field] != expected:
                raise AuthorityError(f"{label}-binding-mismatch:{field}")
    if action["policy_decision_ref"] != computed_authorization_ref:
        raise AuthorityError("policy-decision-binding-mismatch")
    if action["approval_ref"] != computed_approval_ref or authorization["approval_ref"] != computed_approval_ref:
        raise AuthorityError("approval-binding-mismatch")
    if approval["policy_revision_ref"] != authorization["policy_revision_ref"]:
        raise AuthorityError("policy-revision-binding-mismatch")
    if final_authority["policy_revision_ref"] != authorization["policy_revision_ref"]:
        raise AuthorityError("policy-revision-binding-mismatch:authority")
    if authorization["expires_at"] != approval["expires_at"]:
        raise AuthorityError("authorization-approval-expiry-mismatch")
    if action_expires > _time(authorization["expires_at"], "authorization-expires"):
        raise AuthorityError("authorization-expired-before-action")
    if authorization["decision"] == "require_approval" and approval["status"] != "approved":
        raise AuthorityError("approval-required-but-not-granted")
    if approval["status"] == "approved" and authorization["decision"] not in AUTHORIZATION_DECISIONS:
        raise AuthorityError("approved-action-has-invalid-decision")

    _revocation_check(computed_authorization_ref, action["delegation_generation"], trust, "authorization")
    _revocation_check(computed_approval_ref, action["delegation_generation"], trust, "approval")
    nonces = [item["nonce"] for item in identities] + [item["nonce"] for item in delegations] + [action["nonce"]]
    if len(set(nonces)) != len(nonces):
        raise AuthorityError("nonce-reuse:bundle")
    seen = set(seen_nonces or [])
    if any(not isinstance(item, str) or not NONCE_RE.fullmatch(item) for item in seen):
        raise AuthorityError("invalid-seen-nonce")
    reused = sorted(set(nonces) & seen)
    if reused:
        raise AuthorityError(f"nonce-replay:{','.join(reused)}")
    legacy = any(item["profile"] == LEGACY_PROFILE for item in identities)
    return {
        "status": "passed",
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "authentication_boundary": "local" if set(proof_modes) == {"local"} else "external" if set(proof_modes) == {"external"} else "mixed",
        "legacy_profile": legacy,
        "identity_refs": identity_refs,
        "delegation_refs": delegation_refs,
        "actor_identity_ref": final_identity_ref,
        "authority_ref": final_authority_ref,
        "action_ref": computed_action_ref,
        "policy_decision_ref": computed_authorization_ref,
        "approval_ref": computed_approval_ref,
        "binding_refs": {
            "lease_ref": action["lease_ref"],
            "runtime_episode_ref": action["runtime_episode_ref"],
            "provider_operation_ref": action["provider_operation_ref"],
            "provenance_ref": action["provenance_ref"],
        },
        "nonce_refs": nonces,
        "checks": {
            "proofs": True,
            "delegation_narrowing": True,
            "least_agency": True,
            "audience_workspace": True,
            "expiry": True,
            "revocation_generation": True,
            "nonce_replay": True,
            "policy_revision_binding": True,
            "lease_binding": True,
            "policy_approval_binding": True,
            "runtime_provider_provenance_binding": True,
        },
    }


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorityError(f"cannot-load-json:{path.name}") from exc


def evaluate_corpus(path: Path) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = _mapping(json.loads(line), f"corpus-case-{line_number}")
            case_id = _text(case.get("case_id"), "corpus-case-id", max_length=96)
            expected = case.get("expected")
            if expected not in {"passed", "failed"}:
                raise AuthorityError("invalid-corpus-expected")
            context = _mapping(case.get("context"), "corpus-context")
            bundle = case.get("bundle")
            trust = context.get("trust_policy")
            observed = "passed"
            result: dict[str, Any] | None = None
            error = None
            try:
                result = verify_bundle(
                    bundle,
                    trust_policy=trust,
                    expected_audience_ref=context.get("expected_audience_ref"),
                    expected_workspace_ref=context.get("expected_workspace_ref"),
                    at=context.get("at"),
                    seen_nonces=context.get("seen_nonces", []),
                    generation_state=context.get("generation_state", {}),
                )
            except AuthorityError as exc:
                observed = "failed"
                error = str(exc).split(":", 1)[0]
            status = "pass" if observed == expected else "fail"
            item: dict[str, Any] = {"case_id": case_id, "expected": expected, "observed": observed, "status": status}
            if case.get("threat") is True:
                item["threat"] = True
            if error:
                item["error"] = error
            if result is not None:
                item["action_ref"] = result["action_ref"]
            cases.append(item)
        except (AuthorityError, TypeError, AttributeError) as exc:
            cases.append({"case_id": f"line-{line_number}", "expected": "failed", "observed": "failed", "status": "fail", "error": str(exc).split(":", 1)[0]})
    passed = sum(item["status"] == "pass" for item in cases)
    threat_cases = sum(item.get("threat") is True for item in cases)
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "status": "passed" if passed == len(cases) and cases else "failed",
        "case_count": len(cases),
        "threat_cases": threat_cases,
        "deterministic": True,
        "authentication_boundary": "external-reference",
        "cases": cases,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify Forge identity and delegated authority evidence offline.")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="verify one authority bundle")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--trust-policy", type=Path, required=True)
    verify.add_argument("--audience", required=True)
    verify.add_argument("--workspace", required=True)
    verify.add_argument("--at", required=True)
    verify.add_argument("--seen-nonces", type=Path)
    verify.add_argument("--generation-state", type=Path)
    verify.add_argument("--json", action="store_true")
    corpus = sub.add_parser("evaluate", help="evaluate a JSONL authority corpus")
    corpus.add_argument("--corpus", type=Path, required=True)
    corpus.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "evaluate":
            result = evaluate_corpus(args.corpus)
        else:
            seen = load_json(args.seen_nonces) if args.seen_nonces else []
            generations = load_json(args.generation_state) if args.generation_state else {}
            result = verify_bundle(
                load_json(args.bundle),
                trust_policy=load_json(args.trust_policy),
                expected_audience_ref=args.audience,
                expected_workspace_ref=args.workspace,
                at=args.at,
                seen_nonces=seen,
                generation_state=generations,
            )
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        return 0 if result["status"] in {"passed", "pass"} else 1
    except (AuthorityError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc).split(":", 1)[0]}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
