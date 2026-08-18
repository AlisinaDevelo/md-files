#!/usr/bin/env python3
"""Validate A2A Agent Cards and emit digest-only Forge trust evidence."""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
CONTRACT_REVISION = "forge-a2a-card-v1"
SCHEMA_URI = "https://github.com/AlisinaDevelo/md-files/schema/runtime/a2a-card/v1"
DEFAULT_PROTOCOL_VERSION = "1.0"
REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+$")
MODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]*/[A-Za-z0-9][A-Za-z0-9.+_-]*(?:\+[A-Za-z0-9.+_-]+)?$")
BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
SECURE_SCHEMES = {"https", "wss"}
SECURITY_SCHEME_TYPES = {
    "apiKeySecurityScheme",
    "httpAuthSecurityScheme",
    "oauth2SecurityScheme",
    "openIdConnectSecurityScheme",
    "mutualTlsSecurityScheme",
}
DECLARATION_KEY_NAMES = {
    "authorizationcode",
    "clientcredentials",
    "devicecode",
    "implicit",
    "mutualtlssecurityscheme",
    "oauth2securityscheme",
    "openidconnectsecurityscheme",
    "apikeysecurityscheme",
    "httpauthsecurityscheme",
}
FORBIDDEN_KEY_PARTS = (
    "access_token",
    "client_secret",
    "cookie",
    "credential",
    "password",
    "private",
    "secret",
)
CREDENTIAL_VALUE_RE = re.compile(
    r"(?:"
    r"(?:github_pat_|gh[opusr]_)[A-Za-z0-9_]{16,}"
    r"|Bearer\s+[A-Za-z0-9._~+/=-]{16,}"
    r"|eyJ[A-Za-z0-9._-]{16,}"
    r"|sk-[A-Za-z0-9]{16,}"
    r")",
    re.IGNORECASE,
)
KNOWN_CARD_FIELDS = {
    "name",
    "description",
    "supportedInterfaces",
    "provider",
    "version",
    "documentationUrl",
    "iconUrl",
    "capabilities",
    "securitySchemes",
    "securityRequirements",
    "defaultInputModes",
    "defaultOutputModes",
    "skills",
    "signatures",
}


class A2ACardError(ValueError):
    """Raised when an A2A Agent Card cannot be trusted as a Forge input."""


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise A2ACardError(f"canonical-json: {exc}") from exc


def digest_ref(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise A2ACardError(f"invalid-{label}: expected object with string keys")
    return {str(key): copy.deepcopy(child) for key, child in value.items()}


def _text(
    value: Any,
    label: str,
    *,
    maximum: int = 256,
    pattern: re.Pattern[str] | None = None,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or (not value and not allow_empty) or len(value) > maximum:
        raise A2ACardError(f"invalid-{label}: expected bounded string")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        raise A2ACardError(f"invalid-{label}: control character")
    if pattern is not None and not pattern.fullmatch(value):
        raise A2ACardError(f"invalid-{label}: malformed value")
    return value


def _id(value: Any, label: str) -> str:
    return _text(value, label, maximum=128, pattern=ID_RE)


def _opaque(value: Any, label: str) -> str:
    return _text(
        value,
        label,
        maximum=256,
        pattern=re.compile(r"^[a-z][a-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._:/@-]{0,191}$"),
    )


def _string_list(
    value: Any,
    label: str,
    *,
    maximum: int = 64,
    item_maximum: int = 256,
    pattern: re.Pattern[str] | None = None,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty) or len(value) > maximum:
        qualifier = "bounded array" if allow_empty else "non-empty bounded array"
        raise A2ACardError(f"invalid-{label}: expected a {qualifier}")
    result = [_text(item, f"{label}-item", maximum=item_maximum, pattern=pattern) for item in value]
    if len(set(result)) != len(result):
        raise A2ACardError(f"invalid-{label}: duplicate values")
    return result


def _url(value: Any, label: str) -> str:
    text = _text(value, label, maximum=2048)
    parsed = urlsplit(text)
    if parsed.scheme not in SECURE_SCHEMES or not parsed.netloc:
        raise A2ACardError(f"insecure-{label}: HTTPS or WSS is required")
    if parsed.username is not None or parsed.password is not None:
        raise A2ACardError(f"invalid-{label}: credentials in URL")
    if parsed.fragment:
        raise A2ACardError(f"invalid-{label}: fragments are not allowed")
    return text


def _uri(value: Any, label: str) -> str:
    text = _text(value, label, maximum=2048)
    parsed = urlsplit(text)
    if not parsed.scheme or any(char.isspace() for char in text):
        raise A2ACardError(f"invalid-{label}: expected URI")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise A2ACardError(f"invalid-{label}: unsafe URI")
    if parsed.scheme in SECURE_SCHEMES and not parsed.netloc:
        raise A2ACardError(f"invalid-{label}: secure URI requires an authority")
    return text


def _validate_secure_urls(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower().endswith("url"):
                _url(child, child_path)
            else:
                _validate_secure_urls(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_secure_urls(child, f"{path}[{index}]")


def _reject_credentials(value: Any, path: str = "card") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            lowered = key_text.lower().replace("-", "_")
            is_url_field = lowered.endswith("url")
            is_signature_field = path.startswith("card.signatures") and lowered in {
                "protected",
                "signature",
            }
            if (
                not is_url_field
                and not is_signature_field
                and lowered not in DECLARATION_KEY_NAMES
                and any(part in lowered for part in FORBIDDEN_KEY_PARTS)
            ):
                raise A2ACardError(f"{path}.{key_text} may contain credential material")
            _reject_credentials(child, f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_credentials(child, f"{path}[{index}]")
    elif isinstance(value, str) and CREDENTIAL_VALUE_RE.search(value):
        if path.startswith("card.signatures") and path.rsplit(".", 1)[-1] in {
            "protected",
            "signature",
        }:
            return
        raise A2ACardError(f"{path} contains a credential-shaped value")


def _interfaces(value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(value, list) or not value or len(value) > 16:
        raise A2ACardError("invalid-supportedInterfaces: expected a non-empty bounded array")
    interfaces: list[dict[str, Any]] = []
    versions: list[str] = []
    for index, raw in enumerate(value):
        item = _mapping(raw, f"supportedInterfaces[{index}]")
        url = _url(item.get("url"), f"supportedInterfaces[{index}].url")
        binding = _text(item.get("protocolBinding"), f"supportedInterfaces[{index}].protocolBinding")
        version = _text(
            item.get("protocolVersion"),
            f"supportedInterfaces[{index}].protocolVersion",
            maximum=32,
            pattern=VERSION_RE,
        )
        if binding not in {"HTTP+JSON", "JSONRPC", "GRPC"} and not (
            binding.startswith(("https://", "wss://", "urn:"))
        ):
            raise A2ACardError(f"unsupported-protocol-binding:{binding}")
        if binding not in {"HTTP+JSON", "JSONRPC", "GRPC"}:
            _uri(binding, f"supportedInterfaces[{index}].protocolBinding")
        normalized = {
            "url": url,
            "protocolBinding": binding,
            "protocolVersion": version,
        }
        if "tenant" in item:
            normalized["tenant"] = _text(
                item["tenant"], f"supportedInterfaces[{index}].tenant", maximum=256
            )
        interfaces.append(normalized)
        versions.append(version)
    return interfaces, sorted(set(versions))


def _modes(value: Any, label: str) -> list[str]:
    return _string_list(value, label, maximum=64, item_maximum=128, pattern=MODE_RE)


def _extensions(value: Any) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    if value is None:
        return [], [], []
    if not isinstance(value, list) or len(value) > 64:
        raise A2ACardError("invalid-capabilities.extensions: expected bounded array")
    extensions: list[dict[str, Any]] = []
    uris: list[str] = []
    required: list[str] = []
    for index, raw in enumerate(value):
        item = _mapping(raw, f"capabilities.extensions[{index}]")
        uri = _uri(item.get("uri"), f"capabilities.extensions[{index}].uri")
        description = _text(
            item.get("description"),
            f"capabilities.extensions[{index}].description",
            maximum=2048,
            allow_empty=True,
        )
        required_flag = item.get("required", False)
        if not isinstance(required_flag, bool):
            raise A2ACardError("invalid-extension-required")
        if uri in uris:
            raise A2ACardError("duplicate-extension-uri")
        normalized = {"uri": uri, "description": description, "required": required_flag}
        if "params" in item:
            _mapping(item["params"], f"capabilities.extensions[{index}].params")
            normalized["params"] = copy.deepcopy(item["params"])
        extensions.append(normalized)
        uris.append(uri)
        if required_flag:
            required.append(uri)
    return extensions, sorted(uris), sorted(required)


def _capabilities(value: Any) -> tuple[dict[str, Any], list[str], list[str]]:
    data = _mapping(value, "capabilities")
    normalized: dict[str, Any] = {}
    for field in ("streaming", "pushNotifications", "extendedAgentCard"):
        if field in data:
            if not isinstance(data[field], bool):
                raise A2ACardError(f"invalid-capabilities.{field}")
            normalized[field] = data[field]
    extensions, extension_uris, required_extensions = _extensions(data.get("extensions"))
    if extensions:
        normalized["extensions"] = extensions
    return normalized, extension_uris, required_extensions


def _security_schemes(value: Any) -> tuple[dict[str, Any], list[str]]:
    if value is None:
        return {}, []
    data = _mapping(value, "securitySchemes")
    normalized: dict[str, Any] = {}
    for name, raw in data.items():
        scheme_name = _id(name, "security-scheme-name")
        scheme = _mapping(raw, f"securitySchemes.{scheme_name}")
        if len(scheme) != 1:
            raise A2ACardError(f"invalid-security-scheme:{scheme_name}")
        scheme_type, definition = next(iter(scheme.items()))
        if scheme_type not in SECURITY_SCHEME_TYPES:
            raise A2ACardError(f"unsupported-security-scheme:{scheme_type}")
        definition_data = _mapping(definition, f"securitySchemes.{scheme_name}.{scheme_type}")
        _validate_secure_urls(
            definition_data,
            f"securitySchemes.{scheme_name}.{scheme_type}",
        )
        if scheme_type == "apiKeySecurityScheme":
            location = _text(definition_data.get("in"), "api-key-location", maximum=16)
            if location not in {"header", "query"}:
                raise A2ACardError("api-key-must-use-header-or-query")
            _text(definition_data.get("name"), "api-key-name", maximum=128)
        if scheme_type == "httpAuthSecurityScheme":
            _text(definition_data.get("scheme"), "http-auth-scheme", maximum=64)
        normalized[scheme_name] = {scheme_type: definition_data}
    return normalized, sorted(normalized)


def _security_requirements(value: Any, scheme_names: set[str]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 32:
        raise A2ACardError("invalid-securityRequirements: expected bounded array")
    requirements: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        data = _mapping(raw, f"securityRequirements[{index}]")
        schemes = _mapping(data.get("schemes"), f"securityRequirements[{index}].schemes")
        normalized_schemes: dict[str, Any] = {}
        for name, requirement in schemes.items():
            if name not in scheme_names:
                raise A2ACardError(f"security-requirement-unknown-scheme:{name}")
            requirement_data = _mapping(requirement, f"securityRequirements[{index}].{name}")
            scopes = requirement_data.get("list", [])
            if not isinstance(scopes, list) or any(
                not isinstance(scope, str) or not scope or len(scope) > 128 for scope in scopes
            ):
                raise A2ACardError(f"invalid-security-scopes:{name}")
            normalized_schemes[name] = {"list": sorted(set(scopes))}
        if not normalized_schemes:
            raise A2ACardError("empty-security-requirement")
        requirements.append({"schemes": normalized_schemes})
    return requirements


def _skills(value: Any, default_inputs: list[str], default_outputs: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(value, list) or len(value) > 128:
        raise A2ACardError("invalid-skills: expected a bounded array")
    skills: list[dict[str, Any]] = []
    ids: list[str] = []
    for index, raw in enumerate(value):
        item = _mapping(raw, f"skills[{index}]")
        skill_id = _id(item.get("id"), f"skills[{index}].id")
        if skill_id in ids:
            raise A2ACardError(f"duplicate-skill-id:{skill_id}")
        name = _text(item.get("name"), f"skills[{index}].name", maximum=256)
        description = _text(
            item.get("description"),
            f"skills[{index}].description",
            maximum=4096,
            allow_empty=True,
        )
        tags = _string_list(
            item.get("tags", []),
            f"skills[{index}].tags",
            maximum=64,
            item_maximum=128,
            allow_empty=True,
        )
        normalized: dict[str, Any] = {
            "id": skill_id,
            "name": name,
            "description": description,
            "tags": tags,
        }
        for field, defaults in (
            ("inputModes", default_inputs),
            ("outputModes", default_outputs),
        ):
            normalized[field] = _modes(item[field], f"skills[{index}].{field}") if field in item else list(defaults)
        if "examples" in item:
            examples = item["examples"]
            if not isinstance(examples, list) or len(examples) > 32:
                raise A2ACardError(f"invalid-skills[{index}].examples")
            normalized["examples"] = [
                _text(example, f"skills[{index}].examples", maximum=4096) for example in examples
            ]
        if "securityRequirements" in item:
            normalized["securityRequirements"] = copy.deepcopy(item["securityRequirements"])
        skills.append(normalized)
        ids.append(skill_id)
    return skills, ids


def _signatures(value: Any) -> tuple[list[str], int]:
    if value is None:
        return [], 0
    if not isinstance(value, list) or len(value) > 16:
        raise A2ACardError("invalid-signatures: expected bounded array")
    refs: list[str] = []
    for index, raw in enumerate(value):
        data = _mapping(raw, f"signatures[{index}]")
        protected = _text(data.get("protected"), f"signatures[{index}].protected", maximum=8192)
        signature = _text(data.get("signature"), f"signatures[{index}].signature", maximum=8192)
        for field, encoded in (("protected", protected), ("signature", signature)):
            if not BASE64URL_RE.fullmatch(encoded):
                raise A2ACardError(f"invalid-signatures[{index}].{field}")
            try:
                base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            except (ValueError, binascii.Error) as exc:
                raise A2ACardError(f"invalid-signatures[{index}].{field}") from exc
        try:
            protected_header = json.loads(
                base64.urlsafe_b64decode(protected + "=" * (-len(protected) % 4))
            )
        except (ValueError, json.JSONDecodeError) as exc:
            raise A2ACardError(f"invalid-signatures[{index}].protected-header") from exc
        protected_data = _mapping(protected_header, f"signatures[{index}].protected-header")
        _text(protected_data.get("alg"), f"signatures[{index}].alg", maximum=32)
        _text(protected_data.get("kid"), f"signatures[{index}].kid", maximum=256)
        if "typ" in protected_data:
            _text(protected_data["typ"], f"signatures[{index}].typ", maximum=32)
        if "jku" in protected_data:
            _url(protected_data["jku"], f"signatures[{index}].jku")
        if "header" in data:
            header = _mapping(data["header"], f"signatures[{index}].header")
            if "jku" in header:
                _url(header["jku"], f"signatures[{index}].header.jku")
        refs.append(digest_ref(data))
    return refs, len(refs)


def parse_card(value: Mapping[str, Any]) -> dict[str, Any]:
    data = _mapping(value, "agent-card")
    _reject_credentials(data)
    if "supportsExtendedAgentCard" in data:
        raise A2ACardError("legacy-extended-agent-card-field")
    required = {
        "name",
        "description",
        "supportedInterfaces",
        "version",
        "capabilities",
        "defaultInputModes",
        "defaultOutputModes",
        "skills",
    }
    missing = sorted(required - set(data))
    if missing:
        raise A2ACardError("missing-agent-card-fields:" + ",".join(missing))
    name = _text(data["name"], "name", maximum=256)
    description = _text(data["description"], "description", maximum=4096, allow_empty=True)
    version = _text(data["version"], "version", maximum=64)
    interfaces, protocol_versions = _interfaces(data["supportedInterfaces"])
    capabilities, extension_uris, required_extensions = _capabilities(data["capabilities"])
    default_inputs = _modes(data["defaultInputModes"], "defaultInputModes")
    default_outputs = _modes(data["defaultOutputModes"], "defaultOutputModes")
    security_schemes, scheme_names = _security_schemes(data.get("securitySchemes"))
    security_requirements = _security_requirements(
        data.get("securityRequirements"), set(scheme_names)
    )
    if capabilities.get("extendedAgentCard") and not security_requirements:
        raise A2ACardError("extended-agent-card-requires-authentication")
    skills, skill_ids = _skills(data["skills"], default_inputs, default_outputs)
    signature_refs, signature_count = _signatures(data.get("signatures"))
    unknown_fields = sorted(set(data) - KNOWN_CARD_FIELDS)
    if len(unknown_fields) > 128:
        raise A2ACardError("too-many-unknown-agent-card-fields")
    provider = None
    if "provider" in data:
        provider_data = _mapping(data["provider"], "provider")
        provider = {
            "organization": _text(provider_data.get("organization"), "provider.organization", maximum=256),
            "url": _url(provider_data.get("url"), "provider.url"),
        }
    links: dict[str, str] = {}
    for field in ("documentationUrl", "iconUrl"):
        if field in data:
            links[field] = _url(data[field], field)
    return {
        "name": name,
        "description": description,
        "version": version,
        "interfaces": interfaces,
        "protocol_versions": protocol_versions,
        "capabilities": capabilities,
        "extension_uris": extension_uris,
        "required_extensions": required_extensions,
        "default_input_modes": default_inputs,
        "default_output_modes": default_outputs,
        "security_schemes": security_schemes,
        "security_scheme_names": scheme_names,
        "security_requirements": security_requirements,
        "skills": skills,
        "skill_ids": skill_ids,
        "signature_refs": signature_refs,
        "signature_count": signature_count,
        "provider": provider,
        "links": links,
        "unknown_fields": unknown_fields,
    }


def verify_card(
    value: Mapping[str, Any],
    *,
    expected_host_ref: str,
    expected_audience_ref: str,
    expected_workspace_ref: str,
    expected_resource_ref: str,
    expected_card_ref: str | None = None,
    expected_protocol_versions: list[str] | None = None,
    required_skill_ids: list[str] | None = None,
    required_security_scheme_names: list[str] | None = None,
    supported_extension_uris: list[str] | None = None,
) -> dict[str, Any]:
    card = parse_card(value)
    card_ref = digest_ref(value)
    if expected_card_ref is not None and card_ref != _ref(expected_card_ref, "expected-card-ref"):
        raise A2ACardError("card-digest-mismatch")
    expected_versions = expected_protocol_versions or [DEFAULT_PROTOCOL_VERSION]
    if not set(card["protocol_versions"]) & set(
        _text(version, "expected-protocol-version", maximum=32, pattern=VERSION_RE)
        for version in expected_versions
    ):
        raise A2ACardError("protocol-version-mismatch")
    if required_skill_ids is not None:
        expected_skills = {_id(skill_id, "required-skill-id") for skill_id in required_skill_ids}
        if not expected_skills <= set(card["skill_ids"]):
            raise A2ACardError("required-skill-missing")
    if required_security_scheme_names is not None:
        expected_schemes = {
            _id(name, "required-security-scheme-name") for name in required_security_scheme_names
        }
        if not expected_schemes <= set(card["security_scheme_names"]):
            raise A2ACardError("required-security-scheme-missing")
    if supported_extension_uris is not None:
        supported = {_uri(uri, "supported-extension-uri") for uri in supported_extension_uris}
        if not set(card["required_extensions"]) <= supported:
            raise A2ACardError("required-extension-unsupported")
    context = {
        "host_ref": _opaque(expected_host_ref, "expected-host-ref"),
        "audience_ref": _opaque(expected_audience_ref, "expected-audience-ref"),
        "workspace_ref": _opaque(expected_workspace_ref, "expected-workspace-ref"),
        "resource_ref": _opaque(expected_resource_ref, "expected-resource-ref"),
    }
    interface_refs = [digest_ref(interface) for interface in card["interfaces"]]
    skill_refs = [digest_ref(skill) for skill in card["skills"]]
    security_scheme_refs = [
        digest_ref(card["security_schemes"][name]) for name in card["security_scheme_names"]
    ]
    for label, refs in (
        ("interface", interface_refs),
        ("skill", skill_refs),
        ("security-scheme", security_scheme_refs),
        ("signature", card["signature_refs"]),
    ):
        if len(set(refs)) != len(refs):
            raise A2ACardError(f"duplicate-{label}-reference")
    material = {
        "contract_revision": CONTRACT_REVISION,
        "card_ref": card_ref,
        "context": context,
        "interface_refs": interface_refs,
        "skill_refs": skill_refs,
        "security_scheme_refs": security_scheme_refs,
        "signature_refs": card["signature_refs"],
    }
    return {
        "$schema": SCHEMA_URI,
        "status": "passed",
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "report_id": digest_ref(material),
        "card_ref": card_ref,
        "agent": {
            "name": card["name"],
            "version": card["version"],
            "provider_ref": None if card["provider"] is None else digest_ref(card["provider"]),
        },
        "context": context,
        "protocol_versions": card["protocol_versions"],
        "interface_refs": interface_refs,
        "skill_refs": skill_refs,
        "security_scheme_refs": security_scheme_refs,
        "signature_refs": card["signature_refs"],
        "signature_count": card["signature_count"],
        "unknown_field_count": len(card["unknown_fields"]),
        "required_extensions": card["required_extensions"],
        "authentication_boundary": (
            "external-reference" if card["signature_count"] else "declared-only"
        ),
        "signature_verification": (
            "external-reference" if card["signature_count"] else "not-provided"
        ),
        "authority_grant": False,
        "checks": {
            "required_fields": True,
            "secure_interfaces": True,
            "protocol_version": True,
            "security_requirements": True,
            "skill_identity": True,
            "credential_exclusion": True,
            "forward_extension_digest": True,
            "authority_non_grant": True,
        },
    }


def load_card(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise A2ACardError(f"cannot-load-agent-card:{path}") from exc
    return _mapping(value, "agent-card")


def _ref(value: Any, label: str) -> str:
    return _text(value, label, maximum=71, pattern=REF_RE)


def evaluate_corpus(path: Path) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = _mapping(json.loads(line), f"corpus-case-{line_number}")
            case_id = _text(case.get("case_id"), "corpus-case-id", maximum=96)
            expected = case.get("expected")
            if expected not in {"passed", "failed"}:
                raise A2ACardError("invalid-corpus-expected")
            context = _mapping(case.get("context"), "corpus-context")
            observed = "passed"
            result: dict[str, Any] | None = None
            error = None
            try:
                result = verify_card(
                    _mapping(case.get("card"), "corpus-card"),
                    expected_host_ref=context.get("expected_host_ref"),
                    expected_audience_ref=context.get("expected_audience_ref"),
                    expected_workspace_ref=context.get("expected_workspace_ref"),
                    expected_resource_ref=context.get("expected_resource_ref"),
                    expected_card_ref=context.get("expected_card_ref"),
                    expected_protocol_versions=context.get("expected_protocol_versions"),
                    required_skill_ids=context.get("required_skill_ids"),
                    required_security_scheme_names=context.get("required_security_scheme_names"),
                    supported_extension_uris=context.get("supported_extension_uris"),
                )
            except (A2ACardError, TypeError, AttributeError) as exc:
                observed = "failed"
                error = str(exc).split(":", 1)[0]
            status = "pass" if observed == expected else "fail"
            record: dict[str, Any] = {
                "case_id": case_id,
                "expected": expected,
                "observed": observed,
                "status": status,
            }
            if error is not None:
                record["error"] = error
            if result is not None:
                record["report_id"] = result["report_id"]
                record["card_ref"] = result["card_ref"]
            cases.append(record)
        except (A2ACardError, json.JSONDecodeError, TypeError) as exc:
            cases.append(
                {
                    "case_id": f"line-{line_number}",
                    "expected": "failed",
                    "observed": "failed",
                    "status": "fail",
                    "error": str(exc).split(":", 1)[0],
                }
            )
    passed = sum(item["status"] == "pass" for item in cases)
    threat_cases = sum(item["expected"] == "failed" for item in cases)
    return {
        "status": "passed" if passed == len(cases) else "failed",
        "schema_version": SCHEMA_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "case_count": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "threat_cases": threat_cases,
        "deterministic": True,
        "cases": cases,
        "corpus_digest": digest_ref(cases),
    }


def _json_output(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify", help="verify one A2A Agent Card")
    verify_parser.add_argument("--input", type=Path, required=True)
    verify_parser.add_argument("--host-ref", required=True)
    verify_parser.add_argument("--audience", required=True)
    verify_parser.add_argument("--workspace", required=True)
    verify_parser.add_argument("--resource", required=True)
    verify_parser.add_argument("--card-ref")
    verify_parser.add_argument(
        "--protocol-version", action="append", dest="protocol_versions", default=None
    )
    verify_parser.add_argument("--required-skill", action="append", dest="required_skills")
    verify_parser.add_argument(
        "--required-security-scheme", action="append", dest="required_security_schemes"
    )
    verify_parser.add_argument(
        "--supported-extension", action="append", dest="supported_extensions"
    )
    evaluate_parser = subparsers.add_parser(
        "evaluate", help="evaluate the deterministic A2A Agent Card corpus"
    )
    evaluate_parser.add_argument("--corpus", type=Path, required=True)
    evaluate_parser.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.command == "verify":
            result = verify_card(
                load_card(args.input),
                expected_host_ref=args.host_ref,
                expected_audience_ref=args.audience,
                expected_workspace_ref=args.workspace,
                expected_resource_ref=args.resource,
                expected_card_ref=args.card_ref,
                expected_protocol_versions=args.protocol_versions,
                required_skill_ids=args.required_skills,
                required_security_scheme_names=args.required_security_schemes,
                supported_extension_uris=args.supported_extensions,
            )
        else:
            result = evaluate_corpus(args.corpus)
        _json_output(result)
        return 0 if result.get("status") == "passed" else 1
    except (A2ACardError, OSError, TypeError, ValueError) as exc:
        print(f"forge-a2a-card: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
