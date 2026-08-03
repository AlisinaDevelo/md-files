"""Tests for the canonical capability graph importer and drift gate."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/compile_capabilities.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_capability_compiler", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_canonical_graph_matches_all_sources():
    module = load_module()
    graph = json.loads((REPO / "data/capabilities.json").read_text(encoding="utf-8"))

    assert module._validate_graph(graph) == []
    assert graph == module.import_graph()
    assert len(graph["components"]) == 67
    assert {component["kind"] for component in graph["components"]} == {"agent", "skill", "command"}


def test_host_projection_contract_preserves_degradation_paths():
    module = load_module()
    graph = json.loads((REPO / "data/capabilities.json").read_text(encoding="utf-8"))
    by_key = {(item["kind"], item["id"]): item for item in graph["components"]}

    assert by_key[("skill", "orchestration")]["host_projections"]["codex"]["mode"] == "native"
    assert by_key[("agent", "architect")]["host_projections"]["codex"]["mode"] == "omitted"
    assert by_key[("agent", "architect")]["host_projections"]["agentskills"]["mode"] == "shim"
    assert module._validate_graph(graph) == []


def test_resource_inventory_includes_nested_skill_files():
    graph = json.loads((REPO / "data/capabilities.json").read_text(encoding="utf-8"))
    component = next(item for item in graph["components"] if item["id"] == "stacked-changes")

    assert "scripts/forge-stack.py" in component["resources"]
    assert "REFERENCE.md" in component["resources"]
    assert len(component["resources"]) >= 4


def test_resource_inventory_excludes_python_runtime_caches(tmp_path):
    module = load_module()
    root = tmp_path / "skill"
    root.mkdir()
    source = root / "SKILL.md"
    source.write_text("---\nname: fixture\ndescription: fixture\n---\n", encoding="utf-8")
    references = root / "references"
    references.mkdir()
    (references / "REFERENCE.md").write_text("reference", encoding="utf-8")
    cache = root / "__pycache__"
    cache.mkdir()
    (cache / "fixture.cpython-314.pyc").write_bytes(b"cache")
    (root / "stale.pyc").write_bytes(b"cache")

    assert module._resources("skill", source) == ["references/REFERENCE.md"]
