# OpenAI Agent Plugins Compatibility

Last reviewed: 2026-10-02

Forge is a skills-only OpenAI Agent Plugin candidate. Its local and repository Codex
marketplace installs are supported today. Owner-provided OpenAI project portal evidence
dated 2026-08-18 shows Forge 3.6.0 as **Approved**. This confirms project-level review
state; public listing and universal directory availability remain unverified.

## Research Findings

OpenAI's current plugin model treats a plugin as a package people discover, install, share,
and publish in ChatGPT and Codex. A package can contain:

- Skills for reusable instructions, resources, and workflows.
- An MCP server for authenticated external tools and structured results.
- Optional UI resources returned by an MCP server.

Skills-only is a supported shape. Forge does not need an MCP server or custom UI merely to
be a valid plugin. Hooks and other capabilities may remain surface-specific, so the Claude
plugin and the Codex plugin are intentionally not identical archives.

The package guide recommends root `plugin.json` using Agent Plugins 1.0 and permits a
skills-only bundle. Portable components use fixed `skills/` and optional `mcp.json` paths.
OpenAI settings live in `extensions.com.openai`; a present inline object replaces the
entire `.codex-plugin/plugin.json` overlay, while an absent object uses that overlay as
a compatibility fallback. Root identity remains canonical in both cases.
Local and repository marketplaces remain separate authoring and team-distribution sources,
not evidence of universal directory publication.

The follow-up evaluation is complete: Forge has no current workflow that requires a remote
MCP server or visual interaction. The evidence-backed deferral and reopen criteria are in
[`openai-mcp-ui-decision.md`](openai-mcp-ui-decision.md).

## Current Contract

The current OpenAI contract requires or recognizes the following surfaces:

| Surface | Forge state | Evidence |
|---|---|---|
| Portable `plugin.json` | Present | Agent Plugins 1.0 identity and `extensions.com.openai` |
| `.codex-plugin/plugin.json` | Retained | Compatibility for older clients |
| Stable name and strict semver | Passing | `forge`, `3.10.0` |
| Publisher identity and HTTPS metadata | Present | author, homepage, repository, policy URLs |
| Skills directory | Present | `skills: ./skills/` and 25 validated skills |
| Interface metadata | Present | display name, descriptions, category, prompts, capabilities |
| Directory assets | Present | icon, light logo, dark logo |
| Skills-only submission ZIP | Passing | `forge-3.10.0-openai.zip`, root manifest and skills tree |
| UI screenshots | Intentionally absent | Forge has no custom UI; OpenAI says screenshots are for UI plugins |
| Codex repository marketplace | Present | `.agents/plugins/marketplace.json` |
| MCP server and app template | Not included | Not needed for the current skills-only workflow |

The Codex marketplace contract is separate from public directory publication. Its entries
must declare a local source path, installation policy, authentication timing, and category.
Forge now validates those fields in the local gate and the hosted CI job.

## Portable Release Profile

Run `python3 scripts/compile_agent_plugin.py --write` after editing compatibility metadata.
The generated root manifest is checked by structure validation and the release builder.
The OpenAI ZIP and native host projections include it; older manifests remain packaged.
Validation is offline and does not fetch a remote schema when loading a package.

Forge's validator is a strict release profile, not a general-purpose implementation of
every Agent Plugins component. It requires release metadata, semver, listing fields,
square icons, a subtitle of at most 30 characters, and 2:1 brand-color contrast against
white. Unknown portable core fields are rejected by this profile. Unknown extension
objects remain uninterpreted. The skills-only ZIP deliberately excludes MCP, app, and
hook surfaces; adding those requires a separately tested publication decision.
Every retained compatibility manifest is validated independently for older clients;
that release check does not change the inline settings precedence.

The local tests cover canonical identity, complete inline replacement, overlay fallback,
malformed and duplicate-key JSON, fixed skill discovery, archive containment, and
deterministic installation/replay. These checks establish package and contract behavior,
not model quality, live connected execution, or public directory availability.

## Public Submission Boundary

The OpenAI submission portal is an external publication workflow. Creating or submitting a
draft requires Apps Management write access and a verified developer or business identity;
the form also requires listing and policy metadata, starter prompts, release notes, country
availability, and test evidence. The current submission guidance asks for five positive and
three negative test cases. A repository marketplace passing does not imply public approval.

The project portal review state is now recorded as **Approved** from owner-provided evidence
dated 2026-08-18. Forge must still distinguish that project-level state from public directory
listing and universal availability, which this repository cannot independently verify.

The reproducible owner-review packet is documented in
[`openai-agent-plugin-submission.md`](openai-agent-plugin-submission.md). It records the
exact Codex release candidate, five positive and three negative offline contract cases, and
the project-level approval evidence and public-availability boundary.

## Planned Work

| Task | Release lane | Scope | State |
|---|---|---|---|
| 0038 | minor | Record the official contract and audit Forge's current surfaces | done |
| 0039 | minor | Validate Codex marketplace policy and local source resolution in CI | done |
| 0040 | major | Prepare skills-only submission evidence and an owner-reviewed portal draft | done; project approval recorded; public availability unverified |
| 0041 | major | Evaluate an MCP server or UI extension only if a real workflow requires it | done; deferred |
| 0044 | minor | Define the MCP 2026-07-28 Tasks adapter contract | done; reference-only, hosted server deferred |
| 0045 | minor | Verify DSSE and SLSA v1.2 release attestations | done; local public-key/HMAC contract, GitHub receipt boundary |
| 0046 | minor | Add trajectory and agentic-security regression evidence | done; local deterministic corpus and release-gate evidence |
| 0047 | major | Bind agent identity and delegated authority | done; local offline contract, adversarial corpus, and release-gate evidence |
| 0048 | major | Add host-authenticated admission evidence for connected effects | done; external cryptographic verification remains a host responsibility; local gate passed |
| 0049 | major | Validate signed A2A Agent Cards as bounded delegation evidence | done; offline trust projection passed; live discovery and cryptographic verification remain deferred |
| 0050 | major | Add bounded A2A task handoff and lifecycle evidence | done; local task, interruption, idempotency, stream, push, release, and installed replay evidence passed; live transport remains deferred |

## Submission Test Candidates

These are the candidate cases for task 0040. They are repository evidence, not a claim of
public directory listing or universal availability.

### Positive cases

1. Use Forge orchestration to plan a multi-file feature and create a dependency-ordered task
   ledger.
2. Use the solve loop to implement a focused change, run the relevant tests, and report
   verification evidence.
3. Use the stacked-changes workflow to inspect a stack, identify parent relationships, and
   produce a reviewable delivery plan without mutating GitHub.
4. Use the doctor and policy workflows to inspect repository state and show a staged preview
   before a GitHub or release mutation.
5. Use the Codex repository marketplace to install Forge, discover its skills, and invoke a
   relevant workflow in a fresh task.

### Negative cases

1. An unrelated request that merely mentions code does not trigger a Forge workflow by name
   alone.
2. A requested GitHub or release mutation does not bypass the policy, approval, or
   fail-closed boundary.
3. A malformed plugin manifest or marketplace policy fails validation instead of being
   silently accepted.

## Official Sources

- [Plugin architecture](https://developers.openai.com/plugins/concepts/plugins)
- [Package your plugin](https://developers.openai.com/plugins/build/plugins)
- [Agent Plugins 1.0 specification](https://agent-plugins.org/specification)
- [Codex plugin JSON and marketplace specification](https://github.com/openai/codex/blob/main/codex-rs/skills/src/assets/samples/plugin-creator/references/plugin-json-spec.md)
- [Plugin guidelines](https://developers.openai.com/plugins/app-guidelines)
- [Submit plugins](https://developers.openai.com/plugins/deploy/submission)
- [Plugins in ChatGPT and Codex](https://help.openai.com/en/articles/20001256-plugins-in-codex/)
