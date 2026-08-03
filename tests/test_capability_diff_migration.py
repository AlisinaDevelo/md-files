"""Tests for semantic capability evidence and v1-to-v2 migration."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DIFF_SCRIPT = REPO / "scripts/diff_capabilities.py"
MIGRATION_SCRIPT = REPO / "scripts/migrate_capabilities.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def graph() -> dict:
    return json.loads((REPO / "data/capabilities.json").read_text(encoding="utf-8"))


def to_v1(value: dict) -> dict:
    legacy = copy.deepcopy(value)
    legacy["$schema"] = "https://github.com/AlisinaDevelo/md-files/schema/capabilities/v1"
    legacy["schema_version"] = 1
    legacy["source_contract"].pop("body")
    for component in legacy["components"]:
        for field in (
            "identity",
            "triggers",
            "instructions",
            "tools",
            "permissions",
            "inputs",
            "outputs",
            "scripts",
            "evals",
            "host_extensions",
        ):
            component.pop(field)
    return legacy


def test_semantic_diff_reports_safe_categories_and_digest_only_body_changes():
    module = load_module(DIFF_SCRIPT, "forge_capability_diff")
    before = graph()
    after = copy.deepcopy(before)
    orchestrate = next(item for item in after["components"] if item["id"] == "orchestrate")
    orchestrate["instructions"]["body"] += "\nsecret prompt text that must not enter evidence"
    orchestrate["body_sha256"] = "a" * 64
    orchestrate["permissions"]["effect"] = "read-only"
    orchestrate["permissions"]["approval"] = "none"
    removed = next(item for item in after["components"] if item["id"] == "stack")
    after["components"].remove(removed)
    renamed = copy.deepcopy(removed)
    renamed["id"] = "stack-renamed"
    renamed["identity"]["id"] = "stack-renamed"
    after["components"].append(renamed)
    diff = module.semantic_diff(before, after)
    encoded = json.dumps(diff, sort_keys=True)

    assert diff["summary"] == {"added": 0, "changed": 1, "removed": 0, "renamed": 1}
    assert diff["renamed"] == [{"from": "command:stack", "to": "command:stack-renamed"}]
    changed = next(item for item in diff["changed"] if item["id"] == "orchestrate")
    fields = {item["field"]: item for item in changed["changes"]}
    assert {"instructions", "permissions"}.issubset(fields)
    assert fields["instructions"]["before_sha256"] != fields["instructions"]["after_sha256"]
    assert "secret prompt text" not in encoded


def test_semantic_diff_rendering_is_deterministic():
    module = load_module(DIFF_SCRIPT, "forge_capability_diff_render")
    value = module.semantic_diff(graph(), graph())

    assert module.render(value, "json") == module.render(value, "json")
    markdown = module.render(value, "markdown")
    assert "Capability Semantic Diff" in markdown
    assert "No semantic changes." in markdown


def test_v1_graph_migrates_only_when_source_contract_is_unchanged():
    module = load_module(MIGRATION_SCRIPT, "forge_capability_migration")
    current = graph()

    assert module.migrate_graph(to_v1(current), current) == current

    changed = to_v1(current)
    changed["components"][0]["body_sha256"] = "0" * 64
    with pytest.raises(module.MigrationError, match="body_sha256"):
        module.migrate_graph(changed, current)


def test_migration_rejects_unsupported_schema_and_missing_components():
    module = load_module(MIGRATION_SCRIPT, "forge_capability_migration_errors")
    current = graph()
    unsupported = to_v1(current)
    unsupported["schema_version"] = 9
    with pytest.raises(module.MigrationError, match="schema_version"):
        module.migrate_graph(unsupported, current)

    missing = to_v1(current)
    missing["components"] = missing["components"][1:]
    with pytest.raises(module.MigrationError, match="missing"):
        module.migrate_graph(missing, current)
