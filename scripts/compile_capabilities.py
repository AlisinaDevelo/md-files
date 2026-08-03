#!/usr/bin/env python3
"""Import and validate Forge's canonical capability graph.

The graph records the reviewed Markdown source for every agent, skill, and command,
its semantic frontmatter, body/resource digests, and host projections. Markdown remains
the instruction source; this file prevents host adapters from drifting away from it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "forge"
IR_PATH = REPO / "data/capabilities.json"
VERSION_PATH = PLUGIN / ".claude-plugin/plugin.json"
COMPONENT_SPECS = (
    ("agent", PLUGIN / "agents", "*.md"),
    ("skill", PLUGIN / "skills", "SKILL.md"),
    ("command", PLUGIN / "commands", "*.md"),
)
COMPONENT_KINDS = {kind for kind, _, _ in COMPONENT_SPECS}
COMPONENT_ORDER = {kind: index for index, (kind, _, _) in enumerate(COMPONENT_SPECS)}
HOSTS = {
    "claude": {
        "display_name": "Claude Code",
        "manifest": "plugins/forge/.claude-plugin/plugin.json",
        "native_kinds": ["agent", "skill", "command"],
        "extensions": ["hooks", "output-styles"],
    },
    "codex": {
        "display_name": "OpenAI Codex",
        "manifest": "plugins/forge/.codex-plugin/plugin.json",
        "native_kinds": ["skill"],
        "extensions": [],
    },
    "agentskills": {
        "display_name": "Agent Skills reference format",
        "manifest": ".agents/plugins/marketplace.json",
        "native_kinds": ["skill"],
        "extensions": ["zed/skills/agents", "zed/skills/commands"],
    },
}
SHIM_PATHS = {
    "agent": "zed/skills/agents/forge-{id}.md",
    "command": "zed/skills/commands/forge-cmd-{id}.md",
}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip()
    body = text[end + 4 :]
    values: dict[str, str] = {}
    key: str | None = None
    for line in block.splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if match and not line.startswith(" "):
            key = match.group(1)
            value = match.group(2).strip()
            values[key] = "" if value in {">-", ">", "|", "|-"} else value.strip('"')
        elif key and line.strip():
            values[key] = (values[key] + " " + line.strip()).strip()
    return values, body


def _relative(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _version() -> str:
    data = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("Claude plugin manifest has no version")
    return version


def _component_files() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for kind, root, pattern in COMPONENT_SPECS:
        for path in sorted(root.glob(f"**/{pattern}")):
            if path.is_file():
                found.append((kind, path))
    return found


def _resources(kind: str, source: Path) -> list[str]:
    if kind != "skill":
        return []
    root = source.parent
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "SKILL.md"
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    )


def _projection(kind: str, component_id: str, source: str) -> dict[str, dict[str, str]]:
    projections: dict[str, dict[str, str]] = {}
    if kind in {"agent", "skill", "command"}:
        projections["claude"] = {"mode": "native", "kind": kind, "path": source}
    if kind == "skill":
        projections["codex"] = {"mode": "native", "kind": kind, "path": source}
        projections["agentskills"] = {"mode": "native", "kind": kind, "path": source}
    else:
        projections["agentskills"] = {
            "mode": "shim",
            "kind": "skill",
            "path": SHIM_PATHS[kind].format(id=component_id),
        }
        projections["codex"] = {"mode": "omitted", "kind": kind, "path": ""}
    return projections


def _risk(kind: str, frontmatter: dict[str, str]) -> str:
    tools = frontmatter.get("tools", "") + " " + frontmatter.get("allowed-tools", "")
    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "").lower()
    if "security" in name or "security" in description or "threat" in name:
        return "security-sensitive"
    if any(token in tools for token in ("Write", "Edit", "Bash(gh", "Bash(git", "Bash")):
        return "critical" if any(token in tools for token in ("Write", "Edit", "gh issue", "git")) else "safe"
    if kind in {"agent", "skill"} and tools:
        return "safe"
    return "none"


def _component(kind: str, source: Path) -> dict[str, Any]:
    text = source.read_text(encoding="utf-8")
    frontmatter, body = _parse_frontmatter(text)
    component_id = source.parent.name if kind == "skill" else source.stem
    source_path = _relative(source)
    return {
        "id": component_id,
        "kind": kind,
        "source": source_path,
        "frontmatter": dict(sorted(frontmatter.items())),
        "body_sha256": _sha256(body.encode("utf-8")),
        "source_sha256": _sha256(text.encode("utf-8")),
        "resources": _resources(kind, source),
        "risk": _risk(kind, frontmatter),
        "host_projections": _projection(kind, component_id, source_path),
    }


def import_graph() -> dict[str, Any]:
    components = [_component(kind, source) for kind, source in _component_files()]
    components.sort(key=lambda item: (COMPONENT_ORDER[item["kind"]], item["id"]))
    return {
        "$schema": "https://github.com/AlisinaDevelo/md-files/schema/capabilities/v1",
        "schema_version": 1,
        "project": "forge",
        "version": _version(),
        "source_contract": {
            "root": "plugins/forge",
            "encoding": "utf-8",
            "frontmatter": "simple-folded-yaml",
            "body_digest": "sha256",
            "source_digest": "sha256",
        },
        "hosts": HOSTS,
        "components": components,
        "generated_projections": ["CATALOG.md", "data/catalog.json"],
    }


def _canonical(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True) + "\n"


def _validate_component(component: Any, errors: list[str], index: int) -> None:
    label = f"components[{index}]"
    if not isinstance(component, dict):
        errors.append(f"{label} must be an object")
        return
    component_id = component.get("id")
    kind = component.get("kind")
    source = component.get("source")
    if not isinstance(component_id, str) or not ID_RE.fullmatch(component_id):
        errors.append(f"{label}.id must be a lowercase kebab-case identifier")
    if kind not in COMPONENT_KINDS:
        errors.append(f"{label}.kind must be one of {sorted(COMPONENT_KINDS)}")
    if not isinstance(source, str) or not source.startswith("plugins/forge/") or ".." in Path(source).parts:
        errors.append(f"{label}.source must be a safe Forge-relative path")
    for field in ("body_sha256", "source_sha256"):
        if not isinstance(component.get(field), str) or not SHA256_RE.fullmatch(component[field]):
            errors.append(f"{label}.{field} must be a lowercase SHA-256 digest")
    if not isinstance(component.get("frontmatter"), dict):
        errors.append(f"{label}.frontmatter must be an object")
    if not isinstance(component.get("resources"), list) or not all(isinstance(item, str) for item in component["resources"]):
        errors.append(f"{label}.resources must be a string array")
    if component.get("risk") not in {"none", "safe", "critical", "security-sensitive"}:
        errors.append(f"{label}.risk is unsupported")
    projections = component.get("host_projections")
    if not isinstance(projections, dict) or set(projections) != set(HOSTS):
        errors.append(f"{label}.host_projections must cover {sorted(HOSTS)}")
    elif kind in COMPONENT_KINDS:
        expected = _projection(kind, component_id, source)
        if projections != expected:
            errors.append(f"{label}.host_projections do not match the host contract")


def _validate_graph(graph: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(graph, dict):
        return ["capability graph must be a JSON object"]
    if graph.get("schema_version") != 1 or graph.get("project") != "forge":
        errors.append("capability graph schema_version/project is unsupported")
    if graph.get("version") != _version():
        errors.append(f"capability graph version is {graph.get('version')}, expected {_version()}")
    if graph.get("source_contract") != import_graph()["source_contract"]:
        errors.append("capability graph source_contract is out of date")
    if graph.get("hosts") != HOSTS:
        errors.append("capability graph hosts are out of date")
    components = graph.get("components")
    if not isinstance(components, list):
        return [*errors, "capability graph components must be an array"]
    ids: set[tuple[str, str]] = set()
    for index, component in enumerate(components):
        _validate_component(component, errors, index)
        if isinstance(component, dict):
            ids.add((str(component.get("kind")), str(component.get("id"))))
    expected = import_graph()["components"]
    expected_ids = {(item["kind"], item["id"]) for item in expected}
    if ids != expected_ids:
        errors.append("capability graph component set does not match Forge sources")
        return errors
    actual_by_id = {(item["kind"], item["id"]): item for item in components if isinstance(item, dict)}
    for item in expected:
        key = (item["kind"], item["id"])
        if actual_by_id[key] != item:
            errors.append(f"capability graph drift for {item['kind']}:{item['id']}")
    if graph.get("generated_projections") != ["CATALOG.md", "data/catalog.json"]:
        errors.append("capability graph generated projections are out of date")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import or validate Forge's canonical capability graph.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="import current Forge sources into data/capabilities.json")
    mode.add_argument("--check", action="store_true", help="fail when the graph or host projections drift")
    args = parser.parse_args(argv)
    try:
        if args.write:
            graph = import_graph()
            IR_PATH.write_text(_canonical(graph), encoding="utf-8")
            print(f"Imported {len(graph['components'])} Forge capabilities into {IR_PATH.relative_to(REPO)}.")
            return 0
        if not IR_PATH.is_file():
            print(f"missing {IR_PATH.relative_to(REPO)}", file=sys.stderr)
            return 1
        graph = json.loads(IR_PATH.read_text(encoding="utf-8"))
        errors = _validate_graph(graph)
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(f"capability compiler: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("Capability graph validation failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Capability graph is current for {len(graph['components'])} Forge capabilities.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
