# Forge Receipts

Forge receipts are the evidence contract for orchestration. They are append-only JSONL
events that let a later task sync, policy engine, router, or runtime reconstruct what
happened without treating telemetry as conversation memory.

## Local storage

The bundled standard-library CLI writes to `.forge/receipts.jsonl` by default:

```bash
python3 scripts/forge-receipts.py --file .forge/receipts.jsonl append \
  --event-type run.started --run-id run-2026-08-01 --idempotency-key run-start \
  --attribute goal=release --attribute status=started
python3 scripts/forge-receipts.py --file .forge/receipts.jsonl read --json
python3 scripts/forge-receipts.py --file .forge/receipts.jsonl validate
```

Every event has a schema version, event and run identity, monotonic sequence, RFC3339
timestamp, idempotency key, optional task/agent/model/policy fields, causality, and
structured attributes. The canonical JSON Schema lives at
[`data/receipts.schema.json`](../data/receipts.schema.json).

Retries with the same idempotency key return the existing event and perform zero writes.
The store refuses to append after an incomplete final record. `read` can recover the
valid prefix, while truncation requires the explicit mutating command:

```bash
python3 scripts/forge-receipts.py --file .forge/receipts.jsonl repair
```

## Privacy boundary

Prompts, credentials, tokens, tool arguments, raw results, and content are hashed into a
redaction marker by default. The receipt contains the digest, not the original value.
Do not put secrets in event identifiers or free-form IDs. Content opt-in is available for
local, authorized experiments with `--allow-content`; it is never implicit and does not
override secret-key redaction.

Retention is a storage-owner decision: keep the JSONL file on an encrypted local volume,
rotate it by run or date, and delete it according to the repository's retention policy.
Receipts are evidence, not a backup or a prompt-memory store.

## OTLP export

Export uses OTLP/HTTP JSON with no collector dependency for local operation:

```bash
python3 scripts/forge-receipts.py --file .forge/receipts.jsonl export \
  --endpoint https://otel.example/v1/traces --header Authorization=Bearer:REDACTED
```

Use `--dry-run` to inspect the payload without network access. Forge names its own
`forge.*` attributes and preserves already-approved `gen_ai.*` and `mcp.*` attributes;
the adapter version is pinned in the exporter as `2025.05` so convention changes are
explicit. W3C `traceparent` values become OTLP trace and span identifiers, and
`correlation_id`/`causation_id` remain Forge attributes for task-DAG reconstruction.

The exporter sends spans only. It does not export raw prompts, credentials, tool
arguments, or results.
