#!/usr/bin/env python3
"""Build deterministic Forge host bundles, hashes, and an SPDX 2.3 SBOM."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
SCHEMA_VERSION = 1
IGNORED_GENERATED = {"__pycache__", ".pytest_cache", ".ruff_cache"}
BUNDLE_SPECS: dict[str, tuple[tuple[str, str], ...]] = {
    "claude": (("plugins/forge", "forge"), ("LICENSE", "forge")),
    "codex": (("plugins/forge", "forge"), ("LICENSE", "forge")),
    "agents": (
        ("plugins/forge/skills", "forge-agents/skills"),
        ("zed/skills", "forge-agents/zed/skills"),
        ("zed/AGENTS.md", "forge-agents/zed"),
        ("zed/install.sh", "forge-agents/zed"),
        (".agents/plugins/marketplace.json", "forge-agents/.agents/plugins"),
        ("LICENSE", "forge-agents"),
    ),
}
RENDERED_BUNDLE_SPECS: dict[str, tuple[tuple[str, str], ...]] = {
    "claude": (
        ("claude/plugins/forge", "forge"),
        ("claude/CATALOG.md", "forge"),
        ("claude/data", "forge/data"),
        ("claude/LICENSE", "forge"),
    ),
    "codex": (
        ("codex/plugins/forge", "forge"),
        ("codex/CATALOG.md", "forge"),
        ("codex/data", "forge/data"),
        ("codex/LICENSE", "forge"),
    ),
    "agents": (
        ("agentskills/plugins/forge/skills", "forge-agents/skills"),
        ("agentskills/zed/skills", "forge-agents/zed/skills"),
        ("agentskills/zed/AGENTS.md", "forge-agents/zed"),
        ("agentskills/zed/README.md", "forge-agents/zed"),
        ("agentskills/zed/install.sh", "forge-agents/zed"),
        ("agentskills/zed/settings", "forge-agents/zed/settings"),
        ("agentskills/.agents/plugins/marketplace.json", "forge-agents/.agents/plugins"),
        ("agentskills/CATALOG.md", "forge-agents"),
        ("agentskills/data", "forge-agents/data"),
        ("agentskills/LICENSE", "forge-agents"),
    ),
}
RUNTIME_DEPENDENCIES = (
    {
        "name": "Python",
        "version": ">=3.9",
        "bundled": False,
        "license": "PSF-2.0",
        "purpose": "stdlib-only Forge scripts and verifiers",
    },
    {
        "name": "GitHub CLI",
        "version": "host-provided",
        "bundled": False,
        "license": "MIT",
        "purpose": "optional GitHub task, stack, and policy adapters",
    },
)


class ReleaseBuildError(RuntimeError):
    """Raised when a release cannot be built from a reviewable source tree."""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ReleaseBuildError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _canonical(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tracked_index(repo: Path) -> dict[str, str]:
    output = _git(repo, "ls-files", "--stage", "-z")
    tracked: dict[str, str] = {}
    for record in output.split("\0"):
        if not record:
            continue
        metadata, relative = record.split("\t", 1)
        tracked[relative] = metadata.split()[0]
    return tracked


def _ignored_generated(relative: str) -> bool:
    path = Path(relative)
    return any(part in IGNORED_GENERATED for part in path.parts) or path.suffix == ".pyc"


def _check_clean(repo: Path) -> None:
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ReleaseBuildError("release source tree is dirty; commit reviewed content before packaging")


def _source_files(repo: Path, source: str, tracked: Mapping[str, str]) -> list[tuple[str, Path, str]]:
    root = repo / source
    if not root.exists():
        raise ReleaseBuildError(f"release source path is missing: {source}")
    paths = [root] if root.is_file() else sorted(root.rglob("*"))
    files: list[tuple[str, Path, str]] = []
    for path in paths:
        if path.is_dir():
            continue
        relative = path.relative_to(repo).as_posix()
        if path.is_symlink():
            raise ReleaseBuildError(f"symlinks are not allowed in release bundles: {relative}")
        if relative not in tracked:
            if _ignored_generated(relative):
                continue
            raise ReleaseBuildError(f"untracked file would enter a release bundle: {relative}")
        mode = tracked[relative]
        if mode not in {"100644", "100755"}:
            raise ReleaseBuildError(f"unsupported or submodule mode for release file: {relative} ({mode})")
        file_stat = path.stat()
        if not stat.S_ISREG(file_stat.st_mode):
            raise ReleaseBuildError(f"release bundle input is not a regular file: {relative}")
        executable = bool(file_stat.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        if executable != (mode == "100755"):
            raise ReleaseBuildError(f"filesystem executable mode disagrees with reviewed Git mode: {relative}")
        files.append((relative, path, mode))
    return files


def _generated_files(root: Path) -> list[tuple[str, Path, str]]:
    if not root.exists():
        raise ReleaseBuildError(f"generated release source path is missing: {root}")
    paths = [root] if root.is_file() else sorted(root.rglob("*"))
    files: list[tuple[str, Path, str]] = []
    for path in paths:
        if path.is_dir():
            continue
        relative = path.name if root.is_file() else path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ReleaseBuildError(f"symlinks are not allowed in generated bundles: {relative}")
        file_stat = path.stat()
        if not stat.S_ISREG(file_stat.st_mode):
            raise ReleaseBuildError(f"generated release input is not a regular file: {relative}")
        executable = bool(file_stat.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        files.append((relative, path, "100755" if executable else "100644"))
    return files


def _bundle_files(
    repo: Path,
    bundle: str,
    tracked: Mapping[str, str],
    generated_root: Path | None = None,
) -> list[tuple[str, Path, str]]:
    entries: list[tuple[str, Path, str]] = []
    seen: set[str] = set()
    specs = RENDERED_BUNDLE_SPECS[bundle] if generated_root else BUNDLE_SPECS[bundle]
    for source, prefix in specs:
        source_root = generated_root / source if generated_root else repo / source
        source_files = _generated_files(source_root) if generated_root else _source_files(repo, source, tracked)
        for relative, path, mode in source_files:
            suffix = relative if source_root.is_dir() else Path(relative).name
            archive_path = f"{prefix}/{suffix}"
            if archive_path in seen:
                raise ReleaseBuildError(f"duplicate archive path in {bundle} bundle: {archive_path}")
            seen.add(archive_path)
            entries.append((archive_path, path, mode))
    return sorted(entries, key=lambda item: item[0])


def _archive(bundle: str, entries: Iterable[tuple[str, Path, str]], source_epoch: int) -> tuple[bytes, list[dict[str, Any]]]:
    content: list[dict[str, Any]] = []
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0, compresslevel=9) as compressed, tarfile.open(fileobj=compressed, mode="w|") as archive:
        for archive_path, path, mode in entries:
            data = path.read_bytes()
            content.append({"path": archive_path, "size": len(data), "sha256": _sha256_bytes(data)})
            info = tarfile.TarInfo(archive_path)
            info.size = len(data)
            info.mtime = source_epoch
            info.mode = 0o755 if mode == "100755" else 0o644
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            archive.addfile(info, io.BytesIO(data))
    return output.getvalue(), content


def _version_parity(repo: Path, version: str) -> dict[str, str]:
    paths = {
        "claude_plugin": repo / "plugins/forge/.claude-plugin/plugin.json",
        "codex_plugin": repo / "plugins/forge/.codex-plugin/plugin.json",
        "marketplace": repo / ".claude-plugin/marketplace.json",
    }
    values: dict[str, str] = {}
    for name, path in paths.items():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseBuildError(f"cannot read version manifest {path}: {exc}") from exc
        if name == "marketplace":
            value = str(data.get("metadata", {}).get("version", ""))
        else:
            value = str(data.get("version", ""))
        values[name] = value
        if value != version:
            raise ReleaseBuildError(f"{name} reports {value}, expected {version}")
        if name == "marketplace":
            plugins = data.get("plugins", [])
            plugin_version = str(plugins[0].get("version", "")) if plugins else ""
            values["marketplace_plugin"] = plugin_version
            if plugin_version != version:
                raise ReleaseBuildError(f"marketplace_plugin reports {plugin_version}, expected {version}")
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{version}]" not in changelog:
        raise ReleaseBuildError(f"CHANGELOG.md has no {version} release heading")
    return values


def _spdx_file_id(path: str) -> str:
    return "SPDXRef-File-" + hashlib.sha256(path.encode()).hexdigest()[:24]


def validate_spdx(document: Mapping[str, Any]) -> None:
    required = ("spdxVersion", "dataLicense", "SPDXID", "name", "documentNamespace", "creationInfo", "packages", "files", "relationships")
    missing = [key for key in required if key not in document]
    if missing:
        raise ReleaseBuildError("SPDX document is missing: " + ", ".join(missing))
    if document["spdxVersion"] != "SPDX-2.3":
        raise ReleaseBuildError("release SBOM must use SPDX-2.3 for GitHub attestation compatibility")
    if document["dataLicense"] != "CC0-1.0" or document["SPDXID"] != "SPDXRef-DOCUMENT":
        raise ReleaseBuildError("SPDX document identity or data license is invalid")
    if not isinstance(document["packages"], list) or not isinstance(document["files"], list) or not isinstance(document["relationships"], list):
        raise ReleaseBuildError("SPDX packages, files, and relationships must be arrays")
    for item in document["files"]:
        if not all(key in item for key in ("SPDXID", "fileName", "checksums", "licenseConcluded", "licenseInfoInFile")):
            raise ReleaseBuildError("SPDX file entry is incomplete")
        if not any(checksum.get("algorithm") == "SHA256" for checksum in item["checksums"]):
            raise ReleaseBuildError(f"SPDX file has no SHA256 checksum: {item.get('fileName')}")


def _spdx_document(
    repo: Path,
    version: str,
    tag: str,
    commit: str,
    source_epoch: int,
    bundles: list[dict[str, Any]],
) -> dict[str, Any]:
    file_entries: dict[str, dict[str, Any]] = {}
    for bundle in bundles:
        for content in bundle["contents"]:
            file_entries[content["path"]] = content
    files = []
    relationships = []
    for path, content in sorted(file_entries.items()):
        file_id = _spdx_file_id(path)
        files.append(
            {
                "SPDXID": file_id,
                "fileName": path,
                "checksums": [{"algorithm": "SHA256", "checksumValue": content["sha256"]}],
                "licenseConcluded": "MIT",
                "licenseInfoInFile": ["MIT"],
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append({"spdxElementId": "SPDXRef-Package-Forge", "relationshipType": "CONTAINS", "relatedSpdxElement": file_id})
    packages = [
        {
            "SPDXID": "SPDXRef-Package-Forge",
            "name": "forge",
            "versionInfo": version,
            "downloadLocation": f"https://github.com/AlisinaDevelo/md-files/releases/tag/{tag}",
            "filesAnalyzed": True,
            "licenseConcluded": "MIT",
            "licenseDeclared": "MIT",
            "copyrightText": "NOASSERTION",
        }
    ]
    for index, dependency in enumerate(RUNTIME_DEPENDENCIES, start=1):
        packages.append(
            {
                "SPDXID": f"SPDXRef-Package-Runtime-{index}",
                "name": dependency["name"],
                "versionInfo": dependency["version"],
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": dependency["license"],
                "licenseDeclared": dependency["license"],
                "copyrightText": "NOASSERTION",
                "comment": dependency["purpose"],
            }
        )
    created = dt.datetime.fromtimestamp(source_epoch, dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"Forge {version}",
        "documentNamespace": f"https://github.com/AlisinaDevelo/md-files/spdx/forge-{version}-{commit[:12]}",
        "creationInfo": {"created": created, "creators": ["Tool: forge-release-packager/1.0"]},
        "packages": packages,
        "files": files,
        "relationships": relationships,
        "annotations": [
            {
                "annotationDate": created,
                "annotationType": "OTHER",
                "annotator": "Tool: forge-release-packager/1.0",
                "comment": f"Source commit: {commit}; tag: {tag}; repository: {repo.name}",
            }
        ],
    }
    validate_spdx(document)
    return document


def _write(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def build_release(
    repo: Path,
    output: Path,
    version: str,
    *,
    source_epoch: int,
    tag: str | None = None,
    enforce_clean: bool = True,
) -> dict[str, Any]:
    """Build all release artifacts; repeated calls with the same source epoch are byte-stable."""

    if not VERSION_RE.fullmatch(version):
        raise ReleaseBuildError("version must use MAJOR.MINOR.PATCH")
    repo = repo.resolve()
    output = output.resolve()
    if enforce_clean:
        _check_clean(repo)
    bundle_roots = [repo / source for specs in BUNDLE_SPECS.values() for source, _ in specs]
    if any(output == root or root in output.parents for root in bundle_roots):
        raise ReleaseBuildError("release output must not be inside a bundled source path")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ReleaseBuildError(f"release output must be empty: {output}")
    tag = tag or f"v{version}"
    if tag != f"v{version}":
        raise ReleaseBuildError(f"tag must be v{version}, got {tag}")
    tracked = _tracked_index(repo)
    parity = _version_parity(repo, version)
    subprocess.run([sys.executable, str(repo / "scripts/generate_catalog.py"), "--check"], cwd=repo, check=True)
    if not (repo / "LICENSE").is_file():
        raise ReleaseBuildError("MIT LICENSE is required for the release SBOM")
    commit = _git(repo, "rev-parse", "HEAD")
    subprocess.run([sys.executable, str(repo / "scripts/compile_capabilities.py"), "--check"], cwd=repo, check=True)
    subprocess.run([sys.executable, str(repo / "scripts/render_capabilities.py"), "--check"], cwd=repo, check=True)
    bundles: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="forge-release-surface-") as rendered:
        subprocess.run(
            [sys.executable, str(repo / "scripts/render_capabilities.py"), "--release-surface", "--output", rendered],
            cwd=repo,
            check=True,
        )
        generated_root = Path(rendered)
        for surface in ("claude", "codex", "agents"):
            entries = _bundle_files(repo, surface, tracked, generated_root)
            data, contents = _archive(surface, entries, source_epoch)
            name = f"forge-{version}-{surface}.tar.gz"
            _write(output / name, data)
            bundles.append({"surface": surface, "name": name, "size": len(data), "sha256": _sha256_bytes(data), "contents": contents})
    sbom_name = f"forge-{version}-sbom.spdx.json"
    sbom = _spdx_document(repo, version, tag, commit, source_epoch, bundles)
    sbom_bytes = _canonical(sbom).encode("utf-8")
    _write(output / sbom_name, sbom_bytes)
    artifacts: list[dict[str, Any]] = [*bundles, {"name": sbom_name, "media_type": "application/spdx+json", "size": len(sbom_bytes), "sha256": _sha256_bytes(sbom_bytes)}]
    manifest_name = f"forge-{version}-manifest.json"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "project": "forge",
        "version": version,
        "tag": tag,
        "commit": commit,
        "source_date_epoch": source_epoch,
        "version_parity": parity,
        "runtime_dependencies": list(RUNTIME_DEPENDENCIES),
        "artifacts": artifacts,
        "sbom": {"name": sbom_name, "spdx_version": "SPDX-2.3", "predicate_type": "https://spdx.dev/Document/v2.3"},
        "verification": {
            "hashes_file": "SHA256SUMS",
            "manifest_file": manifest_name,
            "offline": "python3 scripts/verify_release.py --manifest PATH --root DIRECTORY",
        },
    }
    manifest_bytes = _canonical(manifest).encode("utf-8")
    _write(output / manifest_name, manifest_bytes)
    sums = [f"{_sha256_file(output / item['name'])}  {item['name']}" for item in [*artifacts, {"name": manifest_name}]]
    _write(output / "SHA256SUMS", ("\n".join(sums) + "\n").encode("utf-8"))
    return manifest


def _infer_version(repo: Path) -> str:
    path = repo / "plugins/forge/.claude-plugin/plugin.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    version = str(data.get("version", ""))
    if not VERSION_RE.fullmatch(version):
        raise ReleaseBuildError("could not infer a valid plugin version")
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic Forge release archives and an SPDX SBOM.")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--version")
    parser.add_argument("--tag")
    parser.add_argument("--source-date-epoch", type=int)
    parser.add_argument("--allow-dirty", action="store_true", help="development-only: skip clean-tree enforcement")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    try:
        version = args.version or _infer_version(repo)
        epoch = args.source_date_epoch
        if epoch is None:
            epoch = int(_git(repo, "show", "-s", "--format=%ct", "HEAD"))
        manifest = build_release(repo, args.output if args.output.is_absolute() else repo / args.output, version, source_epoch=epoch, tag=args.tag, enforce_clean=not args.allow_dirty)
        result = {"status": "built", "output": str((args.output if args.output.is_absolute() else repo / args.output).resolve()), "manifest": manifest}
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else f"Built Forge {version} release artifacts.")
        return 0
    except (OSError, ReleaseBuildError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
        print(f"build_release: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
