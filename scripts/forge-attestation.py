#!/usr/bin/env python3
"""Verify Forge release attestations and their SLSA bindings offline."""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hashlib
import hmac
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ENVELOPE_TYPE = "application/vnd.in-toto+dsse"
PAYLOAD_TYPES = {
    "application/vnd.in-toto+json",
    "application/vnd.in-toto.provenance+json",
    "application/vnd.in-toto.spdx+json",
}
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
SLSA_PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
BUILD_TYPE = "https://github.com/AlisinaDevelo/md-files/forge/release/v1"
REPOSITORY_URI = "https://github.com/AlisinaDevelo/md-files"
TRUST_ROOT_PROFILE = "forge-trust-root-v1"
PUBLIC_PROFILE = "public-key-dsse-v1"
HMAC_PROFILE = "local-hmac-v1"
GITHUB_PROFILE = "github-artifact-v1"
PUBLIC_KEY_ALGORITHM = "ed25519"
HMAC_ALGORITHM = "hmac-sha256"
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")

# Ed25519 constants from RFC 8032. Keeping verification here avoids adding a
# runtime dependency to a release verifier that must work in an air-gapped host.
_ED_P = 2**255 - 19
_ED_Q = 2**252 + 27742317777372353535851937790883648493
_ED_D = (-121665 * pow(121666, _ED_P - 2, _ED_P)) % _ED_P
_ED_I = pow(2, (_ED_P - 1) // 4, _ED_P)
_ED_B_Y = (4 * pow(5, _ED_P - 2, _ED_P)) % _ED_P

Point = tuple[int, int]
_ED_B_X: int
_ED_B_X = 0


class AttestationError(ValueError):
    """Raised when an attestation or its trust policy fails closed."""


def canonical_json(value: Any) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise AttestationError(f"value is not canonical JSON: {exc}") from exc


def _compact_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AttestationError(f"value is not canonical JSON: {exc}") from exc


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(_compact_json(value))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise AttestationError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AttestationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AttestationError(f"JSON document must be an object: {path}")
    return value


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AttestationError(f"{field} must be an object")
    return value


def _fields(value: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise AttestationError(f"{field} has unsupported fields: {', '.join(unknown)}")


def _string(value: Any, field: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise AttestationError(f"{field} must be a non-empty string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise AttestationError(f"{field} has an invalid format")
    return value


def _b64(value: Any, field: str) -> bytes:
    _string(value, field)
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttestationError(f"{field} is not valid base64") from exc


def _hex_digest(value: Any, field: str) -> str:
    text = _string(value, field)
    text = text.removeprefix("sha256:")
    if HEX64_RE.fullmatch(text) is None:
        raise AttestationError(f"{field} must be a SHA-256 digest")
    return text


def _sha256_ref(value: Any, field: str) -> str:
    return "sha256:" + _hex_digest(value, field)


def _pae(payload_type: bytes, payload: bytes) -> bytes:
    def length(value: bytes) -> bytes:
        return str(len(value)).encode("ascii")

    return b"DSSEv1 " + length(payload_type) + b" " + payload_type + b" " + length(payload) + b" " + payload


def _inv(value: int) -> int:
    return pow(value, _ED_P - 2, _ED_P)


def _recover_x(y: int, sign: int) -> int:
    xx = ((y * y - 1) * _inv((_ED_D * y * y + 1) % _ED_P)) % _ED_P
    x = pow(xx, (_ED_P + 3) // 8, _ED_P)
    if (x * x - xx) % _ED_P != 0:
        x = (x * _ED_I) % _ED_P
    if (x * x - xx) % _ED_P != 0:
        raise AttestationError("Ed25519 point is not on the curve")
    if x & 1 != sign:
        x = _ED_P - x
    if x == 0 and sign:
        raise AttestationError("Ed25519 point has an invalid sign bit")
    return x


def _decode_point(encoded: bytes, field: str) -> Point:
    if len(encoded) != 32:
        raise AttestationError(f"{field} must be 32 bytes")
    y = int.from_bytes(encoded, "little") & ((1 << 255) - 1)
    sign = encoded[31] >> 7
    if y >= _ED_P:
        raise AttestationError(f"{field} has a non-canonical encoding")
    x = _recover_x(y, sign)
    if (-x * x + y * y - 1 - _ED_D * x * x * y * y) % _ED_P != 0:
        raise AttestationError(f"{field} is not on the Ed25519 curve")
    return x, y


def _encode_point(point: Point) -> bytes:
    x, y = point
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _point_add(first: Point, second: Point) -> Point:
    x1, y1 = first
    x2, y2 = second
    product = (_ED_D * x1 * x2 * y1 * y2) % _ED_P
    x3 = ((x1 * y2 + x2 * y1) * _inv(1 + product)) % _ED_P
    y3 = ((y1 * y2 + x1 * x2) * _inv(1 - product)) % _ED_P
    return x3, y3


def _scalar_mult(point: Point, scalar: int) -> Point:
    result: Point = (0, 1)
    addend = point
    while scalar:
        if scalar & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        scalar >>= 1
    return result


def _base_point() -> Point:
    global _ED_B_X
    if _ED_B_X == 0:
        _ED_B_X = _recover_x(_ED_B_Y, 0)
    return _ED_B_X, _ED_B_Y


def _ed25519_verify(signature: bytes, public_key: bytes, message: bytes) -> None:
    if len(signature) != 64:
        raise AttestationError("Ed25519 signature must be 64 bytes")
    if len(public_key) != 32:
        raise AttestationError("Ed25519 public key must be 32 bytes")
    public_point = _decode_point(public_key, "public key")
    encoded_r = signature[:32]
    point_r = _decode_point(encoded_r, "signature R")
    scalar_s = int.from_bytes(signature[32:], "little")
    if scalar_s >= _ED_Q:
        raise AttestationError("Ed25519 signature scalar is out of range")
    if _scalar_mult(public_point, 8) == (0, 1) or _scalar_mult(point_r, 8) == (0, 1):
        raise AttestationError("Ed25519 small-order point is not trusted")
    challenge = int.from_bytes(hashlib.sha512(encoded_r + public_key + message).digest(), "little") % _ED_Q
    left = _scalar_mult(_base_point(), scalar_s)
    right = _point_add(point_r, _scalar_mult(public_point, challenge))
    if _encode_point(_scalar_mult(left, 8)) != _encode_point(_scalar_mult(right, 8)):
        raise AttestationError("Ed25519 signature verification failed")


def _ed25519_public_key(seed: bytes) -> bytes:
    if len(seed) != 32:
        raise AttestationError("Ed25519 seed must be 32 bytes")
    expanded = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(expanded[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return _encode_point(_scalar_mult(_base_point(), scalar))


def _ed25519_sign(seed: bytes, message: bytes) -> bytes:
    if len(seed) != 32:
        raise AttestationError("Ed25519 seed must be 32 bytes")
    expanded = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(expanded[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    public_key = _encode_point(_scalar_mult(_base_point(), scalar))
    nonce = int.from_bytes(hashlib.sha512(expanded[32:] + message).digest(), "little") % _ED_Q
    encoded_r = _encode_point(_scalar_mult(_base_point(), nonce))
    challenge = int.from_bytes(hashlib.sha512(encoded_r + public_key + message).digest(), "little") % _ED_Q
    scalar_s = (nonce + challenge * scalar) % _ED_Q
    return encoded_r + scalar_s.to_bytes(32, "little")


def _validate_trust_root(root: Mapping[str, Any]) -> dict[str, Any]:
    _fields(root, {"schema_version", "profile", "revision", "keys", "revoked_key_ids", "allowed_builder_ids"}, "trust root")
    if root.get("schema_version") != SCHEMA_VERSION or root.get("profile") != TRUST_ROOT_PROFILE:
        raise AttestationError("unsupported trust root")
    revision = _string(root.get("revision"), "trust root revision")
    keys = root.get("keys")
    if not isinstance(keys, list) or not keys:
        raise AttestationError("trust root keys must be a non-empty array")
    revoked = root.get("revoked_key_ids", [])
    if not isinstance(revoked, list) or not all(isinstance(item, str) for item in revoked):
        raise AttestationError("trust root revoked_key_ids must be a string array")
    allowed_builders = root.get("allowed_builder_ids", [])
    if not isinstance(allowed_builders, list) or not all(isinstance(item, str) and item for item in allowed_builders):
        raise AttestationError("trust root allowed_builder_ids must be a string array")
    indexed: dict[str, dict[str, Any]] = {}
    for index, raw_key in enumerate(keys):
        key = _object(raw_key, f"trust root keys[{index}]")
        _fields(key, {"key_id", "algorithm", "status", "public_key_b64", "key_b64"}, f"trust root keys[{index}]")
        key_id = _string(key.get("key_id"), f"trust root keys[{index}].key_id", pattern=KEY_ID_RE)
        if key_id in indexed:
            raise AttestationError(f"trust root repeats key id: {key_id}")
        algorithm = _string(key.get("algorithm"), f"trust root keys[{index}].algorithm")
        if algorithm not in {PUBLIC_KEY_ALGORITHM, HMAC_ALGORITHM}:
            raise AttestationError(f"trust root uses unsupported algorithm: {algorithm}")
        status = _string(key.get("status"), f"trust root keys[{index}].status")
        if status not in {"active", "retired", "revoked"}:
            raise AttestationError(f"trust root uses unsupported key status: {status}")
        material_field = "public_key_b64" if algorithm == PUBLIC_KEY_ALGORITHM else "key_b64"
        if material_field not in key:
            raise AttestationError(f"trust root key {key_id} is missing {material_field}")
        material = _b64(key[material_field], f"trust root key {key_id}.{material_field}")
        if algorithm == PUBLIC_KEY_ALGORITHM and len(material) != 32:
            raise AttestationError(f"trust root public key {key_id} must be 32 bytes")
        if algorithm == HMAC_ALGORITHM and len(material) < 16:
            raise AttestationError(f"trust root HMAC key {key_id} is too short")
        indexed[key_id] = {**key, "key_id": key_id, "algorithm": algorithm, "status": status, "material": material}
    if len(set(revoked)) != len(revoked) or any(item not in indexed for item in revoked):
        raise AttestationError("trust root revoked_key_ids must name known unique keys")
    for key_id in revoked:
        indexed[key_id]["status"] = "revoked"
    return {
        "revision": revision,
        "keys": indexed,
        "revoked_key_ids": sorted(revoked),
        "allowed_builder_ids": sorted(allowed_builders),
    }


def _validate_envelope(envelope: Mapping[str, Any]) -> tuple[dict[str, Any], bytes, bytes]:
    _fields(envelope, {"payloadType", "payload", "signatures", "forge"}, "DSSE envelope")
    payload_type = _string(envelope.get("payloadType"), "DSSE payloadType")
    if payload_type not in PAYLOAD_TYPES:
        raise AttestationError(f"unsupported DSSE payloadType: {payload_type}")
    payload = _b64(envelope.get("payload"), "DSSE payload")
    signatures = envelope.get("signatures")
    if not isinstance(signatures, list) or not signatures:
        raise AttestationError("DSSE signatures must be a non-empty array")
    forge = _object(envelope.get("forge"), "DSSE forge metadata")
    _fields(forge, {"schema_version", "profile", "canonical_json"}, "DSSE forge metadata")
    if forge.get("schema_version") != SCHEMA_VERSION or forge.get("canonical_json") is not True:
        raise AttestationError("DSSE Forge metadata is unsupported")
    profile = _string(forge.get("profile"), "DSSE profile")
    if profile not in {PUBLIC_PROFILE, HMAC_PROFILE}:
        raise AttestationError(f"DSSE envelope is not an offline Forge profile: {profile}")
    try:
        statement = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AttestationError(f"DSSE payload is not UTF-8 JSON: {exc}") from exc
    if not isinstance(statement, dict) or canonical_json(statement) != payload:
        raise AttestationError("DSSE payload must be canonical Forge JSON")
    for index, raw_signature in enumerate(signatures):
        signature = _object(raw_signature, f"DSSE signatures[{index}]")
        _fields(signature, {"keyid", "sig"}, f"DSSE signatures[{index}]")
        _string(signature.get("keyid"), f"DSSE signatures[{index}].keyid", pattern=KEY_ID_RE)
        _b64(signature.get("sig"), f"DSSE signatures[{index}].sig")
    return {"payload_type": payload_type, "profile": profile, "signatures": signatures}, payload, statement


def verify_envelope(envelope: Mapping[str, Any], trust_root: Mapping[str, Any]) -> dict[str, Any]:
    metadata, payload, statement = _validate_envelope(envelope)
    root = _validate_trust_root(trust_root)
    expected_algorithm = PUBLIC_KEY_ALGORITHM if metadata["profile"] == PUBLIC_PROFILE else HMAC_ALGORITHM
    signed = _pae(metadata["payload_type"].encode("utf-8"), payload)
    key_ids: list[str] = []
    for index, raw_signature in enumerate(metadata["signatures"]):
        signature = _object(raw_signature, f"DSSE signatures[{index}]")
        key_id = str(signature["keyid"])
        key = root["keys"].get(key_id)
        if key is None:
            raise AttestationError(f"DSSE signature uses an untrusted key: {key_id}")
        if key["status"] == "revoked":
            raise AttestationError(f"DSSE signature uses a revoked key: {key_id}")
        if key["algorithm"] != expected_algorithm:
            raise AttestationError(f"DSSE profile and trust-root algorithm disagree for key: {key_id}")
        raw_signature_bytes = _b64(signature["sig"], f"DSSE signatures[{index}].sig")
        if expected_algorithm == HMAC_ALGORITHM:
            expected = hmac.new(key["material"], signed, hashlib.sha256).digest()
            if not hmac.compare_digest(raw_signature_bytes, expected):
                raise AttestationError(f"HMAC signature verification failed for key: {key_id}")
        else:
            _ed25519_verify(raw_signature_bytes, key["material"], signed)
        key_ids.append(key_id)
    return {
        "status": "verified",
        "profile": metadata["profile"],
        "key_ids": sorted(key_ids),
        "payload_type": metadata["payload_type"],
        "payload_digest": digest_bytes(payload),
        "statement": statement,
        "trust_root_revision": root["revision"],
    }


def _manifest_subjects(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise AttestationError("release manifest has no artifacts")
    subjects: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_artifact in enumerate(artifacts):
        artifact = _object(raw_artifact, f"release manifest artifacts[{index}]")
        name = _string(artifact.get("name"), f"release manifest artifacts[{index}].name")
        digest = _hex_digest(artifact.get("sha256"), f"release manifest artifacts[{index}].sha256")
        if name in seen:
            raise AttestationError(f"release manifest repeats artifact: {name}")
        seen.add(name)
        subjects.append({"name": name, "digest": {"sha256": digest}})
    return sorted(subjects, key=lambda item: item["name"])


def _statement_subjects(statement: Mapping[str, Any]) -> list[dict[str, Any]]:
    _fields(statement, {"_type", "subject", "predicateType", "predicate"}, "in-toto statement")
    if statement.get("_type") != STATEMENT_TYPE or statement.get("predicateType") != SLSA_PREDICATE_TYPE:
        raise AttestationError("statement is not an in-toto SLSA v1 statement")
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or not subjects:
        raise AttestationError("statement subject must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_subject in enumerate(subjects):
        subject = _object(raw_subject, f"statement subject[{index}]")
        _fields(subject, {"name", "digest"}, f"statement subject[{index}]")
        name = _string(subject.get("name"), f"statement subject[{index}].name")
        if name.startswith("/") or ".." in Path(name).parts:
            raise AttestationError(f"statement subject path is unsafe: {name}")
        digest = _object(subject.get("digest"), f"statement subject[{index}].digest")
        _fields(digest, {"sha256"}, f"statement subject[{index}].digest")
        value = _hex_digest(digest.get("sha256"), f"statement subject[{index}].digest.sha256")
        if name in seen:
            raise AttestationError(f"statement repeats subject: {name}")
        seen.add(name)
        normalized.append({"name": name, "digest": {"sha256": value}})
    return sorted(normalized, key=lambda item: item["name"])


def _normalize_sha_ref(value: str) -> str:
    return "sha256:" + _hex_digest(value, "digest")


def _build_statement(
    manifest_path: Path,
    root: Path,
    policy_path: Path,
    *,
    source_ref: str,
    builder_id: str,
) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    version = _string(manifest.get("version"), "release manifest version")
    tag = _string(manifest.get("tag"), "release manifest tag")
    commit = _string(manifest.get("commit"), "release manifest commit")
    manifest_name = manifest_path.name
    manifest_digest = _sha256_file(manifest_path)
    policy_digest = _sha256_file(policy_path)
    subjects = _manifest_subjects(manifest)
    for subject in subjects:
        artifact_path = (root / subject["name"]).resolve()
        if root.resolve() not in artifact_path.parents or not artifact_path.is_file():
            raise AttestationError(f"release subject is missing: {subject['name']}")
        actual = _sha256_file(artifact_path)
        if actual != subject["digest"]["sha256"]:
            raise AttestationError(f"release subject digest mismatch: {subject['name']}")
    _string(source_ref, "source ref")
    _string(builder_id, "builder id")
    external_parameters = {
        "source": {"repository": REPOSITORY_URI, "commit": commit, "ref": source_ref},
        "release": {"version": version, "tag": tag, "source_date_epoch": manifest.get("source_date_epoch")},
        "policy": {"path": "policies/release.json", "sha256": policy_digest},
        "manifest": {"name": manifest_name, "sha256": manifest_digest},
    }
    resolved_dependencies = [
        {"uri": REPOSITORY_URI, "digest": {"gitCommit": commit}},
        {"uri": f"{REPOSITORY_URI}/blob/{source_ref}/policies/release.json", "digest": {"sha256": policy_digest}},
        {"uri": f"{REPOSITORY_URI}/blob/{source_ref}/{manifest_name}", "digest": {"sha256": manifest_digest}},
    ]
    invocation_id = digest_json({"commit": commit, "manifest": manifest_digest, "policy": policy_digest, "source_ref": source_ref})
    return {
        "_type": STATEMENT_TYPE,
        "subject": subjects,
        "predicateType": SLSA_PREDICATE_TYPE,
        "predicate": {
            "buildDefinition": {
                "buildType": BUILD_TYPE,
                "externalParameters": external_parameters,
                "internalParameters": {"subject_rule": "release-manifest-artifacts-v1"},
                "resolvedDependencies": resolved_dependencies,
            },
            "runDetails": {"builder": {"id": builder_id}, "metadata": {"invocationId": invocation_id}},
        },
    }


def _validate_binding(
    statement: Mapping[str, Any],
    manifest_path: Path,
    root: Path,
    policy_path: Path,
    *,
    source_ref: str,
    expected_builder_id: str | None,
    allowed_builder_ids: list[str],
) -> dict[str, Any]:
    actual_subjects = _statement_subjects(statement)
    manifest = _load_json(manifest_path)
    expected_subjects = _manifest_subjects(manifest)
    if actual_subjects != expected_subjects:
        raise AttestationError("attestation subjects do not match the release manifest")
    for subject in expected_subjects:
        artifact_path = (root / subject["name"]).resolve()
        if root.resolve() not in artifact_path.parents or not artifact_path.is_file():
            raise AttestationError(f"release subject is missing: {subject['name']}")
        if _sha256_file(artifact_path) != subject["digest"]["sha256"]:
            raise AttestationError(f"release subject digest mismatch: {subject['name']}")
    predicate = _object(statement.get("predicate"), "statement predicate")
    _fields(predicate, {"buildDefinition", "runDetails"}, "statement predicate")
    build_definition = _object(predicate.get("buildDefinition"), "statement buildDefinition")
    _fields(build_definition, {"buildType", "externalParameters", "internalParameters", "resolvedDependencies"}, "statement buildDefinition")
    if build_definition.get("buildType") != BUILD_TYPE:
        raise AttestationError("attestation build type does not match Forge release contract")
    external = _object(build_definition.get("externalParameters"), "statement externalParameters")
    _fields(external, {"source", "release", "policy", "manifest"}, "statement externalParameters")
    source = _object(external.get("source"), "statement externalParameters.source")
    _fields(source, {"repository", "commit", "ref"}, "statement externalParameters.source")
    if source != {"repository": REPOSITORY_URI, "commit": manifest.get("commit"), "ref": source_ref}:
        raise AttestationError("attestation source binding does not match the release")
    release = _object(external.get("release"), "statement externalParameters.release")
    _fields(release, {"version", "tag", "source_date_epoch"}, "statement externalParameters.release")
    if release != {
        "version": manifest.get("version"),
        "tag": manifest.get("tag"),
        "source_date_epoch": manifest.get("source_date_epoch"),
    }:
        raise AttestationError("attestation release binding does not match the manifest")
    policy = _object(external.get("policy"), "statement externalParameters.policy")
    _fields(policy, {"path", "sha256"}, "statement externalParameters.policy")
    policy_digest = _sha256_file(policy_path)
    if policy != {"path": "policies/release.json", "sha256": policy_digest}:
        raise AttestationError("attestation policy binding does not match the policy file")
    manifest_binding = _object(external.get("manifest"), "statement externalParameters.manifest")
    _fields(manifest_binding, {"name", "sha256"}, "statement externalParameters.manifest")
    manifest_digest = _sha256_file(manifest_path)
    if manifest_binding != {"name": manifest_path.name, "sha256": manifest_digest}:
        raise AttestationError("attestation manifest binding does not match the manifest file")
    internal = _object(build_definition.get("internalParameters"), "statement internalParameters")
    _fields(internal, {"subject_rule"}, "statement internalParameters")
    if internal.get("subject_rule") != "release-manifest-artifacts-v1":
        raise AttestationError("attestation subject rule is unsupported")
    dependencies = build_definition.get("resolvedDependencies")
    if not isinstance(dependencies, list) or len(dependencies) != 3:
        raise AttestationError("attestation resolvedDependencies must contain exactly three entries")
    normalized_dependencies = []
    for index, value in enumerate(dependencies):
        item = _object(value, f"statement resolvedDependencies[{index}]")
        _fields(item, {"uri", "digest"}, f"statement resolvedDependencies[{index}]")
        _string(item.get("uri"), f"statement resolvedDependencies[{index}].uri")
        digest = _object(item.get("digest"), f"statement resolvedDependencies[{index}].digest")
        _fields(digest, {"gitCommit", "sha256"}, f"statement resolvedDependencies[{index}].digest")
        normalized_dependencies.append((item["uri"], json.dumps(digest, sort_keys=True)))
    dependency_set = set(normalized_dependencies)
    expected_dependencies = {
        (REPOSITORY_URI, json.dumps({"gitCommit": manifest.get("commit")}, sort_keys=True)),
        (f"{REPOSITORY_URI}/blob/{source_ref}/policies/release.json", json.dumps({"sha256": policy_digest}, sort_keys=True)),
        (f"{REPOSITORY_URI}/blob/{source_ref}/{manifest_path.name}", json.dumps({"sha256": manifest_digest}, sort_keys=True)),
    }
    if dependency_set != expected_dependencies:
        raise AttestationError("attestation resolved inputs do not match the release")
    run_details = _object(predicate.get("runDetails"), "statement runDetails")
    _fields(run_details, {"builder", "metadata"}, "statement runDetails")
    builder = _object(run_details.get("builder"), "statement builder")
    _fields(builder, {"id"}, "statement builder")
    builder_id = _string(builder.get("id"), "statement builder.id")
    if expected_builder_id is not None and builder_id != expected_builder_id:
        raise AttestationError("attestation builder identity does not match the expected builder")
    if expected_builder_id is None and not allowed_builder_ids:
        raise AttestationError("attestation builder identity requires an expected builder or trust-root allowlist")
    if allowed_builder_ids and builder_id not in allowed_builder_ids:
        raise AttestationError("attestation builder identity is not allowed by the trust root")
    metadata = _object(run_details.get("metadata"), "statement run metadata")
    _fields(metadata, {"invocationId"}, "statement run metadata")
    invocation_id = _string(metadata.get("invocationId"), "statement invocationId")
    expected_invocation = digest_json(
        {"commit": manifest.get("commit"), "manifest": manifest_digest, "policy": policy_digest, "source_ref": source_ref}
    )
    if invocation_id != expected_invocation:
        raise AttestationError("attestation invocation binding does not match the release inputs")
    return {
        "status": "verified",
        "subject_count": len(actual_subjects),
        "statement_digest": digest_json(statement),
        "binding_digest": digest_json(
            {"source": source, "release": release, "policy": policy, "manifest": manifest_binding, "builder": builder_id}
        ),
        "source_commit": manifest.get("commit"),
    }


def verify_release_attestation(
    envelope: Mapping[str, Any],
    trust_root: Mapping[str, Any],
    manifest_path: Path,
    root: Path,
    policy_path: Path,
    *,
    source_ref: str,
    expected_builder_id: str | None = None,
    expected_profile: str | None = None,
) -> dict[str, Any]:
    cryptographic = verify_envelope(envelope, trust_root)
    if expected_profile is not None and cryptographic["profile"] != expected_profile:
        raise AttestationError("attestation profile does not match the requested profile")
    root_policy = _validate_trust_root(trust_root)
    binding = _validate_binding(
        cryptographic["statement"],
        manifest_path,
        root,
        policy_path,
        source_ref=source_ref,
        expected_builder_id=expected_builder_id,
        allowed_builder_ids=root_policy["allowed_builder_ids"],
    )
    return {
        "status": "verified",
        "profile": cryptographic["profile"],
        "key_ids": cryptographic["key_ids"],
        "payload_type": cryptographic["payload_type"],
        "payload_digest": cryptographic["payload_digest"],
        "trust_root_revision": cryptographic["trust_root_revision"],
        **{key: value for key, value in binding.items() if key != "status"},
    }


def _make_envelope(statement: Mapping[str, Any], profile: str, key_id: str, material: bytes) -> dict[str, Any]:
    payload = canonical_json(statement)
    payload_type = "application/vnd.in-toto+json"
    signed = _pae(payload_type.encode("utf-8"), payload)
    if profile == HMAC_PROFILE:
        signature = hmac.new(material, signed, hashlib.sha256).digest()
    elif profile == PUBLIC_PROFILE:
        signature = _ed25519_sign(material, signed)
    else:
        raise AttestationError(f"unsupported envelope profile: {profile}")
    return {
        "payloadType": payload_type,
        "payload": base64.b64encode(payload).decode("ascii"),
        "signatures": [{"keyid": key_id, "sig": base64.b64encode(signature).decode("ascii")}],
        "forge": {"schema_version": SCHEMA_VERSION, "profile": profile, "canonical_json": True},
    }


def _test_root(profile: str, key_id: str, material: bytes) -> dict[str, Any]:
    key = {
        "key_id": key_id,
        "algorithm": PUBLIC_KEY_ALGORITHM if profile == PUBLIC_PROFILE else HMAC_ALGORITHM,
        "status": "active",
    }
    key["public_key_b64" if profile == PUBLIC_PROFILE else "key_b64"] = base64.b64encode(material).decode("ascii")
    return {
        "schema_version": SCHEMA_VERSION,
        "profile": TRUST_ROOT_PROFILE,
        "revision": "forge-attestation-self-test-v1",
        "keys": [key],
        "revoked_key_ids": [],
        "allowed_builder_ids": ["https://forge.local/build/release/v1"],
    }


def _expect_failure(label: str, operation: Any) -> dict[str, str]:
    try:
        operation()
    except AttestationError:
        return {"case": label, "status": "pass"}
    raise AttestationError(f"negative attestation case unexpectedly passed: {label}")


def self_test(manifest_path: Path, root: Path, policy_path: Path, *, source_ref: str, builder_id: str) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    statement = _build_statement(manifest_path, root, policy_path, source_ref=source_ref, builder_id=builder_id)
    hmac_key = b"forge-attestation-self-test-key-0001"
    hmac_root = _test_root(HMAC_PROFILE, "self-test-hmac", hmac_key)
    hmac_envelope = _make_envelope(statement, HMAC_PROFILE, "self-test-hmac", hmac_key)
    public_seed = bytes(range(32))
    public_root = _test_root(PUBLIC_PROFILE, "self-test-ed25519", _ed25519_public_key(public_seed))
    public_envelope = _make_envelope(statement, PUBLIC_PROFILE, "self-test-ed25519", public_seed)
    profile_results = [
        verify_release_attestation(
            hmac_envelope,
            hmac_root,
            manifest_path,
            root,
            policy_path,
            source_ref=source_ref,
            expected_builder_id=builder_id,
        ),
        verify_release_attestation(
            public_envelope,
            public_root,
            manifest_path,
            root,
            policy_path,
            source_ref=source_ref,
            expected_builder_id=builder_id,
        ),
    ]
    tampered_subject = copy.deepcopy(statement)
    tampered_subject["subject"][0]["digest"]["sha256"] = "0" * 64
    tampered_subject_envelope = _make_envelope(tampered_subject, HMAC_PROFILE, "self-test-hmac", hmac_key)
    tampered_predicate = copy.deepcopy(statement)
    tampered_predicate["predicate"]["buildDefinition"]["externalParameters"]["source"]["ref"] = "refs/heads/evil"
    tampered_predicate_envelope = _make_envelope(tampered_predicate, HMAC_PROFILE, "self-test-hmac", hmac_key)
    tampered_signature = copy.deepcopy(hmac_envelope)
    raw_signature = bytearray(_b64(tampered_signature["signatures"][0]["sig"], "test signature"))
    raw_signature[0] ^= 1
    tampered_signature["signatures"][0]["sig"] = base64.b64encode(raw_signature).decode("ascii")
    tampered_root = copy.deepcopy(public_root)
    public_key = bytearray(_b64(tampered_root["keys"][0]["public_key_b64"], "test public key"))
    public_key[0] ^= 1
    tampered_root["keys"][0]["public_key_b64"] = base64.b64encode(public_key).decode("ascii")
    tampered_binding = copy.deepcopy(statement)
    tampered_binding["predicate"]["buildDefinition"]["externalParameters"]["policy"]["sha256"] = "1" * 64
    tampered_binding_envelope = _make_envelope(tampered_binding, HMAC_PROFILE, "self-test-hmac", hmac_key)
    negative_cases = [
        _expect_failure(
            "subject-mismatch",
            lambda: verify_release_attestation(
                tampered_subject_envelope,
                hmac_root,
                manifest_path,
                root,
                policy_path,
                source_ref=source_ref,
                expected_builder_id=builder_id,
            ),
        ),
        _expect_failure(
            "predicate-mismatch",
            lambda: verify_release_attestation(
                tampered_predicate_envelope,
                hmac_root,
                manifest_path,
                root,
                policy_path,
                source_ref=source_ref,
                expected_builder_id=builder_id,
            ),
        ),
        _expect_failure(
            "signature-mismatch",
            lambda: verify_release_attestation(
                tampered_signature,
                hmac_root,
                manifest_path,
                root,
                policy_path,
                source_ref=source_ref,
                expected_builder_id=builder_id,
            ),
        ),
        _expect_failure(
            "trust-root-mismatch",
            lambda: verify_release_attestation(
                public_envelope,
                tampered_root,
                manifest_path,
                root,
                policy_path,
                source_ref=source_ref,
                expected_builder_id=builder_id,
            ),
        ),
        _expect_failure(
            "binding-mismatch",
            lambda: verify_release_attestation(
                tampered_binding_envelope,
                hmac_root,
                manifest_path,
                root,
                policy_path,
                source_ref=source_ref,
                expected_builder_id=builder_id,
            ),
        ),
    ]
    with tempfile.TemporaryDirectory(prefix="forge-attestation-self-test-") as temporary:
        tampered_root_dir = Path(temporary)
        for path in root.iterdir():
            if path.is_file():
                shutil.copy2(path, tampered_root_dir / path.name)
        first_artifact = _manifest_subjects(manifest)[0]["name"]
        tampered_artifact = tampered_root_dir / first_artifact
        tampered_artifact.write_bytes(tampered_artifact.read_bytes() + b"tampered")
        negative_cases.append(
            _expect_failure(
                "artifact-mismatch",
                lambda: verify_release_attestation(
                    hmac_envelope,
                    hmac_root,
                    tampered_root_dir / manifest_path.name,
                    tampered_root_dir,
                    policy_path,
                    source_ref=source_ref,
                    expected_builder_id=builder_id,
                ),
            )
        )
    return {
        "status": "passed",
        "contract": "forge-release-attestation-v1",
        "subject_count": len(_manifest_subjects(manifest)),
        "source_commit": manifest.get("commit"),
        "statement_digest": digest_json(statement),
        "profiles": [
            {key: value for key, value in result.items() if key in {"status", "profile", "payload_digest", "binding_digest", "subject_count"}}
            for result in profile_results
        ],
        "negative_cases": negative_cases,
    }


def verify_github_receipt(record: Mapping[str, Any], manifest_path: Path, root: Path) -> dict[str, Any]:
    _fields(
        record,
        {"schema_version", "profile", "status", "repository", "workflow", "source_ref", "predicate_type", "subjects", "verification_digest", "verifier"},
        "GitHub attestation receipt",
    )
    if record.get("schema_version") != SCHEMA_VERSION or record.get("profile") != GITHUB_PROFILE or record.get("status") != "verified":
        raise AttestationError("unsupported GitHub attestation receipt")
    if record.get("repository") != "AlisinaDevelo/md-files" or record.get("predicate_type") != SLSA_PREDICATE_TYPE:
        raise AttestationError("GitHub attestation receipt identity is invalid")
    _string(record.get("workflow"), "GitHub receipt workflow")
    _string(record.get("source_ref"), "GitHub receipt source_ref")
    _string(record.get("verifier"), "GitHub receipt verifier")
    if record.get("verifier") != "gh attestation verify":
        raise AttestationError("GitHub receipt must name the gh verifier")
    _sha256_ref(record.get("verification_digest"), "GitHub receipt verification_digest")
    subjects = record.get("subjects")
    if not isinstance(subjects, list):
        raise AttestationError("GitHub receipt subjects must be an array")
    expected = _manifest_subjects(_load_json(manifest_path))
    actual = []
    for index, raw_subject in enumerate(subjects):
        subject = _object(raw_subject, f"GitHub receipt subjects[{index}]")
        _fields(subject, {"name", "sha256"}, f"GitHub receipt subjects[{index}]")
        actual.append({"name": _string(subject.get("name"), "GitHub receipt subject name"), "digest": {"sha256": _hex_digest(subject.get("sha256"), "GitHub receipt subject digest")}})
    if sorted(actual, key=lambda item: item["name"]) != expected:
        raise AttestationError("GitHub receipt subjects do not match the release manifest")
    for subject in expected:
        path = (root / subject["name"]).resolve()
        if root.resolve() not in path.parents or not path.is_file() or _sha256_file(path) != subject["digest"]["sha256"]:
            raise AttestationError(f"GitHub receipt subject is not present with the expected digest: {subject['name']}")
    return {
        "status": "verified",
        "profile": GITHUB_PROFILE,
        "evidence_boundary": "host-verified-external",
        "subject_count": len(expected),
        "verification_digest": record["verification_digest"],
    }


def _print(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True))
    else:
        print(value.get("message", value.get("status", "ok")) if isinstance(value, dict) else value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Forge DSSE/SLSA release evidence offline.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    profile_parser = subparsers.add_parser("profile", help="print the supported release attestation profiles")
    profile_parser.add_argument("--json", action="store_true")
    verify_parser = subparsers.add_parser("verify-release", help="verify a Forge DSSE envelope and release binding")
    verify_parser.add_argument("--envelope", type=Path, required=True)
    verify_parser.add_argument("--trust-root", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    verify_parser.add_argument("--root", type=Path, required=True)
    verify_parser.add_argument("--policy", type=Path, required=True)
    verify_parser.add_argument("--source-ref", required=True)
    verify_parser.add_argument("--builder-id")
    verify_parser.add_argument("--profile")
    verify_parser.add_argument("--json", action="store_true")
    github_parser = subparsers.add_parser("verify-github", help="verify a digest-only receipt from gh attestation verify")
    github_parser.add_argument("--record", type=Path, required=True)
    github_parser.add_argument("--manifest", type=Path, required=True)
    github_parser.add_argument("--root", type=Path, required=True)
    github_parser.add_argument("--json", action="store_true")
    self_parser = subparsers.add_parser("self-test", help="run deterministic positive and tamper fixtures")
    self_parser.add_argument("--manifest", type=Path, required=True)
    self_parser.add_argument("--root", type=Path, required=True)
    self_parser.add_argument("--policy", type=Path, required=True)
    self_parser.add_argument("--source-ref", required=True)
    self_parser.add_argument("--builder-id", default="https://forge.local/build/release/v1")
    self_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "profile":
            _print(
                {
                    "contract": "forge-release-attestation-v1",
                    "schema_version": SCHEMA_VERSION,
                    "envelope_type": ENVELOPE_TYPE,
                    "payload_types": sorted(PAYLOAD_TYPES),
                    "profiles": [HMAC_PROFILE, PUBLIC_PROFILE, GITHUB_PROFILE],
                    "predicate_type": SLSA_PREDICATE_TYPE,
                    "builder_evidence": "explicit trust-root or host-verified receipt",
                },
                args.json,
            )
            return 0
        if args.command == "verify-release":
            result = verify_release_attestation(
                _load_json(args.envelope),
                _load_json(args.trust_root),
                args.manifest,
                args.root,
                args.policy,
                source_ref=args.source_ref,
                expected_builder_id=args.builder_id,
                expected_profile=args.profile,
            )
            _print(result, args.json)
            return 0
        if args.command == "verify-github":
            _print(verify_github_receipt(_load_json(args.record), args.manifest, args.root), args.json)
            return 0
        result = self_test(args.manifest, args.root, args.policy, source_ref=args.source_ref, builder_id=args.builder_id)
        _print(result, args.json)
        return 0
    except (OSError, AttestationError, ValueError, json.JSONDecodeError) as exc:
        print(f"forge-attestation: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
