#!/usr/bin/env python3
"""Normalize the Forge admission policy for GitHub Agentic Workflows egress."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
REVISION = "forge-gh-aw-firewall-v1"
SCHEMA = "https://github.com/AlisinaDevelo/md-files/schema/runtime/gh-aw-firewall/v1"
KNOWN_ECOSYSTEMS = frozenset(
    {
        "defaults",
        "github",
        "local",
        "dev-tools",
        "default-safe-outputs",
        "containers",
        "linux-distros",
        "playwright",
        "chrome",
        "fonts",
        "terraform",
        "bazel",
        "clojure",
        "dart",
        "deno",
        "dotnet",
        "elixir",
        "go",
        "haskell",
        "java",
        "julia",
        "kotlin",
        "latex",
        "lean",
        "lua",
        "node",
        "node-cdns",
        "ocaml",
        "perl",
        "php",
        "powershell",
        "python",
        "python-native",
        "r",
        "ruby",
        "rust",
        "scala",
        "swift",
        "zig",
    }
)
LOG_LEVELS = frozenset({"debug", "info", "warn", "error"})
FIREWALL_MODES = frozenset({"awf", "disabled"})
INTEGRITY_THRESHOLDS = frozenset({"strict", "standard"})
UNTRUSTED_CONTENT_ACTIONS = frozenset({"redact", "reject"})
DOMAIN_RE = re.compile(
    r"^(?:\*\.)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)
URL_PATH_RE = re.compile(r"^/[A-Za-z0-9._~:/*-]+$")
EXPRESSION_RE = re.compile(r"\$\{\{|\}\}|\$\(|\$[A-Za-z_][A-Za-z0-9_]*")
CREDENTIAL_RE = re.compile(
    r"(?:github_pat_|gh[opusr]_|bearer\s+|-----begin)", re.IGNORECASE
)


class FirewallPolicyError(ValueError):
    """Raised when an AWF policy cannot be admitted safely."""


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
        raise FirewallPolicyError(f"policy is not canonical JSON: {exc}") from exc


def policy_digest(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _unknown(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FirewallPolicyError(f"unknown {label} field(s): {', '.join(unknown)}")


def _text(value: Any, label: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or value != value.strip():
        raise FirewallPolicyError(f"{label} must be bounded literal text")
    if EXPRESSION_RE.search(value) or CREDENTIAL_RE.search(value):
        raise FirewallPolicyError(f"{label} contains an expression or credential")
    return value


def _list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise FirewallPolicyError(f"{label} must be a list of non-empty strings")
    if len(value) > 100:
        raise FirewallPolicyError(f"{label} contains too many entries")
    return list(value)


def _host(value: str, label: str) -> str:
    host = value.lower()
    if host.startswith("*."):
        host = host.removeprefix("*.")
    if "*" in host or "." not in host or not DOMAIN_RE.fullmatch(value.lower()):
        raise FirewallPolicyError(f"{label} is not a safe domain pattern")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise FirewallPolicyError(f"{label} must not be an IP address; use the local ecosystem")


def _port(parsed: Any, label: str) -> int | None:
    try:
        return parsed.port
    except ValueError as exc:
        raise FirewallPolicyError(f"{label} has an invalid port") from exc


def _domain(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise FirewallPolicyError(f"{label} must be a literal domain or ecosystem")
    if EXPRESSION_RE.search(value) or CREDENTIAL_RE.search(value) or any(char.isspace() for char in value):
        raise FirewallPolicyError(f"{label} contains an expression, credential, or whitespace")
    lowered = value.lower()
    if lowered.startswith("http://"):
        raise FirewallPolicyError(f"{label} must not use insecure http://")
    if lowered.startswith("https://"):
        parsed = urlsplit(lowered)
        if parsed.username or parsed.password or _port(parsed, label) or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise FirewallPolicyError(f"{label} has an ambiguous URL form")
        if not parsed.hostname:
            raise FirewallPolicyError(f"{label} has no hostname")
        lowered = "https://" + _host(parsed.hostname, label)
        if parsed.hostname.startswith("*."):
            lowered = "https://*." + _host(parsed.hostname[2:], label)
        return lowered
    if "://" in lowered or "@" in lowered or ":" in lowered:
        raise FirewallPolicyError(f"{label} has an unsupported URL or credential form")
    if lowered in KNOWN_ECOSYSTEMS:
        return lowered
    if not DOMAIN_RE.fullmatch(lowered):
        raise FirewallPolicyError(f"{label} is not a known ecosystem or safe domain")
    return "*." + _host(lowered, label) if lowered.startswith("*.") else _host(lowered, label)


def _url_pattern(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise FirewallPolicyError(f"{label} must be a literal HTTPS URL pattern")
    if EXPRESSION_RE.search(value) or CREDENTIAL_RE.search(value):
        raise FirewallPolicyError(f"{label} contains an expression or credential")
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or parsed.username or parsed.password or _port(parsed, label):
        raise FirewallPolicyError(f"{label} must use an unambiguous HTTPS URL")
    if parsed.query or parsed.fragment or not parsed.hostname:
        raise FirewallPolicyError(f"{label} must not contain a query, fragment, or missing host")
    wildcard = parsed.hostname.startswith("*.")
    host = _host(parsed.hostname, label)
    if wildcard:
        host = "*." + host
    path = parsed.path
    if not URL_PATH_RE.fullmatch(path) or "**" in path or "/../" in f"{path}/":
        raise FirewallPolicyError(f"{label} contains an unsafe path pattern")
    return f"https://{host}{path}"


def normalize_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FirewallPolicyError("firewall_policy must be an object")
    _unknown(
        value,
        {
            "schema_version",
            "contract_revision",
            "firewall_mode",
            "allowed_domains",
            "blocked_domains",
            "allowed_url_patterns",
            "log_level",
            "ssl_bump",
            "content_integrity_threshold",
            "untrusted_content",
            "sandbox_mode",
            "disable_justification",
        },
        "firewall_policy",
    )
    if value.get("schema_version") != SCHEMA_VERSION:
        raise FirewallPolicyError("firewall_policy has an unsupported schema version")
    if value.get("contract_revision") != REVISION:
        raise FirewallPolicyError("firewall_policy has an unsupported contract revision")
    firewall_mode = value.get("firewall_mode")
    sandbox_mode = value.get("sandbox_mode")
    if firewall_mode not in FIREWALL_MODES or sandbox_mode not in FIREWALL_MODES:
        raise FirewallPolicyError("firewall_mode and sandbox_mode must be awf or disabled")
    if firewall_mode != sandbox_mode:
        raise FirewallPolicyError("firewall_mode and sandbox_mode must agree")
    allowed = sorted({_domain(item, "allowed_domains") for item in _list(value.get("allowed_domains"), "allowed_domains")})
    blocked = sorted({_domain(item, "blocked_domains") for item in _list(value.get("blocked_domains", []), "blocked_domains")})
    overlap = sorted(set(allowed) & set(blocked))
    if overlap:
        raise FirewallPolicyError("a domain cannot be both allowed and blocked: " + ", ".join(overlap))
    patterns = sorted({_url_pattern(item, "allowed_url_patterns") for item in _list(value.get("allowed_url_patterns", []), "allowed_url_patterns")})
    log_level = value.get("log_level")
    if log_level not in LOG_LEVELS:
        raise FirewallPolicyError("log_level must be debug, info, warn, or error")
    ssl_bump = value.get("ssl_bump")
    if not isinstance(ssl_bump, bool):
        raise FirewallPolicyError("ssl_bump must be a boolean")
    if patterns and not ssl_bump:
        raise FirewallPolicyError("allowed_url_patterns require ssl_bump")
    threshold = value.get("content_integrity_threshold")
    if threshold not in INTEGRITY_THRESHOLDS:
        raise FirewallPolicyError("content_integrity_threshold must be strict or standard")
    untrusted_content = value.get("untrusted_content")
    if untrusted_content not in UNTRUSTED_CONTENT_ACTIONS:
        raise FirewallPolicyError("untrusted_content must redact or reject untrusted content")
    justification = value.get("disable_justification")
    if firewall_mode == "disabled":
        if not isinstance(justification, str) or len(justification.strip()) < 20:
            raise FirewallPolicyError("disabled firewall requires a literal justification of at least 20 characters")
        _text(justification, "disable_justification", maximum=512)
        if ssl_bump or patterns:
            raise FirewallPolicyError("disabled firewall cannot carry URL filtering")
    elif justification is not None:
        raise FirewallPolicyError("disable_justification is only valid when the firewall is disabled")
    normalized = {
        "$schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "contract_revision": REVISION,
        "firewall": {
            "mode": firewall_mode,
            "log_level": log_level,
            "ssl_bump": ssl_bump,
            "allow_urls": patterns,
        },
        "network": {"allowed": allowed, "blocked": blocked},
        "content_integrity": {
            "threshold": threshold,
            "untrusted_content": untrusted_content,
        },
        "sandbox": {
            "agent": "awf" if sandbox_mode == "awf" else False,
            "mode": sandbox_mode,
        },
    }
    if firewall_mode == "disabled":
        normalized["sandbox"]["justification"] = justification.strip()
    return normalized
