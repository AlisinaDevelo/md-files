#!/usr/bin/env python3
"""Build reproducible evidence for Forge's skills-only OpenAI submission."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
SCHEMA_VERSION = 1
EVIDENCE_SCHEMA = "https://github.com/AlisinaDevelo/md-files/schema/openai-agent-plugin-submission-evidence/v1"
VALID_TRIGGER_KINDS = {"delegation", "progressive", "explicit"}


class SubmissionEvidenceError(RuntimeError):
    """Raised when the release candidate cannot produce complete evidence."""


def _load_script_module(name: str) -> Any:
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"forge_submission_{name}", path)
    if spec is None or spec.loader is None:
        raise SubmissionEvidenceError(f"cannot load helper script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SubmissionEvidenceError(f"cannot read JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SubmissionEvidenceError(f"JSON document must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if result.returncode:
        raise SubmissionEvidenceError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _https(value: Any) -> bool:
    parsed = urlparse(value) if isinstance(value, str) else None
    return bool(parsed and parsed.scheme == "https" and parsed.netloc)


def _read_archive(path: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                name = PurePosixPath(member.name)
                if (
                    not member.isfile()
                    or name.is_absolute()
                    or ".." in name.parts
                    or not name.parts
                    or name.parts[0] != "forge"
                ):
                    raise SubmissionEvidenceError(f"candidate archive contains an unsafe member: {member.name}")
                if member.name in files:
                    raise SubmissionEvidenceError(f"candidate archive contains a duplicate member: {member.name}")
                source = archive.extractfile(member)
                if source is None:
                    raise SubmissionEvidenceError(f"candidate archive member is unreadable: {member.name}")
                files[member.name] = source.read()
    except (OSError, tarfile.TarError) as exc:
        raise SubmissionEvidenceError(f"cannot read candidate archive: {exc}") from exc
    return files


def _read_installed_tree(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SubmissionEvidenceError(f"installed candidate contains a symlink: {path.relative_to(root)}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SubmissionEvidenceError(f"installed candidate contains an unsupported entry: {path.relative_to(root)}")
        relative = path.relative_to(root).as_posix()
        files[f"forge/{relative}"] = path.read_bytes()
    return files


def _json_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contains(files: dict[str, bytes], path: str, *needles: str) -> tuple[bool, list[str]]:
    data = files.get(path)
    if data is None:
        return False, [f"missing archive member {path}"]
    text = data.decode("utf-8", errors="replace").lower()
    missing = [needle for needle in needles if needle.lower() not in text]
    if missing:
        return False, [f"{path} is missing {needle!r}" for needle in missing]
    return True, [f"{path} contains {needle!r}" for needle in needles]


def _case(case_id: str, polarity: str, expected: str, paths: list[str], observations: list[str]) -> dict[str, Any]:
    return {
        "id": case_id,
        "polarity": polarity,
        "expected_behavior": expected,
        "status": "pass",
        "mode": "offline-release-candidate-contract",
        "evidence": {"paths": paths, "observations": observations},
    }


def _submission_metadata(repo: Path, version: str) -> dict[str, Any]:
    plugin = _load_json(repo / "plugins/forge/.codex-plugin/plugin.json")
    interface = plugin.get("interface")
    author = plugin.get("author")
    if not isinstance(interface, dict) or not isinstance(author, dict):
        raise SubmissionEvidenceError("Codex plugin manifest is missing interface or author metadata")

    required_interface = (
        "displayName",
        "longDescription",
        "developerName",
        "category",
        "websiteURL",
        "privacyPolicyURL",
        "termsOfServiceURL",
        "defaultPrompt",
    )
    for field in required_interface:
        value = interface.get(field)
        if field == "defaultPrompt":
            if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
                raise SubmissionEvidenceError("interface.defaultPrompt must contain non-empty strings")
        elif not isinstance(value, str) or not value.strip():
            raise SubmissionEvidenceError(f"interface.{field} must be non-empty")
    for field in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
        if not _https(interface[field]):
            raise SubmissionEvidenceError(f"interface.{field} must be an absolute HTTPS URL")
    if not isinstance(author.get("name"), str) or not author["name"].strip() or not _https(author.get("url")):
        raise SubmissionEvidenceError("publisher metadata must include a name and HTTPS URL")

    listing = {
        "display_name": interface["displayName"],
        "description": interface["longDescription"],
        "developer_name": interface["developerName"],
        "category": interface["category"],
        "website_url": interface["websiteURL"],
        "support_url": "https://github.com/AlisinaDevelo/md-files/issues",
        "privacy_policy_url": interface["privacyPolicyURL"],
        "terms_of_service_url": interface["termsOfServiceURL"],
        "starter_prompts": interface["defaultPrompt"],
        "release_notes_url": "https://github.com/AlisinaDevelo/md-files/blob/main/CHANGELOG.md",
        "availability": {"status": "pending_external_submission", "scope": "not-yet-entered"},
    }
    for field in (
        "website_url",
        "support_url",
        "privacy_policy_url",
        "terms_of_service_url",
        "release_notes_url",
    ):
        if not _https(listing[field]):
            raise SubmissionEvidenceError(f"listing.{field} must be an absolute HTTPS URL")

    return {
        "listing": listing,
        "publisher": {
            "name": author["name"],
            "website_url": author["url"],
            "identity_verification": "pending_external_owner_action",
        },
        "publication": {
            "directory": "OpenAI universal Plugin Directory",
            "status": "not_submitted",
            "portal_draft": "blocked_pending_owner_identity",
            "availability_review": "pending_external_submission",
        },
        "plugin_manifest": {
            "name": plugin.get("name"),
            "version": version,
            "shape": "skills-only",
            "skills": plugin.get("skills"),
        },
    }


def _run_cases(files: dict[str, bytes], release_policy: dict[str, Any], validator: Any) -> list[dict[str, Any]]:
    manifest_path = "forge/.codex-plugin/plugin.json"
    orchestration = "forge/skills/orchestration/SKILL.md"
    solve_loop = "forge/skills/iterate-to-done/SKILL.md"
    stacked = "forge/skills/stacked-changes/SKILL.md"
    policy = "forge/skills/policy/SKILL.md"
    doctor = "forge/skills/doctor/SKILL.md"
    graph_path = "forge/data/capabilities.json"

    results: list[dict[str, Any]] = []
    checks = (
        ("positive-orchestration", "positive", "Orchestration plans a non-trivial goal with a dependency-ordered ledger and iterates to done.", orchestration, ("task ledger", "iterate to done")),
        ("positive-solve-loop", "positive", "A focused change is iterated until acceptance criteria and verification are complete.", solve_loop, ("acceptance", "verify")),
        ("positive-stacked-delivery", "positive", "Stacked delivery preserves parent relationships and uses lease-safe Git operations.", stacked, ("immediate parent", "--force-with-lease")),
        ("positive-policy-review", "positive", "Doctor and policy workflows inspect state and keep external effects reviewable.", policy, ("approval", "staged-preview")),
    )
    for case_id, polarity, expected, path, needles in checks:
        passed, observations = _contains(files, path, *needles)
        if not passed:
            raise SubmissionEvidenceError(f"{case_id} failed: {'; '.join(observations)}")
        if case_id == "positive-policy-review":
            doctor_ok, doctor_observations = _contains(files, doctor, "read-only", "preflight")
            if not doctor_ok:
                raise SubmissionEvidenceError(f"{case_id} failed: {'; '.join(doctor_observations)}")
            observations.extend(doctor_observations)
        results.append(_case(case_id, polarity, expected, [path, doctor] if case_id == "positive-policy-review" else [path], observations))

    plugin = json.loads(files[manifest_path].decode("utf-8"))
    skill_paths = [path for path in files if path.startswith("forge/skills/") and path.endswith("/SKILL.md")]
    if plugin.get("skills") != "./skills/" or len(skill_paths) < 20:
        raise SubmissionEvidenceError("positive-codex-discovery failed: skills directory is incomplete")
    results.append(
        _case(
            "positive-codex-discovery",
            "positive",
            "Codex can discover a valid skills-only plugin with a stable manifest and populated skills directory.",
            [manifest_path, "forge/skills/"],
            [f"manifest declares {plugin['skills']}", f"candidate contains {len(skill_paths)} skill entry points"],
        )
    )

    graph = json.loads(files[graph_path].decode("utf-8"))
    components = graph.get("components", [])
    if not components or any(item.get("triggers", {}).get("kind") not in VALID_TRIGGER_KINDS for item in components):
        raise SubmissionEvidenceError("negative-unrelated-request failed: capability triggers are not explicit")
    results.append(
        _case(
            "negative-unrelated-request",
            "negative",
            "An unrelated request does not activate Forge through a catch-all trigger.",
            [graph_path],
            [f"{len(components)} capabilities use explicit delegation, progressive, or command triggers", "no wildcard trigger kind is accepted"],
        )
    )

    rules = release_policy.get("rules", [])
    release_effect = next((rule for rule in rules if rule.get("id") == "release-effect"), None)
    if release_policy.get("default_decision") != "deny" or not isinstance(release_effect, dict) or release_effect.get("decision") != "require_approval":
        raise SubmissionEvidenceError("negative-policy-bypass failed: release policy is not fail-closed")
    results.append(
        _case(
            "negative-policy-bypass",
            "negative",
            "A release or GitHub mutation cannot bypass the explicit approval boundary.",
            ["policies/release.json", policy],
            ["release policy defaults to deny", "release effects require approval"],
        )
    )

    with tempfile.TemporaryDirectory(prefix="forge-openai-negative-") as directory:
        root = Path(directory) / "forge"
        root.mkdir()
        for path, data in files.items():
            relative = Path(path).relative_to("forge")
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        bad_manifest = json.loads((root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        bad_manifest["version"] = "not-semver"
        (root / ".codex-plugin/plugin.json").write_text(json.dumps(bad_manifest), encoding="utf-8")
        errors = validator.validate_plugin(root)
    if not any("strict semver" in error for error in errors):
        raise SubmissionEvidenceError("negative-malformed-manifest failed: malformed manifest was accepted")
    results.append(
        _case(
            "negative-malformed-manifest",
            "negative",
            "A malformed plugin manifest is rejected instead of being silently accepted.",
            [manifest_path],
            ["temporary version mutation was rejected by the strict Codex validator"],
        )
    )
    if len([item for item in results if item["polarity"] == "positive"]) != 5 or len([item for item in results if item["polarity"] == "negative"]) != 3:
        raise SubmissionEvidenceError("submission evidence must contain five positive and three negative cases")
    return results


def _install_and_replay(
    archive: Path,
    archive_files: dict[str, bytes],
    archive_sha256: str,
    version: str,
    release_policy: dict[str, Any],
    validator: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="forge-openai-install-") as directory:
        try:
            installed_root = validator.extract_archive(archive, Path(directory))
        except (OSError, tarfile.TarError, ValueError) as exc:
            raise SubmissionEvidenceError(f"candidate installation failed: {exc}") from exc
        validation_errors = validator.validate_plugin(installed_root, version)
        if validation_errors:
            raise SubmissionEvidenceError("installed candidate failed Codex validation: " + "; ".join(validation_errors))
        installed_files = _read_installed_tree(installed_root)
        if installed_files != archive_files:
            raise SubmissionEvidenceError("installed candidate does not match the release archive byte for byte")

        first_cases = _run_cases(installed_files, release_policy, validator)
        second_cases = _run_cases(installed_files, release_policy, validator)
        first_digest = _json_sha256(first_cases)
        second_digest = _json_sha256(second_cases)
        if first_digest != second_digest or first_cases != second_cases:
            raise SubmissionEvidenceError("installed candidate contract replay is not deterministic")

        manifest = json.loads(installed_files["forge/.codex-plugin/plugin.json"].decode("utf-8"))
        skill_paths = [path for path in installed_files if path.startswith("forge/skills/") and path.endswith("/SKILL.md")]
        tree_inventory = {path: hashlib.sha256(data).hexdigest() for path, data in sorted(installed_files.items())}
        installation = {
            "status": "pass",
            "mode": "isolated-offline-archive",
            "source_archive_sha256": archive_sha256,
            "manifest_version": manifest.get("version"),
            "installed_files": len(installed_files),
            "installed_skills": len(skill_paths),
            "tree_sha256": _json_sha256(tree_inventory),
            "archive_bytes_match": True,
            "strict_validation": "pass",
        }
        replay = {
            "status": "pass",
            "mode": "deterministic-installed-contract",
            "attempts": 2,
            "case_count": len(first_cases),
            "case_set_sha256": first_digest,
            "identical": True,
            "source_inputs": {
                "release_policy": "policies/release.json",
                "release_policy_sha256": _json_sha256(release_policy),
            },
        }
    return first_cases, installation, replay


def build_submission_evidence(repo: Path, output: Path | None = None, *, allow_dirty: bool = False) -> dict[str, Any]:
    repo = repo.resolve()
    manifest = _load_json(repo / "plugins/forge/.claude-plugin/plugin.json")
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise SubmissionEvidenceError("plugin manifest has no version")
    commit = _git(repo, "rev-parse", "HEAD")
    source_epoch = int(_git(repo, "show", "-s", "--format=%ct", commit))
    metadata = _submission_metadata(repo, version)
    release_policy = _load_json(repo / "policies/release.json")
    builder = _load_script_module("build_release")
    validator = _load_script_module("validate_codex_plugin")
    verifier = _load_script_module("verify_release")

    with tempfile.TemporaryDirectory(prefix="forge-openai-candidate-") as directory:
        dist = Path(directory) / "dist"
        dist.mkdir()
        builder.build_release(
            repo,
            dist,
            version,
            source_epoch=source_epoch,
            tag=f"v{version}",
            enforce_clean=not allow_dirty,
        )
        release_manifest = dist / f"forge-{version}-manifest.json"
        verifier.verify_release(release_manifest, dist, expected_version=version, expected_commit=commit)
        archive = dist / f"forge-{version}-codex.tar.gz"
        validation_errors = validator.validate_archive(archive, version)
        if validation_errors:
            raise SubmissionEvidenceError("candidate archive failed Codex validation: " + "; ".join(validation_errors))
        files = _read_archive(archive)
        archive_sha256 = _sha256(archive)
        cases, installation, replay = _install_and_replay(
            archive,
            files,
            archive_sha256,
            version,
            release_policy,
            validator,
        )
        report = {
            "$schema": EVIDENCE_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "type": "openai-agent-plugin-submission-evidence",
            "execution_mode": "offline-release-candidate-contract",
            "plugin": metadata["plugin_manifest"],
            "candidate": {
                "source_commit": commit,
                "source_date_epoch": source_epoch,
                "archive": archive.name,
                "archive_sha256": archive_sha256,
                "release_manifest": release_manifest.name,
                "release_manifest_sha256": _sha256(release_manifest),
                "reproduction": "python3 scripts/build_openai_submission_evidence.py --output PATH",
                "installation": installation,
                "replay": replay,
            },
            "submission_materials": metadata,
            "checks": [
                {"id": "listing-fields", "status": "pass", "observations": ["listing, publisher, support, privacy, terms, starter prompts, release notes, and availability fields are represented"]},
                {"id": "candidate-package", "status": "pass", "observations": ["release manifest, SHA-256 inventory, SPDX metadata, and Codex archive verify offline"]},
                {"id": "candidate-installation", "status": "pass", "observations": ["the exact Codex archive installs into an isolated tree, matches byte for byte, and passes strict validation"]},
                {"id": "contract-replay", "status": "pass", "observations": ["five positive and three negative cases replay twice against the installed candidate and bound release policy with one stable digest"]},
            ],
            "cases": cases,
            "external_blockers": [
                "Publisher identity verification must be completed by the owner in the OpenAI submission portal.",
                "The portal draft, country availability, and external review result are not repository-verifiable.",
            ],
            "limitations": [
                "These are deterministic release-candidate contract checks, not a claim of OpenAI portal approval.",
                "The isolated offline archive installation is distinct from a host CLI marketplace lifecycle test.",
                "Skills-only remains the intended package shape; MCP and custom UI are outside this task.",
            ],
        }
    if output:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic OpenAI Agent Plugin submission evidence for Forge.")
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true", help="development-only: permit a dirty source tree")
    args = parser.parse_args(argv)
    try:
        report = build_submission_evidence(args.repo, args.output, allow_dirty=args.allow_dirty)
    except (OSError, SubmissionEvidenceError, ValueError, json.JSONDecodeError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        print(f"openai-submission-evidence: {exc}", file=sys.stderr)
        return 1
    positive = sum(item["polarity"] == "positive" for item in report["cases"])
    negative = sum(item["polarity"] == "negative" for item in report["cases"])
    print(f"Built OpenAI submission evidence for Forge {report['plugin']['version']}: {positive} positive, {negative} negative cases.")
    print(f"Candidate: {report['candidate']['archive']} sha256={report['candidate']['archive_sha256']}")
    print("External status: identity verification and portal draft remain owner action.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
