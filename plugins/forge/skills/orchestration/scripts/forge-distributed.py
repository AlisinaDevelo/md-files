#!/usr/bin/env python3
"""Etcd-first revision/watch recovery primitives for Forge backend adapters."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

SCHEMA_VERSION = 1
PROVIDER = "etcd"
WATCH_CAPABILITIES = {
    "remote_revisions",
    "watch_delivery",
    "snapshot_recovery",
    "compaction_recovery",
}
REFERENCE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
WATCH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/_-]{0,127}$")


class DistributedRecoveryError(ValueError):
    """Raised when remote observation cannot be safely reconciled."""

    def __init__(self, reason_code: str, message: str, evidence: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.evidence = copy.deepcopy(dict(evidence))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _reference(value: Any, field: str) -> str:
    if not isinstance(value, str) or not REFERENCE_RE.fullmatch(value):
        raise DistributedRecoveryError(
            "invalid_reference",
            f"{field} must be a sha256 reference",
            {"field": field, "value_ref": _digest(str(value))},
        )
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise DistributedRecoveryError(
            "invalid_metadata",
            f"{field} must be a non-empty string of at most 128 characters",
            {"field": field},
        )
    return value


def _watch_id(value: Any, field: str = "watch_id") -> str:
    value = _text(value, field)
    if not WATCH_ID_RE.fullmatch(value):
        raise DistributedRecoveryError("invalid_metadata", f"{field} contains unsupported characters", {"field": field})
    return value


def _positive_revision(value: Any, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if allow_zero else 1):
        raise DistributedRecoveryError("invalid_revision", f"{field} must be a valid revision", {"field": field})
    return value


def _cloud_event(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DistributedRecoveryError("invalid_cloud_event", "cloud_event must be an object", {})
    allowed = {"specversion", "source", "id", "type", "subject", "time", "data_ref", "identity_ref"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DistributedRecoveryError(
            "raw_cloud_event_rejected",
            "cloud_event contains unsupported fields: " + ", ".join(unknown),
            {"unknown_fields": unknown},
        )
    source = _text(value.get("source"), "cloud_event.source")
    event_id = _text(value.get("id"), "cloud_event.id")
    event_type = _text(value.get("type"), "cloud_event.type")
    if any(character.isspace() or ord(character) < 32 for character in source):
        raise DistributedRecoveryError("invalid_cloud_event", "cloud_event.source must be a URI reference", {})
    normalized: dict[str, Any] = {
        "specversion": value.get("specversion", "1.0"),
        "source": source,
        "id": event_id,
        "type": event_type,
    }
    if normalized["specversion"] != "1.0":
        raise DistributedRecoveryError("invalid_cloud_event", "cloud_event.specversion must be 1.0", {})
    if "subject" in value:
        normalized["subject"] = _text(value["subject"], "cloud_event.subject")
    if "time" in value:
        timestamp = _text(value["time"], "cloud_event.time")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DistributedRecoveryError("invalid_cloud_event", "cloud_event.time must be RFC 3339", {}) from exc
        if parsed.tzinfo is None:
            raise DistributedRecoveryError("invalid_cloud_event", "cloud_event.time must include a timezone", {})
        normalized["time"] = timestamp
    if "data_ref" in value:
        normalized["data_ref"] = _reference(value["data_ref"], "cloud_event.data_ref")
    expected_identity = _digest({"source": source, "id": event_id})
    if "identity_ref" in value and value["identity_ref"] != expected_identity:
        raise DistributedRecoveryError("cloud_event_tampered", "cloud event identity reference does not match", {})
    normalized["identity_ref"] = expected_identity
    return normalized


def _notification(value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "watch_id",
        "remote_revision",
        "transaction_ref",
        "event_ref",
        "cloud_event",
    }
    if not isinstance(value, Mapping):
        raise DistributedRecoveryError("invalid_notification", "watch notification must be an object", {})
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DistributedRecoveryError(
            "raw_notification_rejected",
            "watch notification contains unsupported fields: " + ", ".join(unknown),
            {"unknown_fields": unknown},
        )
    if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise DistributedRecoveryError("unsupported_schema", "unsupported watch notification schema", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "watch_id": _watch_id(value.get("watch_id")),
        "remote_revision": _positive_revision(value.get("remote_revision"), "remote_revision"),
        "transaction_ref": _reference(value.get("transaction_ref"), "transaction_ref"),
        "event_ref": _reference(value.get("event_ref"), "event_ref"),
        "cloud_event": _cloud_event(value.get("cloud_event")),
    }


def _cursor(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DistributedRecoveryError("invalid_cursor", "watch cursor must be an object", {})
    allowed = {"schema_version", "watch_id", "remote_revision", "compaction_revision", "cursor_ref"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DistributedRecoveryError(
            "raw_cursor_rejected",
            "watch cursor contains unsupported fields: " + ", ".join(unknown),
            {"unknown_fields": unknown},
        )
    if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise DistributedRecoveryError("unsupported_schema", "unsupported watch cursor schema", {})
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "watch_id": _watch_id(value.get("watch_id")),
        "remote_revision": _positive_revision(value.get("remote_revision"), "remote_revision", allow_zero=True),
        "compaction_revision": _positive_revision(
            value.get("compaction_revision", 0), "compaction_revision", allow_zero=True
        ),
    }
    if normalized["compaction_revision"] > normalized["remote_revision"]:
        raise DistributedRecoveryError(
            "invalid_cursor",
            "cursor compaction revision cannot exceed its remote revision",
            {"cursor_ref": _digest(normalized)},
        )
    expected = _digest(normalized)
    if "cursor_ref" in value and value["cursor_ref"] != expected:
        raise DistributedRecoveryError("cursor_tampered", "watch cursor reference does not match", {})
    normalized["cursor_ref"] = expected
    return normalized


def _snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DistributedRecoveryError("invalid_snapshot", "watch snapshot must be an object", {})
    allowed = {
        "schema_version",
        "watch_id",
        "remote_revision",
        "compaction_revision",
        "state_ref",
        "snapshot_ref",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DistributedRecoveryError(
            "raw_snapshot_rejected",
            "watch snapshot contains unsupported fields: " + ", ".join(unknown),
            {"unknown_fields": unknown},
        )
    if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise DistributedRecoveryError("unsupported_schema", "unsupported watch snapshot schema", {})
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "watch_id": _watch_id(value.get("watch_id")),
        "remote_revision": _positive_revision(value.get("remote_revision"), "remote_revision", allow_zero=True),
        "compaction_revision": _positive_revision(
            value.get("compaction_revision", 0), "compaction_revision", allow_zero=True
        ),
        "state_ref": _reference(value.get("state_ref"), "state_ref"),
    }
    if normalized["compaction_revision"] > normalized["remote_revision"]:
        raise DistributedRecoveryError(
            "invalid_snapshot",
            "snapshot compaction revision cannot exceed its remote revision",
            {"snapshot_ref": _digest(normalized)},
        )
    expected = _digest(normalized)
    if "snapshot_ref" in value and value["snapshot_ref"] != expected:
        raise DistributedRecoveryError("snapshot_tampered", "watch snapshot reference does not match", {})
    normalized["snapshot_ref"] = expected
    return normalized


class RevisionWatchAdapter:
    """Deterministic adapter model for etcd revisions, watches, and compaction."""

    def __init__(self, *, provider: str = PROVIDER, watch_name: str = "forge-runtime") -> None:
        self.provider = _text(provider, "provider")
        watch_name = _text(watch_name, "watch_name")
        self.watch_id = "watch:" + hashlib.sha256(
            _canonical({"provider": self.provider, "watch_name": watch_name}).encode("utf-8")
        ).hexdigest()[:32]
        self.current_revision = 0
        self.compaction_revision = 0
        self._notifications: dict[int, dict[str, Any]] = {}
        self._accepted: dict[int, str] = {}
        self._event_revisions: dict[str, int] = {}
        self._cloud_event_identities: dict[str, str] = {}

    @property
    def capabilities(self) -> set[str]:
        return set(WATCH_CAPABILITIES)

    def cursor(self) -> dict[str, Any]:
        return _cursor(
            {
                "watch_id": self.watch_id,
                "remote_revision": self.current_revision,
                "compaction_revision": self.compaction_revision,
            }
        )

    def publish(
        self,
        *,
        event_ref: str,
        transaction_ref: str,
        cloud_event: Mapping[str, Any],
        remote_revision: int | None = None,
    ) -> dict[str, Any]:
        event_ref = _reference(event_ref, "event_ref")
        transaction_ref = _reference(transaction_ref, "transaction_ref")
        for existing in self._notifications.values():
            if existing["event_ref"] == event_ref:
                if remote_revision is not None and remote_revision != existing["remote_revision"]:
                    raise DistributedRecoveryError(
                        "notification_conflict",
                        "duplicate event reference has a different remote revision",
                        {"event_ref": event_ref},
                    )
                candidate = _notification(
                    {
                        "watch_id": self.watch_id,
                        "remote_revision": existing["remote_revision"],
                        "transaction_ref": transaction_ref,
                        "event_ref": event_ref,
                        "cloud_event": cloud_event,
                    }
                )
                if candidate != existing:
                    raise DistributedRecoveryError(
                        "notification_conflict",
                        "duplicate event reference has different metadata",
                        {"event_ref": event_ref},
                    )
                return copy.deepcopy(existing)
        revision = self.current_revision + 1 if remote_revision is None else _positive_revision(
            remote_revision, "remote_revision"
        )
        if revision <= self.current_revision:
            existing = self._notifications.get(revision)
            if existing is not None and existing["event_ref"] == event_ref:
                return copy.deepcopy(existing)
            raise DistributedRecoveryError(
                "revision_conflict",
                f"remote revision already exists: {revision}",
                {"revision": revision},
            )
        normalized = _notification(
            {
                "watch_id": self.watch_id,
                "remote_revision": revision,
                "transaction_ref": transaction_ref,
                "event_ref": event_ref,
                "cloud_event": cloud_event,
            }
        )
        identity_ref = normalized["cloud_event"]["identity_ref"]
        known_event = self._cloud_event_identities.get(identity_ref)
        if known_event is not None and known_event != event_ref:
            raise DistributedRecoveryError(
                "cloud_event_conflict",
                "CloudEvent source and id identify a different event reference",
                {"identity_ref": identity_ref},
            )
        self.current_revision = revision
        self._notifications[revision] = normalized
        self._event_revisions[event_ref] = revision
        self._cloud_event_identities[identity_ref] = event_ref
        return copy.deepcopy(normalized)

    def notifications(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(self._notifications[key]) for key in sorted(self._notifications)]

    def snapshot(self, *, state_ref: str) -> dict[str, Any]:
        state_ref = _reference(state_ref, "state_ref")
        return _snapshot(
            {
                "watch_id": self.watch_id,
                "remote_revision": self.current_revision,
                "compaction_revision": self.compaction_revision,
                "state_ref": state_ref,
            }
        )

    def compact(self, revision: int) -> dict[str, Any]:
        revision = _positive_revision(revision, "compaction_revision", allow_zero=True)
        if revision > self.current_revision:
            raise DistributedRecoveryError(
                "invalid_compaction",
                "compaction cannot exceed the current revision",
                {"revision": revision, "current_revision": self.current_revision},
            )
        self.compaction_revision = max(self.compaction_revision, revision)
        return {
            "provider": self.provider,
            "compaction_revision": self.compaction_revision,
            "compaction_ref": _digest(
                {"provider": self.provider, "watch_id": self.watch_id, "revision": self.compaction_revision}
            ),
        }

    def observe(self, notifications: Iterable[Mapping[str, Any]], cursor: Mapping[str, Any]) -> dict[str, Any]:
        cursor = _cursor(cursor)
        if cursor["watch_id"] != self.watch_id:
            raise DistributedRecoveryError(
                "watch_identity_mismatch",
                "watch notification belongs to another watch",
                {"expected_watch_ref": _digest(self.watch_id), "actual_watch_ref": _digest(cursor["watch_id"])},
            )
        if cursor["remote_revision"] < self.compaction_revision:
            raise DistributedRecoveryError(
                "compaction_required",
                "watch cursor is older than the compaction boundary",
                {
                    "cursor_ref": cursor["cursor_ref"],
                    "compaction_ref": _digest(
                        {"provider": self.provider, "revision": self.compaction_revision}
                    ),
                },
            )
        normalized = [_notification(item) for item in notifications]
        for item in normalized:
            if item["watch_id"] != self.watch_id:
                raise DistributedRecoveryError(
                    "watch_identity_mismatch",
                    "watch notification belongs to another watch",
                    {"notification_ref": _digest(item)},
                )
        by_revision: dict[int, dict[str, Any]] = {}
        by_event_ref: dict[str, int] = {}
        by_identity: dict[str, str] = {}
        duplicate_count = 0
        for item in normalized:
            revision = item["remote_revision"]
            event_ref = item["event_ref"]
            known_revision = self._event_revisions.get(event_ref)
            if known_revision is not None and known_revision != revision:
                raise DistributedRecoveryError(
                    "notification_conflict",
                    "event reference is bound to a different remote revision",
                    {"event_ref": event_ref},
                )
            previous_revision = by_event_ref.get(event_ref)
            if previous_revision is not None and previous_revision != revision:
                raise DistributedRecoveryError(
                    "notification_conflict",
                    "notification batch binds an event reference to multiple revisions",
                    {"event_ref": event_ref},
                )
            by_event_ref[event_ref] = revision
            identity_ref = item["cloud_event"]["identity_ref"]
            known_event = self._cloud_event_identities.get(identity_ref)
            if known_event is not None and known_event != event_ref:
                raise DistributedRecoveryError(
                    "cloud_event_conflict",
                    "CloudEvent source and id identify a different event reference",
                    {"identity_ref": identity_ref},
                )
            previous_event = by_identity.get(identity_ref)
            if previous_event is not None and previous_event != event_ref:
                raise DistributedRecoveryError(
                    "cloud_event_conflict",
                    "notification batch contains duplicate CloudEvent identity",
                    {"identity_ref": identity_ref},
                )
            by_identity[identity_ref] = event_ref
            existing = by_revision.get(revision)
            if existing is not None:
                if existing != item:
                    raise DistributedRecoveryError(
                        "revision_conflict",
                        f"multiple notifications claim remote revision {revision}",
                        {"revision": revision},
                    )
                duplicate_count += 1
                continue
            by_revision[revision] = item
        accepted: list[dict[str, Any]] = []
        expected = cursor["remote_revision"] + 1
        for revision in sorted(by_revision):
            item = by_revision[revision]
            if revision <= cursor["remote_revision"]:
                if self._accepted.get(revision) == item["event_ref"]:
                    known = self._notifications.get(revision)
                    if known is not None and known != item:
                        raise DistributedRecoveryError(
                            "stale_cursor_conflict",
                            f"notification metadata conflicts with observed revision {revision}",
                            {"revision": revision},
                        )
                    duplicate_count += 1
                    continue
                known = self._notifications.get(revision)
                if known is not None and known["event_ref"] == item["event_ref"]:
                    if known != item:
                        raise DistributedRecoveryError(
                            "stale_cursor_conflict",
                            f"notification metadata conflicts with observed revision {revision}",
                            {"revision": revision},
                        )
                    duplicate_count += 1
                    continue
                raise DistributedRecoveryError(
                    "stale_cursor_conflict",
                    f"notification conflicts with an already observed revision {revision}",
                    {"revision": revision},
                )
            if revision > expected:
                raise DistributedRecoveryError(
                    "cursor_gap",
                    f"watch cursor gap before remote revision {revision}",
                    {"expected_revision": expected, "observed_revision": revision},
                )
            accepted.append(item)
            expected = revision + 1
        for item in accepted:
            revision = item["remote_revision"]
            event_ref = item["event_ref"]
            self._accepted[revision] = event_ref
            self._event_revisions[event_ref] = revision
            self._cloud_event_identities[item["cloud_event"]["identity_ref"]] = event_ref
        next_cursor = _cursor(
            {
                "watch_id": self.watch_id,
                "remote_revision": expected - 1,
                "compaction_revision": self.compaction_revision,
            }
        )
        evidence = {
            "provider": self.provider,
            "watch_id": self.watch_id,
            "from_cursor_ref": cursor["cursor_ref"],
            "to_cursor_ref": next_cursor["cursor_ref"],
            "accepted_event_refs": [item["event_ref"] for item in accepted],
            "duplicate_count": duplicate_count,
        }
        return {
            "status": "advanced",
            "cursor": next_cursor,
            "accepted_revisions": [item["remote_revision"] for item in accepted],
            "duplicate_count": duplicate_count,
            "evidence_digest": _digest(evidence),
        }

    def recover(
        self,
        *,
        snapshot: Mapping[str, Any],
        replay_notifications: Iterable[Mapping[str, Any]],
    ) -> dict[str, Any]:
        snapshot = _snapshot(snapshot)
        if snapshot["watch_id"] != self.watch_id:
            raise DistributedRecoveryError(
                "watch_identity_mismatch",
                "snapshot belongs to another watch",
                {"snapshot_ref": snapshot["snapshot_ref"]},
            )
        if snapshot["remote_revision"] < self.compaction_revision:
            raise DistributedRecoveryError(
                "snapshot_too_old",
                "verified snapshot is older than the compaction boundary",
                {"snapshot_ref": snapshot["snapshot_ref"]},
            )
        result = self.observe(
            replay_notifications,
            {
                "watch_id": self.watch_id,
                "remote_revision": snapshot["remote_revision"],
                "compaction_revision": snapshot["compaction_revision"],
            },
        )
        evidence = {
            "provider": self.provider,
            "snapshot_ref": snapshot["snapshot_ref"],
            "recovery_cursor_ref": result["cursor"]["cursor_ref"],
            "recovery_evidence_digest": result["evidence_digest"],
        }
        return {
            "status": "recovered",
            "snapshot_ref": snapshot["snapshot_ref"],
            "cursor": result["cursor"],
            "evidence_digest": _digest(evidence),
        }
