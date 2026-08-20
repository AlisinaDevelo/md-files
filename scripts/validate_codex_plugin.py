#!/usr/bin/env python3
"""Validate a Codex plugin directory or Forge release archive without dependencies."""

from __future__ import annotations

import argparse
import json
import re
import stat
import tarfile
import tempfile
import unicodedata
import zipfile
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
CODEX_INTERFACE_CATEGORIES = {
    "Productivity",
    "Creativity",
    "Developer Tools",
    "Business & Operations",
    "Data & Analytics",
    "Communication",
    "Education & Research",
    "Security",
    "Finance",
    "Healthcare",
    "Travel",
    "Entertainment",
    "Other",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ZIP_MAX_ENTRIES = 5_000
ZIP_MAX_COMPRESSED_BYTES = 100 * 1024 * 1024
ZIP_MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
OPENAI_TOP_LEVEL = {".codex-plugin", "skills", "assets", "data", "LICENSE"}


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


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as handle:
            if handle.read(8) != PNG_SIGNATURE:
                return None
            length = handle.read(4)
            chunk_type = handle.read(4)
            dimensions = handle.read(8)
    except OSError:
        return None
    if len(length) != 4 or chunk_type != b"IHDR" or len(dimensions) != 8:
        return None
    return (
        int.from_bytes(dimensions[:4], "big"),
        int.from_bytes(dimensions[4:], "big"),
    )


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
    category = interface.get("category")
    if isinstance(category, str) and category.strip() and category not in CODEX_INTERFACE_CATEGORIES:
        errors.append("plugin.json interface.category must use a supported Codex category")
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
            path = _archive_path(plugin_root, interface[field], f"interface.{field}", errors)
            if path and path.suffix.lower() == ".png":
                dimensions = _png_dimensions(path)
                if dimensions is None:
                    errors.append(f"interface.{field} must be a valid PNG file")
                elif dimensions[0] != dimensions[1]:
                    errors.append(
                        f"interface.{field} must be square (got {dimensions[0]}x{dimensions[1]})"
                    )
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


def _safe_zip_member_name(raw: str) -> str:
    if not raw or raw != raw.strip() or "\\" in raw or "\x00" in raw or len(raw) > 1024:
        raise ValueError(f"archive contains an unsafe member: {raw!r}")
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise ValueError(f"archive contains an unsafe member: {raw!r}")
    name = raw[:-1] if raw.endswith("/") else raw
    if not name or "/" in name and any(part == "" for part in name.split("/")):
        raise ValueError(f"archive contains an unsafe member: {raw!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"archive contains an unsafe member: {raw!r}")
    return name


def extract_zip(archive_path: Path, destination: Path) -> Path:
    """Safely extract an OpenAI skills-only ZIP and return its plugin root."""

    destination.mkdir(parents=True, exist_ok=True)
    names: list[tuple[zipfile.ZipInfo, str, bool]] = []
    normalized: set[str] = set()
    total_uncompressed = 0
    with zipfile.ZipFile(archive_path, "r") as archive:
        members = archive.infolist()
        if not members:
            raise ValueError("archive is empty")
        if len(members) > ZIP_MAX_ENTRIES:
            raise ValueError(f"archive has too many entries: {len(members)}")
        for member in members:
            raw = member.filename
            name = _safe_zip_member_name(raw)
            is_directory = member.is_dir() or raw.endswith("/")
            key = unicodedata.normalize("NFC", name).casefold()
            if key in normalized:
                raise ValueError(f"archive contains duplicate members after normalization: {raw}")
            normalized.add(key)
            if member.compress_size > ZIP_MAX_COMPRESSED_BYTES:
                raise ValueError(f"archive member is too large when compressed: {raw}")
            mode = (member.external_attr >> 16) & 0o177777
            file_type = stat.S_IFMT(mode)
            if stat.S_ISLNK(mode) or (file_type and not is_directory and file_type != stat.S_IFREG):
                raise ValueError(f"archive contains an unsupported member type: {raw}")
            if not is_directory:
                total_uncompressed += member.file_size
                if total_uncompressed > ZIP_MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("archive exceeds the uncompressed size limit")
            names.append((member, name, is_directory))

        file_names = {name for _member, name, is_directory in names if not is_directory}
        for _member, name, _is_directory in names:
            parts = PurePosixPath(name).parts
            if any("/".join(parts[:index]) in file_names for index in range(1, len(parts))):
                raise ValueError(f"archive has a file/directory path conflict: {name}")

        manifest_names = [
            name
            for _member, name, is_directory in names
            if not is_directory and (name == ".codex-plugin/plugin.json" or name.endswith("/.codex-plugin/plugin.json"))
        ]
        direct_manifest = ".codex-plugin/plugin.json" in manifest_names
        if direct_manifest:
            if len(manifest_names) != 1:
                raise ValueError("archive has multiple plugin roots")
            root_prefix = ""
        else:
            top_levels = {PurePosixPath(name).parts[0] for _member, name, _is_directory in names}
            if len(top_levels) != 1:
                raise ValueError("archive must contain exactly one top-level plugin directory")
            root_prefix = next(iter(top_levels))
            if manifest_names != [f"{root_prefix}/.codex-plugin/plugin.json"]:
                raise ValueError("archive has no single top-level .codex-plugin/plugin.json")

        for member, name, is_directory in names:
            target = destination / name
            if is_directory:
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise ValueError(f"archive extraction encountered a symlink: {name}")
            data = archive.read(member)
            if len(data) != member.file_size:
                raise ValueError(f"archive member size changed while reading: {name}")
            target.write_bytes(data)
            mode = (member.external_attr >> 16) & 0o777
            target.chmod(mode or 0o644)
    return destination / root_prefix if root_prefix else destination


def validate_openai_plugin(plugin_root: Path, expected_version: str | None = None) -> list[str]:
    """Validate the stricter skills-only shape accepted by the OpenAI portal."""

    errors = validate_plugin(plugin_root, expected_version)
    plugin_root = plugin_root.resolve()
    manifest_path = plugin_root / ".codex-plugin/plugin.json"
    if not manifest_path.is_file():
        return errors
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return errors
    if "mcpServers" in manifest:
        errors.append("skills-only plugin.json must not declare mcpServers")
    if "apps" in manifest:
        errors.append("skills-only plugin.json must not declare apps")
    interface = manifest.get("interface")
    if isinstance(interface, dict) and interface.get("screenshots"):
        errors.append("skills-only plugin.json must not declare screenshots")
    for path in plugin_root.rglob("*"):
        if path.is_file() and path.name in {".mcp.json", ".app.json"}:
            errors.append(f"skills-only plugin must not include {path.name}")
    top_levels = {
        path.relative_to(plugin_root).parts[0]
        for path in plugin_root.rglob("*")
        if path.relative_to(plugin_root).parts
    }
    unexpected = sorted(top_levels - OPENAI_TOP_LEVEL)
    errors.extend(f"skills-only plugin has unsupported top-level path: {name}" for name in unexpected)
    skills_root = plugin_root / "skills"
    skill_directories = (
        [path for path in skills_root.iterdir() if path.is_dir() and not path.name.startswith(".")]
        if skills_root.is_dir()
        else []
    )
    if not skill_directories:
        errors.append("skills-only plugin must contain at least one skill")
    return errors


def validate_openai_zip(archive_path: Path, expected_version: str | None = None) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="forge-openai-zip-validate-") as directory:
        try:
            root = extract_zip(archive_path.resolve(), Path(directory))
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            return [str(exc)]
        return validate_openai_plugin(root, expected_version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Codex plugin directory or Forge release archive.")
    parser.add_argument("plugin_path", nargs="?", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--marketplace", type=Path)
    parser.add_argument("--root", type=Path, help="Repository root for local marketplace source checks")
    parser.add_argument("--version", dest="expected_version")
    args = parser.parse_args(argv)
    targets = [bool(args.plugin_path), bool(args.archive), bool(args.zip), bool(args.marketplace)]
    if sum(targets) != 1:
        parser.error("provide exactly one plugin path, --archive, --zip, or --marketplace")
    if args.root and not args.marketplace:
        parser.error("--root is only valid with --marketplace")
    if args.marketplace:
        errors = validate_marketplace(args.marketplace, args.root)
        success_message = "Codex marketplace validation passed."
    elif args.archive:
        errors = validate_archive(args.archive, args.expected_version)
        success_message = "Codex plugin validation passed."
    elif args.zip:
        errors = validate_openai_zip(args.zip, args.expected_version)
        success_message = "OpenAI skills-only ZIP validation passed."
    else:
        errors = validate_plugin(args.plugin_path, args.expected_version)
        success_message = "Codex plugin validation passed."
    if errors:
        label = "Codex marketplace" if args.marketplace else "OpenAI skills-only ZIP" if args.zip else "Codex plugin"
        print(f"{label} validation failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(success_message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
