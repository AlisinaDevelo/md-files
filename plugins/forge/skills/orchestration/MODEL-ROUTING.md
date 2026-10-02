# Model-Routing Policy

Route a task by the kind of work it needs, not by the importance of the overall project.
The tier labels below describe work categories; they are not portable model IDs, aliases, or
claims that similarly named models behave alike across providers.

## Tiers

| Forge tier | Use it for | Examples |
|---|---|---|
| **Fable / Opus** | High-judgment work where a wrong plan is expensive: architecture, decomposition, difficult root-cause debugging, security analysis, or ambiguous investigations. | Design a migration; trace an intermittent race; plan a multi-part feature. |
| **Sonnet** | Well-specified implementation, tests, refactors with a safety net, documentation, and code review. | Implement a scoped change; add boundary tests; review a focused diff. |
| **Haiku** | Mechanical, bounded, high-volume, or parallel work where little judgment is needed. | Rename symbols; scaffold boilerplate; sweep a defined file set. |

These names are retained Forge routing labels only. Do not pass `opus`, `sonnet`, `haiku`, or
`fable` as if they were universal host model identifiers. Select exact IDs and supported
effort values from the active host's inventory. Forge makes no shared capability or cost
ranking claim across providers.

## Host Selection

Prefer the model and delegation controls exposed by the current session. Host tools know about
the current sign-in, workspace policy, client version, provider configuration, and rollout;
remembered model catalogs and shell aliases do not. When that host supports model inheritance,
an omitted model (or its explicit `inherit` setting) reuses the parent session's selected model.
Inheritance is not an exact tier binding.

A profile maps each task tier to an exact model ID for one host. A caller's explicit model pin
overrides that mapped model and is never replaced with a fallback. An unavailable or retired
pin fails closed. An explicit effort overrides the profile's effort; otherwise the mapped
effort is used when present. If no effort is mapped, the host's existing default or inherited
effort remains in effect. Every explicit effort must be listed for that exact model in the
provided inventory.

Use the offline helper to inspect and resolve the inventory/profile contract. Its result binds
the selected ID and optional effort to both input digests; it does not call a provider or prove
that the inventory was collected from the claimed client. The detailed format and limits are
in [Host Model Bindings](https://github.com/AlisinaDevelo/md-files/blob/main/docs/model-bindings.md).

Run these commands from the installed orchestration skill directory. The same commands
also work from a Forge checkout's root through its convenience launcher.

```bash
python3 scripts/forge-models.py inspect --inventory INVENTORY.json --host codex
python3 scripts/forge-models.py inspect --profile PROFILE.json --host codex
python3 scripts/forge-models.py resolve \
  --host codex --inventory INVENTORY.json --profile PROFILE.json --tier implementation
```

Host syntax differs. Codex configuration uses `model` and `model_reasoning_effort`. Claude
Code uses `/model` or `--model`, and subagent frontmatter uses `model` and `effort`; its family
aliases resolve according to provider and configuration. OpenCode selects enabled
`provider/model` IDs through `/models`, with per-agent `model` and provider-specific options
such as `reasoningEffort`. See [Host Model Bindings](https://github.com/AlisinaDevelo/md-files/blob/main/docs/model-bindings.md) for
current official references and the 2026-10-02 source check.

## Routing Heuristic

Ask: **"If this is done slightly wrong, how expensive is the mistake, and how much judgment
does getting it right require?"** Use that answer to choose a Forge tier, then bind that tier
to a model available to the current host. A tier never grants access to a model or changes
host permissions.
