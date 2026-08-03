"""Tests for deterministic host projection rendering and adapter contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/render_capabilities.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_capability_renderer", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def graph():
    return json.loads((REPO / "data/capabilities.json").read_text(encoding="utf-8"))


def test_builtin_renderers_cover_native_and_degraded_surfaces(tmp_path):
    module = load_module()
    report = module.render_all(REPO, graph(), tmp_path)

    assert set(report) == {"claude", "codex", "agentskills"}
    assert (tmp_path / "claude/plugins/forge/skills/orchestration/SKILL.md").is_file()
    assert not (tmp_path / "codex/plugins/forge/agents/architect.md").exists()
    assert (tmp_path / "codex/plugins/forge/assets/icon.png").is_file()
    shim = tmp_path / "agentskills/zed/skills/agents/forge-architect.md"
    assert shim.is_file()
    assert "name: forge-architect" in shim.read_text(encoding="utf-8")
    assert "You are a software architect." in shim.read_text(encoding="utf-8")
    assert (tmp_path / "agentskills/plugins/forge/skills/stacked-changes/REFERENCE.md").is_file()
    native = (tmp_path / "claude/plugins/forge/skills/orchestration/SKILL.md").read_text(encoding="utf-8")
    source = (REPO / "plugins/forge/skills/orchestration/SKILL.md").read_text(encoding="utf-8")
    assert native.split("---", 2)[-1] == source.split("---", 2)[-1]


def test_command_shim_removes_host_only_argument_and_shell_injection(tmp_path):
    module = load_module()
    module.render_host(REPO, graph(), tmp_path, "agentskills")

    shim = tmp_path / "agentskills/zed/skills/commands/forge-cmd-orchestrate.md"
    text = shim.read_text(encoding="utf-8")

    assert "$ARGUMENTS" not in text
    assert "!`git status" not in text
    assert "disable-model-invocation: true" in text


def test_third_party_adapter_renders_without_core_changes(tmp_path):
    module = load_module()
    adapter = {
        "contract_version": 1,
        "id": "example-host",
        "display_name": "Example Host",
        "native_kinds": ["skill"],
        "shim_kinds": ["agent", "command"],
        "extensions": ["settings"],
        "projection": {
            "native_root": "skills",
            "shim_root": "skills",
            "agent_prefix": "forge-",
            "command_prefix": "forge-cmd-",
        },
    }

    report = module.render_adapter(REPO, graph(), tmp_path, adapter)

    assert report["adapter"] == "example-host"
    assert (tmp_path / "example-host/skills/orchestration/SKILL.md").is_file()
    assert (tmp_path / "example-host/skills/forge-architect/SKILL.md").is_file()
    assert (tmp_path / "example-host/skills/forge-cmd-orchestrate/SKILL.md").is_file()


def test_adapter_rejects_unsafe_or_overlapping_contracts(tmp_path):
    module = load_module()
    adapter = {
        "contract_version": 1,
        "id": "example-host",
        "display_name": "Example Host",
        "native_kinds": ["skill"],
        "shim_kinds": ["agent", "command"],
        "extensions": [],
        "projection": {
            "native_root": "../skills",
            "shim_root": "skills",
            "agent_prefix": "forge-",
            "command_prefix": "forge-cmd-",
        },
    }

    with pytest.raises(module.RenderError, match="unsafe path"):
        module.render_adapter(REPO, graph(), tmp_path, adapter)

    adapter["projection"]["native_root"] = "skills"
    adapter["shim_kinds"] = ["skill"]
    with pytest.raises(module.RenderError, match="disjoint"):
        module.render_adapter(REPO, graph(), tmp_path, adapter)
