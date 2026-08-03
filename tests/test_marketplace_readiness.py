"""Tests for marketplace metadata, resources, and effect boundaries."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_json(relative: str) -> dict:
    return json.loads((REPO / relative).read_text(encoding="utf-8"))


def test_codex_directory_metadata_is_https_and_assets_are_real_files():
    manifest = load_json("plugins/forge/.codex-plugin/plugin.json")
    interface = manifest["interface"]

    for field in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
        assert interface[field].startswith("https://")
    assert interface["screenshots"] == []
    for field in ("composerIcon", "logo", "logoDark"):
        asset = interface[field].removeprefix("./")
        assert (REPO / "plugins/forge" / asset).is_file(), field


def test_marketplace_and_plugin_versions_stay_aligned():
    claude = load_json("plugins/forge/.claude-plugin/plugin.json")
    codex = load_json("plugins/forge/.codex-plugin/plugin.json")
    marketplace = load_json(".claude-plugin/marketplace.json")
    versions = {
        claude["version"],
        codex["version"],
        marketplace["metadata"]["version"],
        marketplace["plugins"][0]["version"],
    }
    assert len(versions) == 1


def test_high_risk_github_and_release_effects_remain_approval_gated():
    github = load_json("policies/github-mutation.json")
    release = load_json("policies/release.json")
    github_rules = {rule["id"]: rule for rule in github["rules"]}
    release_rules = {rule["id"]: rule for rule in release["rules"]}

    assert github_rules["github-stack-merge"]["decision"] == "require_approval"
    assert release_rules["release-effect"]["decision"] == "require_approval"
