"""Behavioral tests for the read-only Forge Doctor preflight."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/doctor/scripts/forge-doctor.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_doctor", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("https://github.com/AlisinaDevelo/md-files.git", ("AlisinaDevelo", "md-files")),
        ("git@github.com:AlisinaDevelo/md-files", ("AlisinaDevelo", "md-files")),
        ("ssh://git@github.com/AlisinaDevelo/md-files.git", ("AlisinaDevelo", "md-files")),
        ("https://gitlab.com/example/project.git", None),
    ],
)
def test_parse_github_remote(remote, expected):
    doctor = load_module()
    assert doctor.parse_github_remote(remote) == expected


def test_offline_report_is_schema_versioned_and_deterministic():
    doctor = load_module()
    first = doctor.Doctor(REPO, offline=True).run()
    second = doctor.Doctor(REPO, offline=True).run()

    assert first == second
    assert first["schema_version"] == 1
    assert first["mode"] == "offline"
    assert {check["status"] for check in first["checks"]} >= {"unknown"}
    network_checks = {"github.auth", "github.branch-policy", "github.rulesets", "github.signatures"}
    assert all(
        check["status"] == "unknown"
        for check in first["checks"]
        if check["id"] in network_checks
    )


def test_offline_mode_never_calls_github_api(monkeypatch):
    doctor = load_module()
    instance = doctor.Doctor(REPO, offline=True)

    def forbidden(_path):
        raise AssertionError("offline doctor called the GitHub API")

    monkeypatch.setattr(instance, "github_api", forbidden)
    report = instance.run()
    assert report["summary"]["unknown"] == 4


def test_manifest_drift_is_a_failure(tmp_path):
    doctor = load_module()
    (tmp_path / "plugins/forge/.claude-plugin").mkdir(parents=True)
    (tmp_path / "plugins/forge/.codex-plugin").mkdir(parents=True)
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / "plugins/forge/.claude-plugin/plugin.json").write_text('{"version":"1.0.0"}\n')
    (tmp_path / "plugins/forge/.codex-plugin/plugin.json").write_text('{"version":"1.1.0"}\n')
    (tmp_path / ".claude-plugin/marketplace.json").write_text(
        json.dumps({"metadata": {"version": "1.0.0"}, "plugins": [{"version": "1.0.0"}]})
    )

    instance = doctor.Doctor(tmp_path, offline=True)
    instance.check_manifests()

    assert instance.checks[0].status == "fail"
    assert "disagree" in instance.checks[0].summary


def test_cli_json_output_is_parseable():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(REPO), "--offline", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    report = json.loads(proc.stdout)
    assert report["tool"] == "forge-doctor"
    assert report["schema_version"] == 1
    assert "checks" in report
