"""Behavioral and recovery tests for Forge run receipts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/forge/skills/observability/scripts/forge-receipts.py"
FIXTURE = REPO / "tests/fixtures/receipts/v1.jsonl"


def load_module():
    spec = importlib.util.spec_from_file_location("forge_receipts", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def event(module, **kwargs):
    return module.make_event(
        kwargs.pop("event_type", "task.started"),
        kwargs.pop("run_id", "run-1"),
        attributes=kwargs.pop("attributes", {}),
        **kwargs,
    )


def test_append_is_monotonic_and_idempotent(tmp_path):
    module = load_module()
    store = module.ReceiptStore(tmp_path / "receipts.jsonl")
    first = event(module, idempotency_key="same-key")
    stored = store.append(first)
    retry = store.append(event(module, idempotency_key="same-key"))
    second = store.append(event(module, idempotency_key="second-key"))

    assert retry == stored
    assert stored["sequence"] == 1
    assert second["sequence"] == 2
    assert len(store.read()[0]) == 2


def test_sensitive_values_are_hashed_not_stored(tmp_path):
    module = load_module()
    store = module.ReceiptStore(tmp_path / "receipts.jsonl")
    stored = store.append(
        event(
            module,
            attributes={
                "prompt": "do not persist this",
                "api_token": "secret-token",
                "status": "ok",
            },
        )
    )

    text = (tmp_path / "receipts.jsonl").read_text()
    assert "do not persist this" not in text
    assert "secret-token" not in text
    assert stored["attributes"]["status"] == "ok"
    assert stored["attributes"]["prompt"]["redacted"] is True
    assert "sha256" in stored["attributes"]["api_token"]


def test_traceparent_and_otlp_preserve_causality():
    module = load_module()
    stored = event(
        module,
        traceparent="00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
        correlation_id="run-1",
        causation_id="event-parent",
        model_route={"gen_ai.system": "openai", "model": "reasoning"},
        attributes={"status": "ok"},
    )
    stored["sequence"] = 1
    span = module.event_to_span(stored)
    payload = module.otlp_payload([stored])

    assert span["traceId"] == "0123456789abcdef0123456789abcdef"
    assert span["spanId"] == stored["trace"]["span_id"]
    assert span["parentSpanId"] == "0123456789abcdef"
    assert any(item["key"] == "gen_ai.system" for item in span["attributes"])
    assert payload["resourceSpans"][0]["scopeSpans"][0]["spans"] == [span]


def test_truncated_final_record_is_readable_and_explicitly_repairable(tmp_path):
    module = load_module()
    target = tmp_path / "receipts.jsonl"
    target.write_bytes(FIXTURE.read_bytes() + b'{"schema_version":1,"event_type":"task.started"')
    store = module.ReceiptStore(target)

    events, truncated = store.read()
    assert len(events) == 2
    assert truncated is True
    with pytest.raises(module.ReceiptError, match="incomplete"):
        store.append(event(module))
    assert store.repair_truncated_final() is True
    assert store.read()[1] is False


def test_fixture_is_backward_readable(tmp_path):
    module = load_module()
    target = tmp_path / "receipts.jsonl"
    target.write_bytes(FIXTURE.read_bytes())
    events, truncated = module.ReceiptStore(target).read()

    assert truncated is False
    assert [item["sequence"] for item in events] == [1, 2]
    assert events[1]["trace"]["causation_id"] == "event-1"


def test_cli_dry_run_does_not_send_or_write(tmp_path, monkeypatch):
    module = load_module()
    store = module.ReceiptStore(tmp_path / "receipts.jsonl")
    store.append(event(module, attributes={"status": "ok"}))
    before = (tmp_path / "receipts.jsonl").read_bytes()
    monkeypatch.setattr(module.request, "urlopen", lambda *_args, **_kwargs: pytest.fail("network call"))
    payload = module.otlp_payload(store.read()[0])

    assert payload["resourceSpans"]
    assert (tmp_path / "receipts.jsonl").read_bytes() == before


def test_invalid_schema_version_is_rejected():
    module = load_module()
    invalid = json.loads(FIXTURE.read_text().splitlines()[0])
    invalid["schema_version"] = 2
    with pytest.raises(module.ReceiptError, match="schema_version"):
        module.validate_event(invalid)
