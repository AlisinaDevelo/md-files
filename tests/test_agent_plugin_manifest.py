"""Portable manifest precedence and release-profile regression tests."""

from __future__ import annotations

import json
import shutil
import zipfile

import pytest

from test_codex_plugin_validation import REPO, VERSION, load


@pytest.fixture
def validator():
    return load(REPO / "scripts/validate_codex_plugin.py", "forge_portable_validator")


@pytest.fixture
def plugin(tmp_path):
    root = tmp_path / "plugin"
    shutil.copytree(REPO / "plugins/forge", root)
    return root


def write(root, relative, value):
    (root / relative).write_text(json.dumps(value), encoding="utf-8")


def test_generated_manifest_is_deterministic():
    compiler = load(REPO / "scripts/compile_agent_plugin.py", "forge_portable_compiler")
    assert compiler.render(REPO) == compiler.render(REPO)
    assert compiler.render(REPO) == (REPO / "plugins/forge/plugin.json").read_text()


def test_portable_identity_and_inline_settings_replace_overlay(plugin, validator):
    overlay = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
    overlay["version"] = "not-semver"
    overlay["skills"] = "./wrong/"
    overlay["interface"]["category"] = "wrong"
    overlay["apps"] = "./missing.json"
    write(plugin, ".codex-plugin/plugin.json", overlay)
    assert validator.validate_plugin(plugin, VERSION) == []
    assert "plugin.json skills must resolve to ./skills/" in validator.validate_openai_plugin(plugin, VERSION)
    assert validator.validate_plugin(plugin, VERSION, legacy_only=True)
    (plugin / ".codex-plugin/plugin.json").unlink()
    assert validator.validate_plugin(plugin, VERSION) == []


def test_absent_inline_settings_use_overlay_without_changing_identity(plugin, validator):
    manifest = json.loads((plugin / "plugin.json").read_text())
    manifest["extensions"] = {"org.example": {"unknown": True}}
    write(plugin, "plugin.json", manifest)
    overlay = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
    overlay["version"] = "different"
    overlay["skills"] = "./wrong/"
    write(plugin, ".codex-plugin/plugin.json", overlay)
    assert validator.validate_plugin(plugin, VERSION) == []


def test_empty_inline_settings_do_not_merge_overlay(plugin, validator):
    manifest = json.loads((plugin / "plugin.json").read_text())
    manifest["extensions"]["com.openai"] = {}
    write(plugin, "plugin.json", manifest)
    assert "plugin.json interface must be an object" in validator.validate_plugin(plugin)


@pytest.mark.parametrize("change", [
    {"$schema": "https://example.com/schema"},
    {"name": "Bad--Name"},
    {"skills": "./skills/"},
    {"keywords": [1]},
    {"keywords": None},
    {"author": {"name": "test", "unknown": "bad"}},
    {"extensions": {"com.openai": None}},
    {"extensions": {"com.openai": {"name": "shadow"}}},
])
def test_invalid_portable_manifest_never_falls_back(plugin, validator, change):
    manifest = json.loads((plugin / "plugin.json").read_text())
    manifest.update(change)
    write(plugin, "plugin.json", manifest)
    assert validator.validate_plugin(plugin, VERSION)


@pytest.mark.parametrize("contents", [b"not-json", b"\xff", b'{"name":"a","name":"b"}', b'{"extensions":{"org.example":{"value":NaN}}}'])
def test_invalid_json_fails_without_overlay_fallback(plugin, validator, contents):
    (plugin / "plugin.json").write_bytes(contents)
    assert "plugin.json must contain valid JSON" in validator.validate_plugin(plugin)


@pytest.mark.parametrize("field,value,expected", [
    ("brandColor", "#FFFFFF", "at least 2:1 contrast"),
    ("shortDescription", "x" * 31, "at most 30 characters"),
])
def test_listing_constraints_are_checked_locally(plugin, validator, field, value, expected):
    manifest = json.loads((plugin / "plugin.json").read_text())
    manifest["extensions"]["com.openai"]["interface"][field] = value
    write(plugin, "plugin.json", manifest)
    assert any(expected in error for error in validator.validate_plugin(plugin))


def test_portable_mcp_is_not_accepted_in_skills_only_profile(plugin, validator):
    (plugin / "mcp.json").write_text("{}")
    assert "skills-only plugin must not include mcp.json" in validator.validate_openai_plugin(plugin)


@pytest.mark.parametrize("prefix", ["", "forge/"])
def test_zip_accepts_portable_and_legacy_manifests_at_one_root(plugin, validator, tmp_path, prefix):
    archive_path = tmp_path / "plugin.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for path in plugin.rglob("*"):
            if path.is_file() and (path.relative_to(plugin).parts[0] in {"plugin.json", ".codex-plugin", "skills", "assets"}):
                archive.write(path, prefix + path.relative_to(plugin).as_posix())
    assert validator.validate_openai_zip(archive_path, VERSION) == []


def test_zip_rejects_two_portable_roots(tmp_path, validator):
    archive_path = tmp_path / "multiple.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("one/plugin.json", "{}")
        archive.writestr("two/plugin.json", "{}")
    assert validator.validate_openai_zip(archive_path) == ["archive has multiple plugin roots"]


def test_legacy_manifest_remains_supported(plugin, validator):
    (plugin / "plugin.json").unlink()
    assert validator.validate_plugin(plugin, VERSION) == []


def test_invalid_skill_encoding_is_reported(plugin, validator):
    skill = plugin / "skills/orchestration/SKILL.md"
    skill.write_bytes(b"\xff")
    assert "skill orchestration is not readable" in validator.validate_plugin(plugin, VERSION)


@pytest.mark.parametrize("name", ["skills/example/./SKILL.md", "./plugin.json", ".codex-plugin/./plugin.json"])
def test_zip_rejects_raw_dot_segment_aliases(tmp_path, validator, name):
    archive_path = tmp_path / "alias.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("plugin.json", (REPO / "plugins/forge/plugin.json").read_bytes())
        archive.writestr(name, b"alias")
    assert any("unsafe member" in error for error in validator.validate_openai_zip(archive_path))


def test_compiler_rejects_duplicate_keys_in_compatibility_source(tmp_path):
    compiler = load(REPO / "scripts/compile_agent_plugin.py", "forge_portable_strict_compiler")
    repo = tmp_path / "repo"
    shutil.copytree(REPO / "plugins/forge", repo / "plugins/forge")
    shutil.copytree(REPO / "scripts", repo / "scripts")
    source = repo / "plugins/forge/.codex-plugin/plugin.json"
    source.write_text('{"name":"forge","name":"shadow"}')
    import subprocess
    with pytest.raises(subprocess.CalledProcessError):
        compiler.render(repo)
