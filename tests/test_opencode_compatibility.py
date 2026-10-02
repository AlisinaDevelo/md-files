"""Tests for the OpenCode Agent Skills projection and installer."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "scripts/install-opencode.sh"


def _run_installer(skills_dir: Path, config_dir: Path, *options: str):
    env = os.environ.copy()
    env["OPENCODE_SKILLS_DIR"] = str(skills_dir)
    env["OPENCODE_CONFIG_DIR"] = str(config_dir)
    return subprocess.run(
        ["bash", str(INSTALLER), *options],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_opencode_config_points_at_methodology_skills():
    config = json.loads((REPO / "opencode.json").read_text(encoding="utf-8"))

    assert config["$schema"] == "https://opencode.ai/config.json"
    assert isinstance(config["skills"], dict)
    assert config["skills"]["paths"] == ["./plugins/forge/skills"]


def test_opencode_v2_profile_uses_array_and_path_derived_skill_ids():
    config = json.loads((REPO / "opencode.v2.json").read_text(encoding="utf-8"))

    assert config["$schema"] == "https://opencode.ai/config.json"
    assert config["skills"] == ["./plugins/forge/skills"]

    for skill_file in sorted((REPO / "plugins/forge/skills").glob("*/SKILL.md")):
        assert f"\nname: {skill_file.parent.name}\n" in skill_file.read_text(
            encoding="utf-8"
        )


def test_opencode_skill_projection_has_expected_surfaces():
    methodology = sorted(
        path for path in (REPO / "plugins/forge/skills").iterdir() if path.is_dir()
    )
    agents = sorted((REPO / "zed/skills/agents").glob("*.md"))
    commands = sorted((REPO / "zed/skills/commands").glob("*.md"))

    assert methodology
    assert agents
    assert commands
    assert all((path / "SKILL.md").is_file() for path in methodology)

    for path in [*(path / "SKILL.md" for path in methodology), *agents, *commands]:
        content = path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "\nname: " in content
        assert "\ndescription: " in content

    doctor_command = (REPO / "zed/skills/commands/forge-cmd-doctor.md").read_text(
        encoding="utf-8"
    )
    assert "python3 ~/.agents/skills/doctor/scripts/forge-doctor.py" in doctor_command
    assert (
        "python3 plugins/forge/skills/doctor/scripts/forge-doctor.py"
        in doctor_command
    )
    assert "Forge repository root" in doctor_command
    assert "python3 scripts/forge-doctor.py" not in doctor_command


def test_opencode_installer_copy_projection(tmp_path):
    skills_dir = tmp_path / "skills"
    config_dir = tmp_path / "config"
    result = _run_installer(skills_dir, config_dir, "--copy")

    assert result.returncode == 0, result.stderr
    installed = sorted(skills_dir.glob("*/SKILL.md"))
    methodology = sorted(
        path.parent.name
        for path in (REPO / "plugins/forge/skills").glob("*/SKILL.md")
    )
    agents = sorted(path.stem for path in (REPO / "zed/skills/agents").glob("*.md"))
    commands = sorted(
        path.stem for path in (REPO / "zed/skills/commands").glob("*.md")
    )
    expected_ids = methodology + agents + commands
    expected = set(expected_ids)
    installed_ids = {path.parent.name for path in installed}

    assert expected
    assert len(expected_ids) == len(expected)
    assert installed_ids == expected
    assert len(installed) == len(expected_ids)
    assert f"Installed {len(expected_ids)} Forge skill surfaces" in result.stdout
    assert (skills_dir / "doctor/scripts/forge-doctor.py").is_file()
    for skill_file in installed:
        assert f"\nname: {skill_file.parent.name}\n" in skill_file.read_text(
            encoding="utf-8"
        )
    installed_doctor = (skills_dir / "forge-cmd-doctor/SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "~/.agents/skills/doctor/scripts/forge-doctor.py" in installed_doctor
    assert (config_dir / "AGENTS.md").read_text(encoding="utf-8") == (
        REPO / "AGENTS.md"
    ).read_text(encoding="utf-8")
    assert not any(path.is_symlink() for path in installed)


def test_opencode_installer_symlink_projection(tmp_path):
    skills_dir = tmp_path / "skills"
    config_dir = tmp_path / "config"
    result = _run_installer(skills_dir, config_dir, "--symlink")

    assert result.returncode == 0, result.stderr
    methodology_skill = skills_dir / "doctor/SKILL.md"
    command_skill = skills_dir / "forge-cmd-doctor/SKILL.md"
    instructions = config_dir / "AGENTS.md"
    assert methodology_skill.is_symlink()
    assert methodology_skill.resolve() == (
        REPO / "plugins/forge/skills/doctor/SKILL.md"
    )
    assert command_skill.is_symlink()
    assert command_skill.resolve() == (REPO / "zed/skills/commands/forge-cmd-doctor.md")
    assert instructions.is_symlink()
    assert instructions.resolve() == (REPO / "AGENTS.md")

    repeated = _run_installer(skills_dir, config_dir, "--symlink")
    assert repeated.returncode == 0, repeated.stderr


def test_opencode_installer_force_replaces_only_conflicting_file(tmp_path):
    skills_dir = tmp_path / "skills"
    config_dir = tmp_path / "config"
    target = skills_dir / "doctor/SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("user-owned content\n", encoding="utf-8")
    unrelated = skills_dir / "keep.txt"
    unrelated.write_text("keep this file\n", encoding="utf-8")
    result = _run_installer(skills_dir, config_dir, "--force")

    assert result.returncode == 0, result.stderr
    assert target.read_text(encoding="utf-8") == (
        REPO / "plugins/forge/skills/doctor/SKILL.md"
    ).read_text(encoding="utf-8")
    assert unrelated.read_text(encoding="utf-8") == "keep this file\n"


def test_opencode_installer_force_refuses_directory_conflicts(tmp_path):
    skills_dir = tmp_path / "skills"
    config_dir = tmp_path / "config"
    target = skills_dir / "doctor/SKILL.md"
    target.mkdir(parents=True)
    sentinel = target / "keep.txt"
    sentinel.write_text("user data\n", encoding="utf-8")
    result = _run_installer(skills_dir, config_dir, "--force")

    assert result.returncode != 0
    assert "refusing to replace directory" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "user data\n"


def test_opencode_installer_dry_run_does_not_write_or_replace(tmp_path):
    skills_dir = tmp_path / "skills"
    config_dir = tmp_path / "config"
    target = skills_dir / "doctor/SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("keep existing content\n", encoding="utf-8")
    result = _run_installer(skills_dir, config_dir, "--force", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "[dry-run] rm -f" in result.stdout
    assert "[dry-run] cp" in result.stdout
    assert target.read_text(encoding="utf-8") == "keep existing content\n"
    assert not (skills_dir / "forge-cmd-doctor/SKILL.md").exists()
    assert not (config_dir / "AGENTS.md").exists()


def test_opencode_installer_preserves_conflicting_instructions_without_force(tmp_path):
    skills_dir = tmp_path / "skills"
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    instructions = config_dir / "AGENTS.md"
    instructions.write_text("user instructions\n", encoding="utf-8")
    result = _run_installer(skills_dir, config_dir, "--copy")

    assert result.returncode != 0
    assert "use --force" in result.stderr
    assert instructions.read_text(encoding="utf-8") == "user instructions\n"
