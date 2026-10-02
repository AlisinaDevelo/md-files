"""Offline host model inventory and binding contract tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-models.py"
LAUNCHER = REPO / "scripts/forge-models.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_models", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def inventory(*, host: str = "codex") -> dict:
    return {
        "schema_version": 1,
        "host": host,
        "models": [
            {"id": "example/strong-v1", "reasoning_efforts": ["high", "medium"]},
            {"id": "example/fast-v1", "reasoning_efforts": ["low", "medium"]},
        ],
        "retired_model_ids": ["example/retired-v1"],
    }


def profile(*, host: str = "codex") -> dict:
    return {
        "schema_version": 1,
        "host": host,
        "tiers": {
            "deep": {"model": "example/strong-v1", "effort": "high"},
            "fast": {"model": "example/fast-v1", "effort": "low"},
        },
    }


def test_explicit_pin_and_effort_override_profile_mapping():
    module = load_module()

    result = module.resolve(
        "codex",
        inventory(),
        profile(),
        "deep",
        model_pin="example/fast-v1",
        effort="low",
    )

    assert result["model"] == "example/fast-v1"
    assert result["effort"] == "low"
    assert result["host"] == "codex"
    assert result["inventory_digest"].startswith("sha256:")
    assert result["profile_digest"].startswith("sha256:")
    assert set(result) == {
        "schema_version",
        "host",
        "model",
        "effort",
        "inventory_digest",
        "profile_digest",
    }


def test_pin_does_not_silently_fall_back_when_retired_or_unknown():
    module = load_module()

    with pytest.raises(module.ModelBindingError) as retired:
        module.resolve(
            "codex", inventory(), profile(), "deep", model_pin="example/retired-v1"
        )
    assert retired.value.code == "model_retired"

    with pytest.raises(module.ModelBindingError) as unknown:
        module.resolve(
            "codex", inventory(), profile(), "deep", model_pin="example/missing-v1"
        )
    assert unknown.value.code == "model_unavailable"


def test_mapped_model_and_explicit_effort_must_be_in_inventory():
    module = load_module()
    stale_profile = profile()
    stale_profile["tiers"]["deep"]["model"] = "example/missing-v1"

    with pytest.raises(module.ModelBindingError) as missing_model:
        module.resolve("codex", inventory(), stale_profile, "deep")
    assert missing_model.value.code == "model_unavailable"

    with pytest.raises(module.ModelBindingError) as effort:
        module.resolve("codex", inventory(), profile(), "fast", effort="high")
    assert effort.value.code == "effort_unsupported"

    with pytest.raises(module.ModelBindingError) as invalid_effort:
        module.resolve("codex", inventory(), profile(), "deep", effort="turbo")
    assert invalid_effort.value.code == "invalid_effort"


def test_explicit_pin_wins_over_stale_tier_model_but_tier_must_exist():
    module = load_module()
    stale_profile = profile()
    stale_profile["tiers"]["deep"]["model"] = "example/missing-v1"

    result = module.resolve(
        "codex",
        inventory(),
        stale_profile,
        "deep",
        model_pin="example/fast-v1",
        effort="low",
    )
    assert result["model"] == "example/fast-v1"

    with pytest.raises(module.ModelBindingError) as missing:
        module.resolve(
            "codex",
            inventory(),
            profile(),
            "unconfigured",
            model_pin="example/fast-v1",
            effort="low",
        )
    assert missing.value.code == "mapping_missing"


def test_host_mismatch_and_invalid_aliases_fail_closed():
    module = load_module()

    with pytest.raises(module.ModelBindingError) as mismatch:
        module.resolve("opencode", inventory(), profile(), "deep")
    assert mismatch.value.code == "host_mismatch"

    with pytest.raises(module.ModelBindingError) as profile_mismatch:
        module.resolve("codex", inventory(), profile(host="opencode"), "deep")
    assert profile_mismatch.value.code == "host_mismatch"

    alias_profile = profile()
    alias_profile["tiers"]["deep"]["model"] = "sonnet"
    with pytest.raises(module.ModelBindingError) as alias:
        module.resolve("codex", inventory(), alias_profile, "deep")
    assert alias.value.code == "invalid_model"

    malformed_profile = profile()
    malformed_profile["tiers"]["deep"]["model"] = "example/model-v1/"
    with pytest.raises(module.ModelBindingError) as malformed:
        module.resolve("codex", inventory(), malformed_profile, "deep")
    assert malformed.value.code == "invalid_value"


def test_missing_effort_is_not_invented_and_outputs_remain_minimal():
    module = load_module()
    no_effort_profile = profile()
    del no_effort_profile["tiers"]["deep"]["effort"]

    result = module.resolve("codex", inventory(), no_effort_profile, "deep")

    assert result["model"] == "example/strong-v1"
    assert "effort" not in result


def test_digests_ignore_object_and_set_like_list_order():
    module = load_module()
    first_inventory = inventory()
    second_inventory = {
        "retired_model_ids": ["example/retired-v1"],
        "models": [
            {"reasoning_efforts": ["medium", "high"], "id": "example/strong-v1"},
            {"reasoning_efforts": ["medium", "low"], "id": "example/fast-v1"},
        ],
        "host": "codex",
        "schema_version": 1,
    }
    first_profile = profile()
    second_profile = {
        "tiers": {
            "fast": {"effort": "low", "model": "example/fast-v1"},
            "deep": {"effort": "high", "model": "example/strong-v1"},
        },
        "host": "codex",
        "schema_version": 1,
    }

    assert (
        module.inspect_inventory(first_inventory)["inventory_digest"]
        == module.inspect_inventory(second_inventory)["inventory_digest"]
    )
    assert (
        module.inspect_profile(first_profile)["profile_digest"]
        == module.inspect_profile(second_profile)["profile_digest"]
    )


def test_unexpected_raw_fields_and_unsafe_json_are_rejected(tmp_path: Path):
    module = load_module()
    unsafe = inventory()
    unsafe["prompt"] = "not inventory data"
    with pytest.raises(module.ModelBindingError) as unexpected:
        module.inspect_inventory(unsafe)
    assert unexpected.value.code == "unknown_field"

    duplicate_key_file = tmp_path / "duplicate.json"
    duplicate_key_file.write_text(
        '{"schema_version":1,"schema_version":1,"host":"codex","models":[],"retired_model_ids":[]}',
        encoding="utf-8",
    )
    with pytest.raises(module.ModelBindingError) as duplicate:
        module.load_json(duplicate_key_file, "inventory")
    assert duplicate.value.code == "duplicate_key"


def test_inventory_size_is_bounded(tmp_path: Path):
    module = load_module()
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (module.MAX_INPUT_BYTES + 1))

    with pytest.raises(module.ModelBindingError) as error:
        module.load_json(oversized, "inventory")
    assert error.value.code == "input_too_large"


def test_launcher_resolves_offline_and_emits_bound_selection(tmp_path: Path):
    inv_path = tmp_path / "inventory.json"
    profile_path = tmp_path / "profile.json"
    inv_path.write_text(json.dumps(inventory()), encoding="utf-8")
    profile_path.write_text(json.dumps(profile()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER),
            "resolve",
            "--host",
            "codex",
            "--inventory",
            str(inv_path),
            "--profile",
            str(profile_path),
            "--tier",
            "deep",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["model"] == "example/strong-v1"
    assert result["effort"] == "high"
    assert result["inventory_digest"].startswith("sha256:")


def test_packaged_resolver_replays_without_repository_imports(tmp_path: Path):
    from test_codex_plugin_validation import VERSION, load

    builder = load(REPO / "scripts/build_release.py", "forge_models_release_builder")
    validator = load(REPO / "scripts/validate_codex_plugin.py", "forge_models_package_validator")
    dist = tmp_path / "dist"
    builder.build_release(REPO, dist, VERSION, source_epoch=1_754_000_000, enforce_clean=False)
    root = validator.extract_zip(dist / f"forge-{VERSION}-openai.zip", tmp_path / "installed")
    installed_script = root / "skills/orchestration/scripts/forge-models.py"
    inv_path = tmp_path / "inventory.json"
    profile_path = tmp_path / "profile.json"
    inv_path.write_text(json.dumps(inventory()), encoding="utf-8")
    profile_path.write_text(json.dumps(profile()), encoding="utf-8")
    command = [sys.executable, str(installed_script), "resolve", "--host", "codex", "--inventory", str(inv_path), "--profile", str(profile_path), "--tier", "deep"]
    expected = load_module().resolve("codex", inventory(), profile(), "deep")
    for _ in range(2):
        result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=True)
        assert json.loads(result.stdout) == expected
