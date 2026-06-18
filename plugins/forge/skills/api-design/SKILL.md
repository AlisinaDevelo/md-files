---
name: api-design
description: >-
  Use when designing or reviewing an API — REST, GraphQL, gRPC, or a library
  interface. Covers consistency, resource modeling, versioning and evolution, error
  contracts, pagination, and idempotency so the interface stays usable and
  changeable after it ships.
---

# API Design

An interface is a contract: cheap to change before release, expensive after. Optimize
for the caller's clarity and your ability to evolve without breaking them.

## Foundational principles

- **Consistency beats cleverness.** Match the conventions already in the codebase —
  naming, casing, pagination, error shape, auth. Predictability is usability.
- **Least surprise.** Correct semantics: GET safe & idempotent, PUT/DELETE idempotent,
  POST for non-idempotent creation. Meaningful status codes. Names that mean what they
  say.
- **Design for evolution.** On a published contract, only additive change: new optional
  fields, never repurposed ones. Version explicitly. In protobuf, never reuse field
  numbers. Breaking changes are deliberate, announced events.

## Errors are first-class

One consistent error envelope across the whole API. Stable machine-readable codes (not
just prose), actionable human messages, and correct status mapping (4xx caller, 5xx
server). Callers spend more code on errors than on success — design for it.

```json
{ "error": { "code": "insufficient_funds", "message": "Balance 12.00 < charge 30.00", "request_id": "req_abc" } }
```

## Collections

Every list endpoint has pagination (cursor for large/changing sets), filtering, sorting,
and a hard limit. No unbounded list endpoints — they're a latency and memory bomb
waiting to happen.

## Mutation safety

Anything touching money or external state takes an idempotency key so retries are safe.
Define what a retry means and make duplicate requests harmless.

## Review checklist

Naming consistency · verb/status semantics · uniform error contract · pagination &
limits on collections · authn/authz on every route · documented input constraints ·
backward compatibility · over/under-fetching · nullability clear · rate-limit & timeout
behavior · examples in docs.

## Anti-patterns

Tunneling everything through POST. Returning 200 with an error body. Booleans that should
be enums (no room to grow). Leaking database columns as the API. Breaking changes shipped
silently. Inconsistent error shapes per endpoint.
