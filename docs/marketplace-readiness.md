# Marketplace Readiness

This document separates what Forge supports today from external directory status. A
repository marketplace is a distribution mechanism; it is not evidence that a host has
accepted a public directory submission.

## Publication state

| Surface | Current state | Evidence or next action |
|---|---|---|
| GitHub repository marketplace | Available | Install from `AlisinaDevelo/md-files`; tag `v3.5.0` is the verified release. |
| Claude Code repository marketplace | Available | `claude plugin marketplace add AlisinaDevelo/md-files` then `claude plugin install forge@forge`. |
| Codex local/repository marketplace | Available | `codex plugin marketplace add AlisinaDevelo/md-files` then `codex plugin add forge@forge`. |
| Claude public/curated directory | Not submitted | Do not claim listing or approval; submit only after the checklist below is reviewed. |
| Codex Plugin Directory | Not submitted | The directory is an external OpenAI surface; listing and refresh timing are controlled by OpenAI. |
| Agent Skills ecosystem directories | Not submitted | The `.agents` bundle is installable and validated, but no third-party directory approval is claimed. |

The Codex directory is described by [OpenAI's plugin directory documentation](https://help.openai.com/en/articles/20001256-plugins-in-codex/). Claude's repository marketplace flow is documented in [Claude Code marketplace documentation](https://code.claude.com/docs/en/plugin-marketplaces).

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
python3 scripts/build_release.py --output "$RUNNER_TEMP/forge-dist" --version X.Y.Z
python3 scripts/validate_codex_plugin.py \
  --archive "$RUNNER_TEMP/forge-dist/forge-X.Y.Z-codex.tar.gz" \
  --version X.Y.Z
python3 scripts/verify_release.py \
  --manifest "$RUNNER_TEMP/forge-dist/forge-X.Y.Z-manifest.json" \
  --root "$RUNNER_TEMP/forge-dist" \
  --version X.Y.Z
```

The CI host-validation job covers strict Claude validation, Codex marketplace resolution,
and the exact-archive Codex validator. The release workflow additionally verifies online
artifact provenance and the SPDX predicate.

## Submission and smoke-test matrix

Before any external submission, record a dated result for each case in the issue or PR:

| Case | Expected result |
|---|---|
| Positive activation | The installed host discovers Forge's orchestration and release skills. |
| Near-miss request | Unrelated prompts do not invoke a Forge skill solely because they mention code. |
| Permission boundary | Read-only work does not require mutation approval; GitHub/release effects remain policy-gated. |
| Clean install | A fresh user can add the documented repository marketplace and install `forge@forge`. |
| Upgrade | Version `3.5.0` replaces the prior cache entry without stale skill content. |
| Uninstall | Removing Forge removes the host registration while leaving the user's repository untouched. |
| Resource loading | Every declared skill, command, hook, asset, and referenced file loads from the cached plugin root. |

External directory review, approval, listing, and refresh remain open actions. This project
must not claim completion until the host owner confirms them.
