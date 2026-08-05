"""Tests for graph-derived release surfaces and metadata."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/render_capabilities.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_release_surface_renderer", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def graph():
    return json.loads((REPO / "data/capabilities.json").read_text(encoding="utf-8"))


def snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_release_surface_derives_metadata_and_install_inputs(tmp_path):
    module = load_module()
    report = module.render_release_surface(REPO, graph(), tmp_path)

    assert set(report["hosts"]) == {"claude", "codex", "agentskills"}
    assert (tmp_path / "claude/CATALOG.md").is_file()
    bundles = json.loads((tmp_path / "claude/data/bundles.json").read_text(encoding="utf-8"))
    workflows = json.loads((tmp_path / "claude/data/workflows.json").read_text(encoding="utf-8"))
    assert bundles["schema_version"] == 2
    assert workflows["capability_graph"]["schema_version"] == 2
    assert any(item["resolved_components"] for item in bundles["bundles"])
    assert any(item["resolved_steps"] for item in workflows["workflows"])
    assert (tmp_path / "claude/data/runtime-events.schema.json").is_file()
    assert (tmp_path / "codex/data/runtime-state.schema.json").is_file()
    assert (tmp_path / "claude/data/runtime-outbox.schema.json").is_file()
    assert (tmp_path / "codex/data/runtime-inbox.schema.json").is_file()
    assert (tmp_path / "claude/data/runtime-lease-events.schema.json").is_file()
    assert (tmp_path / "codex/data/runtime-checkpoints.schema.json").is_file()
    assert (tmp_path / "claude/data/runtime-restore.schema.json").is_file()
    assert (tmp_path / "codex/data/runtime-migrations.schema.json").is_file()
    assert (tmp_path / "claude/data/runtime-waits.schema.json").is_file()
    assert (tmp_path / "codex/plugins/forge/skills/orchestration/scripts/forge-mcp-tasks.py").is_file()
    assert (tmp_path / "claude/data/runtime-receipts.schema.json").is_file()
    assert (tmp_path / "codex/data/runtime-lineage.schema.json").is_file()
    assert (tmp_path / "claude/data/runtime-backend.schema.json").is_file()
    assert (tmp_path / "claude/data/runtime-backend-evidence.schema.json").is_file()
    assert (tmp_path / "codex/data/runtime-conformance.schema.json").is_file()
    assert (tmp_path / "claude/data/runtime-distributed.schema.json").is_file()
    assert (tmp_path / "claude/data/runtime-definitions.schema.json").is_file()
    assert (tmp_path / "codex/data/runtime-compatibility.schema.json").is_file()
    assert (tmp_path / "claude/plugins/forge/skills/observability/scripts/forge-lineage.py").is_file()
    assert (tmp_path / "codex/plugins/forge/skills/observability/scripts/forge-lineage.py").is_file()
    assert (tmp_path / "agentskills/zed/install.sh").stat().st_mode & 0o111
    manifest = json.loads((tmp_path / "codex/data/projection-manifest.json").read_text(encoding="utf-8"))
    assert manifest["hosts"]["codex"]["components"] == 25
    assert manifest["metadata"]["bundles"]["count"] == 6


def test_release_surface_is_byte_deterministic(tmp_path):
    module = load_module()
    first = tmp_path / "first"
    second = tmp_path / "second"

    module.render_release_surface(REPO, graph(), first)
    module.render_release_surface(REPO, graph(), second)

    assert snapshot(first) == snapshot(second)
