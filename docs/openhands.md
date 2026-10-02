# OpenHands SDK

Forge's release AgentSkills projection can be loaded by the OpenHands SDK. This is an
optional compatibility check, not a runtime Forge dependency or an OpenHands installer.
It verifies the extracted `forge-agents/skills` tree from the `*-agents.tar.gz` release
bundle; the adjacent Zed `.md` shims are not counted as AgentSkills `SKILL.md` entries.

## Verify an Extracted Bundle

Build the release archive using the normal release builder, then extract it and point the
verifier at the extraction root (the directory containing `forge-agents/`):

```bash
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
python3 scripts/build_release.py --output "$WORK/release"
mkdir -p "$WORK/extracted"
tar -xzf "$WORK/release"/*-agents.tar.gz -C "$WORK/extracted"
python3.12 -m venv "$WORK/venv"
PIP_CACHE_DIR="$WORK/pip-cache" "$WORK/venv/bin/python" -m pip install 'openhands-sdk==1.50.1'
OPENHANDS_SUPPRESS_BANNER=1 "$WORK/venv/bin/python" \
  scripts/verify_openhands_skills.py \
  --archive-root "$WORK/extracted" \
  --expected-sdk-version 1.50.1
```

The verified pin is `openhands-sdk==1.50.1`, the [official SDK release](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.50.1); its package metadata requires Python 3.12 or newer. Keep this compatibility dependency in a temporary virtual environment; no project lockfile or global OpenHands installation is needed. The SDK install resolves a sizable runtime dependency set, including LiteLLM, FastMCP, MCP, OpenTelemetry, and their transitive packages.

The verifier calls the SDK's `load_skills_from_dir()` and compares its AgentSkills
`Skill` sources with every packaged `SKILL.md`, so the SDK's fail-soft behavior cannot
silently hide a skipped or malformed skill. Its inventory check uses the graph-rendered
projection manifest and enumerates the extracted Zed shim files; it does not duplicate
the capability graph or pin a skill count. It checks that every loaded `Skill.content`
body is non-empty and registers exactly those skills in `AgentContext` with
`load_public_skills=False`. It calls `discover_skill_resources()` and compares the
returned paths with `Skill.resources`. The SDK returns resource path metadata, not
resource bytes in `Skill.content`; the verifier itself reads every returned packaged
file and confirms it is accessible and non-empty. These APIs are documented in the
[OpenHands skill guide](https://docs.openhands.dev/sdk/guides/skill) and the pinned
[SDK Skill source](https://github.com/OpenHands/software-agent-sdk/blob/v1.50.1/openhands-sdk/openhands/sdk/skills/skill.py).
It creates no Agent or Conversation and makes no LLM calls or provider requests.

## Recorded Verification

On 2026-10-03, the extracted AgentSkills archive was generated from the verification
checkout at Forge commit `6d076ac95d8645c30ece66872cc66e18f593362d`. The release
manifest reported Forge `3.10.0`, so this is not evidence for a Forge `3.11.0` artifact.
The pinned SDK registered all 25 directory-form skills, returned 27 script resource
paths, and the verifier read 1,147,107 resource bytes. The archive SHA-256 was
`b65869f00320b550552c10080d26f4d8e6f27fbbec9804af00ec46a22361eced`; two independent
builds produced the same archive hash. Tests enumerate the extracted bundle and derive
the expected skill inventory rather than pinning 25 or 67. The adjacent Zed agent and
command shims are a separate projection and are not claimed as OpenHands AgentSkills.
Rerun the native verifier against the final `3.11.0` artifact for release-specific
evidence.

The exact Python, SDK, test-runner, and transitive dependency snapshot from the isolated
verification environment is retained as local release evidence and is not embedded in
this public documentation.

The experiment used these commands (with the archive paths above):

```bash
python3.12 -m venv "$WORK/venv"
PIP_CACHE_DIR="$WORK/pip-cache" "$WORK/venv/bin/python" -m pip install 'openhands-sdk==1.50.1' pytest
env -u LLM_API_KEY -u OPENAI_API_KEY -u ANTHROPIC_API_KEY OPENHANDS_SUPPRESS_BANNER=1 \
  "$WORK/venv/bin/python" -m pytest -p no:cacheprovider tests/test_openhands_compatibility.py -q
env -u LLM_API_KEY -u OPENAI_API_KEY -u ANTHROPIC_API_KEY OPENHANDS_SUPPRESS_BANNER=1 \
  "$WORK/venv/bin/python" scripts/verify_openhands_skills.py \
    --archive-root "$WORK/extracted" --expected-sdk-version 1.50.1
```

This proves only the recorded OpenHands SDK release and archive layout. It is not a claim
of compatibility with every AgentSkills host or an end-to-end model/tool execution test.
