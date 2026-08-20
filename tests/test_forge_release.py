"""Tests for deterministic Forge release packaging and offline verification."""

from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO / "scripts/build_release.py"
VERIFY_SCRIPT = REPO / "scripts/verify_release.py"
VERSION = json.loads((REPO / "plugins/forge/.claude-plugin/plugin.json").read_text())["version"]


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

    first_result = build.build_release(REPO, first, VERSION, source_epoch=1_754_000_000, enforce_clean=False)
    second_result = build.build_release(REPO, second, VERSION, source_epoch=1_754_000_000, enforce_clean=False)

    assert first_result["commit"] == second_result["commit"]
    for path in sorted(first.iterdir()):
        assert path.read_bytes() == (second / path.name).read_bytes(), path.name
    verify.verify_release(first / f"forge-{VERSION}-manifest.json", first, expected_version=VERSION)


def test_manifest_contains_host_archives_openai_zip_and_runtime_dependencies(tmp_path):
    build = load(BUILD_SCRIPT, "forge_release_build_manifest")

    build.build_release(REPO, tmp_path, VERSION, source_epoch=1_754_000_000, enforce_clean=False)
    manifest = json.loads((tmp_path / f"forge-{VERSION}-manifest.json").read_text())

    assert {item["name"] for item in manifest["artifacts"]} >= {
        f"forge-{VERSION}-claude.tar.gz",
        f"forge-{VERSION}-codex.tar.gz",
        f"forge-{VERSION}-agents.tar.gz",
        f"forge-{VERSION}-openai.zip",
        f"forge-{VERSION}-sbom.spdx.json",
    }
    assert {item["name"] for item in manifest["runtime_dependencies"]} == {"Python", "GitHub CLI"}
    assert all(item["sha256"] and item["size"] > 0 for item in manifest["artifacts"])
    assert manifest["version_parity"]["claude_plugin"] == VERSION
    assert manifest["version_parity"]["codex_plugin"] == VERSION
    assert manifest["version_parity"]["marketplace_plugin"] == VERSION
    assert manifest["tag"] == f"v{VERSION}"
    assert manifest["verification"]["manifest_file"] == f"forge-{VERSION}-manifest.json"
    assert manifest["attestation"]["predicate_type"] == "https://slsa.dev/provenance/v1"
    assert manifest["attestation"]["profiles"] == ["local-hmac-v1", "public-key-dsse-v1", "github-artifact-v1"]
    assert all(any(item["path"].endswith("LICENSE") for item in artifact["contents"]) for artifact in manifest["artifacts"] if artifact["name"].endswith(".tar.gz"))
    openai = next(item for item in manifest["artifacts"] if item["name"].endswith("-openai.zip"))
    assert openai["media_type"] == "application/zip"
    assert {item["path"] for item in openai["contents"]} >= {
        ".codex-plugin/plugin.json",
        "assets/logo.png",
        "data/capabilities.json",
        "LICENSE",
    }


def test_archives_consume_host_rendered_surfaces(tmp_path):
    build = load(BUILD_SCRIPT, "forge_release_build_rendered_surfaces")
    build.build_release(REPO, tmp_path, VERSION, source_epoch=1_754_000_000, enforce_clean=False)

    with tarfile.open(tmp_path / f"forge-{VERSION}-codex.tar.gz", "r:gz") as archive:
        codex_names = {member.name for member in archive.getmembers()}
    with tarfile.open(tmp_path / f"forge-{VERSION}-agents.tar.gz", "r:gz") as archive:
        agents_names = {member.name for member in archive.getmembers()}

    assert "forge/skills/orchestration/SKILL.md" in codex_names
    assert "forge/agents/architect.md" not in codex_names
    assert "forge/data/projection-manifest.json" in codex_names
    assert "forge-agents/zed/install.sh" in agents_names
    assert "forge-agents/data/bundles.json" in agents_names


def test_openai_zip_contains_only_the_skills_submission_surface(tmp_path):
    build = load(BUILD_SCRIPT, "forge_release_build_openai_zip")
    build.build_release(REPO, tmp_path, VERSION, source_epoch=1_754_000_000, enforce_clean=False)

    with zipfile.ZipFile(tmp_path / f"forge-{VERSION}-openai.zip") as archive:
        names = set(archive.namelist())

    assert ".codex-plugin/plugin.json" in names
    assert "assets/logo.png" in names
    assert "skills/orchestration/SKILL.md" in names
    assert "data/capabilities.json" in names
    assert "LICENSE" in names
    assert not any(name.startswith(".claude-plugin/") for name in names)
    assert not any(name.startswith(prefix) for name in names for prefix in ("agents/", "commands/", "hooks/", "output-styles/"))


def test_spdx_validation_rejects_missing_required_fields():
    build = load(BUILD_SCRIPT, "forge_release_build_spdx")

    with pytest.raises(build.ReleaseBuildError, match="SPDXID"):
        build.validate_spdx({"spdxVersion": "SPDX-2.3"})


def test_offline_verification_detects_archive_tampering(tmp_path):
    build = load(BUILD_SCRIPT, "forge_release_build_tamper")
    verify = load(VERIFY_SCRIPT, "forge_release_verify_tamper")
    build.build_release(REPO, tmp_path, VERSION, source_epoch=1_754_000_000, enforce_clean=False)
    archive = tmp_path / f"forge-{VERSION}-claude.tar.gz"
    archive.write_bytes(archive.read_bytes() + b"tampered")

    with pytest.raises(verify.ReleaseVerificationError, match="sha256"):
        verify.verify_release(tmp_path / f"forge-{VERSION}-manifest.json", tmp_path, expected_version=VERSION)
