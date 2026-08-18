"""Digest-only A2A v1 StreamResponse evidence tests."""

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
FIXTURE = REPO / "tests/fixtures/a2a-stream/v1.jsonl"


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
    assert first["contract_revision"] == "forge-a2a-stream-v1"
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
    assert report["task_id"] is None
    assert report["authority_grant"] is False
    assert report["authentication_boundary"] == "external-reference"
    assert report["checks"]["message_only_closure"] is True
    assert report["checks"]["task_lifecycle"] is False
    assert all(value.startswith("sha256:") for value in report["event_refs"])


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
    assert report["terminal_states"] == ["TASK_STATE_COMPLETED"]
    assert report["checks"]["concurrent_stream_equivalence"] is True
    assert report["checks"]["push_stream_response"] is True


def test_opaque_context_references_cannot_be_urls():
    module = load_module()
    envelope = copy.deepcopy(load_cases()[0]["envelope"])
    envelope["context"]["host_ref"] = "https://provider.example"

    with pytest.raises(module.A2AStreamError, match="URL-shaped reference"):
        module.verify_streams(envelope)


@pytest.mark.parametrize(
    ("case_index", "error"),
    [
        (2, "stream-must-start-with-task-or-message"),
        (3, "concurrent-stream-event-drift"),
        (4, "push-payload-must-match-stream-response"),
        (5, "cannot contain raw provider material"),
    ],
)
def test_threat_cases_fail_closed(case_index, error):
    module = load_module()
    with pytest.raises(module.A2AStreamError, match=error):
        module.verify_streams(load_cases()[case_index]["envelope"])


def test_report_shape_and_root_wrapper_are_json_serializable(tmp_path):
    module = load_module()
    schema = json.loads((REPO / "data/runtime-a2a-stream.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"].endswith("/a2a-stream/v1")
    assert schema["properties"]["authority_grant"] == {"const": False}

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
