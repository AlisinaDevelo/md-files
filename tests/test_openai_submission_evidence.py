"""Tests for reproducible OpenAI skills-only submission evidence."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/build_openai_submission_evidence.py"


def load():
    spec = importlib.util.spec_from_file_location("forge_openai_submission_evidence", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_submission_evidence_has_five_positive_and_three_negative_cases(tmp_path):
    module = load()

    report = module.build_submission_evidence(REPO, tmp_path / "evidence.json", allow_dirty=True)

    assert len(report["cases"]) == 8
    assert sum(item["polarity"] == "positive" for item in report["cases"]) == 5
    assert sum(item["polarity"] == "negative" for item in report["cases"]) == 3
    assert all(item["status"] == "pass" for item in report["cases"])
    required_case_fields = {"prompt", "expected_behavior", "expected_result_shape", "fixture_data"}
    assert all(required_case_fields <= set(item) for item in report["cases"])
    assert all(
        isinstance(item[field], str) and item[field].strip()
        for item in report["cases"]
        for field in required_case_fields
    )
    assert len({item["id"] for item in report["cases"]}) == 8
    assert len({item["prompt"] for item in report["cases"]}) == 8
    assert report["execution_mode"] == "offline-release-candidate-contract"
    assert report["submission_materials"]["publication"]["status"] == "not_submitted"
    assert report["submission_materials"]["publisher"]["identity_verification"] == "not_repository_verifiable"
    assert report["submission_materials"]["publication"]["portal_draft"] == "not_repository_verifiable"
    assert report["submission_materials"]["publication"]["availability_review"] == "public_directory_unverified"
    assert "Project-level portal approval" in report["external_blockers"][0]
    listing = report["submission_materials"]["listing"]
    version = report["plugin"]["version"]
    release_root = "https://github.com/AlisinaDevelo/md-files"
    assert listing["candidate_release_url"] == f"{release_root}/releases/tag/v{version}"
    assert listing["candidate_archive_url"] == (
        f"{release_root}/releases/download/v{version}/forge-{version}-codex.tar.gz"
    )
    assert listing["candidate_checksums_url"] == f"{release_root}/releases/download/v{version}/SHA256SUMS"
    candidate = report["candidate"]
    assert candidate["archive_sha256"]
    assert candidate["installation"]["status"] == "pass"
    assert candidate["installation"]["mode"] == "isolated-offline-archive"
    assert candidate["installation"]["source_archive_sha256"] == candidate["archive_sha256"]
    assert candidate["installation"]["manifest_version"] == report["plugin"]["version"]
    assert candidate["installation"]["installed_files"] > 0
    assert candidate["installation"]["installed_skills"] >= 20
    assert candidate["installation"]["archive_bytes_match"] is True
    assert candidate["installation"]["strict_validation"] == "pass"
    assert candidate["installation"]["tree_sha256"]
    assert candidate["replay"]["status"] == "pass"
    assert candidate["replay"]["mode"] == "deterministic-installed-contract"
    assert candidate["replay"]["attempts"] == 2
    assert candidate["replay"]["case_count"] == len(report["cases"])
    assert candidate["replay"]["case_set_sha256"]
    assert candidate["replay"]["identical"] is True
    assert candidate["replay"]["source_inputs"]["release_policy"] == "policies/release.json"
    assert candidate["replay"]["source_inputs"]["release_policy_sha256"]
    assert {item["id"] for item in report["checks"]} >= {
        "candidate-installation",
        "contract-replay",
    }
    assert (tmp_path / "evidence.json").is_file()


def test_submission_evidence_is_deterministic_for_same_source(tmp_path):
    module = load()

    first = module.build_submission_evidence(REPO, tmp_path / "first.json", allow_dirty=True)
    second = module.build_submission_evidence(REPO, tmp_path / "second.json", allow_dirty=True)

    assert first == second


def test_submission_evidence_rejects_installed_bytes_that_do_not_match_archive(tmp_path, monkeypatch):
    module = load()
    read_archive = module._read_archive

    def tampered_archive(path):
        files = read_archive(path)
        files["forge/LICENSE"] += b"tampered"
        return files

    monkeypatch.setattr(module, "_read_archive", tampered_archive)

    with pytest.raises(module.SubmissionEvidenceError, match="does not match the release archive byte for byte"):
        module.build_submission_evidence(REPO, tmp_path / "evidence.json", allow_dirty=True)
