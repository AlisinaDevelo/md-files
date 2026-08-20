# Forge Delivery Ledger

| id | title | status | agent | model | depends_on |
|----|-------|--------|-------|-------|------------|
| 0001 | Research stacked-change practice | done | architect | opus | - |
| 0002 | Build the stack engine | done | devops-engineer | sonnet | 0001 |
| 0003 | Add stack skills and commands | done | tech-lead | sonnet | 0001 |
| 0004 | Integrate docs, catalog, and installers | done | docs-writer | sonnet | 0002, 0003 |
| 0005 | Verify and release Forge 3.0 | done | test-engineer | opus | 0004 |
| 0006 | Design and import body-aware capability IR v2 | done | architect | opus | - |
| 0007 | Render deterministic native and degraded host surfaces | done | devops-engineer | sonnet | 0006 |
| 0008 | Harden adapter contract and conformance tests | done | test-engineer | sonnet | 0007 |
| 0009 | Integrate compiler gates and update capability docs | done | docs-writer | sonnet | 0007, 0008 |
| 0010 | Add semantic capability diff evidence | done | test-engineer | sonnet | 0006 |
| 0011 | Add fail-closed v1-to-v2 migration | done | migration-specialist | sonnet | 0006 |
| 0012 | Derive release surfaces from the capability graph | done | devops-engineer | sonnet | 0007, 0008, 0010, 0011 |
| 0013 | Add local runtime event store and deterministic replay | done | architect | opus | - |
| 0014 | Add transactional runtime outbox and inbox effects | done | concurrency-engineer | sonnet | 0013 |
| 0015 | Research and refresh the durable runtime roadmap | done | architect | opus | 0014 |
| 0016 | Add generation-fenced worker heartbeats and recovery | done | concurrency-engineer | sonnet | 0014, 0015 |
| 0017 | Add checkpointed recovery and fail-closed migrations | done | migration-specialist | sonnet | 0015, 0016 |
| 0018 | Add verifiable execution lineage and receipt integrity | done | observability-specialist | sonnet | 0017 |
| 0019 | Add durable human-input waits, signals, and cancellation | done | orchestration-specialist | sonnet | 0018 |
| 0020 | Define portable backend adapter and conformance contract | done | architect | opus | 0019 |
| 0021 | Add workflow definition versioning and replay compatibility gates | done | architect | opus | 0017, 0020 |
| 0022 | Add signed trace-context and provenance bridge for runtime episodes | done | observability-specialist | sonnet | 0018, 0020 |
| 0023 | Add distributed revision and watch recovery adapter | done | concurrency-engineer | sonnet | 0020 |
| 0024 | Add deterministic chaos and schedule-shrinking harness | done | test-engineer | sonnet | 0019, 0020 |
| 0025 | Add deterministic adaptive-routing policy and offline replay foundation | done | data-engineer | sonnet | 0018, 0019, 0020, 0021 |
| 0026 | Add bounded GitHub Agentic Workflows compiler adapter | done | devops-engineer | sonnet | 0018, 0020, 0024, 0025 |
| 0027 | Bind gh-aw episodes to the durable Forge runtime | done | orchestration-specialist | sonnet | 0018, 0019, 0021, 0026 |
| 0028 | Add a fenced gh-aw GitHub provider worker | done | security-engineer | sonnet | 0027 |
| 0029 | Add reviewed adaptive-routing rollout certificates | done | architect | opus | 0025 |
| 0030 | Add operator-confirmed gh-aw dispatch reconciliation | done | reliability-engineer | sonnet | 0028 |
| 0031 | Gate pinned native gh-aw compilation | done | devops-engineer | sonnet | 0026, 0030 |
| 0032 | Enforce reproducible native gh-aw output | done | devops-engineer | sonnet | 0031 |
| 0033 | Verify native gh-aw supply-chain and job-graph admission | done | security-engineer | sonnet | 0032 |
| 0034 | Add native gh-aw execution admission preflight | done | reliability-engineer | sonnet | 0033 |
| 0035 | Consume native gh-aw admission in the fenced provider | done | security-engineer | sonnet | 0034 |
| 0036 | Add native gh-aw worker handoff contract | done | reliability-engineer | sonnet | 0035 |
| 0037 | Add native gh-aw provider lease supervision | done | reliability-engineer | sonnet | 0036 |
| 0038 | Audit OpenAI universal Agent Plugin compatibility | done | architect | opus | 0037 |
| 0039 | Add strict Codex marketplace contract validation | done | test-engineer | sonnet | 0038 |
| 0040 | Prepare OpenAI skills-only submission evidence | done | docs-writer | sonnet | 0038, 0039 |
| 0041 | Evaluate optional OpenAI MCP and UI extension | done | architect | opus | 0038 |
| 0042 | Add generic constellation integration bundle | done | architect | opus | 0038, 0041 |
| 0043 | Add installed-candidate replay evidence | done | test-engineer | sonnet | 0040 |
| 0044 | Add MCP 2026-07-28 Tasks adapter contract | done | architect | opus | 0019, 0038 |
| 0045 | Add DSSE and SLSA v1.2 artifact attestation verification | done | security-auditor | opus | 0022, 0033 |
| 0046 | Add trajectory and agentic-security regression harness | done | test-engineer | sonnet | 0024, 0025 |
| 0047 | Add agent identity and delegated authority contract | done | architect | opus | 0018, 0022, 0025 |
| 0048 | Add host-authenticated admission evidence for connected effects | done | security-engineer | standard | 0047 |
| 0049 | Validate signed A2A Agent Cards as bounded delegation evidence | done | security-engineer | standard | 0048 |
| 0050 | Add bounded A2A task handoff and lifecycle evidence | done | interoperability-engineer | standard | 0049, 0047, 0048 |
| 0051 | Add A2A StreamResponse evidence and concurrent-stream checks | done | interoperability-engineer | sonnet | 0020, 0021 |
| 0052 | Admit gh-aw sandbox runtime profiles and MCP Gateway configuration | done | security-engineer | standard | mainline #106 |
| 0053 | Enforce MCP Tasks per-request capability admission | done | interoperability-engineer | standard | 0044 |
