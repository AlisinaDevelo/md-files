---
name: observability
description: >-
  Use when adding logging, metrics, or tracing to code, or designing how a service
  is monitored. Covers the three pillars, structured logging, what to measure (RED/
  USE), useful alerts, and the SLO mindset — so failures are debuggable after the
  fact.
---

# Observability

Observability is the ability to understand a system's internal state from its outputs.
You instrument so that when something breaks at 3 a.m., the signals already exist to
explain it — you can't add a log line after the incident.

## The three pillars

- **Logs** — discrete events with context. Use for the "what exactly happened" of a
  specific request.
- **Metrics** — aggregated numbers over time. Use for trends, rates, and alerting.
  Cheap to store, fast to query.
- **Traces** — the path of one request across services. Use to find *where* latency or
  errors originate in a distributed call.

Connect them: put a trace/request ID on every log line and metric exemplar so you can
pivot from a metric spike to the traces to the logs.

## Structured logging

Log structured key–value pairs (JSON), not interpolated prose — so logs are queryable.
Include request ID, user/tenant (non-PII), operation, duration, and outcome. Log at the
right level: ERROR = needs attention, WARN = unusual but handled, INFO = significant
state change, DEBUG = diagnostic detail. **Never log secrets, tokens, or PII.**

```text
log.info("payment.captured", order_id=o.id, amount=o.total, request_id=ctx.rid, latency_ms=dt)
```

## What to measure

- **RED** (request-driven services): **R**ate, **E**rrors, **D**uration per endpoint.
- **USE** (resources): **U**tilization, **S**aturation, **E**rrors per resource.
- Business signals that matter (signups, checkouts) alongside system signals.

Track distributions (p50/p95/p99), not just averages — the tail is where users feel pain.

## Alerting

Alert on **symptoms users feel** (error rate, latency SLO breach, saturation), not every
internal cause. Every alert must be actionable and point toward a runbook — a pager that
cries wolf gets ignored. Define SLOs (e.g. 99.9% of requests < 300ms) and alert on burn
rate against the error budget.

## Instrumenting new code

For each critical path: emit a metric (rate/error/duration), a span if it crosses a
service boundary, and structured logs at the decision points and failures. Make the
failure path as observable as the success path — that's the part you'll need most.

## Forge receipts

For orchestration evidence, use the bundled `scripts/forge-receipts.py` store rather than
free-form logs. It writes append-only, schema-versioned JSONL with monotonic sequences,
idempotency keys, causation, W3C trace context, and privacy-safe attributes. Read the
[receipt guide](../../../docs/receipts.md) before enabling OTLP export.

## Offline lineage verification

For durable runtime evidence, export from the canonical SQLite history with
`scripts/forge-lineage.py`. The verifier binds scheduling events, effect attempts, lease
generations, adapter revisions, provider references, retries, dead letters, and optional
policy receipts into a deterministic manifest. It is offline-only and fails closed on a
missing parent, digest mismatch, conflicting provider reference, or stale generation:

```bash
python3 scripts/forge-lineage.py export \
  --db .forge/runtime.sqlite3 --receipts .forge/receipts.jsonl \
  --output .forge/lineage.json
python3 scripts/forge-lineage.py verify --manifest .forge/lineage.json
```

Lineage is evidence, not a replacement for canonical runtime history and not an exactly-once
claim. Keep provider bodies, prompts, credentials, and tool content out of the manifest.
