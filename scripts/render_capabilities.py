#!/usr/bin/env python3
"""Render the canonical capability graph into deterministic host projections."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
HOST_NAMES = ("claude", "codex", "agentskills")
COMPONENT_KINDS = {"agent", "skill", "command"}
HOST_ASSETS = {"claude": ["assets"], "codex": ["assets"], "agentskills": []}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SIMPLE_YAML = re.compile(r"^[A-Za-z0-9_./<>\[\]-]+(?: [A-Za-z0-9_./<>\[\]-]+)*$")


class RenderError(ValueError):
    """Raised when a graph or adapter cannot be rendered safely."""


def _load_compiler():
    path = Path(__file__).with_name("compile_capabilities.py")
    spec = importlib.util.spec_from_file_location("forge_capability_compiler", path)
    if spec is None or spec.loader is None:
        raise RenderError(f"cannot load capability compiler: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_graph(graph: dict[str, Any]) -> None:
    errors = _load_compiler()._validate_graph(graph)
    if errors:
        raise RenderError("capability graph is not current: " + "; ".join(errors))


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or Path(value).is_absolute():
        raise RenderError(f"{label} must be a non-empty relative path")
    parts = Path(value).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise RenderError(f"{label} contains an unsafe path segment")
    return Path(value).as_posix()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy(source: Path, target: Path) -> None:
    if not source.is_file():
        raise RenderError(f"render source is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    shutil.copymode(source, target)


def _yaml_value(value: Any) -> str:
    text = str(value)
    if text in {"true", "false", "null"}:
        return text
    if SIMPLE_YAML.fullmatch(text) and text not in {"yes", "no", "on", "off"}:
        return text
    return json.dumps(text, ensure_ascii=False)


def _frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key in sorted(fields):
        if not isinstance(key, str) or not key:
            raise RenderError("frontmatter keys must be non-empty strings")
        lines.append(f"{key}: {_yaml_value(fields[key])}")
    lines.append("---")
    return "\n".join(lines)


def _body(component: dict[str, Any], shim: bool) -> str:
    body = component["instructions"]["body"]
    if not shim:
        return body
    lines = [line for line in body.splitlines(keepends=True) if not re.search(r"!`[^`]+`", line)]
    return "".join(lines).replace("$ARGUMENTS", "the goal supplied by the user")


def _component_fields(component: dict[str, Any], shim_kind: str | None = None) -> dict[str, str]:
    source = component["frontmatter"]
    if shim_kind is None:
        return dict(source)
    name = f"forge-{component['id']}"
    if shim_kind == "command":
        name = f"forge-cmd-{component['id']}"
    fields = {
        "description": source.get("description", component["identity"]["name"]),
        "name": name,
    }
    if shim_kind == "command":
        fields["disable-model-invocation"] = "true"
    return fields


def _render_component(component: dict[str, Any], target: Path, shim_kind: str | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    _write(target, _frontmatter(_component_fields(component, shim_kind)) + _body(component, shim_kind is not None))


def _copy_resources(repo: Path, component: dict[str, Any], target: Path) -> int:
    source_root = repo / Path(component["source"]).parent
    count = 0
    for resource in component["resources"]:
        relative = _safe_relative(resource, f"resource for {component['id']}")
        _copy(source_root / relative, target.parent / relative)
        count += 1
    return count


def _native_target(root: Path, component: dict[str, Any], projection: dict[str, str]) -> Path:
    return root / _safe_relative(projection["path"], f"projection for {component['id']}")


def _copy_manifest(repo: Path, root: Path, manifest: str) -> int:
    relative = _safe_relative(manifest, "host manifest")
    source = repo / relative
    if not source.is_file():
        raise RenderError(f"host manifest is missing: {source}")
    _copy(source, root / relative)
    return 1


def _copy_extensions(repo: Path, root: Path, host: str, extensions: list[str]) -> int:
    if host == "agentskills":
        return 0
    count = 0
    for extension in [*extensions, *HOST_ASSETS[host]]:
        relative = _safe_relative(extension, f"{host} extension")
        source = repo / "plugins" / "forge" / relative
        if not source.exists():
            raise RenderError(f"host extension is missing: {source}")
        destination = root / "plugins" / "forge" / relative
        if source.is_file():
            _copy(source, destination)
            count += 1
            continue
        for path in sorted(source.rglob("*")):
            if path.is_file():
                _copy(path, destination / path.relative_to(source))
                count += 1
    return count


def _load_json(repo: Path, relative: str) -> dict[str, Any]:
    path = repo / relative
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderError(f"cannot read {relative}: {exc}") from exc
    if not isinstance(value, dict):
        raise RenderError(f"{relative} must contain a JSON object")
    return value


def _reference_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    references: dict[str, dict[str, Any]] = {}
    for component in graph["components"]:
        kind = component["kind"]
        component_id = component["id"]
        reference = f"/{component_id}" if kind == "command" else component_id
        if reference in references:
            raise RenderError(f"ambiguous capability reference: {reference}")
        references[reference] = component
    return references


def _resolve_references(value: str, references: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    slash_names = re.findall(r"/([a-z0-9][a-z0-9-]*)", value)
    if slash_names:
        for name in slash_names:
            reference = f"/{name}"
            if reference not in references:
                raise RenderError(f"metadata references unknown capability: {reference}")
            matches.append(references[reference])
        return matches
    if value in references:
        return [references[value]]
    return []


def _resolved_metadata(graph: dict[str, Any], repo: Path) -> dict[str, dict[str, Any]]:
    references = _reference_map(graph)
    output: dict[str, dict[str, Any]] = {}
    for filename, collection_key, reference_key in (
        ("data/bundles.json", "bundles", "components"),
        ("data/workflows.json", "workflows", "steps"),
    ):
        source = _load_json(repo, filename)
        entries = source.get(collection_key)
        if not isinstance(entries, list):
            raise RenderError(f"{filename} {collection_key} must be an array")
        seen: set[str] = set()
        rendered: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                raise RenderError(f"{filename} contains an invalid {collection_key[:-1]} entry")
            if entry["id"] in seen:
                raise RenderError(f"{filename} contains duplicate id {entry['id']}")
            seen.add(entry["id"])
            references_for_entry = entry.get(reference_key)
            if not isinstance(references_for_entry, list) or not all(isinstance(item, str) for item in references_for_entry):
                raise RenderError(f"{filename} {entry['id']} {reference_key} must be a string array")
            resolved: list[dict[str, Any]] = []
            for reference in references_for_entry:
                for component in _resolve_references(reference, references):
                    resolved.append(
                        {
                            "id": component["id"],
                            "kind": component["kind"],
                            "source": component["source"],
                            "host_projections": component["host_projections"],
                        }
                    )
            rendered.append({**entry, "resolved_components" if reference_key == "components" else "resolved_steps": resolved})
        output[collection_key] = {
            "schema_version": 2,
            "source_version": source.get("version"),
            "capability_graph": {"schema_version": graph["schema_version"], "version": graph["version"]},
            collection_key: rendered,
        }
    return output


def _catalog(repo: Path) -> tuple[str, str]:
    path = repo / "scripts" / "generate_catalog.py"
    spec = importlib.util.spec_from_file_location("forge_catalog_generator", path)
    if spec is None or spec.loader is None:
        raise RenderError(f"cannot load catalog generator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO = repo
    module.PLUGIN = repo / "plugins" / "forge"
    module.CAPABILITIES = repo / "data" / "capabilities.json"
    return module.render_catalog(module.component_rows())


def _copy_zed_surface(repo: Path, root: Path) -> int:
    count = 0
    for relative in ("zed/AGENTS.md", "zed/README.md", "zed/install.sh", "zed/settings/profiles.json"):
        _copy(repo / relative, root / relative)
        count += 1
    return count


def render_release_surface(repo: Path, graph: dict[str, Any], output: Path) -> dict[str, Any]:
    """Render hosts plus release metadata and install inputs from one graph."""
    _validate_graph(graph)
    reports = render_all(repo, graph, output)
    resolved_metadata = _resolved_metadata(graph, repo)
    catalog_markdown, catalog_json = _catalog(repo)
    graph_json = json.dumps(graph, indent=2, ensure_ascii=True) + "\n"
    metadata_files = {
        "CATALOG.md": catalog_markdown,
        "data/catalog.json": catalog_json,
        "data/bundles.json": json.dumps(resolved_metadata["bundles"], indent=2, ensure_ascii=True) + "\n",
        "data/workflows.json": json.dumps(resolved_metadata["workflows"], indent=2, ensure_ascii=True) + "\n",
        "data/capabilities.json": graph_json,
    }
    metadata_sources = (
        "data/capabilities.schema.json",
        "data/host-adapter.schema.json",
        "data/runtime-events.schema.json",
        "data/runtime-state.schema.json",
        "data/runtime-outbox.schema.json",
        "data/runtime-inbox.schema.json",
        "data/runtime-lease-events.schema.json",
        "data/runtime-checkpoints.schema.json",
        "data/runtime-restore.schema.json",
        "data/runtime-migrations.schema.json",
        "data/runtime-waits.schema.json",
        "data/runtime-receipts.schema.json",
        "data/runtime-lineage.schema.json",
        "data/runtime-provenance.schema.json",
        "data/runtime-backend.schema.json",
        "data/runtime-backend-evidence.schema.json",
        "data/runtime-conformance.schema.json",
        "data/runtime-distributed.schema.json",
        "data/runtime-chaos-schedule.schema.json",
        "data/runtime-chaos-result.schema.json",
        "data/runtime-chaos-corpus.schema.json",
        "data/runtime-definitions.schema.json",
        "data/runtime-compatibility.schema.json",
        "data/runtime-routing-policy.schema.json",
        "data/runtime-routing-decision.schema.json",
        "data/runtime-routing-replay.schema.json",
        "data/runtime-routing-rollout.schema.json",
        "data/runtime-gh-aw.schema.json",
        "data/runtime-gh-aw-episode.schema.json",
        "data/runtime-gh-aw-admission.schema.json",
        "data/runtime-gh-aw-provider-request.schema.json",
        "data/gh-aw-workflows.json",
        "policies/gh-aw.json",
    )
    common_manifest = {
        "schema_version": 1,
        "project": "forge",
        "graph": {"schema_version": graph["schema_version"], "version": graph["version"]},
        "hosts": {
            host: {
                "components": reports[host]["components"],
                "files": reports[host]["files"] + len(metadata_files) + len(metadata_sources) + 1 + (4 if host == "agentskills" else 0),
            }
            for host in HOST_NAMES
        },
        "metadata": {key: {"source_version": value["source_version"], "count": len(value[key])} for key, value in resolved_metadata.items()},
    }
    for host in HOST_NAMES:
        root = output / host
        for relative, content in metadata_files.items():
            _write(root / relative, content)
        for relative in metadata_sources:
            _copy(repo / relative, root / relative)
        _copy(repo / "LICENSE", root / "LICENSE")
        if host == "agentskills":
            _copy_zed_surface(repo, root)
        _write(root / "data/projection-manifest.json", json.dumps(common_manifest, indent=2, ensure_ascii=True) + "\n")
        reports[host]["files"] = common_manifest["hosts"][host]["files"] + 1
    return {
        "schema_version": 1,
        "graph": {"schema_version": graph["schema_version"], "version": graph["version"]},
        "hosts": reports,
        "metadata": common_manifest["metadata"],
    }


def render_host(repo: Path, graph: dict[str, Any], output: Path, host: str) -> dict[str, Any]:
    """Render one built-in host under ``output/<host>``."""
    if host not in HOST_NAMES:
        raise RenderError(f"unknown built-in host: {host}")
    _validate_graph(graph)
    root = output / host
    files = 0
    components = 0
    for component in graph["components"]:
        projection = component["host_projections"][host]
        if projection["mode"] == "omitted":
            continue
        components += 1
        target = _native_target(root, component, projection)
        shim_kind = component["kind"] if projection["mode"] == "shim" else None
        _render_component(component, target, shim_kind)
        files += 1
        if component["kind"] == "skill":
            files += _copy_resources(repo, component, target)
    host_spec = graph["hosts"][host]
    files += _copy_manifest(repo, root, host_spec["manifest"])
    files += _copy_extensions(repo, root, host, host_spec["extensions"])
    return {"host": host, "components": components, "files": files}


def _validate_adapter(adapter: dict[str, Any]) -> None:
    if adapter.get("contract_version") != 1:
        raise RenderError("host adapter contract_version must be 1")
    adapter_id = adapter.get("id")
    if not isinstance(adapter_id, str) or not ID_RE.fullmatch(adapter_id):
        raise RenderError("host adapter id must be lowercase kebab-case")
    if not isinstance(adapter.get("display_name"), str) or not adapter["display_name"]:
        raise RenderError("host adapter display_name must be non-empty")
    native = adapter.get("native_kinds")
    shim = adapter.get("shim_kinds")
    if not isinstance(native, list) or not isinstance(shim, list):
        raise RenderError("host adapter native_kinds and shim_kinds must be arrays")
    if not set(native).issubset(COMPONENT_KINDS) or not set(shim).issubset(COMPONENT_KINDS):
        raise RenderError("host adapter component kinds are unsupported")
    if set(native) & set(shim):
        raise RenderError("host adapter native and shim kinds must be disjoint")
    if not isinstance(adapter.get("extensions"), list) or not all(isinstance(item, str) for item in adapter["extensions"]):
        raise RenderError("host adapter extensions must be a string array")
    for extension in adapter["extensions"]:
        _safe_relative(extension, "host adapter extension")
    projection = adapter.get("projection")
    if not isinstance(projection, dict):
        raise RenderError("host adapter projection must be an object")
    for key in ("native_root", "shim_root"):
        _safe_relative(projection.get(key), f"adapter projection {key}")
    for key in ("agent_prefix", "command_prefix"):
        value = projection.get(key)
        if not isinstance(value, str) or "/" in value or "\\" in value or value.startswith("."):
            raise RenderError(f"adapter projection {key} must be a safe filename prefix")


def _adapter_target(root: Path, projection: dict[str, str], component: dict[str, Any], native: bool) -> Path:
    kind = component["kind"]
    base_key = "native_root" if native else "shim_root"
    base = root / _safe_relative(projection[base_key], f"adapter projection {base_key}")
    if not native:
        prefix_key = {"agent": "agent_prefix", "command": "command_prefix"}.get(kind)
        prefix = projection[prefix_key] if prefix_key else ""
        return base / f"{prefix}{component['id']}" / "SKILL.md"
    if kind == "skill":
        return base / component["id"] / "SKILL.md"
    directory = "agents" if kind == "agent" else "commands"
    return base / directory / f"{component['id']}.md"


def render_adapter(repo: Path, graph: dict[str, Any], output: Path, adapter: dict[str, Any]) -> dict[str, Any]:
    """Render a third-party adapter using the stable v1 adapter contract."""
    _validate_graph(graph)
    _validate_adapter(adapter)
    root = output / adapter["id"]
    projection = adapter["projection"]
    native_kinds = set(adapter["native_kinds"])
    shim_kinds = set(adapter["shim_kinds"])
    files = 0
    components = 0
    for component in graph["components"]:
        kind = component["kind"]
        if kind in native_kinds:
            target = _adapter_target(root, projection, component, native=True)
            _render_component(component, target)
            files += 1
            components += 1
            if kind == "skill":
                files += _copy_resources(repo, component, target)
        elif kind in shim_kinds:
            target = _adapter_target(root, projection, component, native=False)
            _render_component(component, target, kind)
            files += 1
            components += 1
    return {"adapter": adapter["id"], "components": components, "files": files}


def render_all(repo: Path, graph: dict[str, Any], output: Path) -> dict[str, dict[str, Any]]:
    return {host: render_host(repo, graph, output, host) for host in HOST_NAMES}


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _load_graph(repo: Path) -> dict[str, Any]:
    path = repo / "data" / "capabilities.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderError(f"cannot read capability graph: {exc}") from exc
    if not isinstance(value, dict):
        raise RenderError("capability graph must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify all built-in projections are deterministic")
    mode.add_argument("--adapter", type=Path, help="render a JSON host adapter contract")
    mode.add_argument("--release-surface", action="store_true", help="render hosts, metadata, and install inputs")
    parser.add_argument("--host", choices=("all", *HOST_NAMES), default="all")
    parser.add_argument("--output", type=Path, default=Path("build/capability-projections"))
    args = parser.parse_args(argv)
    try:
        graph = _load_graph(REPO)
        if args.check:
            with tempfile.TemporaryDirectory(prefix="forge-render-") as first, tempfile.TemporaryDirectory(prefix="forge-render-") as second:
                render_all(REPO, graph, Path(first))
                render_all(REPO, graph, Path(second))
                if _snapshot(Path(first)) != _snapshot(Path(second)):
                    raise RenderError("built-in host projections are not deterministic")
            print("Capability projections are deterministic for Claude, Codex, and Agent Skills.")
            return 0
        if args.adapter:
            adapter = json.loads(args.adapter.read_text(encoding="utf-8"))
            report = render_adapter(REPO, graph, args.output, adapter)
        elif args.release_surface:
            report = render_release_surface(REPO, graph, args.output)
        elif args.host == "all":
            report = render_all(REPO, graph, args.output)
        else:
            report = {args.host: render_host(REPO, graph, args.output, args.host)}
    except (OSError, json.JSONDecodeError, RenderError, KeyError, TypeError) as exc:
        print(f"capability renderer: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
