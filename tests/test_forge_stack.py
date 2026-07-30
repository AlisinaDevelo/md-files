"""Behavioral tests for Forge's vendor-neutral stacked-change engine."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPO
    / "plugins"
    / "forge"
    / "skills"
    / "stacked-changes"
    / "scripts"
    / "forge-stack.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("forge_stack", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def forge_stack():
    return load_module()


def manifest(branches=None):
    return {
        "version": 1,
        "provider": "github",
        "trunk": "main",
        "remote": "origin",
        "branches": branches or [],
    }


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def git_repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Forge Test")
    git(tmp_path, "config", "user.email", "forge@example.test")
    (tmp_path / "base.txt").write_text("base\n")
    git(tmp_path, "add", "base.txt")
    git(tmp_path, "commit", "-m", "base")

    git(tmp_path, "switch", "-c", "feature/schema")
    (tmp_path / "schema.txt").write_text("schema\n")
    git(tmp_path, "add", "schema.txt")
    git(tmp_path, "commit", "-m", "schema")

    git(tmp_path, "switch", "-c", "feature/api")
    (tmp_path / "api.txt").write_text("api\n")
    git(tmp_path, "add", "api.txt")
    git(tmp_path, "commit", "-m", "api")
    return tmp_path


def test_validate_accepts_ordered_stack(forge_stack):
    data = manifest(
        [
            {"name": "feature/schema", "parent": "main"},
            {"name": "feature/api", "parent": "feature/schema"},
        ]
    )
    assert forge_stack.validate_manifest(data) == []


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"version": 2, "trunk": "main", "remote": "origin", "branches": []}, "version"),
        (manifest([{"name": "x", "parent": "missing"}]), "unknown parent"),
        (
            manifest([{"name": "x", "parent": "main"}, {"name": "x", "parent": "main"}]),
            "duplicate",
        ),
        (manifest([{"name": "main", "parent": "main"}]), "trunk"),
        (manifest([{"name": "x", "parent": "x"}]), "itself"),
    ],
)
def test_validate_rejects_invalid_manifests(forge_stack, data, message):
    assert any(message in error.lower() for error in forge_stack.validate_manifest(data))


def test_inspect_repo_reports_incremental_commits(forge_stack, git_repo):
    data = manifest(
        [
            {"name": "feature/schema", "parent": "main"},
            {"name": "feature/api", "parent": "feature/schema"},
        ]
    )
    rows, errors = forge_stack.inspect_repo(data, git_repo)
    assert errors == []
    assert [row["commits"] for row in rows] == [1, 1]
    assert all(row["parent_is_ancestor"] for row in rows)


def test_inspect_repo_flags_missing_branch(forge_stack, git_repo):
    data = manifest([{"name": "feature/missing", "parent": "main"}])
    _, errors = forge_stack.inspect_repo(data, git_repo)
    assert any("feature/missing" in error and "missing" in error for error in errors)


def test_inspect_repo_flags_non_ancestor_parent(forge_stack, git_repo):
    git(git_repo, "switch", "main")
    git(git_repo, "switch", "-c", "feature/other")
    (git_repo / "other.txt").write_text("other\n")
    git(git_repo, "add", "other.txt")
    git(git_repo, "commit", "-m", "other")
    data = manifest(
        [
            {"name": "feature/schema", "parent": "main"},
            {"name": "feature/other", "parent": "feature/schema"},
        ]
    )
    _, errors = forge_stack.inspect_repo(data, git_repo)
    assert any("not an ancestor" in error for error in errors)


def test_submission_plan_is_bottom_up_and_draft(forge_stack):
    data = manifest(
        [
            {"name": "feature/schema", "parent": "main"},
            {"name": "feature/api", "parent": "feature/schema", "pr": 42},
        ]
    )
    commands = forge_stack.submission_plan(data)
    assert commands[0] == "git push --set-upstream origin feature/schema"
    assert "gh pr create --base main --head feature/schema --draft --fill" in commands[1]
    assert commands[2] == "git push --set-upstream origin feature/api"
    assert commands[3] == "gh pr edit 42 --base feature/schema"


def test_restack_plan_uses_force_with_lease_only(forge_stack):
    data = manifest(
        [
            {"name": "feature/schema", "parent": "main"},
            {"name": "feature/api", "parent": "feature/schema"},
        ]
    )
    commands = forge_stack.restack_plan(data)
    rendered = "\n".join(commands)
    assert "git rebase main" in rendered
    assert "git rebase feature/schema" in rendered
    assert "--force-with-lease origin feature/schema" in rendered
    assert " --force " not in rendered


def test_github_native_adapter_is_the_default(forge_stack):
    data = manifest([{"name": "feature/schema", "parent": "main"}])
    assert forge_stack.adapter_plan(data, "submit", "github") == ["gh stack submit"]
    assert forge_stack.adapter_plan(data, "restack", "github") == [
        "gh stack rebase",
        "gh stack push",
    ]
    assert forge_stack.adapter_plan(data, "land", "github") == [
        "gh stack merge --yes --squash"
    ]


def test_vanilla_adapter_keeps_explicit_commands(forge_stack):
    data = manifest([{"name": "feature/schema", "parent": "main"}])
    commands = forge_stack.adapter_plan(data, "submit", "vanilla")
    assert commands == forge_stack.submission_plan(data)


def test_validate_rejects_unknown_provider(forge_stack):
    data = manifest()
    data["provider"] = "mystery"
    assert any("provider" in error.lower() for error in forge_stack.validate_manifest(data))


def test_pr_body_has_stack_navigation_and_current_marker(forge_stack):
    data = manifest(
        [
            {"name": "feature/schema", "parent": "main", "pr": 41},
            {"name": "feature/api", "parent": "feature/schema", "pr": 42},
        ]
    )
    body = forge_stack.pr_body(data, "feature/api")
    assert "2 of 2" in body
    assert "← #41" in body
    assert "**#42**" in body
    assert "Base: `feature/schema`" in body
    assert "<!-- forge-stack:v1 -->" in body


def test_cli_init_add_and_status_json(git_repo):
    manifest_path = git_repo / ".forge" / "stack.json"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(git_repo), "init", "--trunk", "main"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(git_repo),
            "add",
            "feature/schema",
            "--parent",
            "main",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(git_repo), "status", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout)
    assert manifest_path.exists()
    assert payload["valid"] is True
    assert payload["provider"] == "github"
    assert payload["branches"][0]["name"] == "feature/schema"


def test_cli_check_fails_for_missing_branch(tmp_path):
    path = tmp_path / ".forge"
    path.mkdir()
    (path / "stack.json").write_text(
        json.dumps(manifest([{"name": "feature/missing", "parent": "main"}]))
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(tmp_path), "check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "missing" in proc.stdout.lower()


def test_cli_rejects_non_object_manifest_without_traceback(tmp_path):
    path = tmp_path / ".forge"
    path.mkdir()
    (path / "stack.json").write_text("[]\n")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(tmp_path), "check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "must contain an object" in proc.stderr
    assert "Traceback" not in proc.stderr
