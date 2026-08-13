#!/usr/bin/env python3
"""Validate a Codex plugin directory or Forge release archive without dependencies."""

from __future__ import annotations

import argparse
import json
import re
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
HEX_COLOR_RE = re.compile(r"^#[0-9A-F]{6}$", re.IGNORECASE)
TODO_MARKER = "[TODO:"
MARKETPLACE_INSTALLATION = {"NOT_AVAILABLE", "AVAILABLE", "INSTALLED_BY_DEFAULT"}
MARKETPLACE_AUTHENTICATION = {"ON_INSTALL", "ON_USE"}


def _https(value: Any) -> bool:
    parsed = urlparse(value) if isinstance(value, str) else None
    return bool(parsed and parsed.scheme == "https" and parsed.netloc)


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in _walk_strings(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _walk_strings(child)]
    return []


def _load_json(path: Path, errors: list[str], label: str) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append(f"missing {label}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append(f"{label} must contain valid JSON")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return None
    return value


def _archive_path(root: Path, raw: Any, field: str, errors: list[str]) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        errors.append(f"{field} must be a non-empty relative path")
        return None
    candidate = PurePosixPath(raw.replace("\\", "/"))
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        errors.append(f"{field} must stay inside the plugin archive")
        return None
    candidate_path = root / candidate.as_posix()
    if candidate_path.is_symlink():
        errors.append(f"{field} points to a symlink")
        return None
    resolved = candidate_path.resolve()
    if root.resolve() not in resolved.parents and resolved != root.resolve():
        errors.append(f"{field} must stay inside the plugin archive")
        return None
    if not resolved.is_file():
        errors.append(f"{field} points to a missing file")
        return None
    return resolved


def _validate_skill(skill_root: Path, errors: list[str]) -> None:
    skill = skill_root / "SKILL.md"
    if not skill.is_file():
        errors.append(f"skill {skill_root.name} is missing SKILL.md")
        return
    try:
        contents = skill.read_text(encoding="utf-8")
    except OSError:
        errors.append(f"skill {skill_root.name} is not readable")
        return
    if TODO_MARKER in contents:
        errors.append(f"skill {skill_root.name} contains a TODO placeholder")
    if not contents.startswith("---\n"):
        errors.append(f"skill {skill_root.name} must start with YAML frontmatter")
        return
    end = contents.find("\n---", 4)
    if end == -1:
        errors.append(f"skill {skill_root.name} frontmatter is not closed")
        return
    fields: dict[str, str] = {}
    for line in contents[4:end].splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if match:
            fields[match.group(1)] = match.group(2).strip().strip('"')
    for field in ("name", "description"):
        if not fields.get(field):
            errors.append(f"skill {skill_root.name} frontmatter needs {field}")


def validate_plugin(plugin_root: Path, expected_version: str | None = None) -> list[str]:
    errors: list[str] = []
    plugin_root = plugin_root.resolve()
    manifest = _load_json(plugin_root / ".codex-plugin/plugin.json", errors, ".codex-plugin/plugin.json")
    if manifest is None:
        return errors
    for value in _walk_strings(manifest):
        if TODO_MARKER in value:
            errors.append("plugin.json contains a TODO placeholder")

    allowed = {"id", "name", "version", "description", "skills", "apps", "mcpServers", "interface", "author", "homepage", "repository", "license", "keywords"}
    for field in sorted(set(manifest) - allowed):
        errors.append(f"plugin.json has unsupported field {field}")
    for field in ("name", "version", "description"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            errors.append(f"plugin.json {field} must be a non-empty string")
    version = manifest.get("version")
    if isinstance(version, str) and not SEMVER_RE.fullmatch(version):
        errors.append("plugin.json version must use strict semver")
    if expected_version and version != expected_version:
        errors.append(f"plugin.json version is {version}, expected {expected_version}")
    for field in ("homepage", "repository"):
        if field in manifest and not _https(manifest[field]):
            errors.append(f"plugin.json {field} must be an absolute https URL")

    author = manifest.get("author")
    if not isinstance(author, dict) or not isinstance(author.get("name"), str) or not author["name"].strip():
        errors.append("plugin.json author.name must be a non-empty string")
    elif "url" in author and not _https(author["url"]):
        errors.append("plugin.json author.url must be an absolute https URL")

    skills = manifest.get("skills")
    if skills != "./skills/" or not (plugin_root / "skills").is_dir():
        errors.append("plugin.json skills must resolve to ./skills/")
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        errors.append("plugin.json interface must be an object")
        interface = {}
    allowed_interface = {
        "displayName", "shortDescription", "longDescription", "developerName", "category",
        "capabilities", "websiteURL", "privacyPolicyURL", "termsOfServiceURL", "brandColor",
        "composerIcon", "logo", "logoDark", "screenshots", "defaultPrompt", "default_prompt",
    }
    for field in sorted(set(interface) - allowed_interface):
        errors.append(f"plugin.json interface has unsupported field {field}")
    for field in ("displayName", "shortDescription", "longDescription", "developerName", "category"):
        if not isinstance(interface.get(field), str) or not interface[field].strip():
            errors.append(f"plugin.json interface.{field} must be a non-empty string")
    prompts = interface.get("defaultPrompt", interface.get("default_prompt"))
    if not isinstance(prompts, list) or not prompts or len(prompts) > 3 or not all(isinstance(item, str) and item.strip() and len(item) <= 128 for item in prompts):
        errors.append("plugin.json interface.defaultPrompt must contain one to three short strings")
    capabilities = interface.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities or not all(isinstance(item, str) and item.strip() for item in capabilities):
        errors.append("plugin.json interface.capabilities must be a non-empty string array")
    for field in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
        if not _https(interface.get(field)):
            errors.append(f"plugin.json interface.{field} must be an absolute https URL")
    if "brandColor" in interface and (not isinstance(interface["brandColor"], str) or not HEX_COLOR_RE.fullmatch(interface["brandColor"])):
        errors.append("plugin.json interface.brandColor must use #RRGGBB")
    for field in ("composerIcon", "logo", "logoDark"):
        if field in interface:
            _archive_path(plugin_root, interface[field], f"interface.{field}", errors)
    screenshots = interface.get("screenshots", [])
    if not isinstance(screenshots, list):
        errors.append("plugin.json interface.screenshots must be an array")
    else:
        for index, raw_path in enumerate(screenshots):
            path = _archive_path(plugin_root, raw_path, f"interface.screenshots[{index}]", errors)
            if path and path.suffix.lower() != ".png":
                errors.append(f"interface.screenshots[{index}] must be a PNG file")

    for path in sorted((plugin_root / "skills").iterdir()) if (plugin_root / "skills").is_dir() else []:
        if path.is_dir() and not path.name.startswith("."):
            _validate_skill(path, errors)
    for path in plugin_root.rglob("*"):
        if path.is_symlink() or (path.exists() and not path.is_file() and not path.is_dir()):
            errors.append(f"plugin contains an unsupported filesystem entry: {path.relative_to(plugin_root)}")
    return errors


def validate_marketplace(marketplace_path: Path, root: Path | None = None) -> list[str]:
    """Validate the Codex marketplace contract and optional local source paths."""

    errors: list[str] = []
    marketplace = _load_json(marketplace_path.resolve(), errors, "marketplace.json")
    if marketplace is None:
        return errors

    allowed = {"name", "interface", "plugins"}
    for field in sorted(set(marketplace) - allowed):
        errors.append(f"marketplace.json has unsupported field {field}")
    if not isinstance(marketplace.get("name"), str) or not marketplace["name"].strip():
        errors.append("marketplace.json name must be a non-empty string")

    interface = marketplace.get("interface", {})
    if not isinstance(interface, dict):
        errors.append("marketplace.json interface must be an object")
    elif "displayName" in interface and (
        not isinstance(interface["displayName"], str) or not interface["displayName"].strip()
    ):
        errors.append("marketplace.json interface.displayName must be a non-empty string")

    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        errors.append("marketplace.json plugins must be an array")
        return errors

    root_path = root.resolve() if root else None
    for index, entry in enumerate(plugins):
        label = f"marketplace.json plugins[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue
        allowed_entry = {"name", "source", "policy", "category"}
        for field in sorted(set(entry) - allowed_entry):
            errors.append(f"{label} has unsupported field {field}")
        if not isinstance(entry.get("name"), str) or not entry["name"].strip():
            errors.append(f"{label}.name must be a non-empty string")
        if not isinstance(entry.get("category"), str) or not entry["category"].strip():
            errors.append(f"{label}.category must be a non-empty string")

        source = entry.get("source")
        if not isinstance(source, dict):
            errors.append(f"{label}.source must be an object")
        else:
            if source.get("source") != "local":
                errors.append(f"{label}.source.source must be local")
            raw_path = source.get("path")
            if not isinstance(raw_path, str) or not raw_path.startswith("./"):
                errors.append(f"{label}.source.path must start with ./")
            else:
                relative = PurePosixPath(raw_path[2:])
                if (
                    not relative.parts
                    or any(part in {"", ".", ".."} for part in relative.parts)
                ):
                    errors.append(f"{label}.source.path must stay inside the marketplace root")
                elif root_path:
                    candidate = (root_path / relative.as_posix()).resolve()
                    if root_path not in candidate.parents:
                        errors.append(f"{label}.source.path must stay inside the marketplace root")
                    elif not (candidate / ".codex-plugin/plugin.json").is_file():
                        errors.append(f"{label}.source.path has no .codex-plugin/plugin.json")

        policy = entry.get("policy")
        if not isinstance(policy, dict):
            errors.append(f"{label}.policy must be an object")
        else:
            installation = policy.get("installation")
            if installation not in MARKETPLACE_INSTALLATION:
                errors.append(f"{label}.policy.installation has an unsupported value")
            authentication = policy.get("authentication")
            if authentication not in MARKETPLACE_AUTHENTICATION:
                errors.append(f"{label}.policy.authentication has an unsupported value")
            products = policy.get("products")
            if products is not None and (
                not isinstance(products, list)
                or not all(isinstance(product, str) and product.strip() for product in products)
            ):
                errors.append(f"{label}.policy.products must be a string array")
    return errors


def extract_archive(archive_path: Path, destination: Path) -> Path:
    """Safely install a Codex plugin archive into an existing directory."""

    root_name = "forge"
    seen: set[str] = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            name = PurePosixPath(member.name)
            if not member.isfile() or name.is_absolute() or ".." in name.parts or not name.parts or name.parts[0] != root_name:
                raise ValueError(f"archive contains an unsafe member: {member.name}")
            if member.name in seen:
                raise ValueError(f"archive contains a duplicate member: {member.name}")
            seen.add(member.name)
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"archive member is unreadable: {member.name}")
            target.write_bytes(source.read())
            target.chmod(member.mode & 0o777)
    return destination / root_name


def validate_archive(archive_path: Path, expected_version: str | None = None) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="forge-codex-validate-") as directory:
        try:
            root = extract_archive(archive_path.resolve(), Path(directory))
        except (OSError, tarfile.TarError, ValueError) as exc:
            return [str(exc)]
        return validate_plugin(root, expected_version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Codex plugin directory or Forge release archive.")
    parser.add_argument("plugin_path", nargs="?", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--marketplace", type=Path)
    parser.add_argument("--root", type=Path, help="Repository root for local marketplace source checks")
    parser.add_argument("--version", dest="expected_version")
    args = parser.parse_args(argv)
    targets = [bool(args.plugin_path), bool(args.archive), bool(args.marketplace)]
    if sum(targets) != 1:
        parser.error("provide exactly one plugin path, --archive, or --marketplace")
    if args.root and not args.marketplace:
        parser.error("--root is only valid with --marketplace")
    if args.marketplace:
        errors = validate_marketplace(args.marketplace, args.root)
        success_message = "Codex marketplace validation passed."
    elif args.archive:
        errors = validate_archive(args.archive, args.expected_version)
        success_message = "Codex plugin validation passed."
    else:
        errors = validate_plugin(args.plugin_path, args.expected_version)
        success_message = "Codex plugin validation passed."
    if errors:
        print(f"{('Codex marketplace' if args.marketplace else 'Codex plugin')} validation failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(success_message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
