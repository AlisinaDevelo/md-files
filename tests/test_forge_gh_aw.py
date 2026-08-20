"""Tests for the bounded Forge GitHub Agentic Workflows adapter."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-gh-aw.py"
SPEC_PATH = REPO / "data/gh-aw-workflows.json"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_gh_aw", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def native_fixture(module, output: Path) -> dict:
    manifest = module.compile_artifacts(REPO, SPEC_PATH, output)
    definitions = {item["id"]: item for item in manifest["workflows"]}
    for lock_path in sorted((output / "workflows").glob("*.lock.yml")):
        workflow_id = lock_path.name.removesuffix(".lock.yml")
        source_hash = module.file_digest(output / "workflows" / f"{workflow_id}.md")
        metadata = {
            "compiler_version": manifest["upstream"]["version"],
            "schema_version": manifest["upstream"]["workflow_schema"],
            "strict": True,
        }
        container_image = "ghcr.io/example/forge-fixture"
        container_digest = "sha256:" + "b" * 64
        upstream_manifest = {
            "actions": [{"repo": "actions/checkout", "sha": "a" * 40}],
            "containers": [{
                "image": container_image,
                "digest": container_digest,
                "pinned_image": f"{container_image}@{container_digest}",
            }],
            "secrets": [],
            "version": 1,
        }
        header = "".join([
            "# Forge adapter evidence: forge-gh-aw-v1\n",
            f"# forge-source-sha256: {source_hash}\n",
            f"# forge-definition-sha256: {definitions[workflow_id]['definition_digest']}\n",
            f"# gh-aw-metadata: {json.dumps(metadata, sort_keys=True, separators=(',', ':'))}\n",
            f"# gh-aw-manifest: {json.dumps(upstream_manifest, sort_keys=True, separators=(',', ':'))}\n",
        ])
        native_lock = "\n".join([
            "name: Native fixture",
            "permissions: {}",
            f"# pinned-container: {container_image}@{container_digest}",
            "jobs:",
            "  activation:",
            "    permissions: {}",
            "  agent:",
            "    needs: activation",
            "    name: Read-only Forge agent contract",
            "    permissions:",
            "      actions: read",
            "      contents: read",
            "      issues: read",
            "      pull-requests: read",
            "    steps:",
            f"      - uses: actions/checkout@{'a' * 40}",
            "  detection:",
            "    needs:",
            "      - activation",
            "      - agent",
            "    permissions:",
            "      contents: read",
            "  safe_outputs:",
            "    needs:",
            "      - activation",
            "      - agent",
            "      - detection",
            "    permissions:",
            "      issues: write",
            "  conclusion:",
            "    needs:",
            "      - activation",
            "      - agent",
            "      - detection",
            "      - safe_outputs",
            "    permissions:",
            "      actions: write",
            "",
        ])
        lock_path.write_text(header + native_lock, encoding="utf-8")
        artifact = next(item for item in manifest["artifacts"] if item["path"] == f"workflows/{lock_path.name}")
        artifact["sha256"] = module.file_digest(lock_path)
    manifest["mode"] = "upstream-gh-aw"
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def test_spec_has_pinned_dispatch_and_policy_contract():
    module = load_module()
    spec = load_json(SPEC_PATH)
    graph = load_json(REPO / "data/capabilities.json")

    normalized = module.validate_spec(REPO, spec, graph)
    plans = module._policy_plans(REPO, normalized)

    assert normalized["upstream"]["version"] == "v0.85.4"
    assert normalized["upstream"]["commit"] == "53843da968225dc56e1590978a7ed6407a8438ac"
    dispatcher = next(item for item in normalized["workflows"] if item["id"] == "forge-dispatcher")
    assert dispatcher["dispatches"] == [
        "forge-issue-triage",
        "forge-ci-diagnosis",
        "forge-docs-maintenance",
        "forge-feature-planning",
    ]
    assert all(effect["policy"]["decision"] == "require_approval" for values in plans.values() for effect in values)


def test_compile_and_check_produce_read_only_preview(tmp_path):
    module = load_module()
    manifest = module.compile_artifacts(REPO, SPEC_PATH, tmp_path)

    assert manifest["mode"] == "contract-preview"
    assert len(manifest["workflows"]) == 5
    module.check_artifacts(REPO, SPEC_PATH, tmp_path)

    source = (tmp_path / "workflows/forge-dispatcher.md").read_text(encoding="utf-8")
    lock = (tmp_path / "workflows/forge-dispatcher.lock.yml").read_text(encoding="utf-8")
    assert "forge-gh-aw-v1" in source
    assert "The agent is read-only." in source
    assert "safe-output effect set" in lock
    assert "${{ secrets." not in lock
    assert "contents: write" not in lock.split("  agent:", 1)[1].split("  preview:", 1)[0]


def test_compile_is_byte_deterministic(tmp_path):
    module = load_module()
    first = tmp_path / "first"
    second = tmp_path / "second"

    module.compile_artifacts(REPO, SPEC_PATH, first)
    module.compile_artifacts(REPO, SPEC_PATH, second)

    assert snapshot(first) == snapshot(second)


def test_check_rejects_artifact_drift(tmp_path):
    module = load_module()
    module.compile_artifacts(REPO, SPEC_PATH, tmp_path)
    path = tmp_path / "workflows/forge-ci-diagnosis.lock.yml"
    path.write_text(path.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")

    with pytest.raises(module.GhAwError, match="source-to-lock drift"):
        module.check_artifacts(REPO, SPEC_PATH, tmp_path)


def test_check_rejects_nonempty_top_level_permissions(tmp_path):
    module = load_module()
    manifest = native_fixture(module, tmp_path)
    path = tmp_path / "workflows/forge-ci-diagnosis.lock.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "permissions: {}\n",
            "permissions:\n  contents: read\n",
            1,
        ),
        encoding="utf-8",
    )
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "workflows/forge-ci-diagnosis.lock.yml")
    artifact["sha256"] = module.file_digest(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.GhAwError, match="top-level permissions"):
        module.check_artifacts(REPO, SPEC_PATH, tmp_path)


def test_check_rejects_writes_outside_safe_output_boundary(tmp_path):
    module = load_module()
    manifest = module.compile_artifacts(REPO, SPEC_PATH, tmp_path)
    path = tmp_path / "workflows/forge-ci-diagnosis.lock.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "    permissions: {}\n",
            "    permissions:\n      contents: write\n",
            1,
        ),
        encoding="utf-8",
    )
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "workflows/forge-ci-diagnosis.lock.yml")
    artifact["sha256"] = module.file_digest(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.GhAwError, match="outside safe-output boundary"):
        module.check_artifacts(REPO, SPEC_PATH, tmp_path)


def test_check_rejects_scalar_job_permissions(tmp_path):
    module = load_module()
    manifest = module.compile_artifacts(REPO, SPEC_PATH, tmp_path)
    path = tmp_path / "workflows/forge-ci-diagnosis.lock.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "    permissions: {}\n",
            "    permissions: write-all\n",
            1,
        ),
        encoding="utf-8",
    )
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "workflows/forge-ci-diagnosis.lock.yml")
    artifact["sha256"] = module.file_digest(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.GhAwError, match="unsupported job permissions"):
        module.check_artifacts(REPO, SPEC_PATH, tmp_path)


def test_check_rejects_unknown_native_secret_reference(tmp_path):
    module = load_module()
    manifest = module.compile_artifacts(REPO, SPEC_PATH, tmp_path)
    path = tmp_path / "workflows/forge-ci-diagnosis.lock.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "    name: Read-only Forge agent contract\n",
            "    name: Read-only Forge agent contract\n    env: ${{ secrets.UNKNOWN_SECRET }}\n",
            1,
        ),
        encoding="utf-8",
    )
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "workflows/forge-ci-diagnosis.lock.yml")
    artifact["sha256"] = module.file_digest(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.GhAwError, match="unknown upstream secrets"):
        module.check_artifacts(REPO, SPEC_PATH, tmp_path)


def test_check_accepts_docker_sbx_upstream_secret_references(tmp_path):
    module = load_module()
    manifest = native_fixture(module, tmp_path)
    path = tmp_path / "workflows/forge-ci-diagnosis.lock.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "    name: Read-only Forge agent contract\n",
            "    name: Read-only Forge agent contract\n"
            "    env: ${{ secrets.DOCKER_PAT }}\n"
            "    DOCKER_USERNAME: ${{ secrets.DOCKER_USERNAME }}\n",
            1,
        ),
        encoding="utf-8",
    )
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "workflows/forge-ci-diagnosis.lock.yml")
    artifact["sha256"] = module.file_digest(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    module.check_artifacts(REPO, SPEC_PATH, tmp_path)


def test_native_mode_requires_bound_upstream_evidence(tmp_path):
    module = load_module()
    manifest = native_fixture(module, tmp_path)
    module.check_artifacts(REPO, SPEC_PATH, tmp_path)

    path = tmp_path / "workflows/forge-ci-diagnosis.lock.yml"
    path.write_text(path.read_text(encoding="utf-8").replace("# Forge adapter evidence:", "# forge adapter evidence:", 1), encoding="utf-8")
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "workflows/forge-ci-diagnosis.lock.yml")
    artifact["sha256"] = module.file_digest(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.GhAwError, match="missing Forge native evidence"):
        module.check_artifacts(REPO, SPEC_PATH, tmp_path)


def test_native_mode_rejects_unpinned_upstream_metadata(tmp_path):
    module = load_module()
    manifest = native_fixture(module, tmp_path)
    path = tmp_path / "workflows/forge-ci-diagnosis.lock.yml"
    path.write_text(path.read_text(encoding="utf-8").replace('"v0.85.4"', '"v0.85.3"', 1), encoding="utf-8")
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "workflows/forge-ci-diagnosis.lock.yml")
    artifact["sha256"] = module.file_digest(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.GhAwError, match="compiler version"):
        module.check_artifacts(REPO, SPEC_PATH, tmp_path)


def test_native_mode_rejects_unlisted_pinned_action(tmp_path):
    module = load_module()
    manifest = native_fixture(module, tmp_path)
    path = tmp_path / "workflows/forge-ci-diagnosis.lock.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f"actions/checkout@{'a' * 40}",
            f"actions/checkout@{'c' * 40}",
            1,
        ),
        encoding="utf-8",
    )
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "workflows/forge-ci-diagnosis.lock.yml")
    artifact["sha256"] = module.file_digest(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.GhAwError, match="does not cover every emitted action"):
        module.check_artifacts(REPO, SPEC_PATH, tmp_path)


def test_native_mode_rejects_unpinned_list_action(tmp_path):
    module = load_module()
    manifest = native_fixture(module, tmp_path)
    path = tmp_path / "workflows/forge-ci-diagnosis.lock.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f"actions/checkout@{'a' * 40}",
            "actions/checkout@v7",
            1,
        ),
        encoding="utf-8",
    )
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "workflows/forge-ci-diagnosis.lock.yml")
    artifact["sha256"] = module.file_digest(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.GhAwError, match="contains an unpinned action"):
        module.check_artifacts(REPO, SPEC_PATH, tmp_path)


def test_native_mode_rejects_unbound_container_digest(tmp_path):
    module = load_module()
    manifest = native_fixture(module, tmp_path)
    path = tmp_path / "workflows/forge-ci-diagnosis.lock.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "# pinned-container: ghcr.io/example/forge-fixture@sha256:" + "b" * 64,
            "# pinned-container: ghcr.io/example/forge-fixture@sha256:" + "c" * 64,
            1,
        ),
        encoding="utf-8",
    )
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "workflows/forge-ci-diagnosis.lock.yml")
    artifact["sha256"] = module.file_digest(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.GhAwError, match="does not bind upstream container digest"):
        module.check_artifacts(REPO, SPEC_PATH, tmp_path)


def test_native_job_graph_rejects_dependency_drift(tmp_path):
    module = load_module()
    native_fixture(module, tmp_path)
    path = tmp_path / "workflows/forge-ci-diagnosis.lock.yml"
    text = path.read_text(encoding="utf-8").replace(
        "  detection:\n    needs:\n      - activation\n      - agent\n",
        "  detection:\n    needs: activation\n",
        1,
    )

    with pytest.raises(module.GhAwError, match="graph drift for detection"):
        module._check_native_job_graph(text, path)


def test_check_rejects_source_drift_even_when_manifest_hash_is_rewritten(tmp_path):
    module = load_module()
    manifest = module.compile_artifacts(REPO, SPEC_PATH, tmp_path)
    path = tmp_path / "workflows/forge-ci-diagnosis.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "workflows/forge-ci-diagnosis.md")
    artifact["sha256"] = module.file_digest(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(module.GhAwError, match="generated source drift"):
        module.check_artifacts(REPO, SPEC_PATH, tmp_path)


def test_spec_rejects_protected_pull_request_paths_and_secrets():
    module = load_module()
    original = load_json(SPEC_PATH)
    graph = load_json(REPO / "data/capabilities.json")

    protected = copy.deepcopy(original)
    docs = next(item for item in protected["workflows"] if item["id"] == "forge-docs-maintenance")
    docs["safe_outputs"][0]["allowed-files"] = [".github/workflows/ci.yml"]
    with pytest.raises(module.GhAwError, match="protected path"):
        module.validate_spec(REPO, protected, graph)

    secret = copy.deepcopy(original)
    secret["defaults"]["network_allowed"] = ["${{ secrets.BAD }}"]
    with pytest.raises(module.GhAwError, match="secret reference"):
        module.validate_spec(REPO, secret, graph)
