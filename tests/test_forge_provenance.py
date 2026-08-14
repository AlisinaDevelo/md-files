"""Offline signed trace-context and provenance bridge tests."""

from __future__ import annotations

import base64
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/observability/scripts/forge-provenance.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_provenance", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_effect(task_id: str = "build"):
    return {
        "effect_type": "github.issue.create",
        "task_id": task_id,
        "activity_id": "github-issue",
        "attempt": 1,
        "effect_definition_revision": "effect-v1",
        "payload": {
            "target_ref": "github:issues/1",
            "request_digest": "sha256:request",
        },
    }


def prepared_runtime(tmp_path):
    module = load_module()
    runtime = module._lineage_module()._runtime_module()
    tmp_path.mkdir(parents=True, exist_ok=True)
    database = tmp_path / "runtime.sqlite3"
    store = runtime.RuntimeStore(database)
    store.start_run(
        "run-1",
        "feature-flow",
        "definition-v1",
        "policy-v1",
        occurred_at="2026-08-06T00:00:00Z",
    )
    store.append_event(
        "run-1",
        "task.scheduled",
        {"task_id": "build", "depends_on": []},
        idempotency_key="task-build-scheduled",
        effect=make_effect(),
        occurred_at="2026-08-06T00:00:01Z",
    )
    effect_id = store.list_outbox("run-1")[0]["effect_id"]
    claimed = store.claim_outbox("worker-a", now="2026-08-06T00:00:02Z")[0]
    store.acknowledge_outbox(
        effect_id,
        "worker-a",
        {"status": "succeeded", "provider_request_id": "provider:req-1"},
        lease_generation=claimed["lease_generation"],
        received_at="2026-08-06T00:00:03Z",
    )
    store.close()
    return module, database


def write_key_and_policy(tmp_path, module, *, key_id="key-a", key=b"forge-provenance-test-key-0001", status="active"):
    key_path = tmp_path / f"{key_id}.key"
    key_path.write_bytes(key)
    policy_path = tmp_path / "trust-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy_revision": "trust-v1",
                "keys": [
                    {
                        "key_id": key_id,
                        "algorithm": "hmac-sha256",
                        "key_b64": base64.b64encode(key).decode("ascii"),
                        "status": status,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return key_path, policy_path


def export_bundle(
    tmp_path,
    *,
    key_id="key-a",
    key=b"forge-provenance-test-key-0001",
    status="active",
    policy_revision="policy-v1",
    **kwargs,
):
    module, database = prepared_runtime(tmp_path)
    key_path, policy_path = write_key_and_policy(tmp_path, module, key_id=key_id, key=key, status=status)
    database_before = database.read_bytes()
    bundle = module.export_bundle(
        database,
        source_revision="git:source-v1",
        policy_revision=policy_revision,
        signing_key_path=key_path,
        trust_policy_path=policy_path,
        key_id=key_id,
        **kwargs,
    )
    return module, database, key_path, policy_path, bundle, database_before


def redigest_bundle(module, bundle):
    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    bundle["bundle_digest"] = module.digest_ref(body)


def test_export_is_reproducible_and_correlates_runtime_evidence(tmp_path):
    module, database, _key_path, policy_path, first, database_before = export_bundle(
        tmp_path / "first",
        traceparent="00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
        tracestate="vendor=opaque",
    )
    _module, _database, _key_path, _policy_path, second, _database_before = export_bundle(
        tmp_path / "second",
        traceparent="00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
        tracestate="vendor=opaque",
    )

    assert first == second
    assert module.verify_bundle(first, policy_path)["verified"] is True
    assert first["mapping"]["version"] == module.OTEL_MAPPING_VERSION
    assert first["mapping"]["otel_spec_version"] == module.OTEL_SPEC_VERSION
    assert first["mapping"]["gen_ai_semconv_version"] == module.GEN_AI_SEMCONV_VERSION
    assert first["trace_context"]["tracestate"] == "vendor=opaque"
    assert first["trace_context"]["traceparent"].startswith("00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-")
    trace = first["traces"][0]
    assert trace["trace_id"] == "a" * 32
    assert any(span["name"] == "invoke_workflow" for span in trace["spans"])
    assert any(span["attributes"].get("forge.effect.id") for span in trace["spans"])
    assert first["provenance"]["subject"][0]["digest"]["sha256"]
    assert "forge-provenance-test-key-0001" not in json.dumps(first)
    assert database.read_bytes() == database_before


def test_trace_context_preserves_future_fields_and_rejects_invalid_context():
    module = load_module()
    future = "01-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01-ff00"
    parsed = module.parse_trace_context(future, "vendor=opaque")
    assert parsed["traceparent"] == future
    assert parsed["unknown_fields"] == ["ff00"]
    assert parsed["tracestate"] == "vendor=opaque"

    with pytest.raises(module.ProvenanceError, match="traceparent"):
        module.parse_trace_context("00-00000000000000000000000000000000-bbbbbbbbbbbbbbbb-01", None)
    with pytest.raises(module.ProvenanceError, match="tracestate"):
        module.parse_trace_context("00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01", "invalid state")
    with pytest.raises(module.ProvenanceError, match="tracestate requires"):
        module.parse_trace_context(None, "vendor=opaque")


def test_privacy_defaults_to_digest_and_requires_explicit_export_policy():
    module = load_module()
    safe = module.sanitize_attributes(
        {
            "prompt": "do not export this prompt",
            "tool_arguments": {"token": "credential"},
            "status": "ok",
        }
    )
    rendered = json.dumps(safe)
    assert "do not export" not in rendered
    assert "credential" not in rendered
    assert safe["status"] == "ok"
    assert safe["prompt"]["redacted"] is True

    variant_keys = module.sanitize_attributes(
        {
            "toolArguments": "must stay private",
            "apiKey": "credential",
            "provider.response": "raw provider output",
        }
    )
    assert all(value["redacted"] is True for value in variant_keys.values())

    policy = {
        "schema_version": 1,
        "allow_content": True,
        "export_enabled": True,
        "allowed_keys": ["description"],
        "max_length": 8,
    }
    opted_in = module.sanitize_attributes({"description": "abcdefghijk", "password": "keep-hidden"}, policy)
    assert opted_in["description"]["value"] == "abcdefgh"
    assert opted_in["description"]["truncated"] is True
    assert opted_in["password"]["redacted"] is True
    with pytest.raises(module.ProvenanceError, match="export_enabled"):
        module.sanitize_attributes({"description": "raw"}, {**policy, "export_enabled": False})


def test_tampering_fails_after_bundle_digest_is_recomputed(tmp_path):
    module, _database, _key_path, policy_path, bundle, _database_before = export_bundle(tmp_path)
    changed = copy.deepcopy(bundle)
    changed["provenance"]["predicate"]["buildDefinition"]["externalParameters"]["source_revision"] = "git:other"
    redigest_bundle(module, changed)
    with pytest.raises(module.ProvenanceError, match="signature|invocation"):
        module.verify_bundle(changed, policy_path)


def test_policy_revision_is_bound_to_lineage(tmp_path):
    module, _database, key_path, policy_path, bundle, _database_before = export_bundle(tmp_path / "valid")

    mismatch_root = tmp_path / "export-mismatch"
    mismatch_module, mismatch_database = prepared_runtime(mismatch_root)
    mismatch_key_path, mismatch_policy_path = write_key_and_policy(mismatch_root, mismatch_module)
    with pytest.raises(module.ProvenanceError, match="policy_revision does not match lineage"):
        module.export_bundle(
            mismatch_database,
            source_revision="git:source-v1",
            policy_revision="policy-v2",
            signing_key_path=mismatch_key_path,
            trust_policy_path=mismatch_policy_path,
            key_id="key-a",
        )

    changed = copy.deepcopy(bundle)
    changed["provenance"]["predicate"]["buildDefinition"]["externalParameters"]["policy_revision"] = "policy-v2"
    changed["signature"] = module._signature(changed["provenance"], "key-a", key_path.read_bytes())
    redigest_bundle(module, changed)
    with pytest.raises(module.ProvenanceError, match="policy_revision does not match lineage"):
        module.verify_bundle(changed, policy_path)

    changed = copy.deepcopy(bundle)
    changed["traces"][0]["spans"].reverse()
    redigest_bundle(module, changed)
    with pytest.raises(module.ProvenanceError, match="trace projection"):
        module.verify_bundle(changed, policy_path)


def test_key_rotation_allows_retired_keys_and_rejects_revoked_keys(tmp_path):
    module, _database, key_path, policy_path, bundle, _database_before = export_bundle(tmp_path / "old")
    retired = json.loads(policy_path.read_text(encoding="utf-8"))
    retired["keys"][0]["status"] = "retired"
    policy_path.write_text(json.dumps(retired) + "\n", encoding="utf-8")
    assert module.verify_bundle(bundle, policy_path)["key_id"] == "key-a"

    revoked = copy.deepcopy(retired)
    revoked["keys"][0]["status"] = "revoked"
    policy_path.write_text(json.dumps(revoked) + "\n", encoding="utf-8")
    with pytest.raises(module.ProvenanceError, match="revoked"):
        module.verify_bundle(bundle, policy_path)

    new_key = b"forge-provenance-rotated-key-0002"
    module2, _database2, new_key_path, new_policy_path, new_bundle, _database_before = export_bundle(
        tmp_path / "new", key_id="key-b", key=new_key
    )
    assert module2.verify_bundle(new_bundle, new_policy_path)["key_id"] == "key-b"
    assert key_path.read_bytes() != new_key_path.read_bytes()


def test_malformed_trust_material_fails_closed(tmp_path):
    module, _database, _key_path, policy_path, bundle, _database_before = export_bundle(tmp_path)
    malformed = json.loads(policy_path.read_text(encoding="utf-8"))
    malformed["keys"][0]["key_b64"] = "not-base64"
    policy_path.write_text(json.dumps(malformed) + "\n", encoding="utf-8")
    with pytest.raises(module.ProvenanceError, match="base64"):
        module.verify_bundle(bundle, policy_path)


def test_cli_verifier_is_offline_and_actionable(tmp_path, capsys):
    module, _database, _key_path, policy_path, bundle, _database_before = export_bundle(tmp_path)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert module.main(["verify", "--bundle", str(bundle_path), "--trust-policy", str(policy_path)]) == 0
    assert '"verified": true' in capsys.readouterr().out


def test_provenance_schema_is_versioned_and_release_ready():
    schema = json.loads((REPO / "data/runtime-provenance.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"].endswith("/provenance/v1")
    assert schema["properties"]["schema_version"]["const"] == 1
    assert "signature" in schema["required"]
    assert schema["$defs"]["signature"]["properties"]["algorithm"]["const"] == "hmac-sha256"
