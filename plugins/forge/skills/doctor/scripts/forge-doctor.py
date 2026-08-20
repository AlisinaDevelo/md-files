#!/usr/bin/env python3
"""Run a read-only Forge host and repository preflight."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STATUSES = ("pass", "warn", "fail", "unknown")
PLUGIN = Path("plugins/forge")
PROFILE_RELATIVE = Path("data/doctor-profiles.json")
HOST_VERSION_TIMEOUT_SECONDS = 30
PLUGIN_LIST_TIMEOUT_SECONDS = 45


@dataclass
class Check:
    check_id: str
    status: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    remediation: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.check_id,
            "status": self.status,
            "summary": self.summary,
            "evidence": self.evidence,
        }
        if self.remediation:
            result["remediation"] = self.remediation
        return result


class Doctor:
    def __init__(self, repo: Path, offline: bool = False, profile: str = "auto") -> None:
        self.repo = repo.resolve()
        self.offline = offline
        self.profile = profile
        self.checks: list[Check] = []
        self._remote: tuple[str, str] | None = None

    def add(
        self,
        check_id: str,
        status: str,
        summary: str,
        evidence: list[str] | None = None,
        remediation: str | None = None,
    ) -> None:
        if status not in STATUSES:
            raise ValueError(f"invalid check status: {status}")
        self.checks.append(
            Check(check_id, status, summary, evidence or [], remediation)
        )

    def command(self, args: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                cwd=self.repo,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(
                args, 1, "", f"{type(exc).__name__}: {exc}"
            )

    def run(self) -> dict[str, Any]:
        self.check_repo()
        self.check_profile()
        self.check_worktree()
        self.check_manifests()
        self.check_catalog()
        self.check_python_sources()
        self.check_executables()
        self.check_plugin_surfaces()
        self.check_workflow()
        self.check_stack()
        self.check_github()

        counts = {status: 0 for status in STATUSES}
        for check in self.checks:
            counts[check.status] += 1
        overall = "fail" if counts["fail"] else "pass"
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": "forge-doctor",
            "repository": {
                "name": self.repo.name,
                "path": str(self.repo),
            },
            "mode": "offline" if self.offline else "online",
            "overall": overall,
            "summary": counts,
            "checks": [check.as_dict() for check in self.checks],
        }

    def _profile_source(self) -> Path | None:
        candidates = [self.repo / PROFILE_RELATIVE]
        package_root = Path(__file__).resolve().parents[5]
        candidates.append(package_root / PROFILE_RELATIVE)
        for path in candidates:
            if path.is_file():
                return path
        return None

    def _origin(self) -> tuple[str, str] | None:
        if self._remote is not None:
            return self._remote
        result = self.command(["git", "remote", "get-url", "origin"])
        if result.returncode:
            return None
        return parse_github_remote(result.stdout.strip())

    def _profile_match(
        self, profile: dict[str, Any]
    ) -> tuple[str, list[str], tuple[str, str] | None] | None:
        repository_aliases = profile.get("repository_aliases")
        if not isinstance(repository_aliases, dict):
            return None
        workspace_aliases = {
            str(alias).casefold()
            for alias in profile.get("workspace_aliases", [])
            if isinstance(alias, str)
        }
        owners = {
            str(owner).casefold()
            for owner in profile.get("remote_owners", [])
            if isinstance(owner, str)
        }
        workspace_matches = [
            parent.name
            for parent in self.repo.parents
            if parent.name.casefold() in workspace_aliases
        ]
        remote = self._origin()
        remote_owner_match = bool(remote and remote[0].casefold() in owners)
        repository_name = self.repo.name.casefold()
        for canonical, aliases in repository_aliases.items():
            names = {str(canonical).casefold()}
            names.update(
                str(alias).casefold()
                for alias in aliases
                if isinstance(alias, str)
            )
            local_match = repository_name in names
            remote_match = bool(remote_owner_match and remote and remote[1].casefold() in names)
            if (local_match and workspace_matches) or remote_match:
                return str(canonical), workspace_matches, remote
        return None

    def _tracked_files(self) -> list[Path]:
        result = self.command(["git", "ls-files", "-z"], timeout=10)
        if result.returncode == 0:
            return [Path(item) for item in result.stdout.split("\0") if item]
        return sorted(
            path.relative_to(self.repo)
            for path in self.repo.rglob("*")
            if path.is_file() and ".git" not in path.parts
        )

    def check_profile(self) -> None:
        if self.profile == "none":
            return
        source = self._profile_source()
        if source is None:
            if self.profile != "auto":
                self.add(
                    "forge.profile",
                    "fail",
                    "requested doctor profile data is unavailable",
                    [str(PROFILE_RELATIVE)],
                    "Restore data/doctor-profiles.json before using an explicit profile.",
                )
            return
        try:
            document = json.loads(source.read_text(encoding="utf-8"))
            if document.get("schema_version") != 1 or not isinstance(document.get("profiles"), list):
                raise ValueError("profile document must use schema_version 1 and contain profiles")
            profiles = [item for item in document["profiles"] if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.add(
                "forge.profile",
                "fail",
                "doctor profile data is invalid",
                [str(exc), str(source)],
                "Repair the profile document before using profile preflight detection.",
            )
            return

        selected: dict[str, Any] | None = None
        match: tuple[str, list[str], tuple[str, str] | None] | None = None
        if self.profile == "auto":
            for candidate in profiles:
                candidate_match = self._profile_match(candidate)
                if candidate_match:
                    selected = candidate
                    match = candidate_match
                    break
            if selected is None:
                return
        else:
            selected = next(
                (candidate for candidate in profiles if candidate.get("id") == self.profile),
                None,
            )
            if selected is None:
                self.add(
                    "forge.profile",
                    "fail",
                    "requested doctor profile is not registered",
                    [self.profile],
                    "Use a profile id from data/doctor-profiles.json or omit --profile for auto detection.",
                )
                return
            match = self._profile_match(selected)
            if match is None:
                self.add(
                    "forge.profile",
                    "fail",
                    "requested doctor profile does not match this repository",
                    [f"profile {self.profile}", self.repo.name],
                    "Run the requested profile from its declared workspace or repository remote.",
                )
                return

        canonical, workspace_matches, remote = match
        boundaries = selected.get("boundaries")
        expected_boundaries = {
            "execution": "read-only",
            "security": "defensive-only",
            "external_authority": "none",
        }
        if boundaries != expected_boundaries:
            self.add(
                "forge.profile",
                "fail",
                "doctor profile boundary is broader than the read-only contract",
                [f"profile {selected.get('id', 'unknown')}", json.dumps(boundaries, sort_keys=True)],
                "Keep profile detection read-only, defensive-only, and without external authority.",
            )
            return

        matrix = selected.get("language_matrix")
        repository_languages = selected.get("repository_languages")
        expected_languages = repository_languages.get(canonical, []) if isinstance(repository_languages, dict) else None
        if (
            not isinstance(matrix, dict)
            or not isinstance(expected_languages, list)
            or not all(isinstance(language, str) for language in expected_languages)
        ):
            self.add(
                "forge.profile",
                "fail",
                "doctor profile language matrix is invalid",
                [f"profile {selected.get('id', 'unknown')}"] ,
                "Declare a language matrix and repository language expectations as string arrays.",
            )
            return

        markers: dict[str, set[str]] = {}
        for language, values in matrix.items():
            if (
                not isinstance(language, str)
                or not isinstance(values, list)
                or not all(isinstance(value, str) for value in values)
            ):
                self.add(
                    "forge.profile",
                    "fail",
                    "doctor profile language matrix contains invalid entries",
                    [f"profile {selected.get('id', 'unknown')}", str(language)],
                    "Use language names mapped to string extension or filename arrays.",
                )
                return
            markers[language] = {value.casefold() for value in values}

        counts = {language: 0 for language in markers}
        unknown: set[str] = set()
        for path in self._tracked_files():
            filename = path.name.casefold()
            suffix = path.suffix.casefold()
            language = next(
                (
                    candidate
                    for candidate, values in markers.items()
                    if filename in values or suffix in values
                ),
                None,
            )
            if language is None:
                if suffix:
                    unknown.add(suffix)
                continue
            counts[language] += 1

        missing = [language for language in expected_languages if counts.get(language, 0) == 0]
        status = "pass" if not missing and not unknown else "warn"
        language_evidence = [
            f"{language}={counts[language]}"
            for language in markers
            if counts[language]
        ]
        evidence = [
            f"profile {selected.get('id', 'unknown')}",
            f"repository alias {canonical}",
            f"workspace aliases matched: {', '.join(workspace_matches) if workspace_matches else 'remote only'}",
            f"language matrix: {', '.join(language_evidence) if language_evidence else 'no recognized files'}",
            "execution=read-only",
            "security=defensive-only",
            "external_authority=none",
        ]
        if remote:
            evidence.append(f"remote {remote[0]}/{remote[1]}")
        if missing:
            evidence.append("missing expected languages: " + ", ".join(missing))
        if unknown:
            evidence.append("unclassified extensions: " + ", ".join(sorted(unknown)))
        self.add(
            "forge.profile",
            status,
            f"{selected.get('name', selected.get('id', 'Forge'))} profile recognized",
            evidence,
            "Review the repository language matrix before relying on cross-repository comparisons." if status == "warn" else None,
        )

    def check_repo(self) -> None:
        git_dir = self.repo / ".git"
        if not git_dir.exists():
            self.add(
                "repository.git",
                "fail",
                "repository is not a Git worktree",
                [str(self.repo)],
                "Run doctor from a Git repository or pass --repo to one.",
            )
            return
        result = self.command(["git", "rev-parse", "--show-toplevel"])
        if result.returncode:
            self.add(
                "repository.git",
                "fail",
                "Git worktree could not be inspected",
                [result.stderr.strip() or "git rev-parse failed"],
                "Repair the worktree before starting an orchestration run.",
            )
        else:
            self.add("repository.git", "pass", "Git worktree is readable", [result.stdout.strip()])

    def check_worktree(self) -> None:
        branch_result = self.command(["git", "branch", "--show-current"])
        branch = branch_result.stdout.strip() or "(detached HEAD)"
        status_result = self.command(["git", "status", "--porcelain"])
        markers = []
        git_dir = self.repo / ".git"
        if (git_dir / "MERGE_HEAD").exists():
            markers.append("merge in progress")
        if (git_dir / "CHERRY_PICK_HEAD").exists():
            markers.append("cherry-pick in progress")
        if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
            markers.append("rebase in progress")
        if markers:
            self.add(
                "worktree.operation",
                "fail",
                "worktree has an unfinished Git operation",
                markers,
                "Finish or abort the active Git operation before orchestrating changes.",
            )
        elif branch == "(detached HEAD)":
            self.add(
                "worktree.branch",
                "warn",
                "worktree is detached",
                [branch],
                "Switch to an owned branch before creating changes.",
            )
        else:
            self.add("worktree.branch", "pass", "worktree is on a named branch", [branch])

        dirty = [line for line in status_result.stdout.splitlines() if line]
        if dirty:
            self.add(
                "worktree.clean",
                "warn",
                "worktree has uncommitted changes",
                [f"{len(dirty)} changed path(s)"],
                "Review and preserve existing changes before orchestration mutates anything.",
            )
        else:
            self.add("worktree.clean", "pass", "worktree is clean")

    def check_manifests(self) -> None:
        paths = [
            self.repo / PLUGIN / ".claude-plugin" / "plugin.json",
            self.repo / PLUGIN / ".codex-plugin" / "plugin.json",
            self.repo / ".claude-plugin" / "marketplace.json",
        ]
        try:
            manifests = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
            versions = [
                manifests[0]["version"],
                manifests[1]["version"],
                manifests[2]["metadata"]["version"],
                manifests[2]["plugins"][0]["version"],
            ]
        except (OSError, KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
            self.add(
                "forge.manifests",
                "fail",
                "Forge manifests are missing or invalid",
                [str(exc)],
                "Run the repository validation gate and repair manifest parity.",
            )
            return
        if len(set(versions)) != 1:
            self.add(
                "forge.manifests",
                "fail",
                "Forge host manifests disagree on version",
                [", ".join(versions)],
                "Align Claude, Codex, and marketplace manifest versions.",
            )
        else:
            self.add(
                "forge.manifests",
                "pass",
                "Forge host manifests are valid and version-aligned",
                [f"version {versions[0]}", "Claude", "Codex", "marketplace"],
            )

    def check_catalog(self) -> None:
        script = self.repo / "scripts" / "generate_catalog.py"
        if not script.exists():
            self.add(
                "forge.catalog",
                "unknown",
                "catalog generator is unavailable",
                [str(script)],
                "Install or restore the Forge repository source before relying on catalog checks.",
            )
            return
        result = self.command([sys.executable, str(script), "--check"])
        if result.returncode:
            self.add(
                "forge.catalog",
                "fail",
                "generated catalog is stale",
                [result.stderr.strip() or result.stdout.strip() or "catalog check failed"],
                "Run python3 scripts/generate_catalog.py and review the generated diff.",
            )
        else:
            self.add("forge.catalog", "pass", "generated catalog is current")

    def check_python_sources(self) -> None:
        roots = [
            self.repo / "scripts",
            self.repo / PLUGIN / "hooks" / "scripts",
            self.repo / PLUGIN / "skills",
        ]
        files = sorted(
            path
            for root in roots
            if root.exists()
            for path in root.rglob("*.py")
            if path.is_file()
        )
        failures: list[str] = []
        for path in files:
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except (OSError, SyntaxError) as exc:
                failures.append(f"{path.relative_to(self.repo)}: {exc}")
        if failures:
            self.add(
                "forge.sources",
                "fail",
                "Forge Python hook and skill sources contain syntax errors",
                failures,
                "Repair the reported sources and rerun doctor.",
            )
        else:
            self.add(
                "forge.sources",
                "pass",
                "Forge Python hook and skill sources compile in memory",
                [f"{len(files)} source file(s) checked"],
            )

    def check_executables(self) -> None:
        required = {"git": ["--version"], "python3": ["--version"]}
        optional = {
            "gh": ["--version"],
            "claude": ["--version"],
            "codex": ["--version"],
            "jq": ["--version"],
        }
        missing_required = [name for name in required if not shutil.which(name)]
        if missing_required:
            self.add(
                "host.required-tools",
                "fail",
                "required host tools are missing",
                missing_required,
                "Install Git and Python 3 before starting Forge.",
            )
        else:
            self.add("host.required-tools", "pass", "required host tools are available")

        missing_optional = []
        found_optional = []
        for name, args in optional.items():
            executable = shutil.which(name)
            if not executable:
                missing_optional.append(name)
                continue
            result = self.command(
                [executable, *args], timeout=HOST_VERSION_TIMEOUT_SECONDS
            )
            version = (result.stdout or result.stderr).splitlines()[0] if result.returncode == 0 else "unavailable"
            found_optional.append(f"{name}: {version}")
        if missing_optional:
            self.add(
                "host.optional-tools",
                "warn",
                "some optional host tools are unavailable",
                found_optional + [f"missing: {name}" for name in missing_optional],
                "Install the missing host or GitHub CLI for the affected integrations.",
            )
        else:
            self.add("host.optional-tools", "pass", "Claude, Codex, GitHub CLI, and jq are available", found_optional)

    def check_workflow(self) -> None:
        workflows = sorted((self.repo / ".github" / "workflows").glob("*.y*ml"))
        if not workflows:
            self.add(
                "github.merge-group",
                "unknown",
                "no GitHub Actions workflows were found",
                [],
                "Add or identify the workflow that owns required repository checks.",
            )
            return
        merge_group = [path for path in workflows if "merge_group:" in path.read_text(encoding="utf-8")]
        if merge_group:
            self.add(
                "github.merge-group",
                "pass",
                "required workflow coverage includes merge_group",
                [str(path.relative_to(self.repo)) for path in merge_group],
            )
        else:
            self.add(
                "github.merge-group",
                "warn",
                "workflow coverage does not declare merge_group",
                [str(path.relative_to(self.repo)) for path in workflows],
                "Add merge_group checks when the repository uses GitHub Merge Queue.",
            )

    def check_plugin_surfaces(self) -> None:
        expected = None
        manifest = self.repo / PLUGIN / ".codex-plugin" / "plugin.json"
        try:
            expected = json.loads(manifest.read_text(encoding="utf-8"))["version"]
        except (OSError, KeyError, json.JSONDecodeError, TypeError):
            self.add(
                "host.plugin-surfaces",
                "unknown",
                "installed-host drift could not be compared to a Forge version",
                [str(manifest)],
                "Repair the Codex plugin manifest before checking installed host surfaces.",
            )
            return

        findings: list[str] = []
        problems: list[str] = []
        for host, args in (
            ("Claude", ["claude", "plugin", "list", "--json"]),
            ("Codex", ["codex", "plugin", "list", "--json"]),
        ):
            if not shutil.which(args[0]):
                findings.append(f"{host}: CLI unavailable")
                continue
            result = self.command(args, timeout=PLUGIN_LIST_TIMEOUT_SECONDS)
            if result.returncode:
                problems.append(f"{host}: plugin list failed")
                continue
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                problems.append(f"{host}: plugin list was not valid JSON")
                continue
            entries = payload if host == "Claude" else payload.get("installed", [])
            entry = next(
                (
                    item
                    for item in entries
                    if item.get("id") == "forge@forge" or item.get("pluginId") == "forge@forge"
                ),
                None,
            )
            if not entry:
                problems.append(f"{host}: Forge is not installed")
                continue
            installed = entry.get("version", "unknown")
            findings.append(f"{host}: {installed}")
            if installed != expected:
                problems.append(f"{host}: installed {installed}, source {expected}")

        if problems:
            self.add(
                "host.plugin-surfaces",
                "warn",
                "installed host surfaces have drift or are unavailable",
                findings + problems,
                "Install or refresh Forge in each host before relying on its newest capabilities.",
            )
        else:
            self.add(
                "host.plugin-surfaces",
                "pass",
                "installed Claude and Codex Forge surfaces match the source version",
                [f"version {expected}"] + findings,
            )

    def check_stack(self) -> None:
        manifest = self.repo / ".forge" / "stack.json"
        if not manifest.exists():
            self.add("forge.stack", "pass", "no Forge stack is active in this checkout")
            return
        script = self.repo / PLUGIN / "skills" / "stacked-changes" / "scripts" / "forge-stack.py"
        if not script.exists():
            self.add(
                "forge.stack",
                "unknown",
                "stack manifest exists but the stack engine is unavailable",
                [str(manifest)],
                "Restore the Forge stack engine before changing stack branches.",
            )
            return
        result = self.command([sys.executable, str(script), "--repo", str(self.repo), "check"])
        if result.returncode:
            self.add(
                "forge.stack",
                "fail",
                "active Forge stack is not valid",
                [result.stderr.strip() or result.stdout.strip() or str(manifest)],
                "Resolve stack ancestry and manifest errors before delivery.",
            )
        else:
            self.add("forge.stack", "pass", "active Forge stack is valid", [str(manifest)])

    def check_github(self) -> None:
        if self.offline:
            for check_id in ("github.auth", "github.branch-policy", "github.rulesets", "github.signatures"):
                self.add(
                    check_id,
                    "unknown",
                    "network-backed GitHub check skipped in offline mode",
                    [],
                    "Rerun without --offline to inspect GitHub repository policy.",
                )
            return
        gh = shutil.which("gh")
        if not gh:
            for check_id in ("github.auth", "github.branch-policy", "github.rulesets", "github.signatures"):
                self.add(
                    check_id,
                    "unknown",
                    "GitHub CLI is unavailable",
                    [],
                    "Install and authenticate gh to inspect GitHub policy.",
                )
            return
        remote = self.command(["git", "remote", "get-url", "origin"])
        parsed = parse_github_remote(remote.stdout.strip()) if remote.returncode == 0 else None
        if not parsed:
            for check_id in ("github.auth", "github.branch-policy", "github.rulesets", "github.signatures"):
                self.add(
                    check_id,
                    "unknown",
                    "origin is not a recognizable GitHub remote",
                    [remote.stdout.strip() or "origin unavailable"],
                    "Configure a GitHub origin or use --offline for local-only diagnostics.",
                )
            return
        self._remote = parsed
        owner, repo = parsed
        repository = self.github_api(["repos", owner, repo])
        if repository is None:
            self.add(
                "github.auth",
                "unknown",
                "GitHub repository metadata could not be read",
                [f"{owner}/{repo}"],
                "Authenticate gh and confirm the repository is reachable.",
            )
            return
        self.add("github.auth", "pass", "GitHub API is readable", [f"{owner}/{repo}"])
        default_branch = repository.get("default_branch", "main")
        branch_info = self.github_api(["repos", owner, repo, "branches", default_branch])
        protection = self.github_api(["repos", owner, repo, "branches", default_branch, "protection"])
        if protection is None:
            if branch_info and branch_info.get("protected"):
                self.add(
                    "github.branch-policy",
                    "unknown",
                    "default branch is marked protected but detailed policy is unavailable",
                    [default_branch],
                    "Confirm the token can read the branch protection details.",
                )
            else:
                self.add(
                    "github.branch-policy",
                    "fail",
                    "default branch protection could not be read or is absent",
                    [default_branch],
                    "Protect the default branch and require the repository validation checks.",
                )
        else:
            required = protection.get("required_status_checks") or {}
            reviews = protection.get("required_pull_request_reviews")
            problems = []
            if not required.get("contexts") and not required.get("checks"):
                problems.append("no required status checks")
            if reviews is None:
                problems.append("pull requests are not required")
            if (protection.get("allow_force_pushes") or {}).get("enabled"):
                problems.append("force pushes are allowed")
            if (protection.get("allow_deletions") or {}).get("enabled"):
                problems.append("branch deletion is allowed")
            if not (protection.get("required_conversation_resolution") or {}).get("enabled"):
                problems.append("conversation resolution is not required")
            status = "fail" if problems else "pass"
            self.add(
                "github.branch-policy",
                status,
                "default branch protection is configured" if not problems else "default branch policy has gaps",
                [default_branch] + problems,
                "Repair the listed branch protection gaps before a protected landing." if problems else None,
            )

        rulesets = self.github_api(["repos", owner, repo, "rulesets"])
        if rulesets is None:
            self.add(
                "github.rulesets",
                "unknown",
                "repository rulesets could not be inspected",
                [],
                "Confirm the token can read repository rulesets.",
            )
        else:
            self.add("github.rulesets", "pass", "repository rulesets are readable", [f"{len(rulesets)} rule set(s)"])

        signatures = self.github_api(["repos", owner, repo, "branches", default_branch, "protection", "required_signatures"])
        if signatures is None:
            self.add(
                "github.signatures",
                "warn",
                "required commit-signature policy is unavailable or disabled",
                [default_branch],
                "Enable signed commits when repository policy requires cryptographic author identity.",
            )
        else:
            self.add("github.signatures", "pass", "required commit-signature policy is enabled", [default_branch])

    def github_api(self, path: list[str]) -> Any | None:
        result = self.command(["gh", "api", "/".join(path)], timeout=20)
        if result.returncode:
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None


def parse_github_remote(remote: str) -> tuple[str, str] | None:
    patterns = (
        r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$",
        r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$",
        r"^git@github-[^:]+:([^/]+)/([^/]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/([^/]+)/([^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.match(pattern, remote)
        if match:
            return match.group(1), match.group(2)
    return None


def render_human(report: dict[str, Any]) -> str:
    lines = [
        f"Forge Doctor (schema v{report['schema_version']})",
        f"Repository: {report['repository']['name']} [{report['mode']} mode]",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"[{check['status'].upper():7}] {check['id']}: {check['summary']}")
        for evidence in check["evidence"]:
            lines.append(f"          - {evidence}")
        if check.get("remediation"):
            lines.append(f"          -> {check['remediation']}")
    summary = report["summary"]
    lines += [
        "",
        "Summary: "
        + ", ".join(f"{status}={summary[status]}" for status in STATUSES),
        f"Overall: {report['overall']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run read-only Forge host and repository diagnostics.")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository to inspect (default: current directory)")
    parser.add_argument("--json", action="store_true", help="emit the schema-versioned JSON report")
    parser.add_argument("--offline", action="store_true", help="skip all network-backed GitHub checks")
    parser.add_argument("--profile", default="auto", help="doctor profile id or 'auto'/'none' (default: auto)")
    parser.add_argument("--strict", action="store_true", help="return failure for warnings or unknown checks")
    args = parser.parse_args(argv)

    report = Doctor(args.repo, offline=args.offline, profile=args.profile).run()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_human(report))
    if report["overall"] == "fail":
        return 1
    if args.strict and (report["summary"]["warn"] or report["summary"]["unknown"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
