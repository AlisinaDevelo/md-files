"""Tests for the offline gh-aw firewall admission policy."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
POLICY_SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge_gh_aw_firewall.py"
COMPILER_SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-gh-aw.py"
SPEC_PATH = REPO / "data/gh-aw-workflows.json"


def load_policy():
    spec = importlib.util.spec_from_file_location("forge_gh_aw_firewall_test", POLICY_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_compiler():
    spec = importlib.util.spec_from_file_location("forge_gh_aw_compiler_firewall_test", COMPILER_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def base_policy() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))["defaults"]["firewall_policy"]


def test_policy_normalization_is_sorted_digestable_and_awf_native():
    module = load_policy()
    policy = base_policy()
    policy["allowed_domains"] = ["github", "defaults"]
    normalized = module.normalize_policy(policy)

    assert normalized["network"]["allowed"] == ["defaults", "github"]
    assert normalized["firewall"] == {
        "mode": "awf",
        "log_level": "info",
        "ssl_bump": False,
        "allow_urls": [],
    }
    assert normalized["sandbox"] == {
        "agent": "awf",
        "mode": "awf",
        "runtime": "docker",
        "mcp_gateway": {"enabled": False, "port": 8080},
    }
    assert module.policy_digest(normalized) == module.policy_digest(copy.deepcopy(normalized))


def test_runtime_profile_and_mcp_gateway_render_as_native_admission_fields(tmp_path):
    module = load_policy()
    policy = base_policy()
    policy["runtime_profile"] = "gvisor"
    policy["runtime_justification"] = "run untrusted agent code under gVisor isolation"
    policy["mcp_gateway"] = {"enabled": True, "port": 9090}
    normalized = module.normalize_policy(policy)

    assert normalized["sandbox"]["runtime"] == "gvisor"
    assert normalized["sandbox"]["runtime_justification"].startswith("run untrusted")
    assert normalized["sandbox"]["mcp_gateway"] == {"enabled": True, "port": 9090}

    compiler = load_compiler()
    assert compiler._firewall_fields({"defaults": {"firewall_policy": normalized}})["sandbox"]["agent"] == {
        "runtime": "gvisor"
    }
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec["defaults"]["firewall_policy"] = policy
    output = tmp_path / "gh-aw"
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    compiler.compile_artifacts(REPO, spec_path, output)
    source = (output / "workflows/forge-dispatcher.md").read_text(encoding="utf-8")
    assert "runtime: gvisor" in source
    assert "mcp-gateway: true" in source
    assert "port: 9090" in source


def test_default_runtime_is_explicit_in_native_admission_fields():
    firewall = load_policy()
    compiler = load_compiler()
    normalized = firewall.normalize_policy(base_policy())

    fields = compiler._firewall_fields({"defaults": {"firewall_policy": normalized}})
    upstream_fields = compiler._firewall_fields({"defaults": {"firewall_policy": normalized}}, upstream=True)

    assert fields["sandbox"]["agent"] == {"runtime": "docker"}
    assert upstream_fields["sandbox"]["agent"] == {"runtime": "docker-sbx", "sudo": True}


def test_upstream_runtime_rejects_profiles_outside_pinned_compiler():
    firewall = load_policy()
    compiler = load_compiler()
    policy = base_policy()
    policy["runtime_profile"] = "cloud-hypervisor"
    policy["runtime_justification"] = "isolate untrusted workloads in a dedicated virtual machine"
    normalized = firewall.normalize_policy(policy)

    with pytest.raises(compiler.GhAwError, match="pinned gh-aw"):
        compiler._firewall_fields({"defaults": {"firewall_policy": normalized}}, upstream=True)


def test_runtime_and_gateway_policy_fail_closed():
    module = load_policy()
    policy = base_policy()
    policy["runtime_profile"] = "unknown-runtime"
    with pytest.raises(module.FirewallPolicyError, match="runtime_profile"):
        module.normalize_policy(policy)

    policy = base_policy()
    policy["runtime_profile"] = "docker-sudo-iptables"
    with pytest.raises(module.FirewallPolicyError, match="runtime.*justification"):
        module.normalize_policy(policy)

    policy["runtime_justification"] = "privileged host networking is required for services"
    policy["sandbox_mode"] = "disabled"
    policy["firewall_mode"] = "disabled"
    policy["disable_justification"] = "offline fixture with no agent network access"
    with pytest.raises(module.FirewallPolicyError, match="enabled AWF sandbox"):
        module.normalize_policy(policy)

    policy = base_policy()
    policy["mcp_gateway"] = {"enabled": True, "port": 80}
    with pytest.raises(module.FirewallPolicyError, match="1024"):
        module.normalize_policy(policy)


def test_policy_preserves_single_leading_wildcards():
    module = load_policy()
    policy = base_policy()
    policy["allowed_domains"] = ["*.example.com"]
    policy["allowed_url_patterns"] = ["https://*.api.example.com/v1/*"]
    policy["ssl_bump"] = True
    normalized = module.normalize_policy(policy)

    assert normalized["network"]["allowed"] == ["*.example.com"]
    assert normalized["firewall"]["allow_urls"] == ["https://*.api.example.com/v1/*"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("allowed_domains", ["${{ secrets.BAD }}"], "expression"),
        ("allowed_domains", ["127.0.0.1"], "IP address"),
        ("allowed_domains", ["https://api.example.com/path"], "ambiguous"),
        ("allowed_domains", ["http://api.example.com"], "insecure"),
        ("allowed_url_patterns", ["http://api.example.com/v1/*"], "HTTPS"),
        ("content_integrity_threshold", "permissive", "strict or standard"),
        ("sandbox_mode", "disabled", "must agree"),
    ],
)
def test_policy_rejects_unsafe_drift(field, value, message):
    module = load_policy()
    policy = base_policy()
    policy[field] = value
    with pytest.raises(module.FirewallPolicyError, match=message):
        module.normalize_policy(policy)


def test_policy_requires_ssl_bump_and_literal_sandbox_opt_out_reason():
    module = load_policy()
    policy = base_policy()
    policy["allowed_url_patterns"] = ["https://api.example.com/repos/*/issues"]
    with pytest.raises(module.FirewallPolicyError, match="ssl_bump"):
        module.normalize_policy(policy)

    policy["allowed_url_patterns"] = []
    policy["firewall_mode"] = "disabled"
    policy["sandbox_mode"] = "disabled"
    with pytest.raises(module.FirewallPolicyError, match="justification"):
        module.normalize_policy(policy)
    policy["disable_justification"] = "development-only offline compiler fixture"
    normalized = module.normalize_policy(policy)
    assert normalized["sandbox"]["agent"] is False
    assert normalized["sandbox"]["justification"].startswith("development-only")


def test_compiler_manifest_and_lock_carry_firewall_evidence(tmp_path):
    compiler = load_compiler()
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    normalized = compiler.validate_spec(
        REPO, spec, json.loads((REPO / "data/capabilities.json").read_text(encoding="utf-8"))
    )
    output = tmp_path / "gh-aw"
    manifest = compiler.compile_artifacts(REPO, SPEC_PATH, output)

    assert manifest["firewall_policy_revision"] == "forge-gh-aw-firewall-v2"
    assert manifest["firewall_policy_digest"].startswith("sha256:")
    assert normalized["defaults"]["firewall_policy"]["network"]["allowed"] == [
        "defaults",
        "github",
    ]
    source = (output / "workflows/forge-dispatcher.md").read_text(encoding="utf-8")
    lock = (output / "workflows/forge-dispatcher.lock.yml").read_text(encoding="utf-8")
    assert "forge-firewall-policy-digest" in source
    assert "sandbox:" in source
    network = source.split("network:", 1)[1].split("on:", 1)[0]
    assert "firewall:" not in network
    assert "FORGE_FIREWALL_POLICY_DIGEST" in lock
    assert "firewall:" in lock
