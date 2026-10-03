"""Compatibility tests for the native OpenHands SDK AgentSkills loader."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import pytest

from scripts.verify_openhands_skills import VerificationError, verify_archive

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _require_optional_openhands_sdk():
    pytest.importorskip(
        "openhands.sdk",
        reason="OpenHands SDK is an optional compatibility dependency",
    )
    pytest.importorskip(
        "openhands.sdk.skills",
        reason="OpenHands SDK is an optional compatibility dependency",
    )


def _write_skill(
    archive_root: Path,
    name: str,
    content: str,
    resources: dict[str, dict[str, bytes]] | None = None,
) -> None:
    skill_dir = archive_root / "forge-agents/skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill for OpenHands loading.\n---\n\n{content}\n",
        encoding="utf-8",
    )
    for resource_type, files in (resources or {}).items():
        resource_dir = skill_dir / resource_type
        resource_dir.mkdir()
        for filename, body in files.items():
            (resource_dir / filename).write_bytes(body)
    _write_projection_manifest(archive_root)


def _write_projection_manifest(archive_root: Path) -> None:
    skill_files = list((archive_root / "forge-agents/skills").rglob("SKILL.md"))
    zed_skills_dir = archive_root / "forge-agents/zed/skills"
    zed_skills_dir.mkdir(parents=True, exist_ok=True)
    shim_files = list(zed_skills_dir.rglob("*.md"))
    manifest_path = archive_root / "forge-agents/data/projection-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {"hosts": {"agentskills": {"components": len(skill_files) + len(shim_files)}}}
        ),
        encoding="utf-8",
    )


def test_openhands_registers_content_and_reads_native_resource_paths(tmp_path):
    archive_root = tmp_path / "extracted"
    _write_skill(
        archive_root,
        "native-check",
        "A deterministic SDK-loaded body.",
        {
            "scripts": {"check.py": b"print('ok')\n"},
            "references": {"guide.md": b"Reference content.\n"},
            "assets": {"marker.txt": b"asset bytes\n"},
        },
    )

    report = verify_archive(archive_root)

    assert report["status"] == "verified"
    assert report["skill_count"] == 1
    assert report["registered_skill_names"] == ["native-check"]
    assert report["skill_content_characters"]["native-check"] == len(
        "A deterministic SDK-loaded body."
    )
    assert report["resource_counts"] == {"scripts": 1, "references": 1, "assets": 1}
    assert report["resource_file_count"] == 3
    assert report["resource_bytes_read"] > 0
    assert report["public_skill_loading"] is False
    assert report["llm_calls"] == 0


def test_openhands_rejects_empty_skill_content(tmp_path):
    archive_root = tmp_path / "extracted"
    _write_skill(archive_root, "empty-content", "")

    with pytest.raises(VerificationError, match="empty skill content"):
        verify_archive(archive_root)


def test_openhands_fails_closed_when_sdk_skips_a_packaged_skill(tmp_path):
    archive_root = tmp_path / "extracted"
    skill_dir = archive_root / "forge-agents/skills/native-check"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: different-name\ndescription: Invalid directory/name pairing.\n---\n\nBody.\n",
        encoding="utf-8",
    )
    _write_projection_manifest(archive_root)

    with pytest.raises(VerificationError, match="SDK did not register every packaged SKILL.md"):
        verify_archive(archive_root)


def test_openhands_rejects_an_archive_without_the_packaged_skill_root(tmp_path):
    archive_root = tmp_path / "extracted"
    archive_root.mkdir()

    with pytest.raises(VerificationError, match="must contain forge-agents/skills"):
        verify_archive(archive_root)


def test_openhands_loads_every_skill_from_the_built_release_archive():
    with tempfile.TemporaryDirectory(prefix="forge-openhands-test-") as temporary:
        work = Path(temporary)
        release_dir = work / "release"
        extracted_dir = work / "extracted"
        negative_dir = work / "negative"
        result = subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts/build_release.py"),
                "--output",
                str(release_dir),
                "--allow-dirty",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

        archives = list(release_dir.glob("forge-*-agents.tar.gz"))
        assert len(archives) == 1
        extracted_dir.mkdir()
        with tarfile.open(archives[0], "r:gz") as archive:
            archive.extractall(extracted_dir, filter="data")

        archived_skills = sorted(
            (extracted_dir / "forge-agents/skills").rglob("SKILL.md")
        )
        assert archived_skills
        report = verify_archive(extracted_dir)
        assert report["status"] == "verified"
        assert report["skill_count"] == len(archived_skills)
        assert report["skill_count"] == len(report["registered_skill_names"])
        assert len(report["skill_content_characters"]) == report["skill_count"]

        shutil.copytree(extracted_dir, negative_dir)
        skill_file = sorted(
            (negative_dir / "forge-agents/skills").rglob("SKILL.md")
        )[0]
        skill_file.unlink()
        with pytest.raises(
            VerificationError,
            match=(
                "extracted AgentSkills inventory differs|"
                "SDK did not register every packaged SKILL.md|no SKILL.md files"
            ),
        ):
            verify_archive(negative_dir)
