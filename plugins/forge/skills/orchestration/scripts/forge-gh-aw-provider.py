#!/usr/bin/env python3
"""Execute fenced Forge gh-aw effects through a bounded GitHub REST adapter.

Planning and approval are local-only. The execute command remains inert unless ``--execute``
is supplied, then rechecks the runtime lease, exact request-bound policy approval, expected
GitHub login, and provider preconditions immediately before one external effect.
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows does not expose fcntl.
    fcntl = None


REPO = Path(__file__).resolve().parents[5]
DEFAULT_SPEC = REPO / "data" / "gh-aw-workflows.json"
DEFAULT_OUTPUT = REPO / "build" / "gh-aw"
DEFAULT_DB = REPO / ".forge" / "runtime.sqlite3"
DEFAULT_APPROVALS = REPO / ".forge" / "approvals.jsonl"
DEFAULT_RECEIPTS = REPO / ".forge" / "receipts.jsonl"
DEFAULT_JOURNAL = REPO / ".forge" / "gh-aw-provider.jsonl"
REQUEST_SCHEMA = "https://github.com/AlisinaDevelo/md-files/schema/runtime/gh-aw-provider-request/v1"
PROVIDER_REVISION = "forge-gh-aw-provider-v1"
FIREWALL_POLICY_REVISION = "forge-gh-aw-firewall-v2"
SCHEMA_VERSION = 1
GITHUB_API_VERSION = "2026-03-10"
SAFE_OUTPUT_TYPES = {
    "add-comment",
    "create-issue",
    "create-pull-request",
    "dispatch-workflow",
}
REQUEST_KEYS = {
    "$schema",
    "schema_version",
    "adapter_contract_revision",
    "episode_id",
    "request_ref",
    "repository",
    "workflow_id",
    "contract_evidence",
    "contract_evidence_ref",
    "safe_output_type",
    "operations",
}
OPERATION_KEYS = {
    "add-comment": {"type", "item_number", "body"},
    "create-issue": {"type", "title", "body", "labels"},
    "create-pull-request": {
        "type",
        "title",
        "body",
        "head",
        "base",
        "head_sha",
        "changed_files",
        "draft",
    },
    "dispatch-workflow": {"type", "workflow_id", "ref", "inputs"},
}
REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORKFLOW_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
EPISODE_RE = re.compile(r"^gh-aw:[A-Za-z0-9._:/-]+$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
CREDENTIAL_VALUE_RE = re.compile(
    r"(?:github_pat_|gh[opusr]_[A-Za-z0-9]|Bearer\s+[A-Za-z0-9._~+/=-])",
    re.IGNORECASE,
)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
UNSAFE_PROTOCOL_RE = re.compile(r"\b(?:javascript|data|file|vbscript)\s*:", re.IGNORECASE)
MENTION_RE = re.compile(r"(?<![A-Za-z0-9_.])@([A-Za-z0-9_-]+)")
LINK_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
GENESIS_HASH = "sha256:" + "0" * 64
JOURNAL_KEYS = {
    "schema_version",
    "sequence",
    "event_type",
    "effect_id",
    "execution_digest",
    "occurred_at",
    "previous_hash",
    "details",
    "event_hash",
}
AUTHORIZED_DETAIL_KEYS = {"approval_id", "approval_ref", "action_digest"}
SUCCEEDED_DETAIL_KEYS = {"receipt", "recovered", "reconciled"}
SUCCEEDED_REQUIRED_DETAIL_KEYS = {"receipt", "recovered"}
RECEIPT_KEYS = {
    "status",
    "episode_id",
    "workflow_id",
    "safe_output_type",
    "approval_id",
    "adapter_contract_revision",
    "provider_request_id",
    "resource_ref",
    "result_ref",
}


class GhAwProviderError(ValueError):
    """Raised when a provider request or transition fails closed."""


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GhAwProviderError(f"cannot load Forge module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _bridge() -> Any:
    return _load_module(
        "forge_gh_aw_provider_bridge",
        Path(__file__).with_name("forge-gh-aw-runtime.py"),
    )


def _policy() -> Any:
    return _load_module(
        "forge_gh_aw_provider_policy",
        REPO / "plugins" / "forge" / "skills" / "policy" / "scripts" / "forge-policy.py",
    )


def _host_admission() -> Any:
    return _load_module(
        "forge_gh_aw_provider_host_admission",
        REPO
        / "plugins"
        / "forge"
        / "skills"
        / "policy"
        / "scripts"
        / "forge-host-admission.py",
    )


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise GhAwProviderError(f"value is not canonical JSON: {exc}") from exc


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _timestamp(value: str | None = None) -> str:
    if value is None:
        parsed = datetime.now(timezone.utc)
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise GhAwProviderError("now must be an RFC3339 timestamp") from exc
        if parsed.tzinfo is None:
            raise GhAwProviderError("now must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _clock(value: str | None) -> Callable[[], datetime]:
    timestamp = _timestamp(value)
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return lambda: parsed


def _unknown(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise GhAwProviderError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _text(value: Any, label: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise GhAwProviderError(
            f"{label} must be non-empty text of at most {maximum} characters"
        )
    return value


def _ref(value: Any, label: str) -> str:
    if not isinstance(value, str) or not REF_RE.fullmatch(value):
        raise GhAwProviderError(f"{label} must be a sha256 reference")
    return value


def _string_list(
    value: Any,
    label: str,
    *,
    maximum_items: int = 50,
    maximum_length: int = 256,
    allow_empty: bool = True,
) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise GhAwProviderError(f"{label} must be a list of at most {maximum_items} strings")
    if not allow_empty and not value:
        raise GhAwProviderError(f"{label} must not be empty")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_text(item, f"{label}[{index}]", maximum=maximum_length))
    if len(set(result)) != len(result):
        raise GhAwProviderError(f"{label} must not contain duplicates")
    return result


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GhAwProviderError(f"{label} must be a positive integer")
    return value


def _reject_credentials(value: Any, path: str = "request") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower().replace("-", "_")
            if any(
                token in lowered
                for token in ("token", "secret", "password", "private_key", "authorization")
            ):
                raise GhAwProviderError(f"{path}.{key} may contain a credential")
            _reject_credentials(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_credentials(child, f"{path}[{index}]")
    elif isinstance(value, str) and CREDENTIAL_VALUE_RE.search(value):
        raise GhAwProviderError(f"{path} contains a credential-shaped value")


def _branch(value: Any, label: str) -> str:
    branch = _text(value, label, maximum=255)
    if (
        not BRANCH_RE.fullmatch(branch)
        or ".." in branch
        or "@{" in branch
        or branch.endswith(("/", "."))
    ):
        raise GhAwProviderError(f"{label} is not a safe Git reference")
    return branch


def _path(value: Any, label: str) -> str:
    path = _text(value, label, maximum=512)
    if (
        path.startswith(("/", "~"))
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise GhAwProviderError(f"{label} must be a normalized repository-relative path")
    return path


def _validate_operation(value: Any, output_type: str, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GhAwProviderError(f"operations[{index}] must be an object")
    operation = copy.deepcopy(dict(value))
    _unknown(operation, OPERATION_KEYS[output_type], f"operations[{index}]")
    if operation.get("type") != output_type:
        raise GhAwProviderError(f"operations[{index}].type must be {output_type}")
    if output_type == "dispatch-workflow":
        workflow_id = _text(
            operation.get("workflow_id"),
            f"operations[{index}].workflow_id",
            maximum=128,
        )
        if not WORKFLOW_RE.fullmatch(workflow_id):
            raise GhAwProviderError(f"operations[{index}].workflow_id is invalid")
        inputs = operation.get("inputs", {})
        if not isinstance(inputs, Mapping) or len(inputs) > 25:
            raise GhAwProviderError(
                f"operations[{index}].inputs must be an object with at most 25 properties"
            )
        normalized_inputs: dict[str, Any] = {}
        for key, child in inputs.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", key):
                raise GhAwProviderError(f"operations[{index}].inputs has an invalid key")
            if isinstance(child, bool):
                normalized_inputs[key] = child
            elif isinstance(child, (str, int, float)) and not isinstance(child, bool):
                canonical_json(child)
                normalized_inputs[key] = child
            else:
                raise GhAwProviderError(
                    f"operations[{index}].inputs.{key} must be a string, number, or boolean"
                )
        return {
            "type": output_type,
            "workflow_id": workflow_id,
            "ref": _branch(operation.get("ref"), f"operations[{index}].ref"),
            "inputs": normalized_inputs,
        }
    if output_type == "add-comment":
        body = _text(operation.get("body"), f"operations[{index}].body", maximum=65_536)
        return {
            "type": output_type,
            "item_number": _positive_int(
                operation.get("item_number"), f"operations[{index}].item_number"
            ),
            "body": body,
        }
    if output_type == "create-issue":
        return {
            "type": output_type,
            "title": _text(
                operation.get("title"), f"operations[{index}].title", maximum=256
            ),
            "body": _text(
                operation.get("body"), f"operations[{index}].body", maximum=65_536
            ),
            "labels": _string_list(
                operation.get("labels", []),
                f"operations[{index}].labels",
                maximum_items=20,
                maximum_length=64,
            ),
        }
    changed_files = _string_list(
        operation.get("changed_files"),
        f"operations[{index}].changed_files",
        maximum_items=300,
        maximum_length=512,
        allow_empty=False,
    )
    draft = operation.get("draft", True)
    if not isinstance(draft, bool):
        raise GhAwProviderError(f"operations[{index}].draft must be a boolean")
    head_sha = _text(
        operation.get("head_sha"), f"operations[{index}].head_sha", maximum=40
    )
    if not SHA_RE.fullmatch(head_sha):
        raise GhAwProviderError(f"operations[{index}].head_sha must be a lowercase commit SHA")
    return {
        "type": output_type,
        "title": _text(operation.get("title"), f"operations[{index}].title", maximum=256),
        "body": _text(operation.get("body"), f"operations[{index}].body", maximum=65_536),
        "head": _branch(operation.get("head"), f"operations[{index}].head"),
        "base": _branch(operation.get("base"), f"operations[{index}].base"),
        "head_sha": head_sha,
        "changed_files": [_path(item, f"operations[{index}].changed_files") for item in changed_files],
        "draft": draft,
    }


def validate_request(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GhAwProviderError("provider request must be an object")
    request = copy.deepcopy(dict(value))
    _unknown(request, REQUEST_KEYS, "request")
    if request.get("$schema") != REQUEST_SCHEMA:
        raise GhAwProviderError("provider request has the wrong schema URI")
    if request.get("schema_version") != SCHEMA_VERSION:
        raise GhAwProviderError("unsupported provider request schema version")
    if request.get("adapter_contract_revision") != PROVIDER_REVISION:
        raise GhAwProviderError("unsupported provider adapter contract revision")
    episode_id = _text(request.get("episode_id"), "episode_id", maximum=256)
    if not EPISODE_RE.fullmatch(episode_id):
        raise GhAwProviderError("episode_id must use the canonical gh-aw format")
    repository = _text(request.get("repository"), "repository", maximum=256)
    if not REPOSITORY_RE.fullmatch(repository):
        raise GhAwProviderError("repository must use owner/repository form")
    workflow_id = _text(request.get("workflow_id"), "workflow_id", maximum=128)
    if not WORKFLOW_RE.fullmatch(workflow_id):
        raise GhAwProviderError("workflow_id must be lowercase kebab-case")
    contract_evidence = request.get("contract_evidence")
    if not isinstance(contract_evidence, Mapping):
        raise GhAwProviderError("contract_evidence must be an object")
    _unknown(
        contract_evidence,
        {"revision", "firewall_policy_digest", "source_digest", "lock_digest"},
        "contract_evidence",
    )
    if contract_evidence.get("revision") != FIREWALL_POLICY_REVISION:
        raise GhAwProviderError("contract_evidence has an unsupported revision")
    normalized_evidence = {
        "revision": FIREWALL_POLICY_REVISION,
        "firewall_policy_digest": _ref(
            contract_evidence.get("firewall_policy_digest"),
            "contract_evidence.firewall_policy_digest",
        ),
        "source_digest": _ref(
            contract_evidence.get("source_digest"),
            "contract_evidence.source_digest",
        ),
        "lock_digest": _ref(
            contract_evidence.get("lock_digest"),
            "contract_evidence.lock_digest",
        ),
    }
    contract_evidence_ref = _ref(
        request.get("contract_evidence_ref"), "contract_evidence_ref"
    )
    if contract_evidence_ref != digest(normalized_evidence):
        raise GhAwProviderError("contract_evidence_ref does not match contract_evidence")
    output_type = request.get("safe_output_type")
    if output_type not in SAFE_OUTPUT_TYPES:
        raise GhAwProviderError("safe_output_type is unsupported")
    operations = request.get("operations")
    if not isinstance(operations, list) or not operations or len(operations) > 50:
        raise GhAwProviderError("operations must contain between 1 and 50 entries")
    _reject_credentials(operations, "request.operations")
    normalized_operations = [
        _validate_operation(operation, output_type, index)
        for index, operation in enumerate(operations)
    ]
    material = {
        "repository": repository,
        "workflow_id": workflow_id,
        "safe_output_type": output_type,
        "operations": normalized_operations,
    }
    request_ref = request.get("request_ref")
    if not isinstance(request_ref, str) or not REF_RE.fullmatch(request_ref):
        raise GhAwProviderError("request_ref must be a sha256 reference")
    if request_ref != digest(material):
        raise GhAwProviderError("request_ref does not match the canonical operation material")
    return {
        "$schema": REQUEST_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "adapter_contract_revision": PROVIDER_REVISION,
        "episode_id": episode_id,
        "request_ref": request_ref,
        "contract_evidence": normalized_evidence,
        "contract_evidence_ref": contract_evidence_ref,
        **material,
    }


def _sanitize_content(value: str, label: str, *, maximum: int) -> tuple[str, bool]:
    normalized = unicodedata.normalize("NFC", value)
    normalized = "".join(
        character
        for character in normalized
        if character not in {"\u200b", "\u200c", "\u200d", "\ufeff"}
        and (character in "\n\r\t" or ord(character) >= 32)
        and ord(character) != 127
    )
    normalized = HTML_COMMENT_RE.sub("", normalized)
    normalized = UNSAFE_PROTOCOL_RE.sub("[URL removed: unauthorized protocol]", normalized)
    if normalized.startswith("/"):
        normalized = "\\" + normalized
    mentions = MENTION_RE.findall(normalized)
    links = LINK_RE.findall(normalized)
    if len(mentions) > 10:
        raise GhAwProviderError(f"{label} contains {len(mentions)} mentions; maximum is 10")
    if len(links) > 50:
        raise GhAwProviderError(f"{label} contains {len(links)} links; maximum is 50")
    normalized = MENTION_RE.sub(lambda match: f"@ {match.group(1)}", normalized)
    if len(normalized) > maximum:
        raise GhAwProviderError(f"{label} exceeds the {maximum} character limit")
    return normalized, normalized != value


def _prefixed_title(title: str, prefix: str | None, label: str) -> tuple[str, bool]:
    normalized, changed = _sanitize_content(title, label, maximum=256)
    if prefix and not normalized.startswith(prefix):
        normalized = prefix + normalized
        changed = True
    if len(normalized) > 256:
        raise GhAwProviderError(f"{label} exceeds 256 characters after title-prefix")
    return normalized, changed


def _provider_key(effect: Mapping[str, Any], request_ref: str, index: int) -> str:
    return digest(
        {
            "provider_revision": PROVIDER_REVISION,
            "effect_id": effect["effect_id"],
            "runtime_idempotency_key": effect["idempotency_key"],
            "request_ref": request_ref,
            "operation_index": index,
        }
    )


def _marker(provider_key: str) -> str:
    return f"<!-- forge-gh-aw:{provider_key[7:39]} -->"


def _marked_body(body: str, marker: str, label: str) -> str:
    result = f"{body.rstrip()}\n\n{marker}"
    if len(result) > 65_536:
        raise GhAwProviderError(f"{label} exceeds 65536 characters after provider evidence")
    return result


def _compile_operations(
    request: Mapping[str, Any],
    output: Mapping[str, Any],
    effect: Mapping[str, Any],
) -> list[dict[str, Any]]:
    output_type = request["safe_output_type"]
    operations = list(request["operations"])
    maximum = int(output["max"])
    if len(operations) > maximum:
        raise GhAwProviderError(
            f"{output_type} request exceeds compiled max: {len(operations)} > {maximum}"
        )
    if output_type == "dispatch-workflow":
        allowed = list(output.get("workflows", []))
        targets = [operation["workflow_id"] for operation in operations]
        if len(set(targets)) != len(targets) or sorted(targets) != sorted(allowed):
            raise GhAwProviderError(
                "dispatch-workflow operations must cover each compiled workflow exactly once"
            )
        target = effect["payload"].get("worker_workflow_id")
        operations = [operation for operation in operations if operation["workflow_id"] == target]
        if len(operations) != 1:
            raise GhAwProviderError("dispatch effect target is missing from the request")
    compiled: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        provider_key = _provider_key(effect, request["request_ref"], index)
        marker = _marker(provider_key)
        changed = False
        if output_type == "dispatch-workflow":
            workflow_file = quote(f"{operation['workflow_id']}.lock.yml", safe="")
            endpoint = (
                f"/repos/{request['repository']}/actions/workflows/{workflow_file}/dispatches"
            )
            body = {
                "ref": operation["ref"],
                "inputs": copy.deepcopy(operation["inputs"]),
                "return_run_details": True,
            }
        elif output_type == "add-comment":
            sanitized, changed = _sanitize_content(
                operation["body"], f"operations[{index}].body", maximum=65_536
            )
            body = {"body": _marked_body(sanitized, marker, f"operations[{index}].body")}
            endpoint = (
                f"/repos/{request['repository']}/issues/{operation['item_number']}/comments"
            )
        elif output_type == "create-issue":
            title, title_changed = _prefixed_title(
                operation["title"], output.get("title-prefix"), f"operations[{index}].title"
            )
            sanitized, body_changed = _sanitize_content(
                operation["body"], f"operations[{index}].body", maximum=65_536
            )
            configured_labels = list(output.get("labels", []))
            unexpected = sorted(set(operation["labels"]) - set(configured_labels))
            if unexpected:
                raise GhAwProviderError(
                    "create-issue labels exceed the compiled allowlist: " + ", ".join(unexpected)
                )
            body = {
                "title": title,
                "body": _marked_body(sanitized, marker, f"operations[{index}].body"),
                "labels": sorted(set(configured_labels) | set(operation["labels"])),
            }
            endpoint = f"/repos/{request['repository']}/issues"
            changed = title_changed or body_changed
        else:
            title, title_changed = _prefixed_title(
                operation["title"], output.get("title-prefix"), f"operations[{index}].title"
            )
            sanitized, body_changed = _sanitize_content(
                operation["body"], f"operations[{index}].body", maximum=65_536
            )
            allowed_files = list(output.get("allowed-files", []))
            outside = [
                path
                for path in operation["changed_files"]
                if not any(fnmatch.fnmatchcase(path, pattern) for pattern in allowed_files)
            ]
            if outside:
                raise GhAwProviderError(
                    "create-pull-request changed_files exceed compiled allowed-files: "
                    + ", ".join(outside)
                )
            body = {
                "title": title,
                "body": _marked_body(sanitized, marker, f"operations[{index}].body"),
                "head": operation["head"],
                "base": operation["base"],
                "draft": operation["draft"],
            }
            endpoint = f"/repos/{request['repository']}/pulls"
            changed = title_changed or body_changed
        operation_digest = digest(
            {
                "method": "POST",
                "endpoint": endpoint,
                "body": body,
                "provider_key": provider_key,
            }
        )
        compiled.append(
            {
                "index": index,
                "type": output_type,
                "method": "POST",
                "endpoint": endpoint,
                "body": body,
                "body_digest": digest(body),
                "operation_digest": operation_digest,
                "provider_key": provider_key,
                "marker": marker,
                "sanitized": changed,
                "source": copy.deepcopy(operation),
            }
        )
    return compiled


def _policy_context(
    context: Mapping[str, Any],
    request: Mapping[str, Any],
    effect: Mapping[str, Any],
    operations: list[dict[str, Any]],
    *,
    approvals_path: Path,
    now: str | None,
    admission_id: str | None = None,
    host_admission_id: str | None = None,
) -> tuple[Any, Any, Any]:
    policy = _policy()
    profile_name = context["spec"]["defaults"]["policy_profile"]
    engine = policy.PolicyEngine(
        policy.PolicyProfile.from_file(REPO / "policies" / f"{profile_name}.json"),
        approvals_path=approvals_path,
        clock=_clock(now),
    )
    output = next(
        item
        for item in context["spec"]["workflows"]
        if item["id"] == request["workflow_id"]
    )
    safe_output = next(
        item for item in output["safe_outputs"] if item["type"] == request["safe_output_type"]
    )
    paths = sorted(
        {
            path
            for operation in operations
            for path in operation["source"].get("changed_files", [])
        }
    )
    branch_values = {
        operation["source"].get("base")
        for operation in operations
        if operation["source"].get("base")
    }
    branch = next(iter(branch_values)) if len(branch_values) == 1 else None
    arguments = {
        "provider_revision": PROVIDER_REVISION,
        "request_ref": request["request_ref"],
        "contract_evidence_ref": request["contract_evidence_ref"],
        "effect_id": effect["effect_id"],
        "safe_output": copy.deepcopy(safe_output),
        "operation_digests": [item["operation_digest"] for item in operations],
    }
    if admission_id is not None:
        arguments["admission_id"] = admission_id
    if host_admission_id is not None:
        arguments["host_admission_id"] = host_admission_id
    action = policy.ActionEnvelope.from_mapping(
        {
            "schema_version": 1,
            "action_id": f"gh-aw-provider:{effect['effect_id']}",
            "tool": "gh-aw.safe-output",
            "arguments": arguments,
            "resource": {
                "repository": request["repository"],
                "branch": branch,
                "paths": paths,
                "domains": ["github.com"],
            },
            "principal": "forge-gh-aw-provider",
            "workspace": str(REPO.resolve()),
            "intent": {
                "effect": context["compiler"]._effect_for_output(
                    request["safe_output_type"]
                ),
                "external": True,
                "risk": "high",
                "cost_usd": 0,
                "fan_out": len(operations),
            },
        }
    )
    evaluation = engine.evaluate(action)
    if evaluation.decision.decision != "require_approval":
        raise GhAwProviderError(
            "provider policy must require approval, got " + evaluation.decision.decision
        )
    return policy, engine, action


@dataclass
class _Prepared:
    bridge: Any
    runtime: Any
    context: dict[str, Any]
    spec_path: Path
    output: Path
    request: dict[str, Any]
    effect: dict[str, Any]
    lease: dict[str, Any]
    operations: list[dict[str, Any]]
    policy_module: Any
    policy_engine: Any
    policy_action: Any
    admission: dict[str, Any] | None
    handoff: dict[str, Any] | None
    host_admission: dict[str, Any] | None
    host_admission_path: Path | None
    host_ref: str | None
    host_audience_ref: str | None
    host_workspace_ref: str | None
    now: str | None
    public: dict[str, Any]


def _paths(spec_path: Path, output: Path) -> tuple[Path, Path]:
    spec_path = spec_path if spec_path.is_absolute() else REPO / spec_path
    output = output if output.is_absolute() else REPO / output
    return spec_path, output


def _compiled_contract_evidence(
    context: Mapping[str, Any], workflow_id: str
) -> dict[str, str]:
    workflow = next(
        (item for item in context["manifest"]["workflows"] if item.get("id") == workflow_id),
        None,
    )
    if not isinstance(workflow, Mapping):
        raise GhAwProviderError(f"manifest is missing workflow evidence: {workflow_id}")
    artifacts = {
        item.get("path"): item
        for item in context["manifest"].get("artifacts", [])
        if isinstance(item, Mapping)
    }
    source = artifacts.get(f"workflows/{workflow_id}.md")
    lock = artifacts.get(f"workflows/{workflow_id}.lock.yml")
    if not isinstance(source, Mapping) or not isinstance(lock, Mapping):
        raise GhAwProviderError(f"manifest is missing source/lock evidence: {workflow_id}")
    return {
        "revision": FIREWALL_POLICY_REVISION,
        "firewall_policy_digest": _ref(
            context["manifest"].get("firewall_policy_digest"),
            "manifest firewall policy digest",
        ),
        "source_digest": _ref(source.get("sha256"), "manifest source digest"),
        "lock_digest": _ref(lock.get("sha256"), "manifest lock digest"),
    }


def compiled_contract(spec_path: Path, output: Path, workflow_id: str) -> dict[str, Any]:
    """Return the digest-only evidence a provider request must repeat."""

    bridge = _bridge()
    spec_path, output = _paths(spec_path, output)
    context = bridge._contract(spec_path, output)
    evidence = _compiled_contract_evidence(context, workflow_id)
    return {"contract_evidence": evidence, "contract_evidence_ref": digest(evidence)}


def _verify_contract_evidence(
    context: Mapping[str, Any],
    request: Mapping[str, Any],
    admission: Mapping[str, Any] | None = None,
) -> None:
    expected = _compiled_contract_evidence(context, request["workflow_id"])
    if request["contract_evidence"] != expected:
        raise GhAwProviderError("provider contract evidence does not match compiled source, lock, or policy")
    if request["contract_evidence_ref"] != digest(expected):
        raise GhAwProviderError("provider contract evidence reference is stale")
    if admission is not None:
        if request["contract_evidence"]["revision"] != admission["firewall_policy_revision"]:
            raise GhAwProviderError("provider contract revision does not match native admission")
        if request["contract_evidence"]["firewall_policy_digest"] != admission["firewall_policy_digest"]:
            raise GhAwProviderError("provider firewall policy does not match native admission")


def _host_lease_ref(host_module: Any, effect: Mapping[str, Any], lease: Mapping[str, Any]) -> str:
    return host_module.digest_ref(
        {
            "provider_revision": PROVIDER_REVISION,
            "effect_id": effect["effect_id"],
            "worker_id": lease["worker_id"],
            "lease_generation": lease["lease_generation"],
        }
    )


def _host_provider_operation_ref(
    host_module: Any, request: Mapping[str, Any], effect: Mapping[str, Any]
) -> str:
    return host_module.digest_ref(
        {
            "provider_revision": PROVIDER_REVISION,
            "effect_id": effect["effect_id"],
            "request_ref": request["request_ref"],
            "contract_evidence_ref": request["contract_evidence_ref"],
            "safe_output_type": request["safe_output_type"],
        }
    )


def _host_admission_for_effect(
    request: Mapping[str, Any],
    effect: Mapping[str, Any],
    lease: Mapping[str, Any],
    admission_path: Path | None,
    *,
    host_ref: str | None,
    host_audience_ref: str | None,
    host_workspace_ref: str | None,
    now: str | None,
) -> dict[str, Any] | None:
    if admission_path is None:
        return None
    if not host_ref or not host_audience_ref or not host_workspace_ref:
        raise GhAwProviderError(
            "host admission requires --host-ref, --host-audience, and --host-workspace"
        )
    host_module = _host_admission()
    expected_scope_refs = [
        "scope:github.safe-output",
        f"scope:github.{request['safe_output_type']}",
    ]
    try:
        return host_module.verify_file(
            admission_path,
            expected_audience_ref=host_audience_ref,
            expected_workspace_ref=host_workspace_ref,
            expected_resource_ref=f"resource:repo/{request['repository']}",
            expected_request_ref=request["request_ref"],
            expected_host_ref=host_ref,
            expected_scope_refs=expected_scope_refs,
            expected_bindings={
                "lease_ref": _host_lease_ref(host_module, effect, lease),
                "provider_operation_ref": _host_provider_operation_ref(
                    host_module, request, effect
                ),
            },
            at=_timestamp(now),
        )
    except host_module.HostAdmissionError as exc:
        raise GhAwProviderError(f"host admission verification failed: {exc}") from exc


def _admission_for_request(
    bridge: Any,
    context: Mapping[str, Any],
    spec_path: Path,
    output: Path,
    database: Path,
    request: Mapping[str, Any],
    admission_path: Path | None,
) -> dict[str, Any] | None:
    native = context["manifest"]["mode"] == "upstream-gh-aw"
    if native and admission_path is None:
        raise GhAwProviderError("native execution requires an admission certificate")
    if not native and admission_path is not None:
        raise GhAwProviderError("admission certificate requires native artifacts")
    if admission_path is None:
        return None
    try:
        return bridge.verify_admission_certificate(
            spec_path,
            output,
            database,
            admission_path,
            episode_id=request["episode_id"],
        )
    except bridge.GhAwRuntimeError as exc:
        raise GhAwProviderError(f"native admission verification failed: {exc}") from exc


def _validate_request_admission(
    spec_path: Path,
    output: Path,
    database: Path,
    request: Mapping[str, Any],
    admission_path: Path | None,
) -> dict[str, Any] | None:
    bridge = _bridge()
    spec_path, output = _paths(spec_path, output)
    try:
        context = bridge._contract(spec_path, output)
    except bridge.GhAwRuntimeError as exc:
        raise GhAwProviderError(f"native admission verification failed: {exc}") from exc
    return _admission_for_request(
        bridge,
        context,
        spec_path,
        output,
        database,
        request,
        admission_path,
    )


def _prepare(
    spec_path: Path,
    output: Path,
    database: Path,
    raw_request: Mapping[str, Any],
    effect_id: str,
    worker_id: str,
    lease_generation: int,
    *,
    approvals_path: Path,
    now: str | None,
    admission_path: Path | None,
    handoff_path: Path | None,
    host_admission_path: Path | None,
    host_ref: str | None,
    host_audience_ref: str | None,
    host_workspace_ref: str | None,
) -> _Prepared:
    request = validate_request(raw_request)
    bridge = _bridge()
    runtime = bridge._runtime()
    spec_path, output = _paths(spec_path, output)
    context = bridge._contract(spec_path, output)
    if request["repository"] != context["spec"]["defaults"]["repository"]:
        raise GhAwProviderError("request repository does not match the compiled repository")
    _verify_contract_evidence(context, request)
    admission = _admission_for_request(
        bridge,
        context,
        spec_path,
        output,
        database,
        request,
        admission_path,
    )
    _verify_contract_evidence(context, request, admission)
    try:
        with runtime.RuntimeStore(database) as store:
            state = store.state(request["episode_id"])
            effects = [
                item
                for item in store.list_outbox(request["episode_id"])
                if item["effect_id"] == effect_id
            ]
            if not effects:
                raise GhAwProviderError(f"unknown episode effect: {effect_id}")
            effect = effects[0]
            expected_effect_type = bridge.SAFE_OUTPUT_EFFECT_TYPES[request["safe_output_type"]]
            if effect["effect_type"] != expected_effect_type:
                raise GhAwProviderError(
                    "leased effect type does not match the requested safe output"
                )
            if effect["status"] != "leased":
                raise GhAwProviderError(
                    f"effect must hold a current lease before planning: {effect['status']}"
                )
            lease = store.authorize_outbox_effect(
                effect_id,
                worker_id,
                lease_generation=lease_generation,
                now=now,
            )
    except runtime.RuntimeStoreError as exc:
        raise GhAwProviderError(f"runtime lease authorization failed: {exc}") from exc
    if state["status"] != "running":
        raise GhAwProviderError(f"episode is not running: {state['status']}")
    host_admission = _host_admission_for_effect(
        request,
        effect,
        lease,
        host_admission_path,
        host_ref=host_ref,
        host_audience_ref=host_audience_ref,
        host_workspace_ref=host_workspace_ref,
        now=now,
    )
    dispatcher_id = state["workflow_id"].removeprefix("gh-aw:")
    if admission is not None and admission["dispatcher_workflow_id"] != dispatcher_id:
        raise GhAwProviderError("native admission dispatcher does not match the runtime episode")
    if request["workflow_id"] != effect["payload"].get("workflow_id"):
        raise GhAwProviderError("request workflow_id does not match the leased effect")
    if request["safe_output_type"] != effect["payload"].get("safe_output_type"):
        raise GhAwProviderError("request safe_output_type does not match the leased effect")
    expected_ref = (
        effect["payload"].get("request_digest")
        if request["safe_output_type"] == "dispatch-workflow"
        else effect["payload"].get("output_ref")
    )
    if request["request_ref"] != expected_ref:
        raise GhAwProviderError("request_ref does not match the leased effect payload reference")
    handoff = None
    if handoff_path is not None:
        if admission_path is None:
            raise GhAwProviderError("worker handoff requires an admission certificate")
        try:
            handoff = bridge.verify_native_worker_handoff(
                spec_path,
                output,
                database,
                handoff_path,
                admission_path,
                episode_id=request["episode_id"],
                dispatcher_id=dispatcher_id,
                effect_id=effect_id,
                worker_id=worker_id,
                lease_generation=lease_generation,
                request_ref=request["request_ref"],
            )
        except bridge.GhAwRuntimeError as exc:
            raise GhAwProviderError(f"native worker handoff verification failed: {exc}") from exc
    workflow = bridge._workflow(context, request["workflow_id"])
    output_config = next(
        (
            item
            for item in workflow["safe_outputs"]
            if item["type"] == request["safe_output_type"]
        ),
        None,
    )
    if output_config is None:
        raise GhAwProviderError("request safe output is not compiled for the workflow")
    compiled_plan = bridge._policy_plan(
        context, request["workflow_id"], request["safe_output_type"]
    )
    compiled_digest = compiled_plan["action_digest"]
    if not compiled_digest.startswith("sha256:"):
        compiled_digest = "sha256:" + compiled_digest
    if effect["payload"].get("policy_action_digest") != compiled_digest:
        raise GhAwProviderError("leased effect policy action digest is stale or inconsistent")
    operations = _compile_operations(request, output_config, effect)
    policy_module, policy_engine, policy_action = _policy_context(
        context,
        request,
        effect,
        operations,
        approvals_path=approvals_path,
        now=now,
        admission_id=admission["admission_id"] if admission is not None else None,
        host_admission_id=(
            host_admission["admission_id"] if host_admission is not None else None
        ),
    )
    evaluation = policy_engine.evaluate(policy_action)
    authorization_digest = "sha256:" + evaluation.decision.action_digest
    execution_material = {
        "provider_revision": PROVIDER_REVISION,
        "effect_id": effect["effect_id"],
        "request_ref": request["request_ref"],
        "contract_evidence_ref": request["contract_evidence_ref"],
        "compiled_action_digest": compiled_digest,
        "authorization_action_digest": authorization_digest,
        "operation_digests": [item["operation_digest"] for item in operations],
    }
    if admission is not None:
        execution_material["admission_id"] = admission["admission_id"]
    if handoff is not None:
        execution_material["handoff_id"] = handoff["handoff_id"]
    if host_admission is not None:
        execution_material["host_admission_id"] = host_admission["admission_id"]
    execution_digest = digest(execution_material)
    public = {
        "schema_version": SCHEMA_VERSION,
        "provider_revision": PROVIDER_REVISION,
        "status": "staged",
        "episode_id": request["episode_id"],
        "dispatcher_workflow_id": dispatcher_id,
        "workflow_id": request["workflow_id"],
        "safe_output_type": request["safe_output_type"],
        "repository": request["repository"],
        "effect_id": effect["effect_id"],
        "request_ref": request["request_ref"],
        "contract_evidence_ref": request["contract_evidence_ref"],
        "runtime_idempotency_key": effect["idempotency_key"],
        "execution_digest": execution_digest,
        "operation_count": len(operations),
        "operation_digests": [item["operation_digest"] for item in operations],
        "provider_idempotency_keys": [item["provider_key"] for item in operations],
        "sanitized": any(item["sanitized"] for item in operations),
        "lease": copy.deepcopy(lease),
        "policy": {
            "profile": evaluation.decision.profile,
            "revision": "sha256:" + evaluation.decision.policy_revision,
            "decision": evaluation.decision.decision,
            "compiled_action_digest": compiled_digest,
            "authorization_action_digest": authorization_digest,
        },
        "transport": [
            {
                "method": item["method"],
                "endpoint": item["endpoint"],
                "body_digest": item["body_digest"],
            }
            for item in operations
        ],
    }
    if admission is not None:
        public["admission_id"] = admission["admission_id"]
    if handoff is not None:
        public["handoff_id"] = handoff["handoff_id"]
    if host_admission is not None:
        public["host_admission_id"] = host_admission["admission_id"]
    return _Prepared(
        bridge=bridge,
        runtime=runtime,
        context=context,
        spec_path=spec_path,
        output=output,
        request=request,
        effect=effect,
        lease=lease,
        operations=operations,
        policy_module=policy_module,
        policy_engine=policy_engine,
        policy_action=policy_action,
        admission=admission,
        handoff=handoff,
        host_admission=host_admission,
        host_admission_path=host_admission_path,
        host_ref=host_ref,
        host_audience_ref=host_audience_ref,
        host_workspace_ref=host_workspace_ref,
        now=now,
        public=public,
    )


def plan_effect(
    spec_path: Path,
    output: Path,
    database: Path,
    request: Mapping[str, Any],
    effect_id: str,
    worker_id: str,
    lease_generation: int,
    *,
    approvals_path: Path = DEFAULT_APPROVALS,
    admission_path: Path | None = None,
    handoff_path: Path | None = None,
    host_admission_path: Path | None = None,
    host_ref: str | None = None,
    host_audience_ref: str | None = None,
    host_workspace_ref: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    prepared = _prepare(
        spec_path,
        output,
        database,
        request,
        effect_id,
        worker_id,
        lease_generation,
        approvals_path=approvals_path,
        now=now,
        admission_path=admission_path,
        handoff_path=handoff_path,
        host_admission_path=host_admission_path,
        host_ref=host_ref,
        host_audience_ref=host_audience_ref,
        host_workspace_ref=host_workspace_ref,
    )
    return copy.deepcopy(prepared.public)


def issue_approval(
    spec_path: Path,
    output: Path,
    database: Path,
    request: Mapping[str, Any],
    effect_id: str,
    worker_id: str,
    lease_generation: int,
    *,
    approvals_path: Path = DEFAULT_APPROVALS,
    admission_path: Path | None = None,
    handoff_path: Path | None = None,
    host_admission_path: Path | None = None,
    host_ref: str | None = None,
    host_audience_ref: str | None = None,
    host_workspace_ref: str | None = None,
    receipts_path: Path | None = None,
    ttl_seconds: int = 600,
    now: str | None = None,
) -> dict[str, Any]:
    prepared = _prepare(
        spec_path,
        output,
        database,
        request,
        effect_id,
        worker_id,
        lease_generation,
        approvals_path=approvals_path,
        now=now,
        admission_path=admission_path,
        handoff_path=handoff_path,
        host_admission_path=host_admission_path,
        host_ref=host_ref,
        host_audience_ref=host_audience_ref,
        host_workspace_ref=host_workspace_ref,
    )
    try:
        approval = prepared.policy_engine.issue_approval(
            prepared.policy_action,
            ttl_seconds=ttl_seconds,
            receipts_path=receipts_path,
        )
    except prepared.policy_module.PolicyError as exc:
        raise GhAwProviderError(f"provider approval failed: {exc}") from exc
    result = {
        "schema_version": SCHEMA_VERSION,
        "provider_revision": PROVIDER_REVISION,
        "status": "approval-issued",
        "effect_id": effect_id,
        "execution_digest": prepared.public["execution_digest"],
        "action_digest": prepared.public["policy"]["authorization_action_digest"],
        "approval_id": approval.approval_id,
        "approval_ref": digest({"approval_id": approval.approval_id}),
        "expires_at": approval.expires_at,
    }
    if prepared.admission is not None:
        result["admission_id"] = prepared.admission["admission_id"]
    if prepared.handoff is not None:
        result["handoff_id"] = prepared.handoff["handoff_id"]
    if prepared.host_admission is not None:
        result["host_admission_id"] = prepared.host_admission["admission_id"]
    return result


def _validate_journal_details(event_type: str, details: Any, number: int | str) -> None:
    if not isinstance(details, Mapping):
        raise GhAwProviderError(f"provider journal details are invalid at record {number}")
    if event_type == "authorized":
        _unknown(details, AUTHORIZED_DETAIL_KEYS, f"provider journal record {number} details")
        if set(details) != AUTHORIZED_DETAIL_KEYS:
            raise GhAwProviderError(
                f"provider journal authorization is incomplete at record {number}"
            )
        _text(details.get("approval_id"), "journal approval_id", maximum=128)
        for key in ("approval_ref", "action_digest"):
            if not isinstance(details.get(key), str) or not REF_RE.fullmatch(details[key]):
                raise GhAwProviderError(
                    f"provider journal {key} is invalid at record {number}"
                )
        return
    _unknown(details, SUCCEEDED_DETAIL_KEYS, f"provider journal record {number} details")
    if not SUCCEEDED_REQUIRED_DETAIL_KEYS <= set(details) or not isinstance(
        details.get("recovered"), bool
    ):
        raise GhAwProviderError(f"provider journal success is incomplete at record {number}")
    if "reconciled" in details and not isinstance(details["reconciled"], bool):
        raise GhAwProviderError(f"provider journal reconciliation marker is invalid at record {number}")
    receipt = details.get("receipt")
    if not isinstance(receipt, Mapping):
        raise GhAwProviderError(f"provider journal receipt is invalid at record {number}")
    _unknown(receipt, RECEIPT_KEYS, f"provider journal record {number} receipt")
    if set(receipt) != RECEIPT_KEYS or receipt.get("status") != "succeeded":
        raise GhAwProviderError(f"provider journal receipt is incomplete at record {number}")
    for key in ("approval_id", "result_ref"):
        if not isinstance(receipt.get(key), str) or not REF_RE.fullmatch(receipt[key]):
            raise GhAwProviderError(
                f"provider journal receipt {key} is invalid at record {number}"
            )
    for key in (
        "episode_id",
        "workflow_id",
        "safe_output_type",
        "adapter_contract_revision",
        "provider_request_id",
        "resource_ref",
    ):
        _text(receipt.get(key), f"journal receipt {key}", maximum=512)


class ProviderJournal:
    """Append-only, hash-chained provider handoff evidence with no raw operation bodies."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _records(self, handle: Any) -> list[dict[str, Any]]:
        handle.seek(0)
        records: list[dict[str, Any]] = []
        effect_states: dict[str, str] = {}
        previous = GENESIS_HASH
        for number, line in enumerate(handle.read().splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise GhAwProviderError(f"invalid provider journal record {number}") from exc
            if not isinstance(record, dict):
                raise GhAwProviderError(f"invalid provider journal record {number}")
            _unknown(record, JOURNAL_KEYS, f"provider journal record {number}")
            if set(record) != JOURNAL_KEYS:
                raise GhAwProviderError(f"incomplete provider journal record {number}")
            if record.get("schema_version") != SCHEMA_VERSION:
                raise GhAwProviderError(f"unsupported provider journal record {number}")
            if record.get("sequence") != len(records) + 1:
                raise GhAwProviderError(f"provider journal sequence mismatch at record {number}")
            if record.get("previous_hash") != previous:
                raise GhAwProviderError(f"provider journal hash chain mismatch at record {number}")
            material = {key: copy.deepcopy(value) for key, value in record.items() if key != "event_hash"}
            expected = digest(material)
            if record.get("event_hash") != expected:
                raise GhAwProviderError(f"provider journal event hash mismatch at record {number}")
            if record.get("event_type") not in {"authorized", "succeeded"}:
                raise GhAwProviderError(f"invalid provider journal event at record {number}")
            if not isinstance(record.get("execution_digest"), str) or not REF_RE.fullmatch(
                record["execution_digest"]
            ):
                raise GhAwProviderError(
                    f"invalid provider journal execution digest at record {number}"
                )
            _timestamp(record.get("occurred_at"))
            _validate_journal_details(record["event_type"], record.get("details"), number)
            effect_id = record.get("effect_id")
            if not isinstance(effect_id, str) or not effect_id:
                raise GhAwProviderError(f"invalid provider journal effect at record {number}")
            current = effect_states.get(effect_id)
            if record["event_type"] == "authorized" and current is not None:
                raise GhAwProviderError(
                    f"duplicate provider authorization at record {number}"
                )
            if record["event_type"] == "succeeded" and current != "authorized":
                raise GhAwProviderError(
                    f"provider success has no prior authorization at record {number}"
                )
            effect_states[effect_id] = record["event_type"]
            previous = expected
            records.append(record)
        return records

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as handle:
            return self._records(handle)

    def for_effect(self, effect_id: str, execution_digest: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for record in self.read():
            if record.get("effect_id") != effect_id:
                continue
            if record.get("execution_digest") != execution_digest:
                raise GhAwProviderError("provider journal execution digest conflicts with effect")
            event_type = record["event_type"]
            if event_type in result and result[event_type]["details"] != record["details"]:
                raise GhAwProviderError(f"conflicting provider journal {event_type} evidence")
            result[event_type] = record
        if "succeeded" in result:
            authorized = result.get("authorized")
            receipt = result["succeeded"].get("details", {}).get("receipt")
            approval_id = (
                authorized.get("details", {}).get("approval_id") if authorized else None
            )
            if (
                not isinstance(receipt, Mapping)
                or not isinstance(approval_id, str)
                or receipt.get("approval_id") != digest({"approval_id": approval_id})
            ):
                raise GhAwProviderError(
                    "provider journal receipt is not bound to its authorization"
                )
        return result

    def append(
        self,
        event_type: str,
        effect_id: str,
        execution_digest: str,
        details: Mapping[str, Any],
        *,
        occurred_at: str | None,
    ) -> dict[str, Any]:
        if event_type not in {"authorized", "succeeded"}:
            raise GhAwProviderError("provider journal event type is unsupported")
        _validate_journal_details(event_type, details, "new")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as handle:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                records = self._records(handle)
                existing = [
                    record
                    for record in records
                    if record["effect_id"] == effect_id and record["event_type"] == event_type
                ]
                if existing:
                    record = existing[-1]
                    if (
                        record["execution_digest"] != execution_digest
                        or record["details"] != dict(details)
                    ):
                        raise GhAwProviderError(
                            f"provider journal {event_type} evidence conflicts with effect"
                        )
                    return copy.deepcopy(record)
                effect_records = [
                    record for record in records if record["effect_id"] == effect_id
                ]
                if event_type == "authorized" and effect_records:
                    raise GhAwProviderError(
                        "provider journal effect was already authorized"
                    )
                if event_type == "succeeded" and not any(
                    record["event_type"] == "authorized" for record in effect_records
                ):
                    raise GhAwProviderError(
                        "provider journal success requires prior authorization"
                    )
                record = {
                    "schema_version": SCHEMA_VERSION,
                    "sequence": len(records) + 1,
                    "event_type": event_type,
                    "effect_id": effect_id,
                    "execution_digest": execution_digest,
                    "occurred_at": _timestamp(occurred_at),
                    "previous_hash": records[-1]["event_hash"] if records else GENESIS_HASH,
                    "details": copy.deepcopy(dict(details)),
                }
                record["event_hash"] = digest(record)
                handle.seek(0, 2)
                handle.write(canonical_json(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                return copy.deepcopy(record)
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class GitHubTransport:
    """Small ``gh api`` transport; tokens remain inside GitHub CLI credential storage."""

    def authenticated_login(self) -> str:
        try:
            result = subprocess.run(
                ["gh", "api", "user", "--jq", ".login"],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise GhAwProviderError(
                "timed out while verifying the authenticated GitHub login"
            ) from exc
        if result.returncode != 0:
            raise GhAwProviderError("cannot verify the authenticated GitHub login")
        return _text(result.stdout.strip(), "authenticated GitHub login", maximum=128)

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        body: dict[str, Any] | None = None,
        paginate: bool = False,
    ) -> Any:
        command = [
            "gh",
            "api",
            "--method",
            method,
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            f"X-GitHub-Api-Version: {GITHUB_API_VERSION}",
            endpoint,
        ]
        if paginate:
            command.extend(["--paginate", "--slurp"])
        if body is not None:
            command.extend(["--input", "-"])
        try:
            result = subprocess.run(
                command,
                input=canonical_json(body) if body is not None else None,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            raise GhAwProviderError(
                f"GitHub provider request timed out ({method} {endpoint})"
            ) from exc
        if result.returncode != 0:
            raise GhAwProviderError(
                f"GitHub provider request failed ({method} {endpoint}, exit {result.returncode})"
            )
        if not result.stdout.strip():
            return {}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GhAwProviderError("GitHub provider returned invalid JSON") from exc


def _heartbeat_lease(prepared: _Prepared, database: Path, *, now: str | None) -> None:
    try:
        with prepared.runtime.RuntimeStore(database) as store:
            store.heartbeat_outbox(
                prepared.effect["effect_id"],
                prepared.lease["worker_id"],
                lease_generation=prepared.lease["lease_generation"],
                now=now,
            )
    except prepared.runtime.RuntimeStoreError as exc:
        raise GhAwProviderError(f"provider lease heartbeat failed: {exc}") from exc


class _LeaseGuard:
    """Fence every provider boundary with the current runtime lease generation."""

    def __init__(
        self,
        transport: Any,
        prepared: _Prepared,
        database: Path,
        *,
        now: str | None,
    ) -> None:
        self.transport = transport
        self.prepared = prepared
        self.database = database
        self.now = now

    def _heartbeat(self) -> None:
        _heartbeat_lease(self.prepared, self.database, now=self.now)

    def authenticated_login(self) -> str:
        self._heartbeat()
        login = self.transport.authenticated_login()
        self._heartbeat()
        return login

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        body: dict[str, Any] | None = None,
        paginate: bool = False,
    ) -> Any:
        self._heartbeat()
        response = self.transport.request(method, endpoint, body=body, paginate=paginate)
        self._heartbeat()
        return response


def _items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        flattened: list[Any] = []
        for item in value:
            if isinstance(item, list):
                flattened.extend(item)
            else:
                flattened.append(item)
        return [dict(item) for item in flattened if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        raw = value.get("items", value.get("workflow_runs", []))
        if isinstance(raw, list):
            return [dict(item) for item in raw if isinstance(item, Mapping)]
    return []


def _preflight_pull_request(operation: Mapping[str, Any], repository: str, transport: Any) -> None:
    source = operation["source"]
    endpoint = (
        f"/repos/{repository}/compare/{quote(source['base'], safe='')}..."
        f"{quote(source['head'], safe='')}"
    )
    response = transport.request("GET", endpoint)
    if not isinstance(response, Mapping):
        raise GhAwProviderError("pull request compare preflight returned an invalid response")
    head_commit = response.get("head_commit")
    files = response.get("files")
    if not isinstance(head_commit, Mapping) or head_commit.get("sha") != source["head_sha"]:
        raise GhAwProviderError("pull request head SHA changed after planning")
    if isinstance(response.get("ahead_by"), bool) or not isinstance(response.get("ahead_by"), int):
        raise GhAwProviderError("pull request compare response is missing ahead_by")
    if response["ahead_by"] < 1:
        raise GhAwProviderError("pull request head has no commits ahead of base")
    if not isinstance(files, list) or any(
        not isinstance(item, Mapping) or not isinstance(item.get("filename"), str)
        for item in files
    ):
        raise GhAwProviderError("pull request compare response has invalid files")
    actual = sorted({str(item["filename"]) for item in files})
    expected = sorted(source["changed_files"])
    if actual != expected:
        raise GhAwProviderError("pull request changed files drifted after planning")


def _recover_operation(operation: Mapping[str, Any], repository: str, transport: Any) -> dict[str, Any] | None:
    output_type = operation["type"]
    if output_type == "dispatch-workflow":
        return None
    if output_type == "add-comment":
        item_number = operation["source"]["item_number"]
        endpoint = (
            f"/repos/{repository}/issues/{item_number}/comments"
            "?per_page=100&sort=created&direction=desc"
        )
    elif output_type == "create-pull-request":
        endpoint = f"/repos/{repository}/pulls?state=all&per_page=100&sort=created&direction=desc"
    else:
        endpoint = f"/repos/{repository}/issues?state=all&per_page=100&sort=created&direction=desc"
    response = transport.request("GET", endpoint, paginate=True)
    candidates = _items(response)
    if output_type == "create-issue":
        candidates = [item for item in candidates if "pull_request" not in item]
    elif output_type == "create-pull-request":
        candidates = [item for item in candidates if "pull_request" in item or "/pull/" in str(item.get("html_url", ""))]
    matches = [
        item
        for item in candidates
        if operation["marker"] in str(item.get("body", ""))
    ]
    if len(matches) > 1:
        raise GhAwProviderError("provider idempotency marker matched multiple GitHub resources")
    return matches[0] if matches else None


def _resource_summary(output_type: str, response: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if output_type == "dispatch-workflow":
        run_id = response.get("workflow_run_id")
        html_url = response.get("html_url")
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
            raise GhAwProviderError("workflow dispatch did not return a workflow_run_id")
        summary = {"workflow_run_id": run_id, "html_url": html_url}
    else:
        resource_id = response.get("id")
        number = response.get("number")
        html_url = response.get("html_url")
        if isinstance(resource_id, bool) or not isinstance(resource_id, int) or resource_id < 1:
            raise GhAwProviderError("GitHub provider result is missing a resource id")
        summary = {"id": resource_id, "html_url": html_url}
        if isinstance(number, int) and not isinstance(number, bool) and number > 0:
            summary["number"] = number
    if not isinstance(html_url, str) or not html_url.startswith("https://github.com/"):
        raise GhAwProviderError("GitHub provider result has an invalid resource URL")
    return html_url, summary


def _reconcile_dispatch_run(
    operation: Mapping[str, Any],
    repository: str,
    run_id: int,
    transport: Any,
) -> tuple[str, dict[str, Any]]:
    """Verify operator-supplied workflow-run evidence without issuing another dispatch."""

    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
        raise GhAwProviderError("run_id must be a positive integer")
    endpoint = f"/repos/{repository}/actions/runs/{run_id}"
    response = transport.request("GET", endpoint)
    if not isinstance(response, Mapping):
        raise GhAwProviderError("workflow run reconciliation response must be an object")
    if response.get("id") != run_id:
        raise GhAwProviderError("workflow run reconciliation returned a different run identity")
    expected_path = f".github/workflows/{operation['source']['workflow_id']}.lock.yml"
    if response.get("path") != expected_path:
        raise GhAwProviderError("workflow run does not match the compiled lock workflow")
    if response.get("event") != "workflow_dispatch":
        raise GhAwProviderError("workflow run is not a workflow_dispatch event")
    if response.get("head_branch") != operation["source"]["ref"]:
        raise GhAwProviderError("workflow run ref does not match the dispatched ref")
    expected_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    if response.get("html_url") != expected_url:
        raise GhAwProviderError("workflow run URL does not match the repository and run identity")
    observed = dict(response)
    observed["workflow_run_id"] = run_id
    return _resource_summary("dispatch-workflow", observed)


def _receipt(
    prepared: _Prepared,
    approval_id: str,
    summaries: list[dict[str, Any]],
    resource_refs: list[str],
) -> dict[str, Any]:
    if not summaries or not resource_refs:
        raise GhAwProviderError("provider result cannot produce an empty receipt")
    return {
        "status": "succeeded",
        "episode_id": prepared.request["episode_id"],
        "workflow_id": prepared.request["workflow_id"],
        "safe_output_type": prepared.request["safe_output_type"],
        "approval_id": digest({"approval_id": approval_id}),
        "adapter_contract_revision": prepared.bridge.BRIDGE_REVISION,
        "provider_request_id": f"forge-gh-aw:{prepared.public['execution_digest'][7:]}",
        "resource_ref": resource_refs[0] if len(resource_refs) == 1 else digest(resource_refs),
        "result_ref": digest(summaries),
    }


def _authorization_from_journal(
    prepared: _Prepared,
    approval_id: str,
    action_digest: str,
    approvals_path: Path,
) -> Any:
    try:
        evaluation = prepared.policy_engine.evaluate(prepared.policy_action)
    except prepared.policy_module.PolicyError as exc:
        raise GhAwProviderError(f"cannot re-evaluate provider policy: {exc}") from exc
    expected_digest = "sha256:" + evaluation.decision.action_digest
    if action_digest != expected_digest:
        raise GhAwProviderError("provider journal authorization action digest is stale")
    try:
        records = prepared.policy_module.ApprovalStore(
            approvals_path,
            clock=prepared.policy_engine.clock,
        ).read()
    except prepared.policy_module.PolicyError as exc:
        raise GhAwProviderError(f"cannot read provider approval evidence: {exc}") from exc
    issued = next(
        (
            record
            for record in records
            if record.get("event") == "issued" and record.get("approval_id") == approval_id
        ),
        None,
    )
    consumed = any(
        record.get("event") == "consumed" and record.get("approval_id") == approval_id
        for record in records
    )
    if issued is None or not consumed:
        raise GhAwProviderError("provider journal approval was not durably consumed")
    if (
        issued.get("action_digest") != evaluation.decision.action_digest
        or issued.get("policy_revision") != evaluation.decision.policy_revision
        or issued.get("principal") != evaluation.action.principal
        or issued.get("workspace") != evaluation.action.workspace
    ):
        raise GhAwProviderError("provider journal approval no longer matches policy evidence")
    authorization = prepared.policy_module.PolicyAuthorization(
        evaluation.action,
        evaluation.effective_action,
        evaluation.decision,
        "authorized",
        approval_id,
    )
    try:
        prepared.policy_engine.recheck(authorization)
    except prepared.policy_module.PolicyError as exc:
        raise GhAwProviderError(f"provider policy recheck failed: {exc}") from exc
    return authorization


def _commit_policy_outcome(
    prepared: _Prepared,
    authorization: Any,
    receipt: Mapping[str, Any],
    *,
    receipts_path: Path | None,
) -> None:
    try:
        prepared.policy_engine.commit(
            authorization,
            {
                "effect_id": prepared.effect["effect_id"],
                "execution_digest": prepared.public["execution_digest"],
                "result_ref": receipt["result_ref"],
            },
            receipts_path=receipts_path,
        )
    except prepared.policy_module.PolicyError as exc:
        raise GhAwProviderError(f"cannot commit provider policy outcome: {exc}") from exc


def _acknowledge(
    prepared: _Prepared,
    database: Path,
    worker_id: str,
    lease_generation: int,
    receipt: Mapping[str, Any],
    *,
    now: str | None,
) -> None:
    try:
        prepared.bridge.acknowledge_episode(
            prepared.spec_path,
            prepared.output,
            database,
            prepared.public["dispatcher_workflow_id"],
            prepared.request["episode_id"],
            prepared.effect["effect_id"],
            worker_id,
            lease_generation,
            receipt,
            received_at=now,
        )
    except (prepared.bridge.GhAwRuntimeError, prepared.runtime.RuntimeStoreError) as exc:
        raise GhAwProviderError(f"provider receipt acknowledgement failed: {exc}") from exc


def _existing_receipt(
    database: Path, request: Mapping[str, Any], effect_id: str
) -> dict[str, Any] | None:
    bridge = _bridge()
    runtime = bridge._runtime()
    try:
        with runtime.RuntimeStore(database) as store:
            effects = [
                item
                for item in store.list_outbox(request["episode_id"])
                if item["effect_id"] == effect_id
            ]
            if not effects or effects[0]["status"] != "succeeded":
                return None
            effect = effects[0]
            payload = effect["payload"]
            if payload.get("repository") != request["repository"]:
                raise GhAwProviderError("provider replay repository does not match the effect")
            if payload.get("workflow_id") != request["workflow_id"]:
                raise GhAwProviderError("provider replay workflow does not match the effect")
            if payload.get("safe_output_type") != request["safe_output_type"]:
                raise GhAwProviderError("provider replay output type does not match the effect")
            expected_ref = (
                payload.get("request_digest")
                if request["safe_output_type"] == "dispatch-workflow"
                else payload.get("output_ref")
            )
            if expected_ref != request["request_ref"]:
                raise GhAwProviderError("provider replay request_ref does not match the effect")
            inbox = [
                item
                for item in store.list_inbox(request["episode_id"])
                if item["effect_id"] == effect_id
            ]
            if len(inbox) != 1:
                raise GhAwProviderError("succeeded effect is missing its unique inbox receipt")
            return copy.deepcopy(inbox[0]["receipt"])
    except runtime.RuntimeStoreError as exc:
        raise GhAwProviderError(f"cannot inspect provider replay state: {exc}") from exc


def _recheck_admission(
    prepared: _Prepared, database: Path, admission_path: Path | None
) -> None:
    if prepared.admission is None:
        return
    if admission_path is None:
        raise GhAwProviderError("native execution requires an admission certificate")
    try:
        current = prepared.bridge.verify_admission_certificate(
            prepared.spec_path,
            prepared.output,
            database,
            admission_path,
            episode_id=prepared.request["episode_id"],
            dispatcher_id=prepared.public["dispatcher_workflow_id"],
        )
    except prepared.bridge.GhAwRuntimeError as exc:
        raise GhAwProviderError(f"native admission verification failed: {exc}") from exc
    if current["admission_id"] != prepared.admission["admission_id"]:
        raise GhAwProviderError("native admission verification failed: admission identity changed")


def _recheck_handoff(
    prepared: _Prepared, database: Path, admission_path: Path | None, handoff_path: Path | None
) -> None:
    if prepared.handoff is None:
        return
    if admission_path is None or handoff_path is None:
        raise GhAwProviderError("native execution requires the admission and worker handoff")
    try:
        current = prepared.bridge.verify_native_worker_handoff(
            prepared.spec_path,
            prepared.output,
            database,
            handoff_path,
            admission_path,
            episode_id=prepared.request["episode_id"],
            dispatcher_id=prepared.public["dispatcher_workflow_id"],
            effect_id=prepared.effect["effect_id"],
            worker_id=prepared.lease["worker_id"],
            lease_generation=prepared.lease["lease_generation"],
            request_ref=prepared.request["request_ref"],
        )
    except prepared.bridge.GhAwRuntimeError as exc:
        raise GhAwProviderError(f"native worker handoff verification failed: {exc}") from exc
    if current["handoff_id"] != prepared.handoff["handoff_id"]:
        raise GhAwProviderError("native worker handoff identity changed")


def _recheck_host_admission(prepared: _Prepared) -> None:
    if prepared.host_admission is None:
        return
    current = _host_admission_for_effect(
        prepared.request,
        prepared.effect,
        prepared.lease,
        prepared.host_admission_path,
        host_ref=prepared.host_ref,
        host_audience_ref=prepared.host_audience_ref,
        host_workspace_ref=prepared.host_workspace_ref,
        now=prepared.now,
    )
    if current is None or current["admission_id"] != prepared.host_admission["admission_id"]:
        raise GhAwProviderError("host admission verification failed: admission identity changed")


def execute_effect(
    spec_path: Path,
    output: Path,
    database: Path,
    request: Mapping[str, Any],
    effect_id: str,
    worker_id: str,
    lease_generation: int,
    approval_id: str,
    *,
    expected_login: str,
    approvals_path: Path = DEFAULT_APPROVALS,
    receipts_path: Path | None = None,
    journal_path: Path = DEFAULT_JOURNAL,
    admission_path: Path | None = None,
    handoff_path: Path | None = None,
    host_admission_path: Path | None = None,
    host_ref: str | None = None,
    host_audience_ref: str | None = None,
    host_workspace_ref: str | None = None,
    transport: Any | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    normalized_request = validate_request(request)
    _validate_request_admission(spec_path, output, database, normalized_request, admission_path)
    existing_receipt = _existing_receipt(database, normalized_request, effect_id)
    if existing_receipt is not None:
        return {
            "schema_version": SCHEMA_VERSION,
            "provider_revision": PROVIDER_REVISION,
            "status": "succeeded",
            "replayed": True,
            "receipt": existing_receipt,
        }
    prepared = _prepare(
        spec_path,
        output,
        database,
        normalized_request,
        effect_id,
        worker_id,
        lease_generation,
        approvals_path=approvals_path,
        now=now,
        admission_path=admission_path,
        handoff_path=handoff_path,
        host_admission_path=host_admission_path,
        host_ref=host_ref,
        host_audience_ref=host_audience_ref,
        host_workspace_ref=host_workspace_ref,
    )
    expected_login = _text(expected_login, "expected_login", maximum=128)
    provider = _LeaseGuard(transport or GitHubTransport(), prepared, database, now=now)
    actual_login = provider.authenticated_login()
    if actual_login.casefold() != expected_login.casefold():
        raise GhAwProviderError(
            f"authenticated GitHub login mismatch: expected {expected_login}, got {actual_login}"
        )
    _recheck_host_admission(prepared)
    _recheck_admission(prepared, database, admission_path)
    _recheck_handoff(prepared, database, admission_path, handoff_path)
    journal = ProviderJournal(journal_path)
    evidence = journal.for_effect(effect_id, prepared.public["execution_digest"])
    if "succeeded" in evidence:
        authorized = evidence.get("authorized")
        if authorized is None:
            raise GhAwProviderError("provider journal success has no authorization")
        recorded_approval = authorized["details"].get("approval_id")
        if recorded_approval != approval_id:
            raise GhAwProviderError("retry approval does not match provider journal evidence")
        receipt = evidence["succeeded"]["details"].get("receipt")
        if not isinstance(receipt, Mapping):
            raise GhAwProviderError("provider journal succeeded evidence has no receipt")
        authorization = _authorization_from_journal(
            prepared,
            approval_id,
            authorized["details"]["action_digest"],
            approvals_path,
        )
        _commit_policy_outcome(
            prepared,
            authorization,
            receipt,
            receipts_path=receipts_path,
        )
        _acknowledge(
            prepared,
            database,
            worker_id,
            lease_generation,
            receipt,
            now=now,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "provider_revision": PROVIDER_REVISION,
            "status": "succeeded",
            "replayed": True,
            "receipt": copy.deepcopy(dict(receipt)),
        }
    for operation in prepared.operations:
        if operation["type"] == "create-pull-request":
            _preflight_pull_request(operation, prepared.request["repository"], provider)
    recovered = [
        _recover_operation(operation, prepared.request["repository"], provider)
        for operation in prepared.operations
    ]
    authorized_evidence = evidence.get("authorized")
    if authorized_evidence is not None:
        if prepared.request["safe_output_type"] == "dispatch-workflow":
            raise GhAwProviderError(
                "workflow dispatch outcome is ambiguous after authorization; reconcile the run before retry"
            )
        if any(item is None for item in recovered):
            raise GhAwProviderError(
                "provider outcome is ambiguous after authorization; no duplicate write was attempted"
            )
        recorded_approval = authorized_evidence["details"].get("approval_id")
        if not isinstance(recorded_approval, str):
            raise GhAwProviderError("provider journal authorization is missing its approval")
        if recorded_approval != approval_id:
            raise GhAwProviderError("retry approval does not match provider journal evidence")
        summaries: list[dict[str, Any]] = []
        resource_refs: list[str] = []
        for response in recovered:
            assert response is not None
            resource_ref, summary = _resource_summary(
                prepared.request["safe_output_type"], response
            )
            resource_refs.append(resource_ref)
            summaries.append(summary)
        receipt = _receipt(prepared, recorded_approval, summaries, resource_refs)
        authorization = _authorization_from_journal(
            prepared,
            recorded_approval,
            authorized_evidence["details"]["action_digest"],
            approvals_path,
        )
        _commit_policy_outcome(
            prepared,
            authorization,
            receipt,
            receipts_path=receipts_path,
        )
        journal.append(
            "succeeded",
            effect_id,
            prepared.public["execution_digest"],
            {"receipt": receipt, "recovered": True},
            occurred_at=now,
        )
        _acknowledge(
            prepared,
            database,
            worker_id,
            lease_generation,
            receipt,
            now=now,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "provider_revision": PROVIDER_REVISION,
            "status": "succeeded",
            "recovered": True,
            "receipt": receipt,
        }
    if any(item is not None for item in recovered):
        raise GhAwProviderError(
            "provider resource exists without matching local authorization evidence"
        )
    try:
        authorization = prepared.policy_engine.authorize(
            prepared.policy_action,
            approval_id=approval_id,
            receipts_path=receipts_path,
        )
    except prepared.policy_module.PolicyError as exc:
        raise GhAwProviderError(f"provider authorization failed: {exc}") from exc
    try:
        with prepared.runtime.RuntimeStore(database) as store:
            store.authorize_outbox_effect(
                effect_id,
                worker_id,
                lease_generation=lease_generation,
                now=now,
            )
        prepared.policy_engine.recheck(authorization, receipts_path=receipts_path)
    except (prepared.runtime.RuntimeStoreError, prepared.policy_module.PolicyError) as exc:
        raise GhAwProviderError(f"pre-effect authorization recheck failed: {exc}") from exc
    journal.append(
        "authorized",
        effect_id,
        prepared.public["execution_digest"],
        {
            "approval_id": approval_id,
            "approval_ref": digest({"approval_id": approval_id}),
            "action_digest": prepared.public["policy"]["authorization_action_digest"],
        },
        occurred_at=now,
    )
    summaries = []
    resource_refs = []
    for operation in prepared.operations:
        response = provider.request(
            operation["method"],
            operation["endpoint"],
            body=operation["body"],
        )
        if not isinstance(response, Mapping):
            raise GhAwProviderError("GitHub provider result must be an object")
        resource_ref, summary = _resource_summary(operation["type"], response)
        resource_refs.append(resource_ref)
        summaries.append(summary)
    receipt = _receipt(prepared, approval_id, summaries, resource_refs)
    _commit_policy_outcome(
        prepared,
        authorization,
        receipt,
        receipts_path=receipts_path,
    )
    journal.append(
        "succeeded",
        effect_id,
        prepared.public["execution_digest"],
        {"receipt": receipt, "recovered": False},
        occurred_at=now,
    )
    _acknowledge(
        prepared,
        database,
        worker_id,
        lease_generation,
        receipt,
        now=now,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "provider_revision": PROVIDER_REVISION,
        "status": "succeeded",
        "recovered": False,
        "receipt": receipt,
    }


def reconcile_effect(
    spec_path: Path,
    output: Path,
    database: Path,
    request: Mapping[str, Any],
    effect_id: str,
    worker_id: str,
    lease_generation: int,
    approval_id: str,
    run_id: int,
    *,
    expected_login: str,
    approvals_path: Path = DEFAULT_APPROVALS,
    receipts_path: Path | None = None,
    journal_path: Path = DEFAULT_JOURNAL,
    admission_path: Path | None = None,
    handoff_path: Path | None = None,
    host_admission_path: Path | None = None,
    host_ref: str | None = None,
    host_audience_ref: str | None = None,
    host_workspace_ref: str | None = None,
    transport: Any | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Reconcile one ambiguous workflow dispatch from verified GitHub run metadata."""

    normalized_request = validate_request(request)
    if normalized_request["safe_output_type"] != "dispatch-workflow":
        raise GhAwProviderError("reconciliation is supported only for workflow dispatch")
    _validate_request_admission(spec_path, output, database, normalized_request, admission_path)
    existing_receipt = _existing_receipt(database, normalized_request, effect_id)
    if existing_receipt is not None:
        return {
            "schema_version": SCHEMA_VERSION,
            "provider_revision": PROVIDER_REVISION,
            "status": "succeeded",
            "reconciled": True,
            "replayed": True,
            "receipt": existing_receipt,
        }
    prepared = _prepare(
        spec_path,
        output,
        database,
        normalized_request,
        effect_id,
        worker_id,
        lease_generation,
        approvals_path=approvals_path,
        now=now,
        admission_path=admission_path,
        handoff_path=handoff_path,
        host_admission_path=host_admission_path,
        host_ref=host_ref,
        host_audience_ref=host_audience_ref,
        host_workspace_ref=host_workspace_ref,
    )
    expected_login = _text(expected_login, "expected_login", maximum=128)
    approval_id = _text(approval_id, "approval_id", maximum=128)
    provider = _LeaseGuard(transport or GitHubTransport(), prepared, database, now=now)
    actual_login = provider.authenticated_login()
    if actual_login.casefold() != expected_login.casefold():
        raise GhAwProviderError(
            f"authenticated GitHub login mismatch: expected {expected_login}, got {actual_login}"
        )
    _recheck_host_admission(prepared)
    _recheck_admission(prepared, database, admission_path)
    _recheck_handoff(prepared, database, admission_path, handoff_path)
    journal = ProviderJournal(journal_path)
    evidence = journal.for_effect(effect_id, prepared.public["execution_digest"])
    authorized = evidence.get("authorized")
    if authorized is None:
        raise GhAwProviderError("cannot reconcile a dispatch without provider authorization evidence")
    recorded_approval = authorized["details"].get("approval_id")
    if recorded_approval != approval_id:
        raise GhAwProviderError("reconciliation approval does not match provider journal evidence")
    if "succeeded" in evidence:
        receipt = evidence["succeeded"]["details"].get("receipt")
        if not isinstance(receipt, Mapping):
            raise GhAwProviderError("provider journal succeeded evidence has no receipt")
        authorization = _authorization_from_journal(
            prepared,
            approval_id,
            authorized["details"]["action_digest"],
            approvals_path,
        )
        _commit_policy_outcome(
            prepared,
            authorization,
            receipt,
            receipts_path=receipts_path,
        )
        _acknowledge(
            prepared,
            database,
            worker_id,
            lease_generation,
            receipt,
            now=now,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "provider_revision": PROVIDER_REVISION,
            "status": "succeeded",
            "reconciled": True,
            "replayed": True,
            "receipt": copy.deepcopy(dict(receipt)),
        }
    if len(prepared.operations) != 1:
        raise GhAwProviderError("workflow dispatch reconciliation requires one compiled operation")
    resource_ref, summary = _reconcile_dispatch_run(
        prepared.operations[0],
        prepared.request["repository"],
        run_id,
        provider,
    )
    receipt = _receipt(prepared, recorded_approval, [summary], [resource_ref])
    authorization = _authorization_from_journal(
        prepared,
        recorded_approval,
        authorized["details"]["action_digest"],
        approvals_path,
    )
    _commit_policy_outcome(
        prepared,
        authorization,
        receipt,
        receipts_path=receipts_path,
    )
    journal.append(
        "succeeded",
        effect_id,
        prepared.public["execution_digest"],
        {"receipt": receipt, "recovered": True, "reconciled": True},
        occurred_at=now,
    )
    _acknowledge(
        prepared,
        database,
        worker_id,
        lease_generation,
        receipt,
        now=now,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "provider_revision": PROVIDER_REVISION,
        "status": "succeeded",
        "reconciled": True,
        "recovered": True,
        "receipt": receipt,
    }


def _load_request(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GhAwProviderError(f"cannot read provider request: {exc}") from exc
    if not isinstance(value, dict):
        raise GhAwProviderError("provider request file must contain an object")
    return value


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--effect-id", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--lease-generation", type=int, required=True)
    parser.add_argument("--approvals", type=Path, default=DEFAULT_APPROVALS)
    parser.add_argument("--admission", type=Path)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--host-admission", type=Path)
    parser.add_argument("--host-ref")
    parser.add_argument("--host-audience")
    parser.add_argument("--host-workspace")
    parser.add_argument("--now")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="validate a leased effect without mutation")
    _common(plan_parser)
    approve_parser = subparsers.add_parser(
        "approve", help="issue a short-lived one-use approval for the exact provider plan"
    )
    _common(approve_parser)
    approve_parser.add_argument("--receipts", type=Path, default=DEFAULT_RECEIPTS)
    approve_parser.add_argument("--ttl-seconds", type=int, default=600)
    execute_parser = subparsers.add_parser(
        "execute", help="perform and acknowledge one explicitly authorized GitHub effect"
    )
    _common(execute_parser)
    execute_parser.add_argument("--approval-id", required=True)
    execute_parser.add_argument("--expected-login", required=True)
    execute_parser.add_argument("--receipts", type=Path, default=DEFAULT_RECEIPTS)
    execute_parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    execute_parser.add_argument(
        "--execute",
        action="store_true",
        help="required acknowledgement that GitHub may be mutated",
    )
    reconcile_parser = subparsers.add_parser(
        "reconcile", help="reconcile an ambiguous workflow dispatch from a verified run"
    )
    _common(reconcile_parser)
    reconcile_parser.add_argument("--approval-id", required=True)
    reconcile_parser.add_argument("--expected-login", required=True)
    reconcile_parser.add_argument("--run-id", type=int, required=True)
    reconcile_parser.add_argument("--receipts", type=Path, default=DEFAULT_RECEIPTS)
    reconcile_parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    reconcile_parser.add_argument(
        "--reconcile",
        action="store_true",
        help="required acknowledgement that the supplied run evidence may complete the effect",
    )
    try:
        args = parser.parse_args(argv)
        request = _load_request(args.request)
        if args.command == "plan":
            result = plan_effect(
                args.spec,
                args.output,
                args.db,
                request,
                args.effect_id,
                args.worker_id,
                args.lease_generation,
                approvals_path=args.approvals,
                admission_path=args.admission,
                handoff_path=args.handoff,
                host_admission_path=args.host_admission,
                host_ref=args.host_ref,
                host_audience_ref=args.host_audience,
                host_workspace_ref=args.host_workspace,
                now=args.now,
            )
        elif args.command == "approve":
            result = issue_approval(
                args.spec,
                args.output,
                args.db,
                request,
                args.effect_id,
                args.worker_id,
                args.lease_generation,
                approvals_path=args.approvals,
                admission_path=args.admission,
                handoff_path=args.handoff,
                host_admission_path=args.host_admission,
                host_ref=args.host_ref,
                host_audience_ref=args.host_audience,
                host_workspace_ref=args.host_workspace,
                receipts_path=args.receipts,
                ttl_seconds=args.ttl_seconds,
                now=args.now,
            )
        elif args.command == "execute":
            if not args.execute:
                raise GhAwProviderError("execute requires the explicit --execute flag")
            result = execute_effect(
                args.spec,
                args.output,
                args.db,
                request,
                args.effect_id,
                args.worker_id,
                args.lease_generation,
                args.approval_id,
                expected_login=args.expected_login,
                approvals_path=args.approvals,
                admission_path=args.admission,
                handoff_path=args.handoff,
                host_admission_path=args.host_admission,
                host_ref=args.host_ref,
                host_audience_ref=args.host_audience,
                host_workspace_ref=args.host_workspace,
                receipts_path=args.receipts,
                journal_path=args.journal,
                now=args.now,
            )
        else:
            if not args.reconcile:
                raise GhAwProviderError("reconcile requires the explicit --reconcile flag")
            result = reconcile_effect(
                args.spec,
                args.output,
                args.db,
                request,
                args.effect_id,
                args.worker_id,
                args.lease_generation,
                args.approval_id,
                args.run_id,
                expected_login=args.expected_login,
                approvals_path=args.approvals,
                admission_path=args.admission,
                handoff_path=args.handoff,
                host_admission_path=args.host_admission,
                host_ref=args.host_ref,
                host_audience_ref=args.host_audience,
                host_workspace_ref=args.host_workspace,
                receipts_path=args.receipts,
                journal_path=args.journal,
                now=args.now,
            )
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0
    except (GhAwProviderError, OSError, TypeError, ValueError) as exc:
        print(f"forge-gh-aw-provider: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
