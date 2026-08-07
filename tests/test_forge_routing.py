"""Deterministic routing decisions and offline replay contract tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-routing.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_routing", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def route(
    route_id: str,
    *,
    score: float,
    structured_output: bool = True,
    context_tokens: int = 128_000,
    tools: list[str] | None = None,
    cost_input: float = 0.01,
    cost_output: float = 0.02,
    latency_ms: int = 500,
) -> dict:
    return {
        "route_id": route_id,
        "provider": f"provider-{route_id}",
        "model": f"model-{route_id}",
        "static_score": score,
        "capabilities": {
            "tools": tools or ["Read", "Grep"],
            "structured_output": structured_output,
            "context_tokens": context_tokens,
            "modalities": ["text"],
            "regions": ["global", "eu"],
            "hosts": ["codex", "claude"],
            "data_policies": ["digest-only"],
            "replay_safe": True,
        },
        "cost_usd_per_1k_input": cost_input,
        "cost_usd_per_1k_output": cost_output,
        "latency_ms": latency_ms,
        "fallback_route_ids": [],
    }


def policy(module, *, mode: str = "static", routes: list[dict] | None = None, budgets: dict | None = None, activation: dict | None = None):
    value = {
        "schema_version": 1,
        "contract_revision": module.CONTRACT_REVISION,
        "policy_id": "routing-test",
        "mode": mode,
        "budgets": budgets
        or {
            "max_input_tokens": 200_000,
            "max_output_tokens": 16_000,
            "max_cost_usd": 1.0,
            "max_latency_ms": 30_000,
            "max_concurrency": 4,
        },
        "activation": activation
        or {
            "min_samples": 2,
            "min_confidence": 0.7,
            "max_quality_regression": 0.05,
            "max_cost_increase_usd": 0.05,
            "max_failure_rate_increase": 0.02,
            "max_approval_burden_increase": 0.5,
            "max_replay_cost_usd": 1.0,
        },
        "routes": routes or [route("fast", score=0.9), route("quality", score=0.7, cost_input=0.04)],
    }
    return module.make_policy(value)


def request(**overrides):
    value = {
        "schema_version": 1,
        "request_id": "request-1",
        "episode_id": "episode-1",
        "task_id": "task-1",
        "host": "codex",
        "required_tools": ["Read"],
        "structured_output": True,
        "context_tokens": 2_000,
        "modalities": ["text"],
        "region": "eu",
        "data_policy": "digest-only",
        "replay_required": True,
        "input_tokens": 1_000,
        "output_tokens": 500,
        "current_concurrency": 1,
    }
    value.update(overrides)
    return value


def outcome(route_id: str, episode_id: str, *, quality: float, cost: float, latency: int = 500):
    return {
        "route_id": route_id,
        "sample_id": f"{episode_id}-{route_id}",
        "quality_score": quality,
        "cost_usd": cost,
        "latency_ms": latency,
        "failed": False,
        "approval_burden": 0,
    }


def test_static_decision_filters_capabilities_and_records_only_digests():
    module = load_module()
    selected_policy = policy(
        module,
        routes=[
            route("small", score=0.99, structured_output=False),
            route("large", score=0.7),
        ],
    )

    decision = module.decide(selected_policy, request())

    assert decision["status"] == "selected"
    assert decision["selected_route"]["route_id"] == "large"
    candidates = {item["route_id"]: item for item in decision["candidates"]}
    assert candidates["small"]["status"] == "excluded"
    assert candidates["small"]["reason_code"] == "structured_output"
    assert decision["policy_revision"] == selected_policy["policy_revision"]
    assert decision["decision_ref"].startswith("sha256:")
    assert "prompt" not in json.dumps(decision)


def test_pins_and_budgets_fail_closed():
    module = load_module()
    budget_policy = policy(module, budgets={**policy(module)["budgets"], "max_cost_usd": 0.001})
    denied = module.decide(budget_policy, request())

    assert denied["status"] == "denied"
    assert denied["denial_reason"] == "no_eligible_route"
    assert {item["reason_code"] for item in denied["candidates"]} == {"budget_cost"}

    pinned = module.decide(
        policy(module),
        request(pin={"provider": "provider-missing"}),
    )
    assert pinned["status"] == "denied"
    assert {item["reason_code"] for item in pinned["candidates"]} == {"pin_provider"}


def test_adaptation_can_be_disabled_but_unactivated_adaptive_mode_fails_closed():
    module = load_module()
    adaptive = policy(module, mode="adaptive")
    denied = module.decide(adaptive, request())
    static_override = module.decide(adaptive, request(disable_adaptation=True))
    disabled = module.decide(policy(module, mode="disabled"), request())

    assert denied["status"] == "denied"
    assert denied["denial_reason"] == "adaptive_not_activated"
    assert {item["status"] for item in denied["candidates"]} == {"eligible"}
    assert static_override["status"] == disabled["status"] == "selected"
    assert static_override["adaptation"]["mode"] == "static"
    assert disabled["adaptation"]["mode"] == "disabled"


def test_outcome_evidence_rejects_agent_confidence_and_raw_content():
    module = load_module()
    with pytest.raises(module.RoutingError, match="agent confidence"):
        module.validate_outcomes(
            [
                {
                    **outcome("fast", "episode-1", quality=0.8, cost=0.01),
                    "confidence": 0.99,
                }
            ]
        )
    with pytest.raises(module.RoutingError, match="privacy"):
        module.validate_request({**request(), "prompt": "must not be routed"})


def test_offline_replay_applies_quality_cost_and_sample_gates():
    module = load_module()
    baseline = policy(module, mode="static")
    candidate = policy(module, mode="adaptive")
    episodes = [
        {
            "schema_version": 1,
            "episode_id": f"episode-{index}",
            "request": request(episode_id=f"episode-{index}"),
            "outcomes": [
                outcome("fast", f"episode-{index}", quality=0.6, cost=0.01),
                outcome("quality", f"episode-{index}", quality=0.95, cost=0.04),
            ],
        }
        for index in (1, 2)
    ]

    replay = module.replay(baseline, candidate, episodes)

    assert replay["status"] == "passed"
    assert replay["baseline"]["metrics"]["observed_samples"] == 2
    assert replay["candidate"]["metrics"]["observed_samples"] == 2
    assert replay["comparison"]["quality_delta"] > 0
    assert replay["activation"]["status"] == "eligible"
    assert replay["activation"]["reasons"] == []
    assert replay["replay_ref"].startswith("sha256:")


def test_cli_decide_and_replay_are_offline(tmp_path, capsys):
    module = load_module()
    selected_policy = policy(module)
    policy_path = tmp_path / "policy.json"
    request_path = tmp_path / "request.json"
    policy_path.write_text(json.dumps(selected_policy) + "\n", encoding="utf-8")
    request_path.write_text(json.dumps(request()) + "\n", encoding="utf-8")

    assert module.main(["decide", "--policy", str(policy_path), "--request", str(request_path)]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["status"] == "selected"

    episodes_path = tmp_path / "episodes.json"
    episodes_path.write_text(json.dumps([]) + "\n", encoding="utf-8")
    assert module.main(
        [
            "replay",
            "--baseline-policy",
            str(policy_path),
            "--candidate-policy",
            str(policy_path),
            "--episodes",
            str(episodes_path),
        ]
    ) == 1
    replay = json.loads(capsys.readouterr().out)
    assert replay["activation"]["status"] == "blocked"
