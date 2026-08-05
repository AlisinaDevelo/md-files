---
id: 0015
title: Research and refresh the durable runtime roadmap
status: done
agent: architect
model: opus
depends_on: [0014]
---

## Goal

Recheck the runtime roadmap against current primary sources and convert the remaining
durability, safety, evidence, interaction, and backend gaps into executable GitHub issues.

## Acceptance criteria

- [x] The live repository, release state, local ledger, and open GitHub roadmap are recorded.
- [x] Primary sources cover durable activities, retries, heartbeats, outbox delivery,
      fencing, checkpoints, human waits, provenance, and merge-queue behavior.
- [x] Issue #54 includes owner fencing and generation requirements, not only lease expiry.
- [x] Issues #55-#58 define checkpoint/migration, execution lineage, human waits, and
      portable backend conformance slices with explicit acceptance criteria.
- [x] Existing runtime, evidence, routing, gh-aw, and stacked-delivery issues are updated
      with the research decisions and remain non-overlapping.
- [x] The next implementation target and release gates are written down for Forge routing.

## Research basis

- [Temporal activity idempotency and heartbeats](https://docs.temporal.io/activity-definition)
- [Temporal retry policy](https://docs.temporal.io/encyclopedia/retry-policies)
- [AWS transactional outbox](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
- [Google Chubby lock sequencers](https://research.google.com/archive/chubby-osdi06.pdf)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)
- [MCP Tasks](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)
- [Dapr durable workflow integrity](https://docs.dapr.io/developing-applications/building-blocks/workflow/workflow-features-concepts/)
- [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/)
- [SLSA v1.2](https://slsa.dev/spec/v1.2/)
- [GitHub artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
- [GitHub merge queues](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)

## Outcome

The current main baseline is the merged #53 transactional effect boundary. The next
implementation target is #54. The proposed durable-runtime sequence is #54 -> #55 -> #56,
then #57 and #58. The gh-aw compiler (#21) and adaptive routing (#22) remain later slices
because they need the runtime evidence and policy contracts first.

No release tag or host reinstall was performed by this research task. The repository still
reports release 3.6.0, while the transactional effect changes remain under Unreleased until
the next implementation slice and full release validation are complete.
