# Host Model Bindings

Forge's model binding helper resolves a task tier against two caller-owned JSON documents:
an inventory for one host and a profile mapping tiers to exact model IDs. It does not query a
provider, discover credentials, score models, or pick a fallback.

## Contracts

An inventory has `schema_version`, `host`, `models`, and `retired_model_ids`. Each available
model entry has an exact host ID and the reasoning-effort values that this client currently
offers for that model:

```json
{
  "schema_version": 1,
  "host": "codex",
  "models": [
    {"id": "provider/model-id", "reasoning_efforts": ["low", "high"]}
  ],
  "retired_model_ids": []
}
```

A profile is scoped to the same host. Each tier maps to an exact model ID. Its `effort` is
optional; when omitted, the resolver leaves the host's effort default or inherited setting
alone.

```json
{
  "schema_version": 1,
  "host": "codex",
  "tiers": {
    "implementation": {"model": "provider/model-id", "effort": "high"}
  }
}
```

The supported host values are `codex`, `claude`, and `opencode`. Model IDs must be exact IDs,
not family aliases such as `opus`, `sonnet`, or `haiku`, and not `inherit`. Effort values use
the normalized set `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, and `ultra`;
the selected inventory entry must list the requested value. `auto` is not an explicit effort;
omit `effort` to keep the host/session default.

Inputs are UTF-8 JSON, limited to 64 KiB each. The validator rejects duplicate keys, unknown
fields, malformed identifiers, unsupported schema versions, duplicate entries, conflicting
available/retired IDs, and unsupported efforts. It accepts only these small contracts; do not
include prompts, credentials, provider response bodies, or other raw data.

## Discover, Inspect, Resolve, Replay

Discover from the host context you intend to use, rather than a remembered catalog:

- Codex: check the active client's model picker or `/model` choices. Copy the exact model ID
  shown for that client; `codex -m ID` is a CLI selection form, not an availability probe.
- Claude Code: use `/model` in the active session and record a full model ID, not a family
  alias. Provider and managed settings can change alias resolution or filter choices.
- OpenCode: use `/models` or `opencode models`; copy the enabled `provider/model` ID for the
  current project. The list depends on configured providers and project availability.

Reduce the host's choices to the inventory fields below: exact IDs, the effort values actually
offered for each ID, and retired IDs known for that host context. Do not paste raw command
output, session data, prompts, or credentials into these files. The inventory snapshot supplied
to the resolver is authoritative for that invocation; Forge does not collect or refresh it.

Inspect both files, then resolve one tier:

The checked-in fixture uses synthetic IDs for contract tests. It is not an inventory of a real
account or client.

```bash
python3 scripts/forge-models.py inspect \
  --inventory tests/fixtures/models/codex.inventory.json --host codex
python3 scripts/forge-models.py inspect \
  --profile tests/fixtures/models/codex.profile.json --host codex
python3 scripts/forge-models.py resolve \
  --host codex \
  --inventory tests/fixtures/models/codex.inventory.json \
  --profile tests/fixtures/models/codex.profile.json \
  --tier deep
```

The fixture pair is [codex.inventory.json](../tests/fixtures/models/codex.inventory.json) and
[codex.profile.json](../tests/fixtures/models/codex.profile.json). Re-running `resolve` against
unchanged files produces the same exact selection and inventory/profile digests. Those files
make the offline contract replayable in tests; replace them with a freshly gathered snapshot
and your own tier profile for real host configuration.

An explicit `--model` pin overrides the tier's model only after that exact ID is found in the
available inventory. It never falls back to the profile model. `--effort`, when supplied,
overrides the tier effort; otherwise the mapped effort is kept and checked against the pinned
model. A missing tier mapping remains an error even with an explicit pin. For example:

```bash
python3 scripts/forge-models.py resolve \
  --host codex \
  --inventory tests/fixtures/models/codex.inventory.json \
  --profile tests/fixtures/models/codex.profile.json \
  --tier deep --model example/fast-v1 --effort low
```

The result contains only the exact `host`, `model`, optional explicit `effort`, and the
`inventory_digest` and `profile_digest` that bind the choice to those inputs. A retired or
unlisted model, host mismatch, missing tier, or unsupported effort exits with status 2 and a
small error object; no alternative is selected.

## Host Boundary

Forge tier names describe work, not provider model IDs. A profile makes the host-specific
mapping explicit. Inheritance is different: when a host's agent/delegation config omits its
model (or uses that host's documented inherit value), it reuses the active session model. That
does not create an exact binding. A profile mapping or user pin is explicit; a pin takes
precedence, and an unavailable pin must stop rather than downgrade. The resolver can validate
only the supplied snapshot; after dispatch, use the active host's status or session UI to
confirm what actually ran.

| Host | Model selection boundary | Effort setting |
|---|---|---|
| Codex | Use the exact model ID exposed by the active client; `codex -m ID` is a CLI form. | `model_reasoning_effort` in Codex configuration; available values depend on model and client. |
| Claude Code | Use `/model` or `claude --model ID`; subagent `model` accepts a full model ID. Aliases such as `opus` and `sonnet` are provider/configuration dependent. | Subagent frontmatter `effort`, session `/effort` or `--effort`; supported values depend on model. |
| OpenCode | Choose from `/models`; IDs use `provider/model`. Agent `model` can be explicit or omitted to inherit the parent session model. | Agent `reasoningEffort` is passed through as a provider/model-specific option. |

Prefer model/delegation tools exposed by the current session. Do not infer availability from a
remembered catalog, transfer an alias between hosts, or assume another host's effort key is
valid. The helper returns normalized `effort`; the host-specific caller must translate it to
that host's documented setting.

## Dated Source Notes

Sources checked on 2026-10-02. These are documentation examples and migration notes, not
claims that a given account, workspace, client, or provider can select a model, nor claims of
measured quality.

- OpenAI's [Codex and ChatGPT model guide](https://learn.chatgpt.com/docs/models) lists IDs
  including `gpt-6.1-sol`, `gpt-6-astra`, and `gpt-6-luna`; its availability notes vary by
  plan, sign-in, client, workspace, and rollout. It says `gpt-5.5` retires from ChatGPT, Work,
  and Codex on 2026-10-14, while `gpt-5.4` and `gpt-5.4-mini` retired from Codex with
  ChatGPT sign-in on 2026-08-31. API availability is a separate boundary.
- [Claude Code model configuration](https://code.claude.com/docs/en/model-config) documents
  aliases, full IDs, provider-specific resolution, and model-dependent effort settings.
  Anthropic's [model deprecations](https://docs.anthropic.com/en/docs/about-claude/model-deprecations)
  page tracks versioned model status.
- OpenCode's [models guide](https://opencode.ai/docs/models/) says to select from the models
  enabled for the current project/provider. Its [agent guide](https://opencode.ai/docs/agents/)
  documents per-agent model configuration and provider-specific model options.

These moving catalogs are why Forge stores neither a universal default model ID nor a shared
claim of account availability. Refresh the inventory from the exact host/client context before
resolving a binding.
