"""Digest-only A2A 1.0 StreamResponse evidence tests."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/orchestration/scripts/forge-a2a-stream.py"
WRAPPER = REPO / "scripts/forge-a2a-stream.py"
FIXTURE = REPO / "tests/fixtures/a2a-stream/v2.jsonl"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_a2a_stream", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_corpus_is_deterministic_and_covers_message_task_and_threat_paths():
    module = load_module()
    first = module.evaluate_corpus(FIXTURE)
    second = module.evaluate_corpus(FIXTURE)

    assert first == second
    assert first["status"] == "passed"
    assert first["contract_revision"] == "forge-a2a-stream-v2"
    assert first["case_count"] == 6
    assert first["threat_cases"] == 4
    assert {case["case_id"] for case in first["cases"]} == {
        "valid-message-only",
        "valid-task-concurrent",
        "reject-first-status",
        "reject-concurrent-drift",
        "reject-push-kind",
        "reject-raw-content",
    }


def test_message_only_report_closes_without_task_authority():
    module = load_module()
    report = module.verify_streams(load_cases()[0]["envelope"])

    assert report["mode"] == "message"
    assert report["stream_count"] == 1
    assert report["terminal_states"] == []
    assert report["interrupted_states"] == []
    assert report["task_id"] is None
    assert report["authority_grant"] is False
    assert report["authentication_boundary"] == "external-reference"
    assert report["checks"]["message_only_closure"] is True
    assert report["checks"]["transport_closure"] is True
    assert report["checks"]["task_lifecycle"] is False
    assert all(value.startswith("sha256:") for value in report["event_refs"])
    assert all(value.startswith("sha256:") for value in report["response_refs"])


def test_concurrent_task_report_requires_equivalent_streams_and_push_refs():
    module = load_module()
    report = module.verify_streams(load_cases()[1]["envelope"])

    assert report["mode"] == "task"
    assert report["stream_count"] == 2
    assert report["task_stream_count"] == 2
    assert report["concurrent_stream_count"] == 2
    assert report["event_count"] == 4
    assert len(report["stream_refs"]) == 2
    assert len(report["push_refs"]) == 1
    assert len(report["response_refs"]) == 4
    assert report["terminal_states"] == ["TASK_STATE_COMPLETED"]
    assert report["interrupted_states"] == []
    assert report["checks"]["concurrent_stream_equivalence"] is True
    assert report["checks"]["push_stream_response"] is True


def test_concurrent_streams_allow_distinct_delivery_metadata():
    module = load_module()
    envelope = copy.deepcopy(load_cases()[1]["envelope"])
    for index, event in enumerate(envelope["streams"][1]["events"], start=1):
        event["event_id"] = f"event:mirror-{index}"
        event["observed_at"] = f"2026-08-18T10:01:0{index - 1}Z"

    report = module.verify_streams(envelope)

    assert report["status"] == "passed"
    assert report["checks"]["concurrent_stream_equivalence"] is True


def test_interrupted_state_can_close_the_observed_stream():
    module = load_module()
    envelope = copy.deepcopy(load_cases()[1]["envelope"])
    stream = envelope["streams"][0]
    stream["events"] = stream["events"][:2]
    stream["events"][-1]["task_state"] = "TASK_STATE_INPUT_REQUIRED"
    envelope["streams"] = [stream]
    envelope.pop("push")

    report = module.verify_streams(envelope)

    assert report["terminal_states"] == []
    assert report["interrupted_states"] == ["TASK_STATE_INPUT_REQUIRED"]
    assert report["concurrent_stream_count"] == 0
    assert report["checks"]["interrupted_closure"] is True


def test_interrupted_state_can_resume_before_terminal_closure():
    module = load_module()
    envelope = copy.deepcopy(load_cases()[1]["envelope"])
    stream = envelope["streams"][0]
    task, working, _, completed = stream["events"]
    auth_required = copy.deepcopy(working)
    auth_required["event_id"] = "event:auth-required"
    auth_required["task_state"] = "TASK_STATE_AUTH_REQUIRED"
    resumed = copy.deepcopy(working)
    resumed["event_id"] = "event:resumed"
    resumed["sequence"] = 3
    resumed["observed_at"] = "2026-08-18T10:00:02Z"
    stream["events"] = [task, auth_required, resumed, completed]
    envelope["streams"] = [stream]
    envelope.pop("push")

    report = module.verify_streams(envelope)

    assert report["terminal_states"] == ["TASK_STATE_COMPLETED"]
    assert report["interrupted_states"] == []


def test_opaque_context_references_cannot_be_urls():
    module = load_module()
    envelope = copy.deepcopy(load_cases()[0]["envelope"])
    envelope["context"]["host_ref"] = "https://provider.example"

    with pytest.raises(module.A2AStreamError, match="URL-shaped reference"):
        module.verify_streams(envelope)


def test_time_regression_reports_the_event_location():
    module = load_module()
    envelope = copy.deepcopy(load_cases()[1]["envelope"])
    envelope["streams"][0]["events"][1]["observed_at"] = "2026-08-18T09:59:59Z"

    with pytest.raises(
        module.A2AStreamError,
        match=r"stream-time-regression:stream-1\.events\[2\]\.observed_at",
    ):
        module.verify_streams(envelope)


@pytest.mark.parametrize(
    ("case_index", "error"),
    [
        (2, "stream-must-start-with-task-or-message"),
        (3, "concurrent-stream-response-drift"),
        (4, "push-payload-must-match-stream-response"),
        (5, "cannot contain raw provider material"),
    ],
)
def test_threat_cases_fail_closed(case_index, error):
    module = load_module()
    with pytest.raises(module.A2AStreamError, match=error):
        module.verify_streams(load_cases()[case_index]["envelope"])


def test_pre_v1_kind_and_final_fields_fail_closed():
    module = load_module()
    envelope = copy.deepcopy(load_cases()[0]["envelope"])
    event = envelope["streams"][0]["events"][0]
    event["kind"] = event.pop("response_member")
    event["final"] = True

    with pytest.raises(
        module.A2AStreamError,
        match=r"unknown-stream-1\.event-1-field:final,kind",
    ):
        module.verify_streams(envelope)


def test_open_transport_evidence_fails_closed():
    module = load_module()
    envelope = copy.deepcopy(load_cases()[0]["envelope"])
    envelope["streams"][0]["closed"] = False

    with pytest.raises(module.A2AStreamError, match="stream-transport-closure-required"):
        module.verify_streams(envelope)


def test_report_shape_and_root_wrapper_are_json_serializable(tmp_path):
    module = load_module()
    schema = json.loads((REPO / "data/runtime-a2a-stream.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"].endswith("/a2a-stream/v2")
    assert schema["properties"]["authority_grant"] == {"const": False}
    assert "response_refs" in schema["required"]
    assert "interrupted_states" in schema["required"]
    assert schema["$defs"]["opaque"]["not"] == {"pattern": "://"}

    envelope = copy.deepcopy(load_cases()[0]["envelope"])
    input_path = tmp_path / "message.json"
    input_path.write_text(json.dumps(envelope), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(WRAPPER), "verify", "--input", str(input_path), "--json"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    assert rendered == module.verify_streams(envelope)
