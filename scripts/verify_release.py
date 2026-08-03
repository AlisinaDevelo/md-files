#!/usr/bin/env python3
"""Verify Forge release hashes, archive contents, and SPDX metadata offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any


class ReleaseVerificationError(RuntimeError):
    """Raised when a release artifact or its inventory cannot be trusted."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseVerificationError(f"JSON document must be an object: {path}")
    return value


def _safe_artifact_path(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if root.resolve() not in path.parents:
        raise ReleaseVerificationError(f"artifact path escapes release root: {name}")
    return path


def _verify_hashes(manifest: dict[str, Any], root: Path) -> None:
    for artifact in manifest.get("artifacts", []):
        path = _safe_artifact_path(root, str(artifact["name"]))
        if not path.is_file():
            raise ReleaseVerificationError(f"missing release artifact: {artifact['name']}")
        actual = _sha256(path)
        if actual != artifact.get("sha256"):
            raise ReleaseVerificationError(f"sha256 mismatch for {artifact['name']}: expected {artifact.get('sha256')}, got {actual}")
        if path.stat().st_size != artifact.get("size"):
            raise ReleaseVerificationError(f"size mismatch for {artifact['name']}")
    hashes_path = _safe_artifact_path(root, str(manifest.get("verification", {}).get("hashes_file", "SHA256SUMS")))
    if not hashes_path.is_file():
        raise ReleaseVerificationError("SHA256SUMS file is missing")
    line_re = re.compile(r"^([0-9a-f]{64})  (.+)$")
    entries: dict[str, str] = {}
    for line in hashes_path.read_text(encoding="utf-8").splitlines():
        match = line_re.fullmatch(line)
        if not match:
            raise ReleaseVerificationError(f"invalid SHA256SUMS line: {line}")
        if match.group(2) in entries:
            raise ReleaseVerificationError(f"duplicate SHA256SUMS entry: {match.group(2)}")
        entries[match.group(2)] = match.group(1)
    manifest_name = str(manifest["verification"].get("manifest_file", f"forge-{manifest['version']}-manifest.json"))
    expected_names = {str(item["name"]) for item in manifest["artifacts"]} | {manifest_name}
    if set(entries) != expected_names:
        raise ReleaseVerificationError("SHA256SUMS does not cover exactly the published artifacts and manifest")
    manifest_path = _safe_artifact_path(root, manifest_name)
    if entries[manifest_name] != _sha256(manifest_path):
        raise ReleaseVerificationError("SHA256SUMS manifest digest is incorrect")
    for name in expected_names - {manifest_name}:
        if entries[name] != _sha256(_safe_artifact_path(root, name)):
            raise ReleaseVerificationError(f"SHA256SUMS digest is incorrect: {name}")


def _verify_spdx(manifest: dict[str, Any], root: Path) -> None:
    sbom_name = str(manifest.get("sbom", {}).get("name", ""))
    sbom = _load(_safe_artifact_path(root, sbom_name))
    required = {"spdxVersion", "dataLicense", "SPDXID", "creationInfo", "packages", "files", "relationships"}
    if not required.issubset(sbom):
        raise ReleaseVerificationError("SPDX SBOM is missing required fields")
    if sbom["spdxVersion"] != "SPDX-2.3" or sbom["dataLicense"] != "CC0-1.0":
        raise ReleaseVerificationError("SPDX SBOM version or data license is invalid")
    indexed = {item.get("fileName"): item for item in sbom.get("files", [])}
    for bundle in manifest.get("artifacts", []):
        for content in bundle.get("contents", []):
            item = indexed.get(content.get("path"))
            if not item:
                raise ReleaseVerificationError(f"SBOM does not cover bundled file: {content.get('path')}")
            checksums = {checksum.get("algorithm"): checksum.get("checksumValue") for checksum in item.get("checksums", [])}
            if checksums.get("SHA256") != content.get("sha256"):
                raise ReleaseVerificationError(f"SBOM checksum mismatch: {content.get('path')}")


def _verify_archives(manifest: dict[str, Any], root: Path) -> None:
    for artifact in manifest.get("artifacts", []):
        contents = artifact.get("contents")
        if not contents:
            continue
        expected = {str(item["path"]): item for item in contents}
        path = _safe_artifact_path(root, str(artifact["name"]))
        try:
            with tarfile.open(path, mode="r:gz") as archive:
                all_members = archive.getmembers()
                members = [member for member in all_members if member.isfile()]
                if len(members) != len(all_members):
                    raise ReleaseVerificationError(f"archive contains a non-regular member: {artifact['name']}")
                actual_names = {member.name for member in members}
                if actual_names != set(expected):
                    raise ReleaseVerificationError(f"archive contents differ for {artifact['name']}")
                for member in members:
                    member_path = Path(member.name)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise ReleaseVerificationError(f"archive member escapes its root: {artifact['name']}:{member.name}")
                    extracted = archive.extractfile(member)
                    data = extracted.read() if extracted else b""
                    expected_item = expected[member.name]
                    if len(data) != expected_item["size"] or hashlib.sha256(data).hexdigest() != expected_item["sha256"]:
                        raise ReleaseVerificationError(f"archive content hash mismatch: {artifact['name']}:{member.name}")
        except (OSError, tarfile.TarError) as exc:
            raise ReleaseVerificationError(f"cannot inspect archive {artifact['name']}: {exc}") from exc


def verify_release(manifest_path: Path, root: Path, *, expected_version: str | None = None, expected_commit: str | None = None) -> dict[str, Any]:
    manifest = _load(manifest_path)
    if manifest.get("schema_version") != 1 or manifest.get("project") != "forge":
        raise ReleaseVerificationError("unsupported Forge release manifest")
    if expected_version and manifest.get("version") != expected_version:
        raise ReleaseVerificationError(f"release version is {manifest.get('version')}, expected {expected_version}")
    if expected_commit and manifest.get("commit") != expected_commit:
        raise ReleaseVerificationError("release commit does not match the expected source commit")
    _verify_hashes(manifest, root)
    _verify_archives(manifest, root)
    _verify_spdx(manifest, root)
    return {"status": "verified", "version": manifest["version"], "commit": manifest["commit"], "artifact_count": len(manifest["artifacts"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Forge release hashes, archives, and SPDX metadata offline.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, help="directory containing the manifest and artifacts; defaults to the manifest directory")
    parser.add_argument("--version", dest="expected_version")
    parser.add_argument("--commit", dest="expected_commit")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = (args.root or args.manifest.parent).resolve()
        result = verify_release(args.manifest.resolve(), root, expected_version=args.expected_version, expected_commit=args.expected_commit)
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else f"Verified Forge {result['version']} release artifacts offline.")
        return 0
    except (OSError, ReleaseVerificationError, ValueError, json.JSONDecodeError) as exc:
        print(f"verify_release: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
