# OSS Release Contract

Forge 3.11.0 focuses on contribution reliability and native open-source host use.
It does not claim software-engineering benchmark leadership.

Primary-source research refreshed on 2026-10-03.

## Deliverables

1. An upstream contribution workflow with reviewed executable checks, exact-head
   evidence, negative controls and a clear maintainer/permission boundary.
2. Native OpenHands SDK registration and content-loading checks against packaged
   AgentSkills, plus investigation of OpenCode v2 discovery.
3. A locally tested, reproducible release, merged source and verified host installs.

## Research Basis

[SWE-Bench Pro Verified](https://arxiv.org/abs/2609.08149) identifies solution leakage
and incorrect task/test contracts as threats to benchmark reliability. The concrete
response here is to retain an explicit check contract and bind its execution evidence
to the source revision. This does not prevent every form of reward hacking.

[SWE-bench Goes Live](https://arxiv.org/abs/2505.23419) addresses stale task collections
with refreshed executable tasks. Forge records the selected upstream revision and
checks instead of presenting a fixed prompt catalog as measured coding ability.

The closest product comparator is the existing Forge PR-authoring skill: it describes
review preparation but does not execute or verify exact-head contribution checks.
The new helper supplies that missing local evidence step. No comparative agent
benchmark, model ranking or automatic maintainer acceptance is established.

[OpenHands' native skill guide](https://docs.openhands.dev/sdk/guides/skill) distinguishes
progressive-disclosure AgentSkills from always-injected legacy content. Compatibility
must therefore prove native discovery and explicit content loading, not just valid YAML.

## Acceptance

Run the complete local release gate on the integrated release candidate and merged
main. Retain source/tree identity, actual commands, versions, failed negative controls,
archive digests and installed replay evidence. Request external review and disclose
unavailable review or CI rather than implying it passed. Merge verified PRs under the
owner's temporary CI exception; do not relax the source or local acceptance contract.
