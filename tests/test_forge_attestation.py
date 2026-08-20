"""Offline DSSE/SLSA release attestation contract tests."""

from __future__ import annotations

import base64
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/forge-attestation.py"
BUILD_SCRIPT = REPO / "scripts/build_release.py"
VERSION = json.loads((REPO / "plugins/forge/.claude-plugin/plugin.json").read_text(encoding="utf-8"))["version"]


def load_module():
    spec = importlib.util.spec_from_file_location("forge_attestation", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def release_fixture(tmp_path):
    build_spec = importlib.util.spec_from_file_location("forge_attestation_release_build", BUILD_SCRIPT)
    assert build_spec and build_spec.loader
    build = importlib.util.module_from_spec(build_spec)
    build_spec.loader.exec_module(build)
    output = tmp_path / "release"
    build.build_release(REPO, output, VERSION, source_epoch=1_754_000_000, enforce_clean=False)
    return output / f"forge-{VERSION}-manifest.json", output


def signed_fixture(tmp_path, profile="public-key-dsse-v1"):
    module = load_module()
    manifest_path, root = release_fixture(tmp_path)
    policy = REPO / "policies/release.json"
    statement = module._build_statement(
        manifest_path,
        root,
        policy,
        source_ref=f"refs/tags/v{VERSION}",
        builder_id="https://forge.local/build/release/v1",
    )
    if profile == module.PUBLIC_PROFILE:
        material = bytes(range(32))
        trust_root = module._test_root(profile, "test-ed25519", module._ed25519_public_key(material))
    else:
        material = b"forge-attestation-test-hmac-key-0001"
        trust_root = module._test_root(profile, "test-hmac", material)
    envelope = module._make_envelope(statement, profile, trust_root["keys"][0]["key_id"], material)
    return module, manifest_path, root, policy, statement, envelope, trust_root, material


def test_ed25519_verifier_matches_rfc_8032_vector():
    module = load_module()
    seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    public_key = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    signature = bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )

    assert module._ed25519_public_key(seed) == public_key
    module._ed25519_verify(signature, public_key, b"")
    with pytest.raises(module.AttestationError, match="verification failed"):
        module._ed25519_verify(signature, public_key, b"changed")


def test_public_key_and_hmac_profiles_bind_release_subjects(tmp_path):
    module, manifest, root, policy, _statement, envelope, trust_root, _material = signed_fixture(tmp_path)

    result = module.verify_release_attestation(
        envelope,
        trust_root,
        manifest,
        root,
        policy,
        source_ref=f"refs/tags/v{VERSION}",
        expected_builder_id="https://forge.local/build/release/v1",
    )
    assert result["status"] == "verified"
    assert result["profile"] == module.PUBLIC_PROFILE
    assert result["subject_count"] == 4
    assert result["payload_digest"].startswith("sha256:")

    hmac_module, hmac_manifest, hmac_root, hmac_policy, _statement, hmac_envelope, hmac_trust_root, _material = signed_fixture(
        tmp_path / "hmac", module.HMAC_PROFILE
    )
    hmac_result = hmac_module.verify_release_attestation(
        hmac_envelope,
        hmac_trust_root,
        hmac_manifest,
        hmac_root,
        hmac_policy,
        source_ref=f"refs/tags/v{VERSION}",
        expected_builder_id="https://forge.local/build/release/v1",
    )
    assert hmac_result["profile"] == module.HMAC_PROFILE


def test_self_test_reports_digest_only_positive_and_negative_evidence(tmp_path):
    module = load_module()
    manifest, root = release_fixture(tmp_path)
    result = module.self_test(
        manifest,
        root,
        REPO / "policies/release.json",
        source_ref=f"refs/tags/v{VERSION}",
        builder_id="https://forge.local/build/release/v1",
    )

    assert result["status"] == "passed"
    assert result["contract"] == "forge-release-attestation-v1"
    assert {item["profile"] for item in result["profiles"]} == {module.HMAC_PROFILE, module.PUBLIC_PROFILE}
    assert len(result["negative_cases"]) == 6
    assert all(item["status"] == "pass" for item in result["negative_cases"])
    rendered = json.dumps(result, sort_keys=True)
    assert "forge-attestation-self-test-key" not in rendered
    assert "forge/skills" not in rendered


def test_tampered_subject_and_binding_fail_after_resigning(tmp_path):
    module = load_module()
    module, manifest, root, policy, statement, envelope, trust_root, material = signed_fixture(tmp_path, module.HMAC_PROFILE)

    changed_subject = copy.deepcopy(statement)
    changed_subject["subject"][0]["digest"]["sha256"] = "0" * 64
    changed_subject_envelope = module._make_envelope(changed_subject, module.HMAC_PROFILE, "test-hmac", material)
    with pytest.raises(module.AttestationError, match="subjects"):
        module.verify_release_attestation(
            changed_subject_envelope,
            trust_root,
            manifest,
            root,
            policy,
            source_ref=f"refs/tags/v{VERSION}",
            expected_builder_id="https://forge.local/build/release/v1",
        )

    changed_binding = copy.deepcopy(statement)
    changed_binding["predicate"]["buildDefinition"]["externalParameters"]["policy"]["sha256"] = "1" * 64
    changed_binding_envelope = module._make_envelope(changed_binding, module.HMAC_PROFILE, "test-hmac", material)
    with pytest.raises(module.AttestationError, match="policy binding"):
        module.verify_release_attestation(
            changed_binding_envelope,
            trust_root,
            manifest,
            root,
            policy,
            source_ref=f"refs/tags/v{VERSION}",
            expected_builder_id="https://forge.local/build/release/v1",
        )

    changed_signature = copy.deepcopy(envelope)
    signature = bytearray(base64.b64decode(changed_signature["signatures"][0]["sig"]))
    signature[-1] ^= 1
    changed_signature["signatures"][0]["sig"] = base64.b64encode(signature).decode("ascii")
    with pytest.raises(module.AttestationError, match="signature"):
        module.verify_release_attestation(
            changed_signature,
            trust_root,
            manifest,
            root,
            policy,
            source_ref=f"refs/tags/v{VERSION}",
            expected_builder_id="https://forge.local/build/release/v1",
        )


def test_trust_root_rotation_and_revocation_are_explicit(tmp_path):
    module, manifest, root, policy, _statement, envelope, trust_root, material = signed_fixture(tmp_path)
    trust_root["keys"][0]["status"] = "retired"
    assert module.verify_release_attestation(
        envelope,
        trust_root,
        manifest,
        root,
        policy,
        source_ref=f"refs/tags/v{VERSION}",
        expected_builder_id="https://forge.local/build/release/v1",
    )["status"] == "verified"

    revoked = copy.deepcopy(trust_root)
    revoked["keys"][0]["status"] = "revoked"
    with pytest.raises(module.AttestationError, match="revoked"):
        module.verify_release_attestation(
            envelope,
            revoked,
            manifest,
            root,
            policy,
            source_ref=f"refs/tags/v{VERSION}",
            expected_builder_id="https://forge.local/build/release/v1",
        )

    rotated_seed = bytes(reversed(range(32)))
    rotated_root = copy.deepcopy(trust_root)
    rotated_root["keys"].append(
        {
            "key_id": "rotated-ed25519",
            "algorithm": module.PUBLIC_KEY_ALGORITHM,
            "status": "active",
            "public_key_b64": base64.b64encode(module._ed25519_public_key(rotated_seed)).decode("ascii"),
        }
    )
    rotated_statement = module._build_statement(
        manifest,
        root,
        policy,
        source_ref=f"refs/tags/v{VERSION}",
        builder_id="https://forge.local/build/release/v1",
    )
    rotated_envelope = module._make_envelope(rotated_statement, module.PUBLIC_PROFILE, "rotated-ed25519", rotated_seed)
    assert module.verify_release_attestation(
        rotated_envelope,
        rotated_root,
        manifest,
        root,
        policy,
        source_ref=f"refs/tags/v{VERSION}",
        expected_builder_id="https://forge.local/build/release/v1",
    )["key_ids"] == ["rotated-ed25519"]
    assert material


def test_github_receipt_is_distinct_from_offline_public_key_evidence(tmp_path):
    module, manifest, root = load_module(), *release_fixture(tmp_path)
    subjects = module._manifest_subjects(json.loads(manifest.read_text(encoding="utf-8")))
    record = {
        "schema_version": 1,
        "profile": module.GITHUB_PROFILE,
        "status": "verified",
        "repository": "AlisinaDevelo/md-files",
        "workflow": "AlisinaDevelo/md-files/.github/workflows/release.yml",
        "source_ref": f"refs/tags/v{VERSION}",
        "predicate_type": module.SLSA_PREDICATE_TYPE,
        "subjects": [{"name": item["name"], "sha256": item["digest"]["sha256"]} for item in subjects],
        "verification_digest": "sha256:" + "a" * 64,
        "verifier": "gh attestation verify",
    }
    result = module.verify_github_receipt(record, manifest, root)
    assert result["profile"] == module.GITHUB_PROFILE
    assert result["evidence_boundary"] == "host-verified-external"

    changed = copy.deepcopy(record)
    changed["subjects"][0]["sha256"] = "0" * 64
    with pytest.raises(module.AttestationError, match="subjects"):
        module.verify_github_receipt(changed, manifest, root)


def test_release_manifest_advertises_attestation_contract(tmp_path):
    build_spec = importlib.util.spec_from_file_location("forge_attestation_manifest_build", BUILD_SCRIPT)
    assert build_spec and build_spec.loader
    build = importlib.util.module_from_spec(build_spec)
    build_spec.loader.exec_module(build)
    output = tmp_path / "release"
    manifest = build.build_release(REPO, output, VERSION, source_epoch=1_754_000_000, enforce_clean=False)
    assert manifest["attestation"] == build.ATTESTATION_CONTRACT
