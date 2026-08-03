"""Tests for the dependency-free Codex plugin validator."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION = json.loads((REPO / "plugins/forge/.claude-plugin/plugin.json").read_text())["version"]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_directory_and_exact_codex_archive_validate(tmp_path):
    build = load(REPO / "scripts/build_release.py", "forge_release_build_for_codex_validation")
    validate = load(REPO / "scripts/validate_codex_plugin.py", "forge_codex_validator")

    assert validate.validate_plugin(REPO / "plugins/forge", VERSION) == []
    build.build_release(REPO, tmp_path, VERSION, source_epoch=1_754_000_000, enforce_clean=False)

    assert validate.validate_archive(tmp_path / f"forge-{VERSION}-codex.tar.gz", VERSION) == []
