"""Tests for the bounded A2A task handoff verifier."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-a2a-task.py"
CORPUS = REPO / "tests/fixtures/a2a-task/v1.jsonl"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_a2a_task_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def corpus_cases() -> dict[str, dict]:
    return {
        case["case_id"]: case
        for case in (
            json.loads(line)
            for line in CORPUS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def envelope(case_id: str = "valid-auth-interruption") -> dict:
    return copy.deepcopy(corpus_cases()[case_id]["envelope"])


def test_corpus_is_deterministic_and_covers_threats():
    module = load_module()
    first = module.evaluate_corpus(CORPUS)
    second = module.evaluate_corpus(CORPUS)

    assert first == second
    assert first["status"] == "passed"
    assert first["case_count"] == 8
    assert first["threat_cases"] == 5


def test_report_is_digest_only_and_binds_interruption():
    module = load_module()
    report = module.verify_task(envelope())

    assert report["status"] == "passed"
    assert report["event_count"] == 5
    assert report["message_count"] == 1
    assert report["artifact_ref_count"] == 1
    assert report["interrupted_states"] == ["TASK_STATE_AUTH_REQUIRED"]
    assert report["terminal_state"] == "TASK_STATE_COMPLETED"
    assert report["authentication_boundary"] == "external-reference"
    assert report["authority_grant"] is False
    assert "must not persist" not in json.dumps(report)


def test_schema_is_strict_and_matches_contract():
    module = load_module()
    schema = json.loads((REPO / "data/runtime-a2a-task.schema.json").read_text(encoding="utf-8"))

    assert schema["properties"]["contract_revision"]["const"] == module.CONTRACT_REVISION
    assert schema["properties"]["authority_grant"]["const"] is False
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    ("case_id", "error"),
    [
        ("reject-terminal-reopen", "event-after-terminal-state"),
        ("reject-sequence-gap", "event-sequence-gap"),
        ("reject-message-drift", "message-id-content-drift"),
        ("reject-private-push", "unsafe-push.url"),
        ("reject-raw-message-body", "raw provider material"),
    ],
)
def test_threat_cases_fail_closed(case_id: str, error: str):
    module = load_module()

    with pytest.raises(module.A2ATaskError, match=error):
        module.verify_task(envelope(case_id))


def test_duplicate_cancel_is_idempotent():
    module = load_module()
    report = module.verify_task(envelope("valid-cancel-retry"))

    assert report["terminal_state"] == "TASK_STATE_CANCELED"
    assert report["event_count"] == 4
    assert report["idempotency_key_count"] == 3


def test_stream_requires_contiguous_positions_and_terminal_marker():
    module = load_module()
    value = envelope()
    for position, event in enumerate(value["task"]["events"]):
        event.update(
            {
                "stream_id": "stream:a2a-auth",
                "stream_position": position,
                "stream_first": position == 0,
                "stream_terminal": position == len(value["task"]["events"]) - 1,
            }
        )

    report = module.verify_task(value)
    assert len(report["stream_refs"]) == 1

    value["task"]["events"][2]["stream_position"] = 4
    with pytest.raises(module.A2ATaskError, match="stream-position-gap"):
        module.verify_task(value)


def test_push_rejects_query_credentials_and_accepts_reference_only_auth():
    module = load_module()
    value = envelope("valid-secure-push")
    value["push"]["url"] = "https://hooks.example.test/a2a?token=secret"

    with pytest.raises(module.A2ATaskError, match="query and fragment"):
        module.verify_task(value)

    value["push"]["url"] = "https://hooks.example.test/a2a"
    value["push"]["authentication_ref"] = "sha256:" + "7" * 64
    report = module.verify_task(value)
    assert report["push_ref"].startswith("sha256:")


def test_context_and_protocol_are_required():
    module = load_module()
    value = envelope()
    del value["context"]["lease_ref"]
    with pytest.raises(module.A2ATaskError, match="missing-context-fields"):
        module.verify_task(value)

    value = envelope()
    value["protocol_version"] = "0.3"
    with pytest.raises(module.A2ATaskError, match="unsupported-protocol-version"):
        module.verify_task(value)


def test_unknown_event_fields_cannot_smuggle_provider_payloads():
    module = load_module()
    value = envelope()
    value["task"]["events"][0]["provider_response"] = {"body": "private"}

    with pytest.raises(module.A2ATaskError, match="raw provider material"):
        module.verify_task(value)
