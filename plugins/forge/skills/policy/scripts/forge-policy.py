#!/usr/bin/env python3
"""Evaluate Forge actions against versioned profiles and scoped approvals."""

from __future__ import annotations

import argparse
import copy
import fnmatch
import getpass
import hashlib
import importlib.util
import json
import os
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows does not expose fcntl.
    fcntl = None


SCHEMA_VERSION = 1
DECISIONS = ("allow", "deny", "require_approval", "constrain", "transform")
ACTION_KEYS = {"schema_version", "action_id", "tool", "arguments", "resource", "principal", "workspace", "intent"}
RESOURCE_KEYS = {"repository", "branch", "paths", "domains"}
INTENT_KEYS = {"effect", "external", "risk", "cost_usd", "fan_out"}
PROFILE_KEYS = {"schema_version", "profile", "description", "default_decision", "protected_paths", "constraints", "rules"}
CONSTRAINT_KEYS = {
    "allowed_tools",
    "allowed_repositories",
    "allowed_branches",
    "allowed_paths",
    "allowed_domains",
    "max_cost_usd",
    "max_fan_out",
}
MATCH_KEYS = {"action_id", "tool", "principal", "workspace", "external", "effect", "risk", "repository", "branch", "paths", "domains", "intent", "resource"}
TRANSFORM_KEYS = {"set", "remove"}


class PolicyError(ValueError):
    """Base class for policy and authorization failures."""


class PolicyValidationError(PolicyError):
    """Raised when a versioned policy or action is malformed."""


class PolicyAuthorizationError(PolicyError):
    """Raised when a policy decision does not authorize an effect."""

    def __init__(self, message: str, decision: PolicyDecision | None = None) -> None:
        super().__init__(message)
        self.decision = decision


class ApprovalRequired(PolicyAuthorizationError):
    """Raised when a matching rule requires a one-time approval."""


class ApprovalError(PolicyAuthorizationError):
    """Raised when an approval is stale, mismatched, expired, or reused."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise PolicyValidationError("timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise PolicyValidationError("timestamp must be a non-empty RFC3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PolicyValidationError("timestamp must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise PolicyValidationError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PolicyValidationError(f"value is not canonical JSON: {exc}") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PolicyValidationError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise PolicyValidationError(f"{label} keys must be strings")
    return {str(key): copy.deepcopy(child) for key, child in value.items()}


def _unknown(data: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise PolicyValidationError(f"unknown {label} field(s): {', '.join(unknown)}")


def _string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise PolicyValidationError(f"{label} must be a non-empty string")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise PolicyValidationError(f"{label} must be a list of non-empty strings")
    return list(value)


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise PolicyValidationError(f"{label} must be a non-negative number")
    return float(value)


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PolicyValidationError(f"{label} must be a positive integer")
    return value


def _validate_constraints(value: Any, label: str) -> dict[str, Any]:
    constraints = _mapping(value, label)
    _unknown(constraints, CONSTRAINT_KEYS, label)
    for key in ("allowed_tools", "allowed_repositories", "allowed_branches", "allowed_paths", "allowed_domains"):
        if key in constraints:
            constraints[key] = _string_list(constraints[key], f"{label}.{key}")
    if "max_cost_usd" in constraints:
        constraints["max_cost_usd"] = _number(constraints["max_cost_usd"], f"{label}.max_cost_usd")
    if "max_fan_out" in constraints:
        constraints["max_fan_out"] = _positive_int(constraints["max_fan_out"], f"{label}.max_fan_out")
    return constraints


def _validate_match(value: Any, label: str) -> dict[str, Any]:
    match = _mapping(value, label)
    _unknown(match, MATCH_KEYS, label)
    for key in ("intent", "resource"):
        if key in match:
            match[key] = _validate_match(match[key], f"{label}.{key}")
    for key, expected in match.items():
        if key in {"intent", "resource"}:
            continue
        if isinstance(expected, (dict, tuple)) or expected is None:
            raise PolicyValidationError(f"{label}.{key} must be a scalar or list")
        if isinstance(expected, list) and any(isinstance(item, (dict, list)) for item in expected):
            raise PolicyValidationError(f"{label}.{key} list values must be scalar")
    return match


def _validate_transform(value: Any, label: str) -> dict[str, Any]:
    transform = _mapping(value, label)
    _unknown(transform, TRANSFORM_KEYS, label)
    if "set" in transform:
        transform["set"] = _mapping(transform["set"], f"{label}.set")
        for path in transform["set"]:
            _string(path, f"{label}.set path")
    if "remove" in transform:
        transform["remove"] = _string_list(transform["remove"], f"{label}.remove")
    if "set" not in transform and "remove" not in transform:
        raise PolicyValidationError(f"{label} must include set or remove")
    return transform


@dataclass(frozen=True)
class ActionEnvelope:
    """The exact, versioned input bound by a policy decision."""

    schema_version: int
    action_id: str
    tool: str
    arguments: dict[str, Any]
    resource: dict[str, Any]
    principal: str
    workspace: str
    intent: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ActionEnvelope:
        data = _mapping(value, "action")
        _unknown(data, ACTION_KEYS, "action")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise PolicyValidationError(f"unsupported action schema_version: {data.get('schema_version')}")
        action_id = _string(data.get("action_id"), "action.action_id")
        tool = _string(data.get("tool"), "action.tool")
        arguments = _mapping(data.get("arguments", {}), "action.arguments")
        resource = _mapping(data.get("resource"), "action.resource")
        _unknown(resource, RESOURCE_KEYS, "resource")
        repository = _string(resource.get("repository"), "resource.repository")
        branch = resource.get("branch")
        if branch is not None:
            branch = _string(branch, "resource.branch")
        paths = _string_list(resource.get("paths", []), "resource.paths")
        domains = _string_list(resource.get("domains", []), "resource.domains")
        principal = _string(data.get("principal"), "action.principal")
        workspace = _string(data.get("workspace"), "action.workspace")
        intent = _mapping(data.get("intent"), "action.intent")
        _unknown(intent, INTENT_KEYS, "intent")
        effect = _string(intent.get("effect"), "intent.effect")
        external = intent.get("external")
        if not isinstance(external, bool):
            raise PolicyValidationError("intent.external must be a boolean")
        risk = _string(intent.get("risk"), "intent.risk")
        cost = _number(intent.get("cost_usd", 0), "intent.cost_usd")
        fan_out = _positive_int(intent.get("fan_out", 1), "intent.fan_out")
        return cls(
            schema_version=SCHEMA_VERSION,
            action_id=action_id,
            tool=tool,
            arguments=arguments,
            resource={
                "repository": repository,
                "branch": branch,
                "paths": sorted(set(paths)),
                "domains": sorted(set(domains)),
            },
            principal=principal,
            workspace=workspace,
            intent={
                "effect": effect,
                "external": external,
                "risk": risk,
                "cost_usd": int(cost) if cost.is_integer() else cost,
                "fan_out": fan_out,
            },
        )

    def as_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "action_id": self.action_id,
            "tool": self.tool,
            "arguments": copy.deepcopy(self.arguments),
            "resource": copy.deepcopy(self.resource),
            "principal": self.principal,
            "workspace": self.workspace,
            "intent": copy.deepcopy(self.intent),
        }


@dataclass(frozen=True)
class PolicyProfile:
    """A readable policy profile whose canonical content determines its revision."""

    schema_version: int
    profile: str
    description: str
    default_decision: str
    protected_paths: list[str]
    constraints: dict[str, Any]
    rules: list[dict[str, Any]]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PolicyProfile:
        data = _mapping(value, "profile")
        _unknown(data, PROFILE_KEYS, "profile")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise PolicyValidationError(f"unsupported profile schema_version: {data.get('schema_version')}")
        name = _string(data.get("profile"), "profile.profile")
        description = _string(data.get("description", name), "profile.description")
        default_decision = data.get("default_decision")
        if default_decision not in DECISIONS:
            raise PolicyValidationError("profile.default_decision must be a supported policy decision")
        protected_paths = _string_list(data.get("protected_paths", []), "profile.protected_paths")
        constraints = _validate_constraints(data.get("constraints", {}), "profile.constraints")
        raw_rules = data.get("rules", [])
        if not isinstance(raw_rules, list):
            raise PolicyValidationError("profile.rules must be a list")
        rules: list[dict[str, Any]] = []
        ids: set[str] = set()
        for index, raw_rule in enumerate(raw_rules):
            rule = _mapping(raw_rule, f"profile.rules[{index}]")
            _unknown(rule, {"id", "decision", "match", "reason", "constraints", "transform"}, f"profile.rules[{index}]")
            rule_id = _string(rule.get("id"), f"profile.rules[{index}].id")
            if rule_id in ids:
                raise PolicyValidationError(f"duplicate policy rule id: {rule_id}")
            ids.add(rule_id)
            decision = rule.get("decision")
            if decision not in DECISIONS:
                raise PolicyValidationError(f"profile.rules[{index}].decision is unsupported")
            normalized = {
                "id": rule_id,
                "decision": decision,
                "match": _validate_match(rule.get("match", {}), f"profile.rules[{index}].match"),
                "reason": _string(rule.get("reason", f"Rule {rule_id} matched."), f"profile.rules[{index}].reason"),
                "constraints": _validate_constraints(rule.get("constraints", {}), f"profile.rules[{index}].constraints"),
            }
            if "transform" in rule:
                if decision != "transform":
                    raise PolicyValidationError(f"profile.rules[{index}].transform requires decision=transform")
                normalized["transform"] = _validate_transform(rule["transform"], f"profile.rules[{index}].transform")
            elif decision == "transform":
                raise PolicyValidationError(f"profile.rules[{index}] transform decision requires a transform")
            rules.append(normalized)
        return cls(SCHEMA_VERSION, name, description, default_decision, protected_paths, constraints, rules)

    @classmethod
    def from_file(cls, path: Path) -> PolicyProfile:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PolicyValidationError(f"cannot load policy profile {path}: {exc}") from exc
        return cls.from_mapping(data)

    @property
    def revision(self) -> str:
        return digest(self.as_mapping())

    def as_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "description": self.description,
            "default_decision": self.default_decision,
            "protected_paths": list(self.protected_paths),
            "constraints": copy.deepcopy(self.constraints),
            "rules": copy.deepcopy(self.rules),
        }


@dataclass(frozen=True)
class PolicyDecision:
    schema_version: int
    decision: str
    profile: str
    policy_revision: str
    action_digest: str
    rule_id: str
    reason: str
    principal: str
    workspace: str
    tool: str
    resource: dict[str, Any]
    intent: dict[str, Any]
    constraints: dict[str, Any]
    approval_required: bool
    transformed_action_digest: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "decision": self.decision,
            "profile": self.profile,
            "policy_revision": self.policy_revision,
            "action_digest": self.action_digest,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "principal": self.principal,
            "workspace": self.workspace,
            "tool": self.tool,
            "resource": copy.deepcopy(self.resource),
            "intent": copy.deepcopy(self.intent),
            "constraints": copy.deepcopy(self.constraints),
            "approval_required": self.approval_required,
        }
        if self.transformed_action_digest:
            result["transformed_action_digest"] = self.transformed_action_digest
        return result


@dataclass(frozen=True)
class PolicyEvaluation:
    action: ActionEnvelope
    effective_action: ActionEnvelope
    decision: PolicyDecision


@dataclass(frozen=True)
class ApprovalRecord:
    schema_version: int
    approval_id: str
    action_digest: str
    principal: str
    workspace: str
    policy_revision: str
    profile: str
    tool: str
    resource: dict[str, Any]
    effect: str
    rule_id: str
    reason: str
    issued_at: str
    expires_at: str
    uses: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "approval_id": self.approval_id,
            "action_digest": self.action_digest,
            "principal": self.principal,
            "workspace": self.workspace,
            "policy_revision": self.policy_revision,
            "profile": self.profile,
            "tool": self.tool,
            "resource": copy.deepcopy(self.resource),
            "effect": self.effect,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "uses": self.uses,
        }


@dataclass(frozen=True)
class PolicyAuthorization:
    action: ActionEnvelope
    effective_action: ActionEnvelope
    decision: PolicyDecision
    status: str
    approval_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "status": self.status,
            "action_digest": self.decision.action_digest,
            "effective_action_digest": digest(self.effective_action.as_mapping()),
            "approval_id": self.approval_id,
            "decision": self.decision.as_dict(),
        }
        return result


class ApprovalStore:
    """Append-only, 0600 approval records with a locked one-use consume path."""

    def __init__(self, path: Path, *, clock: Callable[[], datetime] = utc_now) -> None:
        self.path = path
        self.clock = clock

    def _records(self, handle: Any) -> list[dict[str, Any]]:
        handle.seek(0)
        records: list[dict[str, Any]] = []
        for number, line in enumerate(handle.read().splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ApprovalError(f"invalid approval record {number}") from exc
            if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
                raise ApprovalError(f"invalid approval record {number}")
            if record.get("event") not in {"issued", "consumed"}:
                raise ApprovalError(f"invalid approval event in record {number}")
            records.append(record)
        return records

    def _locked(self, callback: Callable[[Any], Any]) -> Any:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as handle:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                return callback(handle)
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def issue(self, evaluation: PolicyEvaluation, *, ttl_seconds: int = 600) -> ApprovalRecord:
        if evaluation.decision.decision != "require_approval":
            raise PolicyError("approval can only be issued for a require_approval decision")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 86_400:
            raise PolicyValidationError("approval TTL must be an integer between 1 and 86400 seconds")
        now = self.clock()
        record = ApprovalRecord(
            schema_version=SCHEMA_VERSION,
            approval_id=str(uuid.uuid4()),
            action_digest=evaluation.decision.action_digest,
            principal=evaluation.action.principal,
            workspace=evaluation.action.workspace,
            policy_revision=evaluation.decision.policy_revision,
            profile=evaluation.decision.profile,
            tool=evaluation.action.tool,
            resource=copy.deepcopy(evaluation.decision.resource),
            effect=evaluation.action.intent["effect"],
            rule_id=evaluation.decision.rule_id,
            reason=evaluation.decision.reason,
            issued_at=timestamp(now),
            expires_at=timestamp(now + timedelta(seconds=ttl_seconds)),
        )

        def append(handle: Any) -> ApprovalRecord:
            self._records(handle)
            handle.seek(0, 2)
            payload = {"event": "issued", **record.as_dict()}
            handle.write(canonical_json(payload) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            return record

        return self._locked(append)

    def consume(
        self,
        approval_id: str,
        evaluation: PolicyEvaluation,
    ) -> ApprovalRecord:
        _string(approval_id, "approval_id")

        def consume_locked(handle: Any) -> ApprovalRecord:
            records = self._records(handle)
            issued = next((record for record in records if record.get("event") == "issued" and record.get("approval_id") == approval_id), None)
            if issued is None:
                raise ApprovalError("approval was not found")
            if any(record.get("event") == "consumed" and record.get("approval_id") == approval_id for record in records):
                raise ApprovalError("approval was already consumed")
            if issued.get("principal") != evaluation.action.principal:
                raise ApprovalError("approval principal mismatch")
            if issued.get("workspace") != evaluation.action.workspace:
                raise ApprovalError("approval workspace mismatch")
            if issued.get("policy_revision") != evaluation.decision.policy_revision:
                raise ApprovalError("approval policy revision mismatch")
            if issued.get("action_digest") != evaluation.decision.action_digest:
                raise ApprovalError("approval action digest mismatch")
            if parse_timestamp(str(issued.get("expires_at"))) <= self.clock().astimezone(timezone.utc):
                raise ApprovalError("approval has expired")
            record = ApprovalRecord(
                schema_version=SCHEMA_VERSION,
                approval_id=str(issued["approval_id"]),
                action_digest=str(issued["action_digest"]),
                principal=str(issued["principal"]),
                workspace=str(issued["workspace"]),
                policy_revision=str(issued["policy_revision"]),
                profile=str(issued["profile"]),
                tool=str(issued["tool"]),
                resource=copy.deepcopy(issued.get("resource", {})),
                effect=str(issued["effect"]),
                rule_id=str(issued["rule_id"]),
                reason=str(issued["reason"]),
                issued_at=str(issued["issued_at"]),
                expires_at=str(issued["expires_at"]),
                uses=int(issued.get("uses", 1)),
            )
            handle.seek(0, 2)
            handle.write(canonical_json({"event": "consumed", "schema_version": SCHEMA_VERSION, "approval_id": approval_id, "consumed_at": timestamp(self.clock())}) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            return record

        return self._locked(consume_locked)

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as handle:
            return self._records(handle)


def _normalize_path(value: str) -> str:
    result = value.replace("\\", "/")
    while result.startswith("./"):
        result = result[2:]
    return result


def _path_matches(path: str, pattern: str, workspace: str) -> bool:
    normalized_path = _normalize_path(path)
    normalized_pattern = _normalize_path(pattern)
    variants = {normalized_path, normalized_path.lstrip("/")}
    patterns = {normalized_pattern}
    if normalized_pattern.startswith("**/"):
        patterns.add(normalized_pattern[3:])
    if Path(normalized_path).is_absolute():
        try:
            variants.add(_normalize_path(str(Path(normalized_path).relative_to(Path(workspace)))))
        except ValueError:
            pass
    if "/" not in normalized_pattern:
        variants.add(Path(normalized_path).name)
    return any(fnmatch.fnmatchcase(candidate, candidate_pattern) for candidate in variants for candidate_pattern in patterns)


def _match_value(actual: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return actual in expected
    if isinstance(actual, list):
        return expected in actual
    return actual == expected


def _matches(match: Mapping[str, Any], action: ActionEnvelope) -> bool:
    sections = {"intent": action.intent, "resource": action.resource}
    flat = {
        "action_id": action.action_id,
        "tool": action.tool,
        "principal": action.principal,
        "workspace": action.workspace,
        "external": action.intent["external"],
        "effect": action.intent["effect"],
        "risk": action.intent["risk"],
        "repository": action.resource["repository"],
        "branch": action.resource["branch"],
        "paths": action.resource["paths"],
        "domains": action.resource["domains"],
    }
    for key, expected in match.items():
        if key in sections:
            if not isinstance(expected, Mapping):
                return False
            actual = sections[key]
            if any(not _match_value(actual.get(child_key), child_expected) for child_key, child_expected in expected.items()):
                return False
        elif not _match_value(flat.get(key), expected):
            return False
    return True


def _constraint_failure(constraints: Mapping[str, Any], action: ActionEnvelope) -> str | None:
    checks = (
        ("allowed_tools", action.tool, lambda expected: action.tool in expected, "tool"),
        ("allowed_repositories", action.resource["repository"], lambda expected: action.resource["repository"] in expected, "repository"),
        ("allowed_branches", action.resource["branch"], lambda expected: action.resource["branch"] in expected, "branch"),
        ("allowed_domains", action.resource["domains"], lambda expected: all(domain in expected for domain in action.resource["domains"]), "domain"),
    )
    for key, actual, predicate, label in checks:
        if key in constraints and not predicate(constraints[key]):
            return f"{label} is outside the declared {key} constraint"
    if "allowed_paths" in constraints:
        if any(
            not any(_path_matches(path, pattern, action.workspace) for pattern in constraints["allowed_paths"])
            for path in action.resource["paths"]
        ):
            return "path is outside the declared allowed_paths constraint"
    if "max_cost_usd" in constraints and action.intent["cost_usd"] > constraints["max_cost_usd"]:
        return "intended cost exceeds max_cost_usd"
    if "max_fan_out" in constraints and action.intent["fan_out"] > constraints["max_fan_out"]:
        return "fan-out exceeds max_fan_out"
    return None


def _protected_paths(paths: list[str], patterns: list[str], workspace: str) -> list[str]:
    return [path for path in paths if any(_path_matches(path, pattern, workspace) for pattern in patterns)]


def _get_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise PolicyValidationError(f"transform path does not exist: {path}")
        current = current[part]
    return current


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    if any(not part for part in parts):
        raise PolicyValidationError(f"invalid transform path: {path}")
    current: dict[str, Any] = data
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            raise PolicyValidationError(f"transform path is not an object: {path}")
        current = child
    current[parts[-1]] = copy.deepcopy(value)


def _remove_path(data: dict[str, Any], path: str) -> None:
    parts = path.split(".")
    if any(not part for part in parts):
        raise PolicyValidationError(f"invalid transform path: {path}")
    current: dict[str, Any] = data
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            raise PolicyValidationError(f"transform path does not exist: {path}")
        current = child
    if parts[-1] not in current:
        raise PolicyValidationError(f"transform path does not exist: {path}")
    del current[parts[-1]]


def _apply_transform(action: ActionEnvelope, transform: Mapping[str, Any]) -> ActionEnvelope:
    data = action.as_mapping()
    for path, value in transform.get("set", {}).items():
        _get_path(data, path)
        _set_path(data, path, value)
    for path in transform.get("remove", []):
        _remove_path(data, path)
    return ActionEnvelope.from_mapping(data)


def _load_receipts_module() -> Any:
    module_path = Path(__file__).resolve().parents[2] / "observability" / "scripts" / "forge-receipts.py"
    spec = importlib.util.spec_from_file_location("forge_receipts", module_path)
    if spec is None or spec.loader is None:
        raise PolicyError("could not load Forge receipt store")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PolicyEngine:
    """Evaluate actions, issue scoped approvals, and record authorization evidence."""

    def __init__(
        self,
        profile: PolicyProfile,
        *,
        approvals_path: Path | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.profile = profile
        self.approvals_path = approvals_path or Path(".forge/approvals.jsonl")
        self.clock = clock

    def action_digest(self, action: ActionEnvelope | Mapping[str, Any]) -> str:
        envelope = action if isinstance(action, ActionEnvelope) else ActionEnvelope.from_mapping(action)
        return digest({"policy_revision": self.profile.revision, "action": envelope.as_mapping()})

    def evaluate(self, action: ActionEnvelope | Mapping[str, Any]) -> PolicyEvaluation:
        envelope = action if isinstance(action, ActionEnvelope) else ActionEnvelope.from_mapping(action)
        original_digest = self.action_digest(envelope)
        profile_failure = _constraint_failure(self.profile.constraints, envelope)
        selected = next((rule for rule in self.profile.rules if _matches(rule["match"], envelope)), None)
        decision = selected["decision"] if selected else self.profile.default_decision
        rule_id = selected["id"] if selected else "default"
        reason = selected["reason"] if selected else f"Profile default decision: {decision}."
        constraints = {
            "profile": copy.deepcopy(self.profile.constraints),
            "rule": copy.deepcopy(selected["constraints"] if selected else {}),
        }
        if profile_failure:
            decision = "deny"
            rule_id = "profile-constraint"
            reason = profile_failure
        elif selected:
            rule_failure = _constraint_failure(selected["constraints"], envelope)
            if rule_failure:
                decision = "deny"
                rule_id = f"{selected['id']}:constraint"
                reason = rule_failure

        effective = envelope
        if decision == "transform":
            effective = _apply_transform(envelope, selected["transform"])
            transformed_failure = _constraint_failure(self.profile.constraints, effective)
            if transformed_failure:
                decision = "deny"
                rule_id = "transformed-constraint"
                reason = transformed_failure

        protected = _protected_paths(effective.resource["paths"], self.profile.protected_paths, effective.workspace)
        if protected and decision in {"allow", "constrain", "transform"}:
            decision = "require_approval"
            rule_id = "protected-path"
            reason = f"protected resource requires approval ({len(protected)} path(s))"
        transformed_digest = self.action_digest(effective) if effective != envelope else None
        policy_decision = PolicyDecision(
            schema_version=SCHEMA_VERSION,
            decision=decision,
            profile=self.profile.profile,
            policy_revision=self.profile.revision,
            action_digest=original_digest,
            rule_id=rule_id,
            reason=reason,
            principal=envelope.principal,
            workspace=envelope.workspace,
            tool=envelope.tool,
            resource=copy.deepcopy(effective.resource),
            intent=copy.deepcopy(effective.intent),
            constraints=constraints,
            approval_required=decision == "require_approval",
            transformed_action_digest=transformed_digest,
        )
        return PolicyEvaluation(envelope, effective, policy_decision)

    def _record(
        self,
        event_type: str,
        evaluation: PolicyEvaluation,
        *,
        receipts_path: Path | None,
        idempotency_key: str,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        if receipts_path is None:
            return
        module = _load_receipts_module()
        decision = evaluation.decision
        attributes: dict[str, Any] = {
            "action_digest": decision.action_digest,
            "effective_action_digest": decision.transformed_action_digest or decision.action_digest,
            "rule_id": decision.rule_id,
            "reason": decision.reason,
            "principal": evaluation.action.principal,
            "workspace": evaluation.action.workspace,
            "tool": evaluation.action.tool,
            "resource": copy.deepcopy(decision.resource),
            "intended_effect": evaluation.effective_action.intent["effect"],
            "decision": decision.decision,
            "profile": decision.profile,
        }
        attributes.update(dict(extra or {}))
        module.ReceiptStore(receipts_path).append(
            module.make_event(
                event_type,
                f"policy:{self.profile.profile}",
                idempotency_key=idempotency_key,
                policy_revision=decision.policy_revision,
                attributes=attributes,
            )
        )

    def issue_approval(
        self,
        action: ActionEnvelope | Mapping[str, Any],
        *,
        ttl_seconds: int = 600,
        receipts_path: Path | None = None,
    ) -> ApprovalRecord:
        evaluation = self.evaluate(action)
        if evaluation.decision.decision != "require_approval":
            raise PolicyError("the current policy does not require approval for this action")
        approval = ApprovalStore(self.approvals_path, clock=self.clock).issue(evaluation, ttl_seconds=ttl_seconds)
        self._record(
            "approval.requested",
            evaluation,
            receipts_path=receipts_path,
            idempotency_key=f"policy:approval-requested:{approval.approval_id}",
            extra={"approval_id": approval.approval_id, "expires_at": approval.expires_at, "approval_status": "issued"},
        )
        return approval

    def authorize(
        self,
        action: ActionEnvelope | Mapping[str, Any],
        *,
        approval_id: str | None = None,
        staged: bool = False,
        receipts_path: Path | None = None,
    ) -> PolicyAuthorization:
        evaluation = self.evaluate(action)
        decision = evaluation.decision
        if staged:
            self._record(
                "outcome.recorded",
                evaluation,
                receipts_path=receipts_path,
                idempotency_key=f"policy:staged:{decision.action_digest}",
                extra={"committed_effect": "staged-preview", "authorization_status": "staged"},
            )
            return PolicyAuthorization(evaluation.action, evaluation.effective_action, decision, "staged")
        if decision.decision == "deny":
            self._record(
                "approval.denied",
                evaluation,
                receipts_path=receipts_path,
                idempotency_key=f"policy:denied:{decision.action_digest}",
                extra={"authorization_status": "denied"},
            )
            raise PolicyAuthorizationError(f"policy denied action: {decision.reason}", decision)
        if decision.decision == "require_approval":
            if not approval_id:
                self._record(
                    "approval.requested",
                    evaluation,
                    receipts_path=receipts_path,
                    idempotency_key=f"policy:approval-required:{decision.action_digest}",
                    extra={"approval_status": "required"},
                )
                raise ApprovalRequired(f"approval required by rule {decision.rule_id}", decision)
            try:
                approval = ApprovalStore(self.approvals_path, clock=self.clock).consume(approval_id, evaluation)
            except ApprovalError:
                self._record(
                    "approval.denied",
                    evaluation,
                    receipts_path=receipts_path,
                    idempotency_key=f"policy:approval-denied:{decision.action_digest}:{approval_id}",
                    extra={"approval_id": approval_id, "approval_status": "rejected"},
                )
                raise
            self._record(
                "approval.granted",
                evaluation,
                receipts_path=receipts_path,
                idempotency_key=f"policy:approval-granted:{approval.approval_id}",
                extra={"approval_id": approval.approval_id, "approval_status": "consumed"},
            )
            return PolicyAuthorization(evaluation.action, evaluation.effective_action, decision, "authorized", approval.approval_id)
        self._record(
            "approval.granted",
            evaluation,
            receipts_path=receipts_path,
            idempotency_key=f"policy:authorized:{decision.action_digest}",
            extra={"approval_status": "not-required"},
        )
        return PolicyAuthorization(evaluation.action, evaluation.effective_action, decision, "authorized")

    def commit(
        self,
        authorization: PolicyAuthorization,
        result: Mapping[str, Any] | Any,
        *,
        receipts_path: Path | None = None,
    ) -> dict[str, Any]:
        if authorization.status != "authorized":
            raise PolicyAuthorizationError("only an authorized action can be committed", authorization.decision)
        result_digest = digest(result)
        self._record(
            "outcome.recorded",
            PolicyEvaluation(authorization.action, authorization.effective_action, authorization.decision),
            receipts_path=receipts_path,
            idempotency_key=f"policy:outcome:{authorization.decision.action_digest}",
            extra={
                "committed_effect": authorization.effective_action.intent["effect"],
                "committed_result_sha256": result_digest,
                "authorization_status": "committed",
            },
        )
        return {
            "status": "committed",
            "action_digest": authorization.decision.action_digest,
            "committed_effect": authorization.effective_action.intent["effect"],
            "result_sha256": result_digest,
        }

    def recheck(
        self,
        authorization: PolicyAuthorization,
        *,
        receipts_path: Path | None = None,
    ) -> PolicyEvaluation:
        """Re-evaluate an authorized action immediately before an effect."""
        if authorization.status != "authorized":
            raise PolicyAuthorizationError("only an authorized action can be rechecked", authorization.decision)
        current = self.evaluate(authorization.action)
        unchanged = (
            current.decision.policy_revision == authorization.decision.policy_revision
            and current.decision.action_digest == authorization.decision.action_digest
            and current.effective_action == authorization.effective_action
            and current.decision.decision != "deny"
        )
        if not unchanged:
            self._record(
                "approval.denied",
                current,
                receipts_path=receipts_path,
                idempotency_key=f"policy:recheck-denied:{authorization.decision.action_digest}",
                extra={"authorization_status": "recheck-failed"},
            )
            raise PolicyAuthorizationError("policy changed after authorization; refusing the effect", current.decision)
        return current


class PolicySession:
    """Small adapter bridge for mutation backends; enterprise providers can wrap it."""

    def __init__(
        self,
        profile_path: Path,
        *,
        approvals_path: Path | None = None,
        receipts_path: Path | None = None,
        principal: str | None = None,
        workspace: Path | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.receipts_path = receipts_path
        self.principal = principal or os.environ.get("FORGE_PRINCIPAL") or f"user:{getpass.getuser()}"
        self.workspace = str((workspace or Path.cwd()).resolve())
        self.engine = PolicyEngine(
            PolicyProfile.from_file(profile_path),
            approvals_path=approvals_path,
            clock=clock,
        )

    def action(
        self,
        *,
        action_id: str,
        tool: str,
        arguments: Mapping[str, Any],
        repository: str,
        branch: str | None,
        paths: list[str],
        domains: list[str],
        effect: str,
        risk: str,
        cost_usd: int | float = 0,
        fan_out: int = 1,
    ) -> ActionEnvelope:
        return ActionEnvelope.from_mapping(
            {
                "schema_version": SCHEMA_VERSION,
                "action_id": action_id,
                "tool": tool,
                "arguments": dict(arguments),
                "resource": {"repository": repository, "branch": branch, "paths": paths, "domains": domains},
                "principal": self.principal,
                "workspace": self.workspace,
                "intent": {"effect": effect, "external": True, "risk": risk, "cost_usd": cost_usd, "fan_out": fan_out},
            }
        )

    def authorize(self, action: ActionEnvelope, *, approval_id: str | None = None, staged: bool = False) -> PolicyAuthorization:
        return self.engine.authorize(action, approval_id=approval_id, staged=staged, receipts_path=self.receipts_path)

    def commit(self, authorization: PolicyAuthorization, result: Mapping[str, Any] | Any) -> dict[str, Any]:
        return self.engine.commit(authorization, result, receipts_path=self.receipts_path)

    def recheck(self, authorization: PolicyAuthorization) -> PolicyEvaluation:
        return self.engine.recheck(authorization, receipts_path=self.receipts_path)


def resolve_profile(value: str, profiles_dir: Path) -> Path:
    candidate = Path(value)
    if candidate.is_file():
        return candidate
    candidate = profiles_dir / f"{value}.json"
    if candidate.is_file():
        return candidate
    raise PolicyValidationError(f"policy profile not found: {value}")


def load_action(path: Path) -> ActionEnvelope:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyValidationError(f"cannot load action {path}: {exc}") from exc
    return ActionEnvelope.from_mapping(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Forge actions against versioned policy profiles.")
    parser.add_argument("--profile", default="default", help="profile name in --profiles-dir or a JSON path")
    parser.add_argument("--profiles-dir", type=Path, default=Path("policies"))
    parser.add_argument("--approvals", type=Path, default=Path(".forge/approvals.jsonl"))
    parser.add_argument("--receipts", type=Path, default=Path(".forge/receipts.jsonl"))
    parser.add_argument("--json", action="store_true", help="reserved for compatibility; output is JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("profiles", help="list readable policy profiles")
    for name, help_text in (("evaluate", "evaluate an action without authorizing it"), ("stage", "write a no-effect staged preview"), ("approve", "issue a one-time scoped approval"), ("authorize", "authorize an action immediately before its effect"), ("commit", "record final committed-effect evidence")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--action", type=Path, required=True)
    sub.choices["stage"].add_argument("--output", type=Path)
    sub.choices["approve"].add_argument("--ttl-seconds", type=int, default=600)
    sub.choices["authorize"].add_argument("--approval-id")
    sub.choices["authorize"].add_argument("--staged", action="store_true")
    sub.choices["commit"].add_argument("--approval-id")
    sub.choices["commit"].add_argument("--effect", required=True)
    sub.choices["commit"].add_argument("--result-json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "profiles":
            profiles = []
            for path in sorted(args.profiles_dir.glob("*.json")):
                try:
                    value = PolicyProfile.from_file(path)
                except PolicyError:
                    continue
                profiles.append({"profile": value.profile, "description": value.description, "path": str(path), "policy_revision": value.revision})
            print(json.dumps(profiles, indent=2, sort_keys=True))
            return 0
        profile_path = resolve_profile(args.profile, args.profiles_dir)
        engine = PolicyEngine(PolicyProfile.from_file(profile_path), approvals_path=args.approvals)
        envelope = load_action(args.action)
        if args.command == "evaluate":
            print(json.dumps(engine.evaluate(envelope).decision.as_dict(), indent=2, sort_keys=True))
        elif args.command == "stage":
            preview = engine.authorize(envelope, staged=True, receipts_path=args.receipts).as_dict()
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(preview, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps(preview, indent=2, sort_keys=True))
        elif args.command == "approve":
            approval = engine.issue_approval(envelope, ttl_seconds=args.ttl_seconds, receipts_path=args.receipts)
            print(json.dumps(approval.as_dict(), indent=2, sort_keys=True))
        elif args.command == "authorize":
            authorized = engine.authorize(envelope, approval_id=args.approval_id, staged=args.staged, receipts_path=args.receipts)
            print(json.dumps(authorized.as_dict(), indent=2, sort_keys=True))
        elif args.command == "commit":
            if args.effect != envelope.intent["effect"]:
                raise PolicyValidationError("committed effect must match the action intent")
            authorized = engine.authorize(envelope, approval_id=args.approval_id, receipts_path=args.receipts)
            result: Any = {"effect": args.effect}
            if args.result_json:
                try:
                    result = json.loads(args.result_json.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise PolicyValidationError(f"cannot load result JSON: {exc}") from exc
            print(json.dumps(engine.commit(authorized, result, receipts_path=args.receipts), indent=2, sort_keys=True))
    except (OSError, PolicyError) as exc:
        print(f"forge-policy: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
