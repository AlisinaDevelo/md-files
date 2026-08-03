"""Tests for deterministic Forge release packaging and offline verification."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO / "scripts/build_release.py"
VERIFY_SCRIPT = REPO / "scripts/verify_release.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_same_source_epoch_produces_identical_archives_and_manifest(tmp_path):
    build = load(BUILD_SCRIPT, "forge_release_build")
    verify = load(VERIFY_SCRIPT, "forge_release_verify")
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_result = build.build_release(REPO, first, "3.2.0", source_epoch=1_754_000_000, enforce_clean=False)
    second_result = build.build_release(REPO, second, "3.2.0", source_epoch=1_754_000_000, enforce_clean=False)

    assert first_result["commit"] == second_result["commit"]
    for path in sorted(first.iterdir()):
        assert path.read_bytes() == (second / path.name).read_bytes(), path.name
    verify.verify_release(first / "forge-3.2.0-manifest.json", first, expected_version="3.2.0")


def test_manifest_contains_three_host_archives_and_runtime_dependencies(tmp_path):
    build = load(BUILD_SCRIPT, "forge_release_build_manifest")

    build.build_release(REPO, tmp_path, "3.2.0", source_epoch=1_754_000_000, enforce_clean=False)
    manifest = json.loads((tmp_path / "forge-3.2.0-manifest.json").read_text())

    assert {item["name"] for item in manifest["artifacts"]} >= {
        "forge-3.2.0-claude.tar.gz",
        "forge-3.2.0-codex.tar.gz",
        "forge-3.2.0-agents.tar.gz",
        "forge-3.2.0-sbom.spdx.json",
    }
    assert {item["name"] for item in manifest["runtime_dependencies"]} == {"Python", "GitHub CLI"}
    assert all(item["sha256"] and item["size"] > 0 for item in manifest["artifacts"])
    assert manifest["version_parity"]["claude_plugin"] == "3.2.0"
    assert manifest["version_parity"]["codex_plugin"] == "3.2.0"
    assert manifest["version_parity"]["marketplace_plugin"] == "3.2.0"
    assert manifest["tag"] == "v3.2.0"
    assert manifest["verification"]["manifest_file"] == "forge-3.2.0-manifest.json"
    assert all(any(item["path"].endswith("LICENSE") for item in artifact["contents"]) for artifact in manifest["artifacts"] if artifact["name"].endswith(".tar.gz"))


def test_spdx_validation_rejects_missing_required_fields():
    build = load(BUILD_SCRIPT, "forge_release_build_spdx")

    with pytest.raises(build.ReleaseBuildError, match="SPDXID"):
        build.validate_spdx({"spdxVersion": "SPDX-2.3"})


def test_offline_verification_detects_archive_tampering(tmp_path):
    build = load(BUILD_SCRIPT, "forge_release_build_tamper")
    verify = load(VERIFY_SCRIPT, "forge_release_verify_tamper")
    build.build_release(REPO, tmp_path, "3.2.0", source_epoch=1_754_000_000, enforce_clean=False)
    archive = tmp_path / "forge-3.2.0-claude.tar.gz"
    archive.write_bytes(archive.read_bytes() + b"tampered")

    with pytest.raises(verify.ReleaseVerificationError, match="sha256"):
        verify.verify_release(tmp_path / "forge-3.2.0-manifest.json", tmp_path, expected_version="3.2.0")
