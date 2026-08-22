# Marketplace Readiness

This document separates what Forge supports today from external directory status. A
repository marketplace is a distribution mechanism; it is not evidence that a host has
accepted a public directory submission.

## Publication state

| Surface | Current state | Evidence or next action |
|---|---|---|
| GitHub repository marketplace | Available | Install from `AlisinaDevelo/md-files`; tag `v3.9.0` is the current release candidate. |
| Claude Code repository marketplace | Available | `claude plugin marketplace add AlisinaDevelo/md-files` then `claude plugin install forge@forge`. |
| Codex local/repository marketplace | Available | `codex plugin marketplace add AlisinaDevelo/md-files` then `codex plugin add forge@forge`. |
| OpenCode Agent Skills | Available | `./scripts/install-opencode.sh --copy`; OpenCode discovers the installed skills from `~/.agents/skills/`. |
| Claude public/curated directory | Not submitted | Do not claim listing or approval; submit only after the checklist below is reviewed. |
| OpenAI universal Plugin Directory (ChatGPT and Codex) | Project portal approval recorded | Owner-provided evidence dated 2026-08-18 shows Forge 3.6.0 as Approved; the 3.9.0 ZIP is the current candidate; public listing and universal availability are not independently verified. |
| Agent Skills ecosystem directories | Not submitted | The `.agents` bundle is installable and validated, but no third-party directory approval is claimed. |

The OpenAI universal Plugin Directory and package model are described in [OpenAI's plugin
architecture documentation](https://developers.openai.com/plugins/concepts/plugins),
[package guidance](https://developers.openai.com/plugins/build/plugins), and [submission
guidance](https://developers.openai.com/plugins/deploy/submission). The workspace behavior
and admin model are described in [Plugins in ChatGPT and Codex](https://help.openai.com/en/articles/20001256-plugins-in-codex/).
Claude's repository marketplace flow is documented in [Claude Code marketplace documentation](https://code.claude.com/docs/en/plugin-marketplaces).

## Publisher surfaces

- Website and documentation: [Forge README](../README.md) and
  [Getting started](getting-started.md).
- Privacy: [Privacy Policy](privacy.md).
- Terms: [Terms of Use](terms.md).
- Support: [Support](support.md).
- Security: [SECURITY.md](../SECURITY.md).
- Publisher identity: [AlisinaDevelo on GitHub](https://github.com/AlisinaDevelo).

The Codex manifest uses absolute HTTPS URLs for these surfaces. The Claude marketplace
manifest keeps its supported metadata fields strict and points users to the same public
documentation through `homepage` and `repository`.

## Asset policy

Forge is a skills and engineering-workflow plugin, not an interactive application. It
ships a real logo, dark-mode logo, and composer icon under `plugins/forge/assets/` for
host directory presentation. It intentionally ships no screenshots: showing a fake UI
would misrepresent a skills-only product. The release packager includes and inventories
these assets in the Claude and Codex archives.

## Candidate validation checklist

Run these checks from a clean checkout and against the exact candidate archive:

```bash
claude plugin validate --strict plugins/forge
python3 scripts/validate_codex_plugin.py plugins/forge
python3 scripts/validate_codex_plugin.py \
  --marketplace .agents/plugins/marketplace.json --root .
python3 scripts/build_release.py --output "$RUNNER_TEMP/forge-dist" --version X.Y.Z
python3 scripts/validate_codex_plugin.py \
  --archive "$RUNNER_TEMP/forge-dist/forge-X.Y.Z-codex.tar.gz" \
  --version X.Y.Z
python3 scripts/validate_codex_plugin.py \
  --zip "$RUNNER_TEMP/forge-dist/forge-X.Y.Z-openai.zip" \
  --version X.Y.Z
python3 scripts/verify_release.py \
  --manifest "$RUNNER_TEMP/forge-dist/forge-X.Y.Z-manifest.json" \
  --root "$RUNNER_TEMP/forge-dist" \
  --version X.Y.Z
python3 scripts/build_openai_submission_evidence.py \
  --output "$RUNNER_TEMP/openai-agent-plugin-submission.json"
```

The CI host-validation job covers strict Claude validation, Codex marketplace policy and
source validation, Codex marketplace resolution, and the exact-archive Codex validator. The
release workflow additionally verifies online artifact provenance and the SPDX predicate.

## Submission and smoke-test matrix

Before any external submission, record a dated result for each case in the issue or PR:

| Case | Expected result |
|---|---|
| Positive activation | The installed host discovers Forge's orchestration and release skills. |
| Near-miss request | Unrelated prompts do not invoke a Forge skill solely because they mention code. |
| Permission boundary | Read-only work does not require mutation approval; GitHub/release effects remain policy-gated. |
| Clean install | A fresh user can add the documented repository marketplace and install `forge@forge`. |
| Upgrade | Version `3.9.0` replaces the prior cache entry without stale skill content. |
| Uninstall | Removing Forge removes the host registration while leaving the user's repository untouched. |
| Resource loading | Every declared skill, command, hook, asset, and referenced file loads from the cached plugin root. |
| OpenAI submission evidence | Five positive and three negative skills-only cases are recorded with expected behavior and release notes. |

External directory listing, discoverability, and refresh remain open actions even though the
project portal approval is recorded. This project must not claim universal availability until
OpenAI confirms that separate state. See [OpenAI Agent Plugins compatibility](openai-agent-plugins.md)
for the current audit, test plan, and explicit MCP/UI deferral.
