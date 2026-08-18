# Frontier Roadmap

Last reviewed: 2026-08-18.

Forge already has a durable local runtime, policy-gated effects, deterministic replay,
stacked delivery, cross-host packaging, and a strict release gate. The next advantage is not
more skills by volume. It is making agent work portable, attributable, testable, and
reproducible across providers.

## Current position

- The v3.6 runtime slices are local-first and event-history based. Adapters must not become a
  second source of truth.
- The Claude, Codex, and Agent Skills packages are installable and validated. The OpenAI
  project portal shows Forge 3.6.0 as **Approved** in owner-provided evidence dated
  2026-08-18. This confirms project-level review state, not public directory discoverability.
- Forge now has a versioned, reference-only MCP Tasks projection for the final 2026-07-28
  contract. It is not a hosted MCP server, does not implement `server/discover`, and keeps raw
  `inputResponses` outside durable state.
- GitHub-native stacked delivery is a maintained strength. Forge should reconcile native state
  and protect the mutation boundary rather than compete with hosted review UIs.

## Research signals

| Signal | What changed | Forge implication |
| --- | --- | --- |
| MCP interoperability | The 2026-07-28 MCP specification makes the core stateless and moves long-running work into the Tasks extension. | Completed the versioned digest-only adapter profile; keep live server support and MRTR payload handling as explicit future integrations. |
| Agent runtime quality | The OpenAI Agents SDK treats guardrails, handoffs, sessions, usage, and traces as first-class runtime concerns. | Record trajectory and guardrail evidence without persisting prompts, credentials, or provider bodies. |
| Agent identity | NIST's agent standards work and OWASP's agentic guidance make identity, delegated authority, least agency, and non-repudiation central controls. | Bind the principal, delegation chain, policy decision, approval, action, and receipt to one verifiable contract. |
| Supply-chain evidence | SLSA v1.2 defines build provenance around subjects, builder, build definition, external parameters, and resolved dependencies; in-toto recommends DSSE envelopes; GitHub documents offline bundle and trusted-root verification. | Completed a strict Forge DSSE/SLSA contract with Ed25519, local HMAC, explicit trust-root rotation/revocation, and a separate GitHub receipt boundary. Never claim a SLSA build level from a laptop. |
| Delivery topology | GitHub native Stacked Pull Requests are in public preview and GitHub now exposes native issue dependencies. | Import provider state into Forge evidence while keeping the ledger and branch ancestry distinct. |
| Telemetry | OpenTelemetry's GenAI conventions now cover agent, workflow, plan, and tool spans. | Emit stable, privacy-safe correlations and schema versions rather than treating telemetry as runtime state. |
| Skill packaging | Agent Skills uses progressive disclosure and a small required `SKILL.md` contract. | Keep capabilities sharp, validated, and discoverable; do not inflate the catalog to follow directory size. |

## Release lanes

### v3.7 minor: interoperability and evidence

1. [#85 MCP 2026-07-28 Tasks adapter contract](https://github.com/AlisinaDevelo/md-files/issues/85)
   Implemented and locally verified as a versioned, digest-only adapter for `tasks/get`,
   `tasks/update`, and `tasks/cancel`. It covers stateless retries, bounded multi-round input,
   authorization mismatch, expiry, cancellation, handle isolation, and legacy-version rejection.
   A hosted MCP server and MCP Apps UI remain out of scope.
2. [#86 DSSE and SLSA v1.2 artifact attestation verification](https://github.com/AlisinaDevelo/md-files/issues/86)
   Implemented locally: portable DSSE/SLSA statements bind release archives and SBOMs to source,
   build, policy, manifest, and resolved inputs; trust-root rotation/revocation and GitHub's
   host-verified boundary are explicit. Hosted signing and public transparency remain provider
   responsibilities.
3. [#87 trajectory and agentic-security regression harness](https://github.com/AlisinaDevelo/md-files/issues/87)
   Compare digest-only agent trajectories for least agency, approval, scope, replay, leakage,
   unsafe action, cost, latency, and outcome regressions. A live judge remains optional and
   cannot replace deterministic checks.
4. Finish review and merge of the implemented [#65 provenance bridge](https://github.com/AlisinaDevelo/md-files/issues/65)
   and [#66 chaos shrinking](https://github.com/AlisinaDevelo/md-files/issues/66) slices before
   treating the evidence layer as release-complete.

### v4.0 major: authority and connected execution

1. [#88 agent identity and delegated authority](https://github.com/AlisinaDevelo/md-files/issues/88)
   Define versioned principals, parent delegation, audience, scopes, expiry, nonce, revocation,
   and binding to policy, approval, action, runtime, and provenance evidence.
2. [#21 GitHub Agentic Workflows](https://github.com/AlisinaDevelo/md-files/issues/21)
   Move the existing pinned adapter from local admission evidence toward a reviewed external
   control plane without making a workflow lock the canonical Forge history.
3. [#22 adaptive routing](https://github.com/AlisinaDevelo/md-files/issues/22)
   Keep the deterministic filter and replay foundation, then add live activation only after
   quality, cost, failure, approval-burden, and rollback evidence is reviewed.

## Design rules

- Canonical Forge history remains local-first, hash-chained, and replayable.
- Every external protocol is an adapter with a version, capability profile, request identity,
  authorization context, and explicit failure semantics.
- Public claims name the exact evidence boundary: local build, installed replay, provider
  admission, project approval, and public listing are different states.
- Default gates remain offline and bounded. Hosted services, live judges, and provider calls are
  opt-in integration tests, not hidden release dependencies.
- Raw prompts, tool content, credentials, and provider response bodies stay outside durable
  state and public evidence.
- One ledger is the planning source of truth. Branch ancestry, GitHub issue dependencies, and
  runtime history remain separate graphs with explicit reconciliation.

## Deliberate non-goals

Forge should not add a hosted MCP service just to advertise MCP support, copy a directory's
skill count, claim SLSA Build Level 3 without the required builder evidence, or use an opaque LLM
judge as the default release oracle. Each would expand trust or maintenance cost without proving
the requested engineering outcome.

## Re-evaluation triggers

Revisit the roadmap when a real Forge workflow needs a remote authenticated tool, when a host
requires MCP Apps UI, when public-key release verification is available in the target CI
environment, or when a connected control plane can provide durable, auditable authority. Until
then, the local contracts and evidence gates are the product surface.

## Primary sources

- [MCP 2026-07-28 final specification](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [MCP Tasks extension](https://modelcontextprotocol.io/extensions/tasks/overview)
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)
- [OpenAI Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/)
- [Agent Skills specification](https://agentskills.io/specification)
- [NIST AI Agent Standards Initiative](https://www.nist.gov/artificial-intelligence/ai-agent-standards-initiative)
- [OWASP Agentic AI threats and mitigations](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/)
- [SLSA v1.2 provenance](https://slsa.dev/spec/v1.2/provenance)
- [SLSA v1.2 specification](https://slsa.dev/spec/v1.2/)
- [in-toto envelope layer](https://github.com/in-toto/attestation/blob/main/spec/v1/envelope.md)
- [DSSE pre-authentication encoding](https://github.com/secure-systems-lab/dsse/blob/master/envelope.proto)
- [GitHub offline artifact-attestation verification](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline)
- [OpenTelemetry GenAI agent spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md)
- [GitHub Stacked Pull Requests](https://docs.github.com/en/pull-requests/reference/stacked-pull-requests)
