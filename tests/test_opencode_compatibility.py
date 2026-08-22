"""Tests for the OpenCode Agent Skills projection and installer."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "scripts/install-opencode.sh"


def test_opencode_config_points_at_methodology_skills():
    config = json.loads((REPO / "opencode.json").read_text(encoding="utf-8"))

    assert config["$schema"] == "https://opencode.ai/config.json"
    assert config["skills"]["paths"] == ["./plugins/forge/skills"]


def test_opencode_skill_projection_has_expected_surfaces():
    methodology = sorted(
        path for path in (REPO / "plugins/forge/skills").iterdir() if path.is_dir()
    )
    agents = sorted((REPO / "zed/skills/agents").glob("*.md"))
    commands = sorted((REPO / "zed/skills/commands").glob("*.md"))

    assert len(methodology) == 25
    assert len(agents) == 20
    assert len(commands) == 22
    assert all((path / "SKILL.md").is_file() for path in methodology)

    for path in [*(path / "SKILL.md" for path in methodology), *agents, *commands]:
        content = path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "\nname: " in content
        assert "\ndescription: " in content


def test_opencode_installer_copy_projection(tmp_path):
    skills_dir = tmp_path / "skills"
    config_dir = tmp_path / "config"
    env = os.environ.copy()
    env["OPENCODE_SKILLS_DIR"] = str(skills_dir)
    env["OPENCODE_CONFIG_DIR"] = str(config_dir)

    result = subprocess.run(
        ["bash", str(INSTALLER), "--copy"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    installed = sorted(skills_dir.glob("*/SKILL.md"))
    assert len(installed) == 67
    assert "Installed 67 Forge skill surfaces" in result.stdout
    assert (config_dir / "AGENTS.md").read_text(encoding="utf-8") == (
        REPO / "AGENTS.md"
    ).read_text(encoding="utf-8")
    assert not any(path.is_symlink() for path in installed)
