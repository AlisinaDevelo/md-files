#!/usr/bin/env python3
"""Produce prompt-safe semantic evidence for two capability graphs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FIELD_ORDER = (
    "identity",
    "source",
    "frontmatter",
    "triggers",
    "instructions",
    "tools",
    "permissions",
    "inputs",
    "outputs",
    "resources",
    "scripts",
    "evals",
    "risk",
    "host_projections",
    "host_extensions",
    "source_digest",
)


class DiffError(ValueError):
    """Raised when a graph cannot produce semantic evidence."""


def _key(component: dict[str, Any]) -> str:
    kind = component.get("kind")
    component_id = component.get("id")
    if not isinstance(kind, str) or not isinstance(component_id, str):
        raise DiffError("every component needs a string kind and id")
    return f"{kind}:{component_id}"


def _index(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    components = graph.get("components")
    if not isinstance(components, list):
        raise DiffError("capability graph components must be an array")
    result: dict[str, dict[str, Any]] = {}
    for component in components:
        if not isinstance(component, dict):
            raise DiffError("capability graph components must be objects")
        key = _key(component)
        if key in result:
            raise DiffError(f"duplicate component: {key}")
        result[key] = component
    return result


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_summary(field: str, value: Any) -> Any:
    if field == "instructions":
        return {"format": value.get("format"), "body_sha256": value.get("body_sha256")} if isinstance(value, dict) else None
    if field == "frontmatter":
        return {"keys": sorted(value), "sha256": _digest(value)} if isinstance(value, dict) else None
    if field == "triggers" and isinstance(value, dict):
        return {"kind": value.get("kind"), "description_sha256": _digest(value.get("description", ""))}
    return value


def _change(field: str, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    if field == "instructions":
        return {
            "field": field,
            "before_sha256": before.get("body_sha256"),
            "after_sha256": after.get("body_sha256"),
        }
    if field == "source_digest":
        return {"field": field, "before_sha256": before.get("source_sha256"), "after_sha256": after.get("source_sha256")}
    return {
        "field": field,
        "before": _safe_summary(field, before.get(field)),
        "after": _safe_summary(field, after.get(field)),
    }


def _component_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for field in FIELD_ORDER:
        if field == "instructions":
            changed = before.get("body_sha256") != after.get("body_sha256") or before.get("instructions", {}).get("format") != after.get("instructions", {}).get("format")
        elif field == "source_digest":
            changed = before.get("source_sha256") != after.get("source_sha256")
        else:
            changed = before.get(field) != after.get(field)
        if changed:
            changes.append(_change(field, before, after))
    return changes


def semantic_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic, prompt-safe semantic changes between two graphs."""
    before_index = _index(before)
    after_index = _index(after)
    removed_keys = sorted(set(before_index) - set(after_index))
    added_keys = sorted(set(after_index) - set(before_index))
    renamed: list[dict[str, str]] = []
    remaining_removed = list(removed_keys)
    remaining_added = list(added_keys)
    for removed in removed_keys:
        candidates = [
            added
            for added in remaining_added
            if added.split(":", 1)[0] == removed.split(":", 1)[0]
            and before_index[removed].get("source_sha256") == after_index[added].get("source_sha256")
        ]
        if len(candidates) == 1:
            added = candidates[0]
            renamed.append({"from": removed, "to": added})
            remaining_removed.remove(removed)
            remaining_added.remove(added)
    changed: list[dict[str, Any]] = []
    for key in sorted(set(before_index) & set(after_index)):
        changes = _component_changes(before_index[key], after_index[key])
        if changes:
            changed.append({"kind": after_index[key]["kind"], "id": after_index[key]["id"], "changes": changes})
    return {
        "schema_version": 1,
        "before": {"schema_version": before.get("schema_version"), "version": before.get("version")},
        "after": {"schema_version": after.get("schema_version"), "version": after.get("version")},
        "summary": {
            "added": len(remaining_added),
            "changed": len(changed),
            "removed": len(remaining_removed),
            "renamed": len(renamed),
        },
        "added": [{"kind": after_index[key]["kind"], "id": after_index[key]["id"]} for key in remaining_added],
        "removed": [{"kind": before_index[key]["kind"], "id": before_index[key]["id"]} for key in remaining_removed],
        "renamed": renamed,
        "changed": changed,
    }


def render(value: dict[str, Any], format_name: str) -> str:
    if format_name == "json":
        return json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n"
    if format_name != "markdown":
        raise DiffError(f"unsupported output format: {format_name}")
    summary = value["summary"]
    lines = [
        "# Capability Semantic Diff",
        "",
        f"Before schema {value['before']['schema_version']} ({value['before']['version']})",
        f"After schema {value['after']['schema_version']} ({value['after']['version']})",
        "",
        "## Summary",
        "",
        f"- Added: {summary['added']}",
        f"- Changed: {summary['changed']}",
        f"- Removed: {summary['removed']}",
        f"- Renamed: {summary['renamed']}",
    ]
    for title, key in (("Added", "added"), ("Removed", "removed"), ("Renamed", "renamed"), ("Changed", "changed")):
        entries = value[key]
        if not entries:
            continue
        lines.extend(("", f"## {title}", ""))
        for entry in entries:
            if key == "renamed":
                lines.append(f"- `{entry['from']}` -> `{entry['to']}`")
            elif key == "changed":
                fields = ", ".join(change["field"] for change in entry["changes"])
                lines.append(f"- `{entry['kind']}:{entry['id']}`: {fields}")
            else:
                lines.append(f"- `{entry['kind']}:{entry['id']}`")
    if all(not value[key] for key in ("added", "removed", "renamed", "changed")):
        lines.extend(("", "No semantic changes."))
    return "\n".join(lines) + "\n"


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiffError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DiffError(f"{path} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", type=Path, default=REPO / "data/capabilities.json")
    parser.add_argument("--format", choices=("json", "markdown"), default="json", dest="format_name")
    args = parser.parse_args(argv)
    try:
        print(render(semantic_diff(_load(args.before), _load(args.after)), args.format_name), end="")
    except (OSError, DiffError, TypeError) as exc:
        print(f"capability diff: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
