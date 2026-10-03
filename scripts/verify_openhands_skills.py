#!/usr/bin/env python3
"""Verify the extracted Forge AgentSkills bundle with the OpenHands SDK."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path
from typing import Any


RESOURCE_TYPES = ("scripts", "references", "assets")


class VerificationError(RuntimeError):
    """Raised when the archive is incomplete or the SDK cannot load it."""


def verify_archive(
    archive_root: Path, expected_sdk_version: str | None = None
) -> dict[str, Any]:
    """Load and verify every AgentSkills skill in an extracted Forge archive."""
    archive_root = archive_root.resolve()
    if not archive_root.is_dir():
        raise VerificationError(f"archive root is not a directory: {archive_root}")

    skills_dir = archive_root / "forge-agents" / "skills"
    if not skills_dir.is_dir():
        raise VerificationError(
            "extracted archive must contain forge-agents/skills"
        )

    projection_manifest = archive_root / "forge-agents/data/projection-manifest.json"
    try:
        manifest = json.loads(projection_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(
            f"cannot read the graph-rendered projection manifest: {exc}"
        ) from exc
    try:
        declared_components = manifest["hosts"]["agentskills"]["components"]
    except (KeyError, TypeError) as exc:
        raise VerificationError(
            "projection manifest has no AgentSkills component count"
        ) from exc
    if isinstance(declared_components, bool) or not isinstance(declared_components, int):
        raise VerificationError("projection manifest AgentSkills component count is invalid")

    zed_skills_dir = archive_root / "forge-agents/zed/skills"
    if not zed_skills_dir.is_dir():
        raise VerificationError("extracted archive must contain forge-agents/zed/skills")
    shim_files = [path for path in zed_skills_dir.rglob("*.md") if path.is_file()]
    expected_agent_skill_count = declared_components - len(shim_files)
    if expected_agent_skill_count < 1:
        raise VerificationError("projection manifest does not describe AgentSkills skills")

    expected_sources = {
        path.resolve(strict=True)
        for path in skills_dir.rglob("SKILL.md")
        if path.is_file()
    }
    if not expected_sources:
        raise VerificationError(f"no SKILL.md files found under {skills_dir}")
    if len(expected_sources) != expected_agent_skill_count:
        raise VerificationError(
            "extracted AgentSkills inventory differs from the graph-rendered manifest "
            f"(manifest={declared_components}, Zed shims={len(shim_files)}, "
            f"expected SKILL.md={expected_agent_skill_count}, "
            f"found={len(expected_sources)})"
        )

    try:
        sdk_version = importlib.metadata.version("openhands-sdk")
        from openhands.sdk import AgentContext
        from openhands.sdk.skills import (
            discover_skill_resources,
            load_skills_from_dir,
        )
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        raise VerificationError(
            "OpenHands SDK is required; install a pinned openhands-sdk release"
        ) from exc

    if expected_sdk_version and sdk_version != expected_sdk_version:
        raise VerificationError(
            f"expected openhands-sdk {expected_sdk_version}, found {sdk_version}"
        )

    try:
        _, _, agent_skills = load_skills_from_dir(skills_dir, root=skills_dir)
    except Exception as exc:
        raise VerificationError(
            f"OpenHands SDK could not load AgentSkills: {exc}"
        ) from exc

    loaded_sources: dict[Path, str] = {}
    for skill in agent_skills.values():
        if not skill.is_agentskills_format:
            raise VerificationError(f"SDK returned a non-AgentSkills entry: {skill.name}")
        if not skill.source:
            raise VerificationError(f"SDK returned no source path for {skill.name}")
        try:
            source = Path(skill.source).resolve(strict=True)
        except OSError as exc:
            raise VerificationError(
                f"SDK returned an unavailable source for {skill.name}: {skill.source}"
            ) from exc
        if source in loaded_sources:
            raise VerificationError(
                f"SDK registered one SKILL.md more than once: {source}"
            )
        loaded_sources[source] = skill.name

    if set(loaded_sources) != expected_sources:
        missing = sorted(str(path) for path in expected_sources - set(loaded_sources))
        unexpected = sorted(str(path) for path in set(loaded_sources) - expected_sources)
        raise VerificationError(
            "SDK did not register every packaged SKILL.md "
            f"(expected {len(expected_sources)}, loaded {len(loaded_sources)}; "
            f"missing={missing}, unexpected={unexpected})"
        )

    empty_content = sorted(
        skill.name for skill in agent_skills.values() if not skill.content.strip()
    )
    if empty_content:
        raise VerificationError(
            "SDK loaded empty skill content for: " + ", ".join(empty_content)
        )

    try:
        context = AgentContext(
            skills=list(agent_skills.values()),
            load_public_skills=False,
        )
    except Exception as exc:
        raise VerificationError(
            f"OpenHands AgentContext rejected loaded skills: {exc}"
        ) from exc

    registered_names = sorted(skill.name for skill in context.skills)
    expected_names = sorted(skill.name for skill in agent_skills.values())
    if registered_names != expected_names or context.load_public_skills:
        raise VerificationError("OpenHands AgentContext did not register exactly the loaded skills")

    resource_counts = {resource_type: 0 for resource_type in RESOURCE_TYPES}
    resource_files: list[dict[str, Any]] = []
    resource_bytes_read = 0
    for skill in agent_skills.values():
        skill_file = Path(skill.source).resolve(strict=True)
        skill_dir = skill_file.parent
        discovered = discover_skill_resources(skill_dir)
        loaded_resources = skill.resources
        if discovered.has_resources() and loaded_resources is None:
            raise VerificationError(f"SDK did not attach resources for {skill.name}")

        if loaded_resources is not None:
            if Path(loaded_resources.skill_root).resolve() != skill_dir:
                raise VerificationError(f"SDK returned the wrong resource root for {skill.name}")

        for resource_type in RESOURCE_TYPES:
            discovered_paths = list(getattr(discovered, resource_type))
            loaded_paths = (
                list(getattr(loaded_resources, resource_type))
                if loaded_resources is not None
                else []
            )
            if loaded_paths != discovered_paths:
                raise VerificationError(
                    f"SDK resource paths differ for {skill.name}/{resource_type}"
                )

            for relative_name in loaded_paths:
                relative_path = Path(relative_name)
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise VerificationError(
                        "SDK returned an unsafe resource path for "
                        f"{skill.name}: {relative_name}"
                    )
                resource_path = skill_dir / resource_type / relative_path
                try:
                    resolved_resource = resource_path.resolve(strict=True)
                    resolved_resource.relative_to(skill_dir)
                    if not resolved_resource.is_file():
                        raise VerificationError(
                            f"SDK resource is not a file: {skill.name}/{relative_name}"
                        )
                    content = resolved_resource.read_bytes()
                except (OSError, ValueError) as exc:
                    raise VerificationError(
                        "cannot read packaged resource "
                        f"{skill.name}/{resource_type}/{relative_name}: {exc}"
                    ) from exc
                if not content:
                    raise VerificationError(
                        f"packaged resource is empty: {skill.name}/{resource_type}/{relative_name}"
                    )
                resource_counts[resource_type] += 1
                resource_bytes_read += len(content)
                resource_files.append(
                    {
                        "skill": skill.name,
                        "type": resource_type,
                        "path": relative_path.as_posix(),
                        "bytes_read": len(content),
                    }
                )

    return {
        "status": "verified",
        "python_version": sys.version.split()[0],
        "openhands_sdk_version": sdk_version,
        "archive_root": str(archive_root),
        "skills_directory": "forge-agents/skills",
        "skill_count": len(agent_skills),
        "registered_skill_names": registered_names,
        "skill_content_characters": {
            skill.name: len(skill.content) for skill in agent_skills.values()
        },
        "resource_counts": resource_counts,
        "resource_file_count": len(resource_files),
        "resource_bytes_read": resource_bytes_read,
        "resource_files": sorted(
            resource_files,
            key=lambda item: (item["skill"], item["type"], item["path"]),
        ),
        "llm_calls": 0,
        "public_skill_loading": context.load_public_skills,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify Forge AgentSkills in an extracted release archive "
            "with the OpenHands SDK."
        )
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        required=True,
        help="extracted Forge *-agents.tar.gz root containing forge-agents/skills",
    )
    parser.add_argument(
        "--expected-sdk-version",
        help="fail unless this exact openhands-sdk version is installed",
    )
    args = parser.parse_args(argv)

    try:
        report = verify_archive(args.archive_root, args.expected_sdk_version)
    except Exception as exc:
        print(f"verify_openhands_skills: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
