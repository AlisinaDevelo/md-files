#!/usr/bin/env python3
"""Make deterministic, privacy-safe Forge route decisions and replay route policies offline."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CONTRACT_REVISION = "forge-routing-v1"
MAX_ROUTES = 64
MAX_OUTCOMES = 4096
MAX_EPISODES = 4096
ROUTING_MODES = {"static", "adaptive", "disabled"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
REFERENCE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
FORBIDDEN_KEYS = {
    "api_key",
    "arguments",
    "authorization",
    "body",
    "content",
    "credential",
    "message",
    "output",
    "password",
    "prompt",
    "raw",
    "response",
    "result",
    "secret",
    "token",
    "tool_arg",
    "tool_argument",
    "tool_input",
    "tool_output",
    "tool_result",
}
POLICY_KEYS = {
    "schema_version",
    "contract_revision",
    "policy_id",
    "policy_revision",
    "mode",
    "budgets",
    "activation",
    "routes",
}
BUDGET_KEYS = {
    "max_input_tokens",
    "max_output_tokens",
    "max_cost_usd",
    "max_latency_ms",
    "max_concurrency",
}
ACTIVATION_KEYS = {
    "min_samples",
    "min_confidence",
    "max_quality_regression",
    "max_cost_increase_usd",
    "max_failure_rate_increase",
    "max_approval_burden_increase",
    "max_replay_cost_usd",
}
ROUTE_KEYS = {
    "route_id",
    "provider",
    "model",
    "static_score",
    "capabilities",
    "cost_usd_per_1k_input",
    "cost_usd_per_1k_output",
    "latency_ms",
    "fallback_route_ids",
}
CAPABILITY_KEYS = {
    "tools",
    "structured_output",
    "context_tokens",
    "modalities",
    "regions",
    "hosts",
    "data_policies",
    "replay_safe",
}
REQUEST_KEYS = {
    "schema_version",
    "request_id",
    "episode_id",
    "task_id",
    "host",
    "required_tools",
    "structured_output",
    "context_tokens",
    "modalities",
    "region",
    "data_policy",
    "replay_required",
    "input_tokens",
    "output_tokens",
    "current_concurrency",
    "pin",
    "disable_adaptation",
}
PIN_KEYS = {"route_id", "provider", "model"}
OUTCOME_KEYS = {
    "route_id",
    "sample_id",
    "quality_score",
    "cost_usd",
    "latency_ms",
    "failed",
    "approval_burden",
}
EPISODE_KEYS = {"schema_version", "episode_id", "request", "outcomes"}


class RoutingError(ValueError):
    """Raised when a routing policy, request, or replay artifact is invalid."""


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise RoutingError(f"value is not canonical JSON: {error}") from error


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RoutingError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise RoutingError(f"{label} keys must be strings")
    return {str(key): copy.deepcopy(child) for key, child in value.items()}


def _unknown(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RoutingError(f"unknown {label} field(s): {', '.join(unknown)}")


def _string(value: Any, label: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoutingError(f"{label} must be a non-empty string")
    if pattern is not None and not pattern.fullmatch(value):
        raise RoutingError(f"{label} has an invalid format")
    return value


def _number(value: Any, label: str, *, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
        raise RoutingError(f"{label} must be a non-negative number")
    result = float(value)
    if maximum is not None and result > maximum:
        raise RoutingError(f"{label} must be at most {maximum}")
    return result


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RoutingError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RoutingError(f"{label} must be a non-negative integer")
    return value


def _string_list(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise RoutingError(f"{label} must be a string array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise RoutingError(f"{label} must contain only non-empty strings")
    if len(set(value)) != len(value):
        raise RoutingError(f"{label} must not contain duplicates")
    return sorted(value)


def _reject_forbidden(value: Any, path: str = "value") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in FORBIDDEN_KEYS:
                raise RoutingError(f"privacy boundary rejected {path}.{key}")
            _reject_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden(child, f"{path}[{index}]")


def _normalize_capabilities(value: Any, label: str) -> dict[str, Any]:
    capabilities = _mapping(value, label)
    _unknown(capabilities, CAPABILITY_KEYS, label)
    normalized = {
        "tools": _string_list(capabilities.get("tools", []), f"{label}.tools"),
        "structured_output": capabilities.get("structured_output"),
        "context_tokens": _positive_int(capabilities.get("context_tokens"), f"{label}.context_tokens"),
        "modalities": _string_list(capabilities.get("modalities", []), f"{label}.modalities", allow_empty=False),
        "regions": _string_list(capabilities.get("regions", []), f"{label}.regions", allow_empty=False),
        "hosts": _string_list(capabilities.get("hosts", []), f"{label}.hosts", allow_empty=False),
        "data_policies": _string_list(capabilities.get("data_policies", []), f"{label}.data_policies", allow_empty=False),
        "replay_safe": capabilities.get("replay_safe"),
    }
    if not isinstance(normalized["structured_output"], bool):
        raise RoutingError(f"{label}.structured_output must be a boolean")
    if not isinstance(normalized["replay_safe"], bool):
        raise RoutingError(f"{label}.replay_safe must be a boolean")
    return normalized


def _normalize_budgets(value: Any, label: str) -> dict[str, Any]:
    budgets = _mapping(value, label)
    _unknown(budgets, BUDGET_KEYS, label)
    required = BUDGET_KEYS - set(budgets)
    if required:
        raise RoutingError(f"{label} is missing: {', '.join(sorted(required))}")
    normalized = {
        "max_input_tokens": _nonnegative_int(budgets["max_input_tokens"], f"{label}.max_input_tokens"),
        "max_output_tokens": _nonnegative_int(budgets["max_output_tokens"], f"{label}.max_output_tokens"),
        "max_cost_usd": _number(budgets["max_cost_usd"], f"{label}.max_cost_usd"),
        "max_latency_ms": _positive_int(budgets["max_latency_ms"], f"{label}.max_latency_ms"),
        "max_concurrency": _positive_int(budgets["max_concurrency"], f"{label}.max_concurrency"),
    }
    return normalized


def _normalize_activation(value: Any, label: str) -> dict[str, Any]:
    activation = _mapping(value, label)
    _unknown(activation, ACTIVATION_KEYS, label)
    required = ACTIVATION_KEYS - set(activation)
    if required:
        raise RoutingError(f"{label} is missing: {', '.join(sorted(required))}")
    return {
        "min_samples": _positive_int(activation["min_samples"], f"{label}.min_samples"),
        "min_confidence": _number(activation["min_confidence"], f"{label}.min_confidence", maximum=1.0),
        "max_quality_regression": _number(
            activation["max_quality_regression"], f"{label}.max_quality_regression", maximum=1.0
        ),
        "max_cost_increase_usd": _number(activation["max_cost_increase_usd"], f"{label}.max_cost_increase_usd"),
        "max_failure_rate_increase": _number(
            activation["max_failure_rate_increase"], f"{label}.max_failure_rate_increase", maximum=1.0
        ),
        "max_approval_burden_increase": _number(
            activation["max_approval_burden_increase"], f"{label}.max_approval_burden_increase"
        ),
        "max_replay_cost_usd": _number(activation["max_replay_cost_usd"], f"{label}.max_replay_cost_usd"),
    }


def _validate_fallback_graph(routes: list[dict[str, Any]]) -> None:
    route_ids = {route["route_id"] for route in routes}
    for route in routes:
        for fallback in route["fallback_route_ids"]:
            if fallback not in route_ids:
                raise RoutingError(f"{route['route_id']} references unknown fallback route: {fallback}")
            if fallback == route["route_id"]:
                raise RoutingError(f"{route['route_id']} cannot fall back to itself")
    visiting: set[str] = set()
    visited: set[str] = set()
    graph = {route["route_id"]: route["fallback_route_ids"] for route in routes}

    def visit(route_id: str) -> None:
        if route_id in visiting:
            raise RoutingError("fallback routes must not contain cycles")
        if route_id in visited:
            return
        visiting.add(route_id)
        for fallback in graph[route_id]:
            visit(fallback)
        visiting.remove(route_id)
        visited.add(route_id)

    for route_id in sorted(graph):
        visit(route_id)


def validate_policy(value: Any) -> dict[str, Any]:
    _reject_forbidden(value, "policy")
    policy = _mapping(value, "policy")
    _unknown(policy, POLICY_KEYS, "policy")
    if policy.get("schema_version") != SCHEMA_VERSION:
        raise RoutingError(f"unsupported policy schema_version: {policy.get('schema_version')}")
    if policy.get("contract_revision") != CONTRACT_REVISION:
        raise RoutingError("unsupported routing contract revision")
    policy_id = _string(policy.get("policy_id"), "policy.policy_id", pattern=ID_RE)
    mode = policy.get("mode")
    if mode not in ROUTING_MODES:
        raise RoutingError("policy.mode must be static, adaptive, or disabled")
    budgets = _normalize_budgets(policy.get("budgets"), "policy.budgets")
    activation = _normalize_activation(policy.get("activation"), "policy.activation")
    raw_routes = policy.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes or len(raw_routes) > MAX_ROUTES:
        raise RoutingError(f"policy.routes must contain between 1 and {MAX_ROUTES} routes")
    routes: list[dict[str, Any]] = []
    route_ids: set[str] = set()
    for index, raw_route in enumerate(raw_routes):
        route = _mapping(raw_route, f"policy.routes[{index}]")
        _unknown(route, ROUTE_KEYS, f"policy.routes[{index}]")
        route_id = _string(route.get("route_id"), f"policy.routes[{index}].route_id", pattern=ID_RE)
        if route_id in route_ids:
            raise RoutingError(f"duplicate route_id: {route_id}")
        route_ids.add(route_id)
        fallback_ids = _string_list(route.get("fallback_route_ids", []), f"policy.routes[{index}].fallback_route_ids")
        routes.append(
            {
                "route_id": route_id,
                "provider": _string(route.get("provider"), f"policy.routes[{index}].provider"),
                "model": _string(route.get("model"), f"policy.routes[{index}].model"),
                "static_score": _number(route.get("static_score"), f"policy.routes[{index}].static_score", maximum=1.0),
                "capabilities": _normalize_capabilities(route.get("capabilities"), f"policy.routes[{index}].capabilities"),
                "cost_usd_per_1k_input": _number(
                    route.get("cost_usd_per_1k_input"), f"policy.routes[{index}].cost_usd_per_1k_input"
                ),
                "cost_usd_per_1k_output": _number(
                    route.get("cost_usd_per_1k_output"), f"policy.routes[{index}].cost_usd_per_1k_output"
                ),
                "latency_ms": _positive_int(route.get("latency_ms"), f"policy.routes[{index}].latency_ms"),
                "fallback_route_ids": fallback_ids,
            }
        )
    routes.sort(key=lambda item: item["route_id"])
    _validate_fallback_graph(routes)
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "policy_id": policy_id,
        "mode": mode,
        "budgets": budgets,
        "activation": activation,
        "routes": routes,
    }
    expected_revision = digest(normalized)
    supplied_revision = policy.get("policy_revision")
    if supplied_revision is not None and supplied_revision != expected_revision:
        raise RoutingError("policy_revision does not match canonical policy content")
    normalized["policy_revision"] = expected_revision
    return normalized


def make_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    return validate_policy(value)


def validate_request(value: Any) -> dict[str, Any]:
    _reject_forbidden(value, "request")
    request = _mapping(value, "request")
    _unknown(request, REQUEST_KEYS, "request")
    if request.get("schema_version") != SCHEMA_VERSION:
        raise RoutingError(f"unsupported request schema_version: {request.get('schema_version')}")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "request_id": _string(request.get("request_id"), "request.request_id", pattern=ID_RE),
        "episode_id": _string(request.get("episode_id"), "request.episode_id", pattern=ID_RE),
        "task_id": _string(request.get("task_id"), "request.task_id", pattern=ID_RE),
        "host": _string(request.get("host"), "request.host"),
        "required_tools": _string_list(request.get("required_tools", []), "request.required_tools"),
        "structured_output": request.get("structured_output"),
        "context_tokens": _positive_int(request.get("context_tokens"), "request.context_tokens"),
        "modalities": _string_list(request.get("modalities", []), "request.modalities", allow_empty=False),
        "region": _string(request.get("region"), "request.region"),
        "data_policy": _string(request.get("data_policy"), "request.data_policy"),
        "replay_required": request.get("replay_required"),
        "input_tokens": _nonnegative_int(request.get("input_tokens"), "request.input_tokens"),
        "output_tokens": _nonnegative_int(request.get("output_tokens"), "request.output_tokens"),
        "current_concurrency": _positive_int(request.get("current_concurrency"), "request.current_concurrency"),
        "disable_adaptation": request.get("disable_adaptation", False),
    }
    if not isinstance(normalized["structured_output"], bool):
        raise RoutingError("request.structured_output must be a boolean")
    if not isinstance(normalized["replay_required"], bool):
        raise RoutingError("request.replay_required must be a boolean")
    if not isinstance(normalized["disable_adaptation"], bool):
        raise RoutingError("request.disable_adaptation must be a boolean")
    if "pin" in request:
        pin = _mapping(request["pin"], "request.pin")
        _unknown(pin, PIN_KEYS, "request.pin")
        if not pin:
            raise RoutingError("request.pin must contain at least one field")
        normalized["pin"] = {key: _string(pin[key], f"request.pin.{key}") for key in sorted(pin)}
    return normalized


def validate_outcomes(value: Any) -> list[dict[str, Any]]:
    _reject_forbidden(value, "outcomes")
    if not isinstance(value, list) or len(value) > MAX_OUTCOMES:
        raise RoutingError(f"outcomes must contain at most {MAX_OUTCOMES} records")
    outcomes: list[dict[str, Any]] = []
    sample_ids: set[str] = set()
    for index, raw_outcome in enumerate(value):
        outcome = _mapping(raw_outcome, f"outcomes[{index}]")
        if "confidence" in outcome:
            raise RoutingError("agent confidence is not ground-truth quality")
        _unknown(outcome, OUTCOME_KEYS, f"outcomes[{index}]")
        sample_id = _string(outcome.get("sample_id"), f"outcomes[{index}].sample_id", pattern=ID_RE)
        if sample_id in sample_ids:
            raise RoutingError(f"duplicate outcome sample_id: {sample_id}")
        sample_ids.add(sample_id)
        failed = outcome.get("failed")
        if not isinstance(failed, bool):
            raise RoutingError(f"outcomes[{index}].failed must be a boolean")
        outcomes.append(
            {
                "route_id": _string(outcome.get("route_id"), f"outcomes[{index}].route_id", pattern=ID_RE),
                "sample_id": sample_id,
                "quality_score": _number(outcome.get("quality_score"), f"outcomes[{index}].quality_score", maximum=1.0),
                "cost_usd": _number(outcome.get("cost_usd"), f"outcomes[{index}].cost_usd"),
                "latency_ms": _nonnegative_int(outcome.get("latency_ms"), f"outcomes[{index}].latency_ms"),
                "failed": failed,
                "approval_burden": _number(outcome.get("approval_burden"), f"outcomes[{index}].approval_burden"),
            }
        )
    return sorted(outcomes, key=lambda item: (item["route_id"], item["sample_id"]))


def validate_episodes(value: Any) -> list[dict[str, Any]]:
    _reject_forbidden(value, "episodes")
    if not isinstance(value, list) or len(value) > MAX_EPISODES:
        raise RoutingError(f"episodes must contain at most {MAX_EPISODES} records")
    episodes: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, raw_episode in enumerate(value):
        episode = _mapping(raw_episode, f"episodes[{index}]")
        _unknown(episode, EPISODE_KEYS, f"episodes[{index}]")
        if episode.get("schema_version") != SCHEMA_VERSION:
            raise RoutingError(f"episodes[{index}].schema_version is unsupported")
        episode_id = _string(episode.get("episode_id"), f"episodes[{index}].episode_id", pattern=ID_RE)
        if episode_id in ids:
            raise RoutingError(f"duplicate episode_id: {episode_id}")
        ids.add(episode_id)
        request = validate_request(episode.get("request"))
        if request["episode_id"] != episode_id:
            raise RoutingError(f"episodes[{index}] request.episode_id does not match episode_id")
        episodes.append(
            {
                "schema_version": SCHEMA_VERSION,
                "episode_id": episode_id,
                "request": request,
                "outcomes": validate_outcomes(episode.get("outcomes", [])),
            }
        )
    return sorted(episodes, key=lambda item: item["episode_id"])


def _estimated_cost(route: Mapping[str, Any], request: Mapping[str, Any]) -> float:
    return (
        request["input_tokens"] / 1000 * route["cost_usd_per_1k_input"]
        + request["output_tokens"] / 1000 * route["cost_usd_per_1k_output"]
    )


def _stats(outcomes: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not outcomes:
        return {
            "sample_count": 0,
            "quality_mean": 0.0,
            "quality_lower_bound": 0.0,
            "failure_rate": 0.0,
            "cost_mean": 0.0,
            "cost_total": 0.0,
            "latency_mean": 0.0,
            "approval_burden_mean": 0.0,
        }
    count = len(outcomes)
    qualities = [float(item["quality_score"]) for item in outcomes]
    quality_mean = sum(qualities) / count
    variance = sum((quality - quality_mean) ** 2 for quality in qualities) / count
    standard_error = math.sqrt(variance / count)
    return {
        "sample_count": count,
        "quality_mean": quality_mean,
        "quality_lower_bound": max(0.0, quality_mean - 1.96 * standard_error),
        "failure_rate": sum(bool(item["failed"]) for item in outcomes) / count,
        "cost_mean": sum(float(item["cost_usd"]) for item in outcomes) / count,
        "cost_total": sum(float(item["cost_usd"]) for item in outcomes),
        "latency_mean": sum(float(item["latency_ms"]) for item in outcomes) / count,
        "approval_burden_mean": sum(float(item["approval_burden"]) for item in outcomes) / count,
    }


def _group_outcomes(outcomes: list[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for outcome in outcomes:
        grouped.setdefault(str(outcome["route_id"]), []).append(outcome)
    return grouped


def _route_score(
    route: Mapping[str, Any],
    mode: str,
    activation: Mapping[str, Any],
    stats: Mapping[str, Any],
    *,
    allow_adaptive: bool,
) -> tuple[float, str]:
    if mode != "adaptive" or not allow_adaptive:
        return float(route["static_score"]), "static"
    if stats["sample_count"] < activation["min_samples"]:
        return float(route["static_score"]), "static-cold-start"
    if stats["quality_lower_bound"] < activation["min_confidence"]:
        return float(route["static_score"]), "static-low-confidence"
    return float(stats["quality_mean"]), "adaptive-accepted-outcomes"


def _candidate_exclusion(route: Mapping[str, Any], request: Mapping[str, Any], policy: Mapping[str, Any]) -> str | None:
    pin = request.get("pin", {})
    if "route_id" in pin and route["route_id"] != pin["route_id"]:
        return "pin_route"
    if "provider" in pin and route["provider"] != pin["provider"]:
        return "pin_provider"
    if "model" in pin and route["model"] != pin["model"]:
        return "pin_model"
    capabilities = route["capabilities"]
    if not set(request["required_tools"]).issubset(capabilities["tools"]):
        return "required_tool"
    if request["structured_output"] and not capabilities["structured_output"]:
        return "structured_output"
    if request["context_tokens"] > capabilities["context_tokens"]:
        return "context_window"
    if not set(request["modalities"]).issubset(capabilities["modalities"]):
        return "modality"
    if request["region"] not in capabilities["regions"] and "global" not in capabilities["regions"]:
        return "region"
    if request["host"] not in capabilities["hosts"]:
        return "host"
    if request["data_policy"] not in capabilities["data_policies"]:
        return "data_policy"
    if request["replay_required"] and not capabilities["replay_safe"]:
        return "replay_safety"
    estimated_cost = _estimated_cost(route, request)
    budgets = policy["budgets"]
    if request["input_tokens"] > budgets["max_input_tokens"]:
        return "budget_input_tokens"
    if request["output_tokens"] > budgets["max_output_tokens"]:
        return "budget_output_tokens"
    if estimated_cost > budgets["max_cost_usd"]:
        return "budget_cost"
    if route["latency_ms"] > budgets["max_latency_ms"]:
        return "budget_latency"
    if request["current_concurrency"] > budgets["max_concurrency"]:
        return "budget_concurrency"
    return None


def _decision(
    policy: Mapping[str, Any],
    request: Mapping[str, Any],
    outcomes: list[Mapping[str, Any]],
    *,
    allow_adaptive: bool,
) -> dict[str, Any]:
    policy = validate_policy(policy)
    request = validate_request(request)
    outcomes = validate_outcomes(outcomes)
    requested_mode = policy["mode"]
    mode = "static" if request.get("disable_adaptation") and requested_mode == "adaptive" else requested_mode
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "policy_revision": policy["policy_revision"],
        "request_ref": digest(request),
        "status": "denied",
        "candidates": [],
        "selected_route": None,
        "fallback_plan": [],
        "budget_state": {
            "input_tokens": request["input_tokens"],
            "output_tokens": request["output_tokens"],
            "current_concurrency": request["current_concurrency"],
            "policy_budgets": copy.deepcopy(policy["budgets"]),
        },
        "adaptation": {
            "mode": mode,
            "requested_mode": requested_mode,
            "disabled_by_request": bool(request.get("disable_adaptation")),
        },
    }
    grouped = _group_outcomes(outcomes)
    eligible: list[dict[str, Any]] = []
    for route in policy["routes"]:
        route_outcomes = grouped.get(route["route_id"], [])
        route_stats = _stats(route_outcomes)
        exclusion = _candidate_exclusion(route, request, policy)
        evidence = {
            "sample_count": route_stats["sample_count"],
            "quality_mean": route_stats["quality_mean"],
            "quality_lower_bound": route_stats["quality_lower_bound"],
            "evidence_ref": digest(route_outcomes),
        }
        if exclusion is not None:
            body["candidates"].append(
                {
                    "route_id": route["route_id"],
                    "provider": route["provider"],
                    "model": route["model"],
                    "status": "excluded",
                    "reason_code": exclusion,
                    "estimated_cost_usd": _estimated_cost(route, request),
                    "estimated_latency_ms": route["latency_ms"],
                    "evidence": evidence,
                }
            )
            continue
        score, score_source = _route_score(
            route,
            mode,
            policy["activation"],
            route_stats,
            allow_adaptive=allow_adaptive,
        )
        candidate = {
            "route_id": route["route_id"],
            "provider": route["provider"],
            "model": route["model"],
            "status": "eligible",
            "score": round(score, 12),
            "score_source": score_source,
            "estimated_cost_usd": _estimated_cost(route, request),
            "estimated_latency_ms": route["latency_ms"],
            "evidence": evidence,
        }
        body["candidates"].append(candidate)
        eligible.append(candidate)
    body["candidates"].sort(key=lambda item: item["route_id"])
    if mode == "adaptive" and not allow_adaptive:
        body["denial_reason"] = "adaptive_not_activated"
        body["decision_ref"] = digest(body)
        return body
    if not eligible:
        body["denial_reason"] = "no_eligible_route"
        body["decision_ref"] = digest(body)
        return body
    selected = min(eligible, key=lambda item: (-item["score"], item["route_id"]))
    selected_route = next(route for route in policy["routes"] if route["route_id"] == selected["route_id"])
    eligible_ids = {item["route_id"] for item in eligible}
    body["status"] = "selected"
    body["selected_route"] = {
        "route_id": selected["route_id"],
        "provider": selected["provider"],
        "model": selected["model"],
        "estimated_cost_usd": selected["estimated_cost_usd"],
        "estimated_latency_ms": selected["estimated_latency_ms"],
    }
    body["fallback_plan"] = [
        route_id for route_id in selected_route["fallback_route_ids"] if route_id in eligible_ids
    ]
    body["budget_state"]["selected_estimated_cost_usd"] = selected["estimated_cost_usd"]
    body["budget_state"]["selected_estimated_latency_ms"] = selected["estimated_latency_ms"]
    body["decision_ref"] = digest(body)
    return body


def decide(policy: Mapping[str, Any], request: Mapping[str, Any], outcomes: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    return _decision(policy, request, outcomes or [], allow_adaptive=False)


def _metric_summary(observed: list[Mapping[str, Any]], missing: int, total: int) -> dict[str, Any]:
    stats = _stats(observed)
    return {
        "total_episodes": total,
        "observed_samples": stats["sample_count"],
        "missing_outcomes": missing,
        "quality_mean": stats["quality_mean"],
        "quality_lower_bound": stats["quality_lower_bound"],
        "cost_total_usd": stats["cost_total"],
        "cost_mean_usd": stats["cost_mean"],
        "latency_mean_ms": stats["latency_mean"],
        "failure_rate": stats["failure_rate"],
        "approval_burden_mean": stats["approval_burden_mean"],
    }


def _replay_policy(policy: Mapping[str, Any], episodes: list[Mapping[str, Any]]) -> dict[str, Any]:
    observed: list[Mapping[str, Any]] = []
    missing = 0
    decisions: list[dict[str, Any]] = []
    route_counts: dict[str, int] = {}
    evidence = [outcome for episode in episodes for outcome in episode["outcomes"]]
    for episode in episodes:
        # Replay is a bounded offline comparison. It may use the redacted outcome
        # corpus as evidence; live decide() never enables adaptive scoring.
        decision = _decision(policy, episode["request"], evidence, allow_adaptive=True)
        selected = decision.get("selected_route")
        if selected is None:
            missing += 1
            decisions.append({"episode_id": episode["episode_id"], "status": "unroutable", "decision_ref": decision["decision_ref"]})
            continue
        route_id = selected["route_id"]
        route_counts[route_id] = route_counts.get(route_id, 0) + 1
        matches = [outcome for outcome in episode["outcomes"] if outcome["route_id"] == route_id]
        if not matches:
            missing += 1
            decisions.append(
                {
                    "episode_id": episode["episode_id"],
                    "route_id": route_id,
                    "status": "missing_outcome",
                    "decision_ref": decision["decision_ref"],
                }
            )
            continue
        selected_outcome = matches[0]
        observed.append(selected_outcome)
        decisions.append(
            {
                "episode_id": episode["episode_id"],
                "route_id": route_id,
                "status": "observed",
                "outcome_ref": digest(selected_outcome),
                "decision_ref": decision["decision_ref"],
            }
        )
    return {
        "policy_revision": policy["policy_revision"],
        "mode": policy["mode"],
        "metrics": _metric_summary(observed, missing, len(episodes)),
        "route_counts": dict(sorted(route_counts.items())),
        "decisions": decisions,
    }


def _delta(candidate: Mapping[str, Any], baseline: Mapping[str, Any], key: str) -> float:
    return float(candidate["metrics"][key]) - float(baseline["metrics"][key])


def replay(
    baseline_policy: Mapping[str, Any],
    candidate_policy: Mapping[str, Any],
    episodes: list[Mapping[str, Any]],
) -> dict[str, Any]:
    baseline = validate_policy(baseline_policy)
    candidate = validate_policy(candidate_policy)
    normalized_episodes = validate_episodes(episodes)
    baseline_result = _replay_policy(baseline, normalized_episodes)
    candidate_result = _replay_policy(candidate, normalized_episodes)
    comparison = {
        "episode_count": len(normalized_episodes),
        "quality_delta": _delta(candidate_result, baseline_result, "quality_mean"),
        "cost_delta_usd": _delta(candidate_result, baseline_result, "cost_mean_usd"),
        "latency_delta_ms": _delta(candidate_result, baseline_result, "latency_mean_ms"),
        "failure_rate_delta": _delta(candidate_result, baseline_result, "failure_rate"),
        "approval_burden_delta": _delta(candidate_result, baseline_result, "approval_burden_mean"),
    }
    activation = candidate["activation"]
    reasons: list[str] = []
    if candidate["mode"] != "adaptive":
        reasons.append("candidate_not_adaptive")
    if candidate_result["metrics"]["observed_samples"] < activation["min_samples"]:
        reasons.append("insufficient_samples")
    if candidate_result["metrics"]["quality_lower_bound"] < activation["min_confidence"]:
        reasons.append("insufficient_confidence")
    if candidate_result["metrics"]["missing_outcomes"]:
        reasons.append("missing_outcome_evidence")
    if comparison["quality_delta"] < -activation["max_quality_regression"]:
        reasons.append("quality_regression")
    if comparison["cost_delta_usd"] > activation["max_cost_increase_usd"]:
        reasons.append("cost_increase")
    if comparison["failure_rate_delta"] > activation["max_failure_rate_increase"]:
        reasons.append("failure_rate_increase")
    if comparison["approval_burden_delta"] > activation["max_approval_burden_increase"]:
        reasons.append("approval_burden_increase")
    if candidate_result["metrics"]["cost_total_usd"] > activation["max_replay_cost_usd"]:
        reasons.append("replay_budget")
    output = {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "status": "passed",
        "baseline": baseline_result,
        "candidate": candidate_result,
        "comparison": comparison,
        "activation": {
            "status": "eligible" if not reasons else "blocked",
            "reasons": reasons,
            "candidate_policy_revision": candidate["policy_revision"],
        },
    }
    output["replay_ref"] = digest(output)
    return output


def inspect_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    policy = validate_policy(policy)
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "policy_id": policy["policy_id"],
        "policy_revision": policy["policy_revision"],
        "mode": policy["mode"],
        "route_count": len(policy["routes"]),
        "routes": [
            {"route_id": route["route_id"], "provider": route["provider"], "model": route["model"]}
            for route in policy["routes"]
        ],
        "redaction": "digest-only",
    }


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RoutingError(f"cannot read {label}: {error}") from error


def _write_json(value: Any, path: Path | None) -> None:
    rendered = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(rendered, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic Forge route decisions and offline replay")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="inspect policy metadata without exposing route content")
    inspect.add_argument("--policy", type=Path, required=True)
    inspect.add_argument("--output", type=Path)

    decide_parser = sub.add_parser("decide", help="make one deterministic route decision")
    decide_parser.add_argument("--policy", type=Path, required=True)
    decide_parser.add_argument("--request", type=Path, required=True)
    decide_parser.add_argument("--outcomes", type=Path)
    decide_parser.add_argument("--output", type=Path)

    replay_parser = sub.add_parser("replay", help="compare baseline and candidate policies offline")
    replay_parser.add_argument("--baseline-policy", type=Path, required=True)
    replay_parser.add_argument("--candidate-policy", type=Path, required=True)
    replay_parser.add_argument("--episodes", type=Path, required=True)
    replay_parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            _write_json(inspect_policy(_load_json(args.policy, "policy")), args.output)
            return 0
        if args.command == "decide":
            outcomes = _load_json(args.outcomes, "outcomes") if args.outcomes else []
            result = decide(_load_json(args.policy, "policy"), _load_json(args.request, "request"), outcomes)
            _write_json(result, args.output)
            return 0 if result["status"] == "selected" else 1
        result = replay(
            _load_json(args.baseline_policy, "baseline policy"),
            _load_json(args.candidate_policy, "candidate policy"),
            _load_json(args.episodes, "episodes"),
        )
        _write_json(result, args.output)
        return 0 if result["activation"]["status"] == "eligible" else 1
    except (RoutingError, OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "error_ref": digest({"type": type(error).__name__, "message": str(error)})}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
