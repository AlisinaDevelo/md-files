"""Real Git and subprocess contracts for portable contribution evidence."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "plugins/forge/skills/open-source-contribution/scripts/forge-contribute.py"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def workspace(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Contributor")
    git(repo, "config", "user.email", "contributor@example.invalid")
    (repo / "AGENTS.md").write_text("Run the reviewed checks.\n")
    (repo / "source.txt").write_text("original\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Initial source")
    profile = tmp_path / "checks.json"
    data = {"schema": 1, "base_ref": "main", "instruction_paths": ["AGENTS.md"],
            "checks": [{"id": "tests", "argv": [sys.executable, "-c", "print('passed')"],
                        "timeout_seconds": 5, "max_output_bytes": 1024}]}
    profile.write_text(json.dumps(data))
    return repo, profile, data, tmp_path / "receipt.json"


def call(workspace, action, *extra):
    repo, profile, _, receipt = workspace
    argv = [sys.executable, str(HELPER), action, "--repo", str(repo), "--profile", str(profile)]
    if action == "run":
        argv += ["--output", str(receipt)]
    if action == "verify":
        argv += ["--receipt", str(receipt)]
    result = subprocess.run(argv + list(extra), capture_output=True, text=True)
    return result, json.loads(result.stdout) if result.stdout else None


def update(workspace, code):
    _, profile, data, _ = workspace
    data["checks"][0]["argv"] = [sys.executable, "-c", code]
    profile.write_text(json.dumps(data))


def test_plan_does_not_execute(workspace):
    marker = workspace[1].parent / "executed"
    update(workspace, f"from pathlib import Path; Path({str(marker)!r}).touch()")
    result, plan = call(workspace, "plan")
    assert result.returncode == 0, result.stderr
    assert plan["status"] == "ready"
    assert plan["checks"][0]["id"] == "tests"
    assert not marker.exists()


def test_run_requires_explicit_approval(workspace):
    result, _ = call(workspace, "run")
    assert result.returncode == 2
    assert not workspace[3].exists()


def test_run_and_verify_digest_only(workspace):
    secret = "sample-secret-that-must-not-be-published"
    update(workspace, f"print({secret!r})")
    result, receipt = call(workspace, "run", "--yes")
    assert result.returncode == 0, result.stderr
    assert receipt["status"] == "passed"
    assert receipt["source"]["commit"] == git(workspace[0], "rev-parse", "HEAD")
    assert receipt["checks"][0]["output_sha256"] == hashlib.sha256((secret + "\n").encode()).hexdigest()
    assert secret not in workspace[3].read_text()
    assert "argv" not in receipt["checks"][0]
    result, verified = call(workspace, "verify")
    assert result.returncode == 0, result.stderr
    assert verified["status"] == "verified"


@pytest.mark.parametrize("untracked", [False, True])
def test_dirty_source_is_rejected(workspace, untracked):
    (workspace[0] / ("extra.txt" if untracked else "source.txt")).write_text("dirty")
    result, _ = call(workspace, "run", "--yes")
    assert result.returncode == 2
    assert not workspace[3].exists()


def test_failed_check_has_no_acceptance(workspace):
    update(workspace, "raise SystemExit(7)")
    result, receipt = call(workspace, "run", "--yes")
    assert result.returncode == 1
    assert receipt["checks"][0]["returncode"] == 7
    assert receipt["status"] == "failed"
    assert call(workspace, "verify")[0].returncode == 2


def test_timeout_is_failed(workspace):
    update(workspace, "import time; time.sleep(10)")
    workspace[2]["checks"][0]["timeout_seconds"] = 0.1
    workspace[1].write_text(json.dumps(workspace[2]))
    result, receipt = call(workspace, "run", "--yes")
    assert result.returncode == 1
    assert receipt["checks"][0]["status"] == "timeout"


def test_bounded_output_is_failed(workspace):
    update(workspace, "print('x' * 10000)")
    result, receipt = call(workspace, "run", "--yes")
    assert result.returncode == 1
    assert receipt["checks"][0]["status"] == "output-limit"
    assert receipt["checks"][0]["output_bytes"] <= 1024


def test_source_mutation_invalidates_run(workspace):
    update(workspace, "from pathlib import Path; Path('source.txt').write_text('changed')")
    result, receipt = call(workspace, "run", "--yes")
    assert result.returncode == 1
    assert receipt["status"] == "failed"
    assert receipt["source_unchanged"] is False


def test_stale_head_invalidates_receipt(workspace):
    assert call(workspace, "run", "--yes")[0].returncode == 0
    git(workspace[0], "commit", "--allow-empty", "-m", "New revision")
    assert call(workspace, "verify")[0].returncode == 2


def test_changed_profile_invalidates_receipt(workspace):
    assert call(workspace, "run", "--yes")[0].returncode == 0
    update(workspace, "print('different checks')")
    assert call(workspace, "verify")[0].returncode == 2


def test_incomplete_receipt_rejected(workspace):
    assert call(workspace, "run", "--yes")[0].returncode == 0
    receipt = json.loads(workspace[3].read_text())
    receipt["checks"] = []
    workspace[3].write_text(json.dumps(receipt))
    assert call(workspace, "verify")[0].returncode == 2


def test_spawn_failure_is_recorded(workspace):
    workspace[2]["checks"][0]["argv"] = ["/nonexistent/forge-test-command"]
    workspace[1].write_text(json.dumps(workspace[2]))
    result, receipt = call(workspace, "run", "--yes")
    assert result.returncode == 1
    assert receipt["checks"][0]["status"] == "spawn-failed"


def test_contract_mutation_during_run_invalidates_receipt(workspace):
    update(workspace, f"from pathlib import Path; Path({str(workspace[1])!r}).write_text('{{}}')")
    result, receipt = call(workspace, "run", "--yes")
    assert result.returncode == 1
    assert receipt["source_unchanged"] is False


def test_receipt_with_raw_output_rejected(workspace):
    assert call(workspace, "run", "--yes")[0].returncode == 0
    data = json.loads(workspace[3].read_text())
    data["checks"][0]["output"] = "private contents"
    workspace[3].write_text(json.dumps(data))
    assert call(workspace, "verify")[0].returncode == 2


def test_receipt_schema_boolean_is_not_an_integer(workspace):
    assert call(workspace, "run", "--yes")[0].returncode == 0
    data = json.loads(workspace[3].read_text())
    data["schema"] = True
    workspace[3].write_text(json.dumps(data))
    assert call(workspace, "verify")[0].returncode == 2


def test_failure_stops_later_checks(workspace):
    marker = workspace[1].parent / "later-check"
    update(workspace, "raise SystemExit(1)")
    workspace[2]["checks"].append({"id": "later", "argv": [sys.executable, "-c",
                                 f"from pathlib import Path; Path({str(marker)!r}).touch()"],
                                 "timeout_seconds": 5, "max_output_bytes": 1024})
    workspace[1].write_text(json.dumps(workspace[2]))
    result, receipt = call(workspace, "run", "--yes")
    assert result.returncode == 1
    assert len(receipt["checks"]) == 1
    assert not marker.exists()


def test_instruction_symlink_escape_rejected(workspace):
    outside = workspace[1].parent / "outside.md"
    outside.write_text("private")
    link = workspace[0] / "link.md"
    link.symlink_to(outside)
    git(workspace[0], "add", "link.md")
    git(workspace[0], "commit", "-m", "Add link")
    workspace[2]["instruction_paths"] = ["link.md"]
    workspace[1].write_text(json.dumps(workspace[2]))
    assert call(workspace, "plan")[0].returncode == 2


@pytest.mark.parametrize("change", ["empty", "duplicate", "unknown", "escape", "base"])
def test_invalid_contract_rejected(workspace, change):
    data = workspace[2]
    if change == "empty":
        data["checks"] = []
    elif change == "duplicate":
        data["checks"] *= 2
    elif change == "unknown":
        data["checks"][0]["shell"] = True
    elif change == "escape":
        data["instruction_paths"] = ["../outside.md"]
    else:
        data["base_ref"] = "nonexistent-ref"
    workspace[1].write_text(json.dumps(data))
    assert call(workspace, "plan")[0].returncode == 2


def test_existing_output_not_overwritten(workspace):
    workspace[3].write_text("user data")
    assert call(workspace, "run", "--yes")[0].returncode == 2
    assert workspace[3].read_text() == "user data"


def test_output_must_be_outside_repo(workspace):
    inside = workspace[0] / "receipt.json"
    result = subprocess.run([sys.executable, str(HELPER), "run", "--repo", str(workspace[0]),
                             "--profile", str(workspace[1]), "--output", str(inside), "--yes"],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert not inside.exists()


def test_portable_helper_without_checkout(workspace, tmp_path):
    installed = tmp_path / "installed.py"
    installed.write_bytes(HELPER.read_bytes())
    result = subprocess.run([sys.executable, str(installed), "plan", "--repo", str(workspace[0]),
                             "--profile", str(workspace[1])], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "posix", reason="process-group contract is POSIX")
def test_timeout_stops_child_process(workspace):
    pid_file = workspace[1].parent / "child.pid"
    update(workspace, "import subprocess, sys, time; from pathlib import Path; "
           "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)']); "
           f"Path({str(pid_file)!r}).write_text(str(p.pid)); time.sleep(20)")
    workspace[2]["checks"][0]["timeout_seconds"] = 0.5
    workspace[1].write_text(json.dumps(workspace[2]))
    assert call(workspace, "run", "--yes")[0].returncode == 1
    pid = int(pid_file.read_text())
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    assert state.returncode != 0 or state.stdout.strip().startswith("Z")
