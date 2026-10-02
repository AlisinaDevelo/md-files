#!/usr/bin/env python3
"""Inspect host model inventories and resolve exact, offline Forge bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
HOSTS = {"codex", "claude", "opencode"}
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
MODEL_ALIASES = {
    "best",
    "default",
    "fable",
    "haiku",
    "inherit",
    "opus",
    "opusplan",
    "sonnet",
}
MAX_INPUT_BYTES = 65_536
MAX_MODELS = 128
MAX_PROFILE_TIERS = 64
MAX_EFFORTS = len(EFFORTS)

HOST_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
MODEL_ID_RE = re.compile(
    r"^(?:[A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9._:/#@+-]{0,254}[A-Za-z0-9])$"
)
TIER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

INVENTORY_KEYS = {"schema_version", "host", "models", "retired_model_ids"}
MODEL_KEYS = {"id", "reasoning_efforts"}
PROFILE_KEYS = {"schema_version", "host", "tiers"}
TIER_KEYS = {"model", "effort"}


class ModelBindingError(ValueError):
    """Raised when an inventory, profile, or requested binding is invalid."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise ModelBindingError(code, message)


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_key", "input JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    _fail("invalid_json", "input JSON contains a non-finite number")


def load_json(path: Path, label: str) -> Any:
    """Read a bounded UTF-8 JSON document without accepting duplicate keys."""
    try:
        with path.open("rb") as source_file:
            raw = source_file.read(MAX_INPUT_BYTES + 1)
    except OSError as error:
        raise ModelBindingError("input_unreadable", f"cannot read {label}") from error
    if len(raw) > MAX_INPUT_BYTES:
        _fail("input_too_large", f"{label} exceeds the input size limit")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ModelBindingError("invalid_encoding", f"{label} must be UTF-8") from error
    try:
        return json.loads(
            source,
            object_pairs_hook=_pairs_without_duplicates,
            parse_constant=_reject_constant,
        )
    except ModelBindingError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise ModelBindingError(
            "invalid_json", f"{label} is not valid bounded JSON"
        ) from error


def _object(
    value: Any, label: str, *, allowed: set[str], required: set[str]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("invalid_shape", f"{label} must be an object")
    unknown = set(value) - allowed
    if unknown:
        _fail("unknown_field", f"{label} contains an unexpected field")
    if required - set(value):
        _fail("missing_field", f"{label} is missing a required field")
    return value


def _string(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        _fail("invalid_value", f"{label} has an invalid format")
    return value


def _host(value: Any) -> str:
    host = _string(value, "host", HOST_RE)
    if host not in HOSTS:
        _fail("unsupported_host", "host must be codex, claude, or opencode")
    return host


def _model_id(value: Any) -> str:
    model_id = _string(value, "model id", MODEL_ID_RE)
    lowered = model_id.lower()
    if lowered in MODEL_ALIASES or re.fullmatch(r"(?:opus|sonnet)\[1m\]", lowered):
        _fail(
            "invalid_model",
            "model ids must be exact host ids, not aliases or inheritance markers",
        )
    return model_id


def _effort(value: Any) -> str:
    effort = _string(value, "reasoning effort", HOST_RE)
    if effort not in EFFORTS:
        _fail("invalid_effort", "reasoning effort is not a supported normalized level")
    return effort


def _tier(value: Any) -> str:
    return _string(value, "tier", TIER_RE)


def _version(value: Any) -> None:
    if type(value) is not int or value != SCHEMA_VERSION:
        _fail("unsupported_schema", "schema_version must be 1")


def validate_inventory(value: Any) -> dict[str, Any]:
    inventory = _object(
        value, "inventory", allowed=INVENTORY_KEYS, required=INVENTORY_KEYS
    )
    _version(inventory["schema_version"])
    host = _host(inventory["host"])

    models_value = inventory["models"]
    if not isinstance(models_value, list) or len(models_value) > MAX_MODELS:
        _fail(
            "invalid_models", f"models must be an array of at most {MAX_MODELS} entries"
        )
    models: list[dict[str, Any]] = []
    seen_models: set[str] = set()
    for item in models_value:
        row = _object(item, "model entry", allowed=MODEL_KEYS, required=MODEL_KEYS)
        model_id = _model_id(row["id"])
        if model_id in seen_models:
            _fail("duplicate_model", "inventory model ids must be unique")
        seen_models.add(model_id)
        efforts_value = row["reasoning_efforts"]
        if not isinstance(efforts_value, list) or len(efforts_value) > MAX_EFFORTS:
            _fail("invalid_efforts", "reasoning_efforts must be a bounded array")
        efforts = [_effort(item) for item in efforts_value]
        if len(set(efforts)) != len(efforts):
            _fail("duplicate_effort", "reasoning effort entries must be unique")
        models.append({"id": model_id, "reasoning_efforts": sorted(efforts)})

    retired_value = inventory["retired_model_ids"]
    if not isinstance(retired_value, list) or len(retired_value) > MAX_MODELS:
        _fail(
            "invalid_retired_models",
            f"retired_model_ids must be an array of at most {MAX_MODELS} entries",
        )
    retired = [_model_id(item) for item in retired_value]
    if len(set(retired)) != len(retired):
        _fail("duplicate_model", "retired model ids must be unique")
    if seen_models.intersection(retired):
        _fail("inventory_conflict", "a model cannot be both available and retired")

    return {
        "schema_version": SCHEMA_VERSION,
        "host": host,
        "models": sorted(models, key=lambda item: item["id"]),
        "retired_model_ids": sorted(retired),
    }


def validate_profile(value: Any) -> dict[str, Any]:
    profile = _object(value, "profile", allowed=PROFILE_KEYS, required=PROFILE_KEYS)
    _version(profile["schema_version"])
    host = _host(profile["host"])
    tiers_value = profile["tiers"]
    if not isinstance(tiers_value, dict) or len(tiers_value) > MAX_PROFILE_TIERS:
        _fail(
            "invalid_tiers",
            f"tiers must be an object of at most {MAX_PROFILE_TIERS} entries",
        )

    tiers: dict[str, dict[str, str]] = {}
    for raw_tier, raw_mapping in tiers_value.items():
        tier = _tier(raw_tier)
        mapping = _object(
            raw_mapping, "tier mapping", allowed=TIER_KEYS, required={"model"}
        )
        normalized = {"model": _model_id(mapping["model"])}
        if "effort" in mapping:
            normalized["effort"] = _effort(mapping["effort"])
        tiers[tier] = normalized

    return {"schema_version": SCHEMA_VERSION, "host": host, "tiers": tiers}


def _digest(value: Any) -> str:
    canonical = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def inspect_inventory(value: Any, host: str | None = None) -> dict[str, Any]:
    inventory = validate_inventory(value)
    if host is not None and _host(host) != inventory["host"]:
        _fail("host_mismatch", "requested host does not match the inventory")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "inventory",
        "host": inventory["host"],
        "model_count": len(inventory["models"]),
        "retired_model_count": len(inventory["retired_model_ids"]),
        "models": inventory["models"],
        "retired_model_ids": inventory["retired_model_ids"],
        "inventory_digest": _digest(inventory),
    }


def inspect_profile(value: Any, host: str | None = None) -> dict[str, Any]:
    profile = validate_profile(value)
    if host is not None and _host(host) != profile["host"]:
        _fail("host_mismatch", "requested host does not match the profile")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "profile",
        "host": profile["host"],
        "tier_count": len(profile["tiers"]),
        "tiers": profile["tiers"],
        "profile_digest": _digest(profile),
    }


def resolve(
    host: str,
    inventory_value: Any,
    profile_value: Any,
    tier_value: str,
    *,
    model_pin: str | None = None,
    effort: str | None = None,
) -> dict[str, Any]:
    inventory = validate_inventory(inventory_value)
    profile = validate_profile(profile_value)
    requested_host = _host(host)
    if requested_host != inventory["host"] or requested_host != profile["host"]:
        _fail("host_mismatch", "requested host, inventory, and profile must match")

    tier = _tier(tier_value)
    mapping = profile["tiers"].get(tier)
    if mapping is None:
        _fail("mapping_missing", "profile has no mapping for the requested tier")

    selected_model = _model_id(model_pin) if model_pin is not None else mapping["model"]
    available = {item["id"]: item for item in inventory["models"]}
    if selected_model not in available:
        if selected_model in inventory["retired_model_ids"]:
            _fail("model_retired", "selected model is retired in this inventory")
        _fail(
            "model_unavailable",
            "selected model is not present in the available inventory",
        )

    selected_effort = _effort(effort) if effort is not None else mapping.get("effort")
    if (
        selected_effort is not None
        and selected_effort not in available[selected_model]["reasoning_efforts"]
    ):
        _fail(
            "effort_unsupported",
            "selected model does not list the requested reasoning effort",
        )

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "host": requested_host,
        "model": selected_model,
        "inventory_digest": _digest(inventory),
        "profile_digest": _digest(profile),
    }
    if selected_effort is not None:
        result["effort"] = selected_effort
    return result


def _write_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or resolve offline Forge host model bindings"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    inspect = subcommands.add_parser(
        "inspect", help="validate and inspect one inventory or profile"
    )
    source = inspect.add_mutually_exclusive_group(required=True)
    source.add_argument("--inventory", type=Path)
    source.add_argument("--profile", type=Path)
    inspect.add_argument(
        "--host", choices=sorted(HOSTS), help="require this host in the input"
    )

    resolve_parser = subcommands.add_parser(
        "resolve", help="resolve one tier to an exact available host model"
    )
    resolve_parser.add_argument("--host", choices=sorted(HOSTS), required=True)
    resolve_parser.add_argument("--inventory", type=Path, required=True)
    resolve_parser.add_argument("--profile", type=Path, required=True)
    resolve_parser.add_argument("--tier", required=True)
    resolve_parser.add_argument(
        "--model", dest="model_pin", help="explicit exact model pin; never falls back"
    )
    resolve_parser.add_argument("--effort", help="explicit normalized reasoning effort")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            if args.inventory:
                result = inspect_inventory(
                    load_json(args.inventory, "inventory"), args.host
                )
            else:
                result = inspect_profile(load_json(args.profile, "profile"), args.host)
            _write_json(result)
            return 0

        result = resolve(
            args.host,
            load_json(args.inventory, "inventory"),
            load_json(args.profile, "profile"),
            args.tier,
            model_pin=args.model_pin,
            effort=args.effort,
        )
        _write_json(result)
        return 0
    except ModelBindingError as error:
        _write_json({"status": "error", "code": error.code, "message": str(error)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
