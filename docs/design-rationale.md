# Design Rationale

Why Forge is built the way it is. These are the decisions that shaped the toolkit and the
reasoning behind them — kept here so they don't get re-litigated, and so anyone extending
Forge knows which constraints are load-bearing.

## Principle: precision over volume

It is trivial to generate a hundred agents and three hundred skills. It is worthless. An
LLM toolkit's job is to put the *right* capability in front of the model at the *right*
moment — and every extra artifact competes for attention and dilutes triggering. So Forge
is deliberately curated: each agent earns its place by being a distinct role with a sharp
description, a concrete method, and scoped tools. The eval harness exists partly to enforce
this — a vague description or an over-privileged agent fails the static checks.

The same logic governs skill bodies. A skill that dumps everything it knows into `SKILL.md`
costs context budget on every session whether or not it's used. Progressive disclosure —
a lean `SKILL.md` that points to deeper reference files loaded on demand — is how you get
depth without paying for it upfront. `code-review-rubric` and `refactoring-catalog`
demonstrate the pattern; new skills should follow it whenever the reference material is
long.

## Decision: a plugin in a marketplace, not files in `.claude/`

The obvious way to ship this would be a `.claude/` directory people copy. Forge is a
proper Claude Code **plugin** inside a **marketplace** instead, because:

- It installs and updates with two commands and a `git pull`, instead of a manual copy that
  drifts.
- The plugin manifest is the canonical declaration of what's included; the marketplace lets
  the catalog grow to multiple plugins later without restructuring.
- It forced the layout to be *correct* against the real schema (see below), which is the
  difference between "looks like a plugin" and "is one."

The plugin lives in `plugins/forge/` rather than at the marketplace root on purpose. A
marketplace-root source (`source: "./"`) triggers a documented edge case in how component
directories are scanned. Putting the plugin in a subdirectory is the structure every
official example uses and sidesteps the edge case entirely. That decision came from reading
the schema, not guessing — which is the next principle.

## Principle: verify against the source, don't assert from memory

Every schema in this repo — the plugin manifest, the marketplace manifest, hook events and
exit codes, agent/command/skill frontmatter, output-style and status-line formats — was
checked against the official documentation before it was written, and the manifests were
restructured when verification contradicted the first draft. LLM memory of a fast-moving
platform is exactly the kind of confident-but-wrong that this toolkit's own agents are
instructed to avoid. The repo holds itself to that standard.

## Decision: hooks fail open, but block hard

The two guard hooks (`guard-bash`, `scan-secrets`) face a genuine tension. Fail closed and
a malformed payload bricks the session; fail open and a guard can be bypassed. Forge
resolves it deliberately: **fail open on ambiguity, block hard on high-confidence threats.**
A parse error never blocks (it can't be allowed to take down every session); a literal
`rm -rf /` or an AWS key in a file always blocks (exit 2). The patterns are kept
high-precision because a guard that cries wolf gets disabled — and a disabled guard is
worse than none. This is why the test suite weighs true negatives (not crying wolf) as
heavily as true positives.

**Known limitation — `guard-bash` matches the command string, not the parsed command.**
A dangerous pattern that appears only as quoted text (`echo "git push --force … main"`) or
in a comment (`ls  # never rm -rf / here`) is still blocked, because the guard does a
regex match over the raw command rather than parsing the shell. This is a deliberate
trade-off, not an oversight: anchoring patterns to a command boundary to fix the false
positive would *miss* the real threat when it's wrapped (`$(rm -rf /)`, `xargs rm -rf`,
`eval "$cmd"`). For a last-line safety net, a false positive (you rephrase a command) is
cheap; a false negative (a catastrophe slips through) is not. The same property means the
`scan-secrets` hook will block an edit whose content includes a credential-shaped fixture
— including, amusingly, edits to this toolkit's own scanner tests. When that happens,
assemble the fixture from parts (see `tests/test_hooks.py`'s `_tok` helper) so no
contiguous secret literal sits in the file.

Hooks are also where determinism beats intelligence. A model can be talked out of its own
instructions; a shell program that exits 2 cannot. Anything that *must* happen — blocking a
catastrophe, formatting a file — belongs in a hook, not in a prompt that hopes the model
remembers.

## Decision: evals are part of the deliverable, not an afterthought

The honest question about any prompt collection is "does this actually work, or does it
just read well?" Forge answers it two ways: static prompt-quality checks that gate CI for
free, and an LLM-judge behavioral eval that runs each agent against real tasks and scores
the output against explicit criteria. The second one costs API calls, so it's opt-in — but
it's the artifact that turns "trust me" into "run it yourself." Building it was the point at
which this stopped being a pile of markdown and started being something with evidence
behind it.

## Non-goals

Knowing what Forge deliberately *isn't* is as useful as knowing what it is:

- **Not a framework.** No runtime, no abstraction layer, no code to import. Plain markdown
  and small auditable scripts. You can read every byte the model will be told.
- **Not exhaustive.** It won't have an agent for every niche. It covers the spine of the
  software lifecycle well rather than everything shallowly.
- **Not dependency-heavy.** The scripts use stdlib (`python3`) and ubiquitous tools (`git`,
  `jq` with a `python3` fallback). Installing Forge doesn't drag in a toolchain.
- **Not a replacement for judgment.** The agents are instructed to express uncertainty and
  ask when a decision is genuinely the user's. A toolkit that fakes confidence is a
  liability.
- **Not magic.** Every behavior traces to a file you can open and a check you can run.

## How to extend it well

Add an agent/skill/command when there's a real, distinct job it does better than the
generalist — and make `./scripts/validate.sh` and `python3 evals/run.py` pass before you
ship it. If you can't write a sharp triggering description or a gradeable eval criterion for
it, that's a signal the component isn't well-defined yet. See [CONTRIBUTING.md](../CONTRIBUTING.md).
