#!/usr/bin/env python3
"""Verify digest-only host authentication evidence for connected Forge effects."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
CONTRACT_REVISION = "forge-host-admission-v1"
SCHEMA_URI = "https://github.com/AlisinaDevelo/md-files/schema/runtime/host-admission/v1"
REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OPAQUE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._:/@-]{0,191}$")
NONCE_RE = re.compile(r"^nonce:[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
KEY_ID_RE = re.compile(r"^key:[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
AUTH_SCHEMES = {"dpop", "mtls", "spiffe-svid", "jws", "oauth2-bearer"}
REPLAY_PROTECTION = {"sender-constrained", "nonce-cache", "provider-bound"}
DEFAULT_MAX_LIFETIME_SECONDS = 600
FORBIDDEN_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "private_key",
    "authorization",
    "cookie",
    "credential",
    "signature",
)
CREDENTIAL_VALUE_RE = re.compile(
    r"(?:github_pat_|gh[opusr]_[A-Za-z0-9]|Bearer\s+[A-Za-z0-9._~+/=-]|eyJ[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)

ADMISSION_FIELDS = {
    "$schema",
    "schema_version",
    "contract_revision",
    "admission_id",
    "host_ref",
    "audience_ref",
    "workspace_ref",
    "resource_ref",
    "request_ref",
    "authority_ref",
    "action_ref",
    "policy_decision_ref",
    "approval_ref",
    "lease_ref",
    "runtime_episode_ref",
    "provider_operation_ref",
    "provenance_ref",
    "policy_revision_ref",
    "scope_refs",
    "auth",
    "issued_at",
    "expires_at",
    "nonce",
    "generation",
}
AUTH_FIELDS = {"scheme", "key_ref", "proof_ref", "verification_ref", "replay_protection"}
BINDING_FIELDS = {
    "authority_ref",
    "action_ref",
    "policy_decision_ref",
    "approval_ref",
    "lease_ref",
    "runtime_episode_ref",
    "provider_operation_ref",
    "provenance_ref",
}


class HostAdmissionError(ValueError):
    """Raised when host authentication evidence cannot be admitted."""


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise HostAdmissionError(f"canonical-json: {exc}") from exc


def digest_ref(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise HostAdmissionError(f"invalid-{label}: expected object with string keys")
    return {str(key): copy.deepcopy(child) for key, child in value.items()}


def _unknown(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise HostAdmissionError(f"unknown-{label}-field: {','.join(unknown)}")


def _text(
    value: Any,
    label: str,
    *,
    pattern: re.Pattern[str] | None = None,
    maximum: int = 256,
) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise HostAdmissionError(f"invalid-{label}: expected bounded string")
    if pattern is not None and not pattern.fullmatch(value):
        raise HostAdmissionError(f"invalid-{label}: malformed reference")
    return value


def _ref(value: Any, label: str) -> str:
    return _text(value, label, pattern=REF_RE, maximum=71)


def _opaque(value: Any, label: str) -> str:
    return _text(value, label, pattern=OPAQUE_RE, maximum=256)


def _nonce(value: Any, label: str) -> str:
    return _text(value, label, pattern=NONCE_RE, maximum=160)


def _key_id(value: Any, label: str) -> str:
    return _text(value, label, pattern=KEY_ID_RE, maximum=144)


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HostAdmissionError(f"invalid-{label}: expected positive integer")
    return value


def _string_list(value: Any, label: str, *, maximum: int = 64) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > maximum:
        raise HostAdmissionError(f"invalid-{label}: expected a non-empty bounded array")
    result = [_opaque(item, f"{label}-item") for item in value]
    if len(set(result)) != len(result):
        raise HostAdmissionError(f"invalid-{label}: duplicate values")
    return sorted(result)


def _time(value: Any, label: str) -> datetime:
    text = _text(value, label, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HostAdmissionError(f"invalid-{label}: expected RFC3339") from exc
    if parsed.tzinfo is None:
        raise HostAdmissionError(f"invalid-{label}: timezone required")
    return parsed.astimezone(timezone.utc)


def _interval(issued_at: str, expires_at: str) -> tuple[datetime, datetime]:
    issued = _time(issued_at, "issued-at")
    expires = _time(expires_at, "expires-at")
    if expires <= issued:
        raise HostAdmissionError("invalid-interval: expiry must be after issuance")
    return issued, expires


def _reject_credentials(value: Any, path: str = "admission") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower().replace("-", "_")
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                raise HostAdmissionError(f"{path}.{key} may contain credential material")
            _reject_credentials(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_credentials(child, f"{path}[{index}]")
    elif isinstance(value, str) and CREDENTIAL_VALUE_RE.search(value):
        raise HostAdmissionError(f"{path} contains a credential-shaped value")


def _auth(value: Any) -> dict[str, Any]:
    data = _mapping(value, "auth")
    _unknown(data, AUTH_FIELDS, "auth")
    scheme = _text(data.get("scheme"), "auth-scheme", maximum=32)
    if scheme not in AUTH_SCHEMES:
        raise HostAdmissionError("invalid-auth-scheme")
    replay_protection = _text(data.get("replay_protection"), "replay-protection", maximum=32)
    if replay_protection not in REPLAY_PROTECTION:
        raise HostAdmissionError("invalid-replay-protection")
    if scheme in {"dpop", "mtls", "spiffe-svid"} and replay_protection != "sender-constrained":
        raise HostAdmissionError(
            "sender-constrained-auth-requires-sender-constrained-replay-protection"
        )
    if scheme == "oauth2-bearer" and replay_protection == "sender-constrained":
        raise HostAdmissionError("bearer-auth-cannot-claim-sender-constrained-proof")
    return {
        "scheme": scheme,
        "key_ref": _key_id(data.get("key_ref"), "auth-key-ref"),
        "proof_ref": _ref(data.get("proof_ref"), "auth-proof-ref"),
        "verification_ref": _ref(data.get("verification_ref"), "auth-verification-ref"),
        "replay_protection": replay_protection,
    }


def _admission(value: Any) -> dict[str, Any]:
    data = _mapping(value, "host-admission")
    _reject_credentials(data)
    _unknown(data, ADMISSION_FIELDS, "host-admission")
    if data.get("$schema") != SCHEMA_URI:
        raise HostAdmissionError("wrong-schema-uri")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise HostAdmissionError("unsupported-schema-version")
    if data.get("contract_revision") != CONTRACT_REVISION:
        raise HostAdmissionError("unsupported-contract-revision")
    issued_at = _text(data.get("issued_at"), "issued-at", maximum=64)
    expires_at = _text(data.get("expires_at"), "expires-at", maximum=64)
    _interval(issued_at, expires_at)
    return {
        "$schema": SCHEMA_URI,
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "admission_id": _ref(data.get("admission_id"), "admission-id"),
        "host_ref": _opaque(data.get("host_ref"), "host-ref"),
        "audience_ref": _opaque(data.get("audience_ref"), "audience-ref"),
        "workspace_ref": _opaque(data.get("workspace_ref"), "workspace-ref"),
        "resource_ref": _opaque(data.get("resource_ref"), "resource-ref"),
        "request_ref": _ref(data.get("request_ref"), "request-ref"),
        "authority_ref": _ref(data.get("authority_ref"), "authority-ref"),
        "action_ref": _ref(data.get("action_ref"), "action-ref"),
        "policy_decision_ref": _ref(data.get("policy_decision_ref"), "policy-decision-ref"),
        "approval_ref": _ref(data.get("approval_ref"), "approval-ref"),
        "lease_ref": _ref(data.get("lease_ref"), "lease-ref"),
        "runtime_episode_ref": _ref(data.get("runtime_episode_ref"), "runtime-episode-ref"),
        "provider_operation_ref": _ref(
            data.get("provider_operation_ref"), "provider-operation-ref"
        ),
        "provenance_ref": _ref(data.get("provenance_ref"), "provenance-ref"),
        "policy_revision_ref": _ref(data.get("policy_revision_ref"), "policy-revision-ref"),
        "scope_refs": _string_list(data.get("scope_refs"), "scope-refs"),
        "auth": _auth(data.get("auth")),
        "issued_at": issued_at,
        "expires_at": expires_at,
        "nonce": _nonce(data.get("nonce"), "nonce"),
        "generation": _positive_int(data.get("generation"), "generation"),
    }


def admission_ref(value: Mapping[str, Any]) -> str:
    normalized = _admission(value)
    material = {
        key: copy.deepcopy(child)
        for key, child in normalized.items()
        if key != "admission_id"
    }
    return digest_ref(material)


def make_admission(material: Mapping[str, Any]) -> dict[str, Any]:
    data = _mapping(material, "host-admission-material")
    if "admission_id" in data:
        raise HostAdmissionError("host-admission-material must not provide admission_id")
    candidate = {
        "$schema": SCHEMA_URI,
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        **data,
    }
    normalized_material = _admission(
        {**candidate, "admission_id": "sha256:" + "0" * 64}
    )
    material_digest = {
        key: copy.deepcopy(child)
        for key, child in normalized_material.items()
        if key != "admission_id"
    }
    normalized = _admission(
        {**material_digest, "admission_id": digest_ref(material_digest)}
    )
    if normalized["admission_id"] != admission_ref(normalized):
        raise HostAdmissionError("host-admission-material produced an invalid digest")
    return normalized


def _expected_ref(value: str | None, label: str) -> str | None:
    return None if value is None else _ref(value, label)


def _verify_generation_state(value: Mapping[str, Any] | None) -> dict[str, int]:
    state = dict(value or {})
    normalized: dict[str, int] = {}
    for host_ref, generation in state.items():
        normalized[_opaque(host_ref, "generation-host-ref")] = _positive_int(
            generation, "minimum-generation"
        )
    return normalized


def verify_admission(
    value: Mapping[str, Any],
    *,
    expected_audience_ref: str,
    expected_workspace_ref: str,
    expected_resource_ref: str | None = None,
    expected_request_ref: str | None = None,
    expected_host_ref: str | None = None,
    expected_scope_refs: list[str] | None = None,
    expected_bindings: Mapping[str, str] | None = None,
    at: str,
    seen_nonces: list[str] | None = None,
    generation_state: Mapping[str, Any] | None = None,
    max_lifetime_seconds: int = DEFAULT_MAX_LIFETIME_SECONDS,
) -> dict[str, Any]:
    admission = _admission(value)
    if admission["admission_id"] != admission_ref(admission):
        raise HostAdmissionError("admission-digest-mismatch")
    expected_audience = _opaque(expected_audience_ref, "expected-audience-ref")
    expected_workspace = _opaque(expected_workspace_ref, "expected-workspace-ref")
    expected_values: dict[str, str | None] = {
        "audience_ref": expected_audience,
        "workspace_ref": expected_workspace,
        "resource_ref": (
            None
            if expected_resource_ref is None
            else _opaque(expected_resource_ref, "expected-resource-ref")
        ),
        "request_ref": _expected_ref(expected_request_ref, "expected-request-ref"),
        "host_ref": (
            None if expected_host_ref is None else _opaque(expected_host_ref, "expected-host-ref")
        ),
    }
    for field, expected in expected_values.items():
        if expected is not None and admission[field] != expected:
            raise HostAdmissionError(f"{field}-mismatch")
    for field, expected in dict(expected_bindings or {}).items():
        if field not in BINDING_FIELDS:
            raise HostAdmissionError(f"unsupported-expected-binding:{field}")
        if admission[field] != _ref(expected, f"expected-{field}"):
            raise HostAdmissionError(f"{field}-mismatch")
    if expected_scope_refs is not None:
        expected_scopes = {_opaque(item, "expected-scope-ref") for item in expected_scope_refs}
        if not set(admission["scope_refs"]) <= expected_scopes:
            raise HostAdmissionError("scope-escalation")
    if isinstance(max_lifetime_seconds, bool) or not isinstance(max_lifetime_seconds, int):
        raise HostAdmissionError("invalid-max-lifetime")
    if max_lifetime_seconds < 1:
        raise HostAdmissionError("invalid-max-lifetime")
    issued, expires = _interval(admission["issued_at"], admission["expires_at"])
    if (expires - issued).total_seconds() > max_lifetime_seconds:
        raise HostAdmissionError("admission-lifetime-too-long")
    now = _time(at, "verification-at")
    if now < issued or now >= expires:
        raise HostAdmissionError("expired-or-not-yet-valid")
    seen = set(seen_nonces or [])
    if any(not isinstance(item, str) or not NONCE_RE.fullmatch(item) for item in seen):
        raise HostAdmissionError("invalid-seen-nonce")
    if admission["nonce"] in seen:
        raise HostAdmissionError("nonce-replay")
    minimum = _verify_generation_state(generation_state).get(admission["host_ref"])
    if minimum is not None and admission["generation"] < minimum:
        raise HostAdmissionError("stale-generation")
    auth = admission["auth"]
    return {
        "status": "passed",
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "authentication_boundary": "external",
        "admission_id": admission["admission_id"],
        "host_ref": admission["host_ref"],
        "audience_ref": admission["audience_ref"],
        "workspace_ref": admission["workspace_ref"],
        "resource_ref": admission["resource_ref"],
        "request_ref": admission["request_ref"],
        "binding_refs": {field: admission[field] for field in sorted(BINDING_FIELDS)},
        "scope_refs": admission["scope_refs"],
        "auth": {
            "scheme": auth["scheme"],
            "key_ref": auth["key_ref"],
            "proof_ref": auth["proof_ref"],
            "verification_ref": auth["verification_ref"],
            "replay_protection": auth["replay_protection"],
        },
        "nonce_ref": admission["nonce"],
        "generation": admission["generation"],
        "checks": {
            "schema": True,
            "admission_digest": True,
            "audience_workspace_resource": True,
            "request_binding": True,
            "authority_bindings": True,
            "scope_narrowing": True,
            "host_proof_reference": True,
            "replay_protection": True,
            "expiry": True,
            "generation": True,
            "credential_exclusion": True,
        },
    }


def load_admission(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HostAdmissionError(f"cannot-load-admission:{path}") from exc
    return _admission(value)


def verify_file(path: Path, **kwargs: Any) -> dict[str, Any]:
    return verify_admission(load_admission(path), **kwargs)


def evaluate_corpus(path: Path) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = _mapping(json.loads(line), f"corpus-case-{line_number}")
            case_id = _text(case.get("case_id"), "corpus-case-id", maximum=96)
            expected = case.get("expected")
            if expected not in {"passed", "failed"}:
                raise HostAdmissionError("invalid-corpus-expected")
            context = _mapping(case.get("context"), "corpus-context")
            observed = "passed"
            result: dict[str, Any] | None = None
            error = None
            try:
                result = verify_admission(
                    case.get("admission"),
                    expected_audience_ref=context.get("expected_audience_ref"),
                    expected_workspace_ref=context.get("expected_workspace_ref"),
                    expected_resource_ref=context.get("expected_resource_ref"),
                    expected_request_ref=context.get("expected_request_ref"),
                    expected_host_ref=context.get("expected_host_ref"),
                    expected_scope_refs=context.get("expected_scope_refs"),
                    expected_bindings=context.get("expected_bindings", {}),
                    at=context.get("at"),
                    seen_nonces=context.get("seen_nonces", []),
                    generation_state=context.get("generation_state", {}),
                    max_lifetime_seconds=context.get(
                        "max_lifetime_seconds", DEFAULT_MAX_LIFETIME_SECONDS
                    ),
                )
            except (HostAdmissionError, TypeError, AttributeError) as exc:
                observed = "failed"
                error = str(exc).split(":", 1)[0]
            status = "pass" if observed == expected else "fail"
            record: dict[str, Any] = {
                "case_id": case_id,
                "expected": expected,
                "observed": observed,
                "status": status,
            }
            if error is not None:
                record["error"] = error
            if result is not None:
                record["admission_id"] = result["admission_id"]
            cases.append(record)
        except (HostAdmissionError, json.JSONDecodeError, TypeError) as exc:
            cases.append(
                {
                    "case_id": f"line-{line_number}",
                    "expected": "failed",
                    "observed": "failed",
                    "status": "fail",
                    "error": str(exc).split(":", 1)[0],
                }
            )
    passed = sum(item["status"] == "pass" for item in cases)
    threat_cases = sum(item["expected"] == "failed" for item in cases)
    return {
        "status": "passed" if passed == len(cases) else "failed",
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "case_count": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "threat_cases": threat_cases,
        "deterministic": True,
        "authentication_boundary": "external-reference",
        "cases": cases,
        "corpus_digest": digest_ref(cases),
    }


def _json_output(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify", help="verify one host admission file")
    verify_parser.add_argument("--input", type=Path, required=True)
    verify_parser.add_argument("--audience", required=True)
    verify_parser.add_argument("--workspace", required=True)
    verify_parser.add_argument("--resource")
    verify_parser.add_argument("--request-ref")
    verify_parser.add_argument("--host-ref")
    verify_parser.add_argument("--at", required=True)
    verify_parser.add_argument(
        "--max-lifetime-seconds", type=int, default=DEFAULT_MAX_LIFETIME_SECONDS
    )
    verify_parser.add_argument("--seen-nonce", action="append", default=[])
    evaluate_parser = subparsers.add_parser(
        "evaluate", help="evaluate the deterministic host corpus"
    )
    evaluate_parser.add_argument("--corpus", type=Path, required=True)
    evaluate_parser.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.command == "verify":
            result = verify_file(
                args.input,
                expected_audience_ref=args.audience,
                expected_workspace_ref=args.workspace,
                expected_resource_ref=args.resource,
                expected_request_ref=args.request_ref,
                expected_host_ref=args.host_ref,
                at=args.at,
                seen_nonces=args.seen_nonce,
                max_lifetime_seconds=args.max_lifetime_seconds,
            )
        else:
            result = evaluate_corpus(args.corpus)
        _json_output(result)
        return 0 if result.get("status") in {"passed", "pass"} else 1
    except (HostAdmissionError, OSError, TypeError, ValueError) as exc:
        print(f"forge-host-admission: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
