"""Real Git and subprocess contracts for portable contribution evidence."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

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


def test_git_environment_cannot_redirect_identity(workspace, tmp_path, monkeypatch):
    alternate = tmp_path / "alternate-git"
    git(workspace[0], "clone", "--bare", str(workspace[0]), str(alternate))
    git(alternate, "config", "user.name", "Other")
    git(alternate, "config", "user.email", "other@example.invalid")
    original = git(workspace[0], "rev-parse", "HEAD")
    tree = git(workspace[0], "rev-parse", "HEAD^{tree}")
    alternate_head = git(alternate, "commit-tree", tree, "-m", "Alternate identity")
    git(alternate, "update-ref", "refs/heads/main", alternate_head)
    (alternate / "index").write_bytes((workspace[0] / ".git/index").read_bytes())
    monkeypatch.setenv("GIT_DIR", str(alternate))
    monkeypatch.setenv("GIT_WORK_TREE", str(workspace[0]))
    result, plan = call(workspace, "plan")
    assert result.returncode == 0, result.stdout
    assert plan["source"]["commit"] == original


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_hidden_worktree_modifications_rejected(workspace, flag):
    git(workspace[0], "update-index", flag, "source.txt")
    (workspace[0] / "source.txt").write_text("hidden change")
    assert git(workspace[0], "status", "--porcelain") == ""
    assert call(workspace, "plan")[0].returncode == 2


def test_instruction_pathspec_is_not_an_exact_tracked_file(workspace):
    git(workspace[0], "config", "core.excludesfile", str(workspace[1].parent / "ignored"))
    (workspace[1].parent / "ignored").write_text(":(glob)AGENTS*\n")
    literal = workspace[0] / ":(glob)AGENTS*"
    literal.write_text("not tracked instructions")
    workspace[2]["instruction_paths"] = [literal.name]
    workspace[1].write_text(json.dumps(workspace[2]))
    assert git(workspace[0], "status", "--porcelain") == ""
    assert call(workspace, "plan")[0].returncode == 2


def test_ignored_submodule_changes_cannot_claim_exact_head(workspace):
    child_source = workspace[1].parent / "child-source.git"
    git(workspace[0], "clone", "--bare", str(workspace[0]), str(child_source))
    git(workspace[0], "-c", "protocol.file.allow=always", "submodule", "add", str(child_source), "module")
    git(workspace[0], "commit", "-am", "Add module")
    git(workspace[0], "config", "submodule.module.ignore", "all")
    (workspace[0] / "module/source.txt").write_text("unreported change")
    assert git(workspace[0], "status", "--porcelain") == ""
    assert call(workspace, "plan")[0].returncode == 2


def test_stat_cache_cannot_hide_modified_bytes(workspace):
    path = workspace[0] / "source.txt"
    git(workspace[0], "config", "core.trustctime", "false")
    git(workspace[0], "config", "core.checkStat", "minimal")
    old = time.time() - 5
    os.utime(path, (old, old))
    git(workspace[0], "update-index", "--really-refresh")
    original_stat = path.stat()
    with path.open("r+b") as handle:
        handle.write(b"modified\n")
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert git(workspace[0], "status", "--porcelain") == ""
    update(workspace, "from pathlib import Path; assert Path('source.txt').read_text() == 'modified\\n'")
    assert call(workspace, "run", "--yes")[0].returncode == 2


def test_check_vectors_keep_normal_git_pathspec_semantics(workspace):
    expected = subprocess.check_output(["git", "-C", str(workspace[0]), "ls-files", "*.md"])
    assert expected
    workspace[2]["checks"][0]["argv"] = ["git", "ls-files", "*.md"]
    workspace[1].write_text(json.dumps(workspace[2]))
    result, receipt = call(workspace, "run", "--yes")
    assert result.returncode == 0
    assert receipt["checks"][0]["output_sha256"] == hashlib.sha256(expected).hexdigest()


def test_git_replace_cannot_change_recorded_source_tree(workspace):
    original = git(workspace[0], "rev-parse", "HEAD")
    (workspace[0] / "source.txt").write_text("replaced\n")
    git(workspace[0], "commit", "-am", "Other tree")
    replacement = git(workspace[0], "rev-parse", "HEAD")
    git(workspace[0], "update-ref", "refs/heads/main", original)
    git(workspace[0], "replace", original, replacement)
    assert git(workspace[0], "status", "--porcelain") == ""
    assert call(workspace, "plan")[0].returncode == 2


def test_executable_mode_is_checked_even_when_git_ignores_it(workspace):
    git(workspace[0], "config", "core.filemode", "false")
    path = workspace[0] / "source.txt"
    path.chmod(path.stat().st_mode | 0o100)
    assert git(workspace[0], "status", "--porcelain") == ""
    assert call(workspace, "plan")[0].returncode == 2


def test_symlink_text_is_hashed_without_reading_target(workspace):
    target = workspace[1].parent / "private-target"
    target.write_text("private")
    (workspace[0] / "link").symlink_to(target)
    git(workspace[0], "add", "link")
    git(workspace[0], "commit", "-m", "Add symlink")
    assert call(workspace, "run", "--yes")[0].returncode == 0
    target.write_text("different private bytes")
    assert call(workspace, "verify")[0].returncode == 0


def test_transformed_checkout_is_explicitly_rejected(workspace):
    git(workspace[0], "config", "core.autocrlf", "true")
    (workspace[0] / ".gitattributes").write_text("source.txt text eol=crlf\n")
    git(workspace[0], "add", ".gitattributes")
    git(workspace[0], "commit", "-m", "Declare materialized line endings")
    path = workspace[0] / "source.txt"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    git(workspace[0], "add", "source.txt")
    git(workspace[0], "commit", "--allow-empty", "-m", "Materialize checkout")
    assert git(workspace[0], "status", "--porcelain") == ""
    result, report = call(workspace, "plan")
    assert result.returncode == 2
    assert "transformed checkouts" in report["error"]


def test_sha256_git_repository_is_supported(workspace):
    repo = workspace[1].parent / "sha256-repo"
    repo.mkdir()
    git(repo, "init", "--object-format=sha256", "-b", "main")
    git(repo, "config", "user.name", "Contributor")
    git(repo, "config", "user.email", "contributor@example.invalid")
    (repo / "AGENTS.md").write_text("Reviewed checks only.\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "SHA256 source")
    alternate = (repo, *workspace[1:])
    result, receipt = call(alternate, "run", "--yes")
    assert result.returncode == 0, result.stdout
    assert len(receipt["source"]["commit"]) == 64
    assert call(alternate, "verify")[0].returncode == 0


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
