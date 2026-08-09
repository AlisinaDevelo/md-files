"""Tests for reproducible OpenAI skills-only submission evidence."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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
    assert report["execution_mode"] == "offline-release-candidate-contract"
    assert report["submission_materials"]["publication"]["status"] == "not_submitted"
    assert report["candidate"]["archive_sha256"]
    assert (tmp_path / "evidence.json").is_file()


def test_submission_evidence_is_deterministic_for_same_source(tmp_path):
    module = load()

    first = module.build_submission_evidence(REPO, tmp_path / "first.json", allow_dirty=True)
    second = module.build_submission_evidence(REPO, tmp_path / "second.json", allow_dirty=True)

    assert first == second
