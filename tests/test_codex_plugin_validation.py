"""Tests for the dependency-free Codex plugin validator."""

from __future__ import annotations

import importlib.util
import json
import shutil
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


def test_codex_marketplace_contract_and_local_source_validate():
    validate = load(REPO / "scripts/validate_codex_plugin.py", "forge_codex_marketplace_validator")

    assert validate.validate_marketplace(
        REPO / ".agents/plugins/marketplace.json", REPO
    ) == []


def test_codex_marketplace_rejects_invalid_policy(tmp_path):
    validate = load(REPO / "scripts/validate_codex_plugin.py", "forge_codex_marketplace_invalid")
    marketplace = tmp_path / "marketplace.json"
    marketplace.write_text(
        json.dumps(
            {
                "name": "test",
                "plugins": [
                    {
                        "name": "forge",
                        "source": {"source": "local", "path": "./plugins/forge"},
                        "policy": {"installation": "MAYBE", "authentication": "ON_INSTALL"},
                        "category": "Engineering",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    errors = validate.validate_marketplace(marketplace)
    assert "marketplace.json plugins[0].policy.installation has an unsupported value" in errors


def test_codex_plugin_rejects_unsupported_interface_category(tmp_path):
    validate = load(REPO / "scripts/validate_codex_plugin.py", "forge_codex_invalid_category")
    plugin = tmp_path / "plugin"
    shutil.copytree(REPO / "plugins/forge", plugin)
    manifest_path = plugin / ".codex-plugin/plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["interface"]["category"] = "Engineering"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = validate.validate_plugin(plugin, VERSION)
    assert "plugin.json interface.category must use a supported Codex category" in errors


def test_codex_plugin_rejects_non_square_logo(tmp_path):
    validate = load(REPO / "scripts/validate_codex_plugin.py", "forge_codex_invalid_logo")
    plugin = tmp_path / "plugin"
    shutil.copytree(REPO / "plugins/forge", plugin)
    logo = bytearray((plugin / "assets/logo.png").read_bytes())
    logo[16:20] = (512).to_bytes(4, "big")
    logo[20:24] = (160).to_bytes(4, "big")
    (plugin / "assets/logo.png").write_bytes(logo)

    errors = validate.validate_plugin(plugin, VERSION)
    assert "interface.logo must be square (got 512x160)" in errors
