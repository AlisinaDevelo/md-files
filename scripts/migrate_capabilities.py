#!/usr/bin/env python3
"""Migrate a v1 capability graph to the current canonical v2 graph."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


class MigrationError(ValueError):
    """Raised when a graph cannot be migrated without losing source behavior."""


def _index(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    components = graph.get("components")
    if not isinstance(components, list):
        raise MigrationError("components must be an array")
    result: dict[str, dict[str, Any]] = {}
    for component in components:
        if not isinstance(component, dict) or not isinstance(component.get("kind"), str) or not isinstance(component.get("id"), str):
            raise MigrationError("every component needs a string kind and id")
        key = f"{component['kind']}:{component['id']}"
        if key in result:
            raise MigrationError(f"duplicate component: {key}")
        result[key] = component
    return result


def migrate_graph(legacy: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Validate and return the canonical v2 graph for an unchanged v1 source tree."""
    if legacy.get("schema_version") != 1:
        raise MigrationError("source schema_version must be 1")
    if current.get("schema_version") != 2:
        raise MigrationError("target schema_version must be 2")
    if legacy.get("project") != "forge" or current.get("project") != "forge":
        raise MigrationError("only the Forge project is supported")
    legacy_index = _index(legacy)
    current_index = _index(current)
    missing = sorted(set(current_index) - set(legacy_index))
    extra = sorted(set(legacy_index) - set(current_index))
    if missing:
        raise MigrationError("missing legacy components: " + ", ".join(missing))
    if extra:
        raise MigrationError("legacy components are not present in v2: " + ", ".join(extra))
    for key in sorted(current_index):
        old = legacy_index[key]
        new = current_index[key]
        for field in ("source", "body_sha256", "source_sha256", "resources", "risk", "host_projections"):
            if old.get(field) != new.get(field):
                raise MigrationError(f"{key} {field} changed; migration requires reviewed source parity")
    return json.loads(json.dumps(current, ensure_ascii=True))


def _load_compiler():
    path = Path(__file__).with_name("compile_capabilities.py")
    spec = importlib.util.spec_from_file_location("forge_capability_compiler", path)
    if spec is None or spec.loader is None:
        raise MigrationError(f"cannot load compiler: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MigrationError(f"{path} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="legacy v1 capability graph")
    parser.add_argument("--output", required=True, type=Path, help="destination for the migrated v2 graph")
    args = parser.parse_args(argv)
    try:
        migrated = migrate_graph(_load(args.input), _load_compiler().import_graph())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(migrated, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    except (OSError, MigrationError, TypeError) as exc:
        print(f"capability migration: {exc}", file=sys.stderr)
        return 1
    print(f"Migrated v1 capability graph to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
