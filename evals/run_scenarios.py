#!/usr/bin/env python3
"""Run deterministic and opt-in host conformance scenarios for Forge."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
ADAPTER_CONTRACT_VERSION = 1
CATEGORIES = {"positive", "negative", "ambiguity", "denial", "retry", "recovery"}
ADAPTERS = {"reference", "claude", "codex", "agentskills"}
REPO = Path(__file__).resolve().parents[1]
HOST_MATRIX_PATH = REPO / "data/host-capabilities.json"
TARGET_KINDS = {"agent", "skill", "command", "file"}
RISK_LEVELS = {"low", "medium", "high"}
SCENARIO_KEYS = {"schema_version", "id", "category", "risk", "target", "prompt", "setup", "expected", "repetitions"}
TARGET_KEYS = {"kind", "name"}
EXPECTED_KEYS = {
    "must_include",
    "must_not_include",
    "files_exist",
    "required_effects",
    "forbidden_effects",
    "required_tools",
    "forbidden_tools",
    "artifacts",
    "score",
}
SCENARIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")
EFFECT_ALIASES = {
    "approval": ("approval", "approve"),
    "conflict stop": ("conflict", "refuses to write"),
    "redaction": ("redact", "redaction", "privacy-safe"),
    "re-fetch remote state": ("re-fetch", "recheck", "get_stack"),
    "no mutation": ("read-only", "does not install", "never mutate"),
    "documented adapter": ("adapter", "companion"),
}


class ScenarioError(ValueError):
    """Raised when a scenario or adapter result violates the contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def safe_path(repo: Path, value: str) -> Path:
    candidate = (repo / value).resolve()
    try:
        candidate.relative_to(repo.resolve())
    except ValueError as exc:
        raise ScenarioError(f"scenario path escapes repository: {value}") from exc
    return candidate


def target_path(repo: Path, target: Mapping[str, Any]) -> Path:
    kind = target.get("kind")
    name = target.get("name")
    if not isinstance(kind, str) or not isinstance(name, str) or not name:
        raise ScenarioError("scenario target requires kind and name")
    if kind == "agent":
        return safe_path(repo, f"plugins/forge/agents/{name}.md")
    if kind == "skill":
        return safe_path(repo, f"plugins/forge/skills/{name}/SKILL.md")
    if kind == "command":
        return safe_path(repo, f"plugins/forge/commands/{name}.md")
    if kind == "file":
        return safe_path(repo, name)
    raise ScenarioError(f"unsupported target kind: {kind}")


def load_host_matrix(path: Path = HOST_MATRIX_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioError(f"invalid host capability matrix: {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ScenarioError("host capability matrix must use schema_version 1")
    hosts = value.get("hosts")
    if not isinstance(hosts, dict) or set(hosts) != ADAPTERS:
        raise ScenarioError("host capability matrix must declare every adapter exactly once")
    contract_version = value.get("adapter_contract_version")
    if contract_version != ADAPTER_CONTRACT_VERSION:
        raise ScenarioError("unsupported adapter contract version")
    return value


def validate_scenario(value: Mapping[str, Any]) -> None:
    unknown = sorted(set(value) - SCENARIO_KEYS)
    if unknown:
        raise ScenarioError("scenario has unknown field(s): " + ", ".join(unknown))
    required = {"schema_version", "id", "category", "target", "prompt", "expected"}
    missing = sorted(required - value.keys())
    if missing:
        raise ScenarioError("scenario missing: " + ", ".join(missing))
    if value["schema_version"] != SCHEMA_VERSION or isinstance(value["schema_version"], bool):
        raise ScenarioError(f"unsupported scenario schema version: {value['schema_version']}")
    if not isinstance(value["id"], str) or not SCENARIO_ID_RE.fullmatch(value["id"]):
        raise ScenarioError("scenario id must be a lowercase kebab-case string from 3 to 81 characters")
    if not isinstance(value["category"], str) or value["category"] not in CATEGORIES:
        raise ScenarioError(f"unsupported scenario category: {value['category']}")
    if value.get("risk") is not None and (not isinstance(value["risk"], str) or value["risk"] not in RISK_LEVELS):
        raise ScenarioError(f"unsupported scenario risk: {value['risk']}")
    if not isinstance(value["target"], Mapping):
        raise ScenarioError("scenario target must be an object")
    target = value["target"]
    unknown_target = sorted(set(target) - TARGET_KEYS)
    if unknown_target:
        raise ScenarioError("scenario target has unknown field(s): " + ", ".join(unknown_target))
    if not isinstance(target.get("kind"), str) or target["kind"] not in TARGET_KINDS:
        raise ScenarioError(f"unsupported target kind: {target.get('kind')}")
    if not isinstance(target.get("name"), str) or not target["name"]:
        raise ScenarioError("scenario target name must be a non-empty string")
    if not isinstance(value["prompt"], str) or not value["prompt"]:
        raise ScenarioError("scenario prompt must be a non-empty string")
    if not isinstance(value.get("setup", {}), Mapping):
        raise ScenarioError("scenario setup must be an object")
    if not isinstance(value["expected"], Mapping):
        raise ScenarioError("scenario expected must be an object")
    unknown_expected = sorted(set(value["expected"]) - EXPECTED_KEYS)
    if unknown_expected:
        raise ScenarioError("scenario expected has unknown field(s): " + ", ".join(unknown_expected))
    repetitions = value.get("repetitions", 1)
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or not 1 <= repetitions <= 50:
        raise ScenarioError("scenario repetitions must be an integer from 1 to 50")
    for key in (
        "must_include",
        "must_not_include",
        "files_exist",
        "required_effects",
        "forbidden_effects",
        "required_tools",
        "forbidden_tools",
    ):
        entries = value["expected"].get(key, [])
        if not isinstance(entries, list) or not all(isinstance(item, str) for item in entries):
            raise ScenarioError(f"scenario expected.{key} must be a string list")
    artifacts = value["expected"].get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ScenarioError("scenario expected.artifacts must be a list")
    for index, artifact in enumerate(artifacts, start=1):
        if not isinstance(artifact, Mapping) or not isinstance(artifact.get("path"), str) or not artifact["path"]:
            raise ScenarioError(f"scenario expected.artifacts[{index}] requires a path")
        if artifact.get("kind", "file") not in {"file", "json", "text"}:
            raise ScenarioError(f"unsupported artifact kind: {artifact.get('kind')}")
        if not isinstance(artifact.get("required", True), bool):
            raise ScenarioError(f"scenario expected.artifacts[{index}].required must be boolean")
    score = value["expected"].get("score", {})
    if not isinstance(score, Mapping):
        raise ScenarioError("scenario expected.score must be an object")
    unknown_score = sorted(set(score) - {"minimum", "maximum"})
    if unknown_score:
        raise ScenarioError("scenario expected.score has unknown field(s): " + ", ".join(unknown_score))
    for key in ("minimum", "maximum"):
        if key in score and (not isinstance(score[key], (int, float)) or isinstance(score[key], bool) or not 0 <= score[key] <= 1):
            raise ScenarioError(f"scenario expected.score.{key} must be a number from 0 to 1")
    if "minimum" in score and "maximum" in score and score["minimum"] > score["maximum"]:
        raise ScenarioError("scenario expected.score.minimum cannot exceed maximum")


def load_scenarios(path: Path) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ScenarioError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ScenarioError(f"{path}:{line_number}: scenario must be an object")
        validate_scenario(value)
        if value["id"] in seen:
            raise ScenarioError(f"duplicate scenario id: {value['id']}")
        seen.add(value["id"])
        scenarios.append(value)
    if not scenarios:
        raise ScenarioError(f"no scenarios found in {path}")
    return scenarios


def check(status: str, check_id: str, detail: str) -> dict[str, str]:
    return {"id": check_id, "status": status, "detail": detail}


def effect_matches(text: str, effect: str) -> bool:
    needles = EFFECT_ALIASES.get(effect, (effect,))
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


class ReferenceAdapter:
    name = "reference"

    def capabilities(self, repo: Path) -> dict[str, Any]:
        return {
            "deterministic": True,
            "filesystem_contracts": True,
            "live_model": False,
            "host_version": "reference-1",
        }

    def run(self, repo: Path, scenario: Mapping[str, Any], **_: Any) -> dict[str, Any]:
        started = time.monotonic()
        expected = scenario["expected"]
        checks: list[dict[str, str]] = []
        try:
            path = target_path(repo, scenario["target"])
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                checks.append(check("pass", "target-exists", str(path.relative_to(repo))))
                for index, needle in enumerate(expected.get("must_include", []), start=1):
                    checks.append(check("pass" if needle in text else "fail", f"must-include-{index}", needle))
                for index, needle in enumerate(expected.get("must_not_include", []), start=1):
                    checks.append(check("pass" if needle not in text else "fail", f"must-not-include-{index}", needle))
                for index, needle in enumerate(expected.get("required_effects", []), start=1):
                    checks.append(check("pass" if effect_matches(text, needle) else "fail", f"required-effect-{index}", needle))
                for index, needle in enumerate(expected.get("forbidden_effects", []), start=1):
                    checks.append(check("pass" if not effect_matches(text, needle) else "fail", f"forbidden-effect-{index}", needle))
            else:
                checks.append(check("fail", "target-exists", f"missing target: {path.relative_to(repo)}"))
            for index, relative in enumerate(expected.get("files_exist", []), start=1):
                exists = safe_path(repo, relative).exists()
                checks.append(check("pass" if exists else "fail", f"file-exists-{index}", relative))
            for index, artifact in enumerate(expected.get("artifacts", []), start=1):
                relative = artifact["path"]
                artifact_path = safe_path(repo, relative)
                required = artifact.get("required", True)
                if not artifact_path.exists() and not required:
                    checks.append(check("pass", f"artifact-{index}", f"optional artifact absent: {relative}"))
                    continue
                if not artifact_path.is_file():
                    checks.append(check("fail", f"artifact-{index}", f"missing artifact: {relative}"))
                    continue
                kind = artifact.get("kind", "file")
                if kind == "json":
                    try:
                        json.loads(artifact_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        checks.append(check("fail", f"artifact-{index}", f"invalid JSON artifact {relative}: {exc}"))
                        continue
                checks.append(check("pass", f"artifact-{index}", relative))
        except (OSError, ScenarioError) as exc:
            checks.append(check("fail", "adapter-error", str(exc)))
        score = sum(item["status"] == "pass" for item in checks) / len(checks) if checks else 0.0
        score_expectation = expected.get("score", {})
        if "minimum" in score_expectation:
            checks.append(
                check(
                    "pass" if score >= score_expectation["minimum"] else "fail",
                    "score-minimum",
                    str(score_expectation["minimum"]),
                )
            )
        if "maximum" in score_expectation:
            checks.append(
                check(
                    "pass" if score <= score_expectation["maximum"] else "fail",
                    "score-maximum",
                    str(score_expectation["maximum"]),
                )
            )
        status = "passed" if all(item["status"] == "pass" for item in checks) else "failed"
        return {
            "scenario_id": scenario["id"],
            "adapter": self.name,
            "status": status,
            "checks": checks,
            "score": round(score, 6),
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
        }


def validate_live_payload(repo: Path, scenario: Mapping[str, Any], payload: Mapping[str, Any]) -> list[str]:
    """Validate host-runner evidence without trusting its top-level passed flag."""

    expected = scenario["expected"]
    errors: list[str] = []
    tools = payload.get("tools", [])
    if expected.get("required_tools") or expected.get("forbidden_tools"):
        if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
            errors.append("runner tools must be a string list")
        else:
            normalized_tools = {tool.casefold() for tool in tools}
            missing = [tool for tool in expected.get("required_tools", []) if tool.casefold() not in normalized_tools]
            forbidden = [tool for tool in expected.get("forbidden_tools", []) if tool.casefold() in normalized_tools]
            if missing:
                errors.append("missing required tools: " + ", ".join(missing))
            if forbidden:
                errors.append("forbidden tools used: " + ", ".join(forbidden))

    artifacts = payload.get("artifacts", [])
    if expected.get("artifacts"):
        if not isinstance(artifacts, list):
            errors.append("runner artifacts must be a list")
        else:
            reported_paths: set[str] = set()
            for item in artifacts:
                if isinstance(item, str):
                    reported_paths.add(item)
                elif isinstance(item, Mapping) and isinstance(item.get("path"), str):
                    reported_paths.add(item["path"])
                else:
                    errors.append("runner artifact entries must be paths or objects with a path")
            for artifact in expected["artifacts"]:
                if artifact.get("required", True) and artifact["path"] not in reported_paths:
                    errors.append(f"missing required artifact: {artifact['path']}")

    response = payload.get("response")
    if isinstance(response, str):
        for needle in expected.get("must_include", []):
            if needle not in response:
                errors.append(f"response missing required text: {needle}")
        for needle in expected.get("must_not_include", []):
            if needle in response:
                errors.append(f"response contains forbidden text: {needle}")
        for effect in expected.get("required_effects", []):
            if not effect_matches(response, effect):
                errors.append(f"response missing required effect: {effect}")
        for effect in expected.get("forbidden_effects", []):
            if effect_matches(response, effect):
                errors.append(f"response contains forbidden effect: {effect}")

    score_expectation = expected.get("score", {})
    score = payload.get("score")
    if score_expectation and (not isinstance(score, (int, float)) or isinstance(score, bool)):
        errors.append("runner score is required when the scenario declares score bounds")
    elif isinstance(score, (int, float)):
        if "minimum" in score_expectation and score < score_expectation["minimum"]:
            errors.append(f"runner score {score} is below minimum {score_expectation['minimum']}")
        if "maximum" in score_expectation and score > score_expectation["maximum"]:
            errors.append(f"runner score {score} is above maximum {score_expectation['maximum']}")
    return errors


class AgentSkillsAdapter(ReferenceAdapter):
    name = "agentskills"

    def capabilities(self, repo: Path) -> dict[str, Any]:
        return {
            **super().capabilities(repo),
            "official_validator": bool(shutil.which("npx")),
            "validator": "skills-ref@0.1.5",
        }

    def run(self, repo: Path, scenario: Mapping[str, Any], *, official: bool = False, **kwargs: Any) -> dict[str, Any]:
        result = super().run(repo, scenario, **kwargs)
        if official and scenario["target"]["kind"] == "skill":
            path = target_path(repo, scenario["target"])
            command = ["npx", "--yes", "skills-ref@0.1.5", "validate", str(path.parent)]
            try:
                process = subprocess.run(command, cwd=repo, capture_output=True, text=True, check=False, timeout=120)
                result["checks"].append(check("pass" if process.returncode == 0 else "fail", "official-skills-ref", process.stdout.strip() or process.stderr.strip()))
            except (OSError, subprocess.TimeoutExpired) as exc:
                result["checks"].append(check("fail", "official-skills-ref", str(exc)))
            result["status"] = "passed" if all(item["status"] == "pass" for item in result["checks"]) else "failed"
        return result


class CliAdapter:
    """Explicit live adapter contract for a host CLI and external scenario runner."""

    def __init__(self, name: str, binary: str, runner_env: str) -> None:
        self.name = name
        self.binary = binary
        self.runner_env = runner_env

    def host_version(self) -> str | None:
        if not shutil.which(self.binary):
            return None
        try:
            process = subprocess.run([self.binary, "--version"], capture_output=True, text=True, check=False, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = (process.stdout or process.stderr).strip().splitlines()
        return value[0] if value else None

    def capabilities(self, repo: Path) -> dict[str, Any]:
        version = self.host_version()
        return {
            "deterministic": False,
            "live_model": True,
            "installed": version is not None,
            "host_version": version,
            "runner_configured": bool(os.environ.get(self.runner_env)),
            "runner_env": self.runner_env,
        }

    def run(self, repo: Path, scenario: Mapping[str, Any], *, live: bool = False, budget_usd: float = 0.0, repetitions: int = 1, **_: Any) -> dict[str, Any]:
        if not live:
            return {"scenario_id": scenario["id"], "adapter": self.name, "status": "skipped", "reason": "live execution requires --live"}
        if budget_usd <= 0:
            return {"scenario_id": scenario["id"], "adapter": self.name, "status": "error", "reason": "--budget-usd is required for live execution"}
        host_version = self.host_version()
        if host_version is None:
            return {"scenario_id": scenario["id"], "adapter": self.name, "status": "error", "reason": f"{self.binary} CLI is not installed"}
        runner = os.environ.get(self.runner_env)
        if not runner:
            return {"scenario_id": scenario["id"], "adapter": self.name, "status": "error", "reason": f"{self.runner_env} is not configured"}
        try:
            command = shlex.split(runner)
        except ValueError as exc:
            return {"scenario_id": scenario["id"], "adapter": self.name, "status": "error", "reason": f"invalid runner command: {exc}"}
        attempts: list[dict[str, Any]] = []
        for _attempt in range(max(repetitions, int(scenario.get("repetitions", 1)))):
            try:
                process = subprocess.run(command, cwd=repo, input=json.dumps(scenario), capture_output=True, text=True, check=False, timeout=300)
                payload = json.loads(process.stdout) if process.stdout.strip() else {}
                if not isinstance(payload, Mapping):
                    raise ScenarioError("runner output must be a JSON object")
                contract_errors = validate_live_payload(repo, scenario, payload)
                attempts.append({
                    "passed": bool(process.returncode == 0 and payload.get("passed") and not contract_errors),
                    "model": payload.get("model"),
                    "host_version": payload.get("host_version") or host_version,
                    "input_tokens": int(payload.get("input_tokens", 0)),
                    "output_tokens": int(payload.get("output_tokens", 0)),
                    "cost_usd": float(payload.get("cost_usd", 0.0)),
                    "score": payload.get("score"),
                    **({"contract_errors": contract_errors} if contract_errors else {}),
                })
            except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError) as exc:
                attempts.append({"passed": False, "error": str(exc), "host_version": host_version, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        return aggregate_attempts(self.name, scenario["id"], attempts)


def aggregate_attempts(adapter: str, scenario_id: str, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    if not attempts:
        return {"scenario_id": scenario_id, "adapter": adapter, "status": "error", "reason": "no live attempts"}
    passed = sum(1 for attempt in attempts if attempt.get("passed"))
    total = len(attempts)
    rate = passed / total
    variance = rate * (1 - rate)
    z = 1.96
    denominator = 1 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((rate * (1 - rate) + z * z / (4 * total)) / total) / denominator
    status = "passed" if passed == total else "failed" if passed == 0 else "flaky"
    return {
        "scenario_id": scenario_id,
        "adapter": adapter,
        "status": status,
        "attempts": attempts,
        "statistics": {
            "n": total,
            "passed": passed,
            "pass_rate": rate,
            "variance": variance,
            "confidence_interval_95": [max(0.0, centre - margin), min(1.0, centre + margin)],
            "input_tokens": sum(int(item.get("input_tokens", 0)) for item in attempts),
            "output_tokens": sum(int(item.get("output_tokens", 0)) for item in attempts),
            "cost_usd": sum(float(item.get("cost_usd", 0.0)) for item in attempts),
            "models": sorted({str(item["model"]) for item in attempts if item.get("model")}),
            "host_versions": sorted({str(item["host_version"]) for item in attempts if item.get("host_version")}),
            "scores": [float(item["score"]) for item in attempts if isinstance(item.get("score"), (int, float))],
        },
    }


def adapter_for(name: str) -> Any:
    if name == "reference":
        return ReferenceAdapter()
    if name == "agentskills":
        return AgentSkillsAdapter()
    if name == "claude":
        return CliAdapter("claude", "claude", "FORGE_CLAUDE_SCENARIO_RUNNER")
    if name == "codex":
        return CliAdapter("codex", "codex", "FORGE_CODEX_SCENARIO_RUNNER")
    raise ScenarioError(f"unsupported adapter: {name}")


def load_receipt_module() -> Any:
    path = REPO / "plugins/forge/skills/observability/scripts/forge-receipts.py"
    spec = importlib.util.spec_from_file_location("forge_receipts", path)
    if spec is None or spec.loader is None:
        raise ScenarioError("could not load Forge receipt store")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def record_receipts(path: Path, run_id: str, artifact: Path, results: Iterable[Mapping[str, Any]], summary: Mapping[str, Any]) -> None:
    module = load_receipt_module()
    store = module.ReceiptStore(path)
    materialized = list(results)
    store.append(module.make_event("run.started", run_id, idempotency_key=f"scenario-run:{run_id}:started", attributes={"artifact": str(artifact), "scenario_count": len(materialized)}))
    for result in materialized:
        store.append(module.make_event("task.finished", run_id, task_id=str(result["scenario_id"]), idempotency_key=f"scenario-run:{run_id}:{result['adapter']}:{result['scenario_id']}", attributes={"adapter": result["adapter"], "status": result["status"], "artifact": str(artifact)}))
    store.append(module.make_event("run.finished", run_id, idempotency_key=f"scenario-run:{run_id}:finished", attributes={"artifact": str(artifact), "summary": dict(summary)}))


def run_suite(repo: Path, scenario_path: Path, adapter_names: list[str], *, live: bool = False, official: bool = False, repetitions: int = 1, budget_usd: float = 0.0, output: Path | None = None, receipts: Path | None = None) -> dict[str, Any]:
    scenarios = load_scenarios(scenario_path)
    host_matrix = load_host_matrix()
    unknown_adapters = sorted(set(adapter_names) - ADAPTERS)
    if unknown_adapters:
        raise ScenarioError("unsupported adapters: " + ", ".join(unknown_adapters))
    run_id = f"scenario-{uuid.uuid4()}"
    started = utc_now()
    adapter_results: dict[str, Any] = {}
    all_results: list[dict[str, Any]] = []
    for name in adapter_names:
        adapter = adapter_for(name)
        results = [adapter.run(repo, scenario, live=live, official=official, repetitions=repetitions, budget_usd=budget_usd) for scenario in scenarios]
        adapter_results[name] = {"capabilities": adapter.capabilities(repo), "scenarios": results}
        all_results.extend(results)
    summary = {
        "passed": sum(1 for result in all_results if result["status"] == "passed"),
        "failed": sum(1 for result in all_results if result["status"] in {"failed", "error"}),
        "flaky": sum(1 for result in all_results if result["status"] == "flaky"),
        "skipped": sum(1 for result in all_results if result["status"] == "skipped"),
    }
    artifact = output or repo / ".forge/scenario-results" / f"{run_id}.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": SCHEMA_VERSION,
        "adapter_contract_version": ADAPTER_CONTRACT_VERSION,
        "run_id": run_id,
        "started_at": started,
        "finished_at": utc_now(),
        "mode": "live" if live else "deterministic",
        "scenario_file": str(scenario_path),
        "host_matrix": host_matrix["hosts"],
        "adapters": adapter_results,
        "summary": summary,
        "artifact": str(artifact),
    }
    artifact.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if receipts is not None:
        record_receipts(receipts, run_id, artifact, all_results, summary)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Forge cross-host conformance scenarios.")
    parser.add_argument("--scenarios", type=Path, default=REPO / "evals/scenarios.jsonl")
    parser.add_argument("--adapter", choices=sorted((*ADAPTERS, "all")), action="append")
    parser.add_argument("--live", action="store_true", help="enable explicit host runner execution")
    parser.add_argument("--official-validator", action="store_true")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--budget-usd", type=float, default=0.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receipts", type=Path, default=REPO / ".forge/receipts.jsonl")
    parser.add_argument("--no-receipts", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        selected = args.adapter or ["reference"]
        names = sorted(ADAPTERS) if "all" in selected else list(dict.fromkeys(selected))
        if args.repetitions < 1 or args.repetitions > 50:
            raise ScenarioError("--repetitions must be between 1 and 50")
        report = run_suite(REPO, args.scenarios, names, live=args.live, official=args.official_validator, repetitions=args.repetitions, budget_usd=args.budget_usd, output=args.output, receipts=None if args.no_receipts else args.receipts)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            summary = report["summary"]
            print(f"Scenario run {report['run_id']}: {summary['passed']} passed, {summary['failed']} failed, {summary['flaky']} flaky, {summary['skipped']} skipped")
            print(f"Artifact: {report['artifact']}")
        return 1 if report["summary"]["failed"] or report["summary"]["flaky"] else 0
    except (OSError, ScenarioError, json.JSONDecodeError) as exc:
        print(f"forge-scenarios: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
